"""P5 — incremental vs batch metrics 일관성 가드.

`compute_metrics_incremental(closed_trades, equity_snapshot, initial_cash)` 는
streaming KPI 패널이 trade close 마다 호출하는 stateless API. 진행 중 N 회
호출의 final-step 값은 `compute_metrics(equity_curve, trades, initial_cash)`
batch 1 회 호출과 floating-point exact 동일해야 한다 (plan P1 AC).

이 파일은 그 결정성 계약을 가드한다:
- 0 trades / 1 trade / 다수 trade / drawdown / winning streak
- progressive N 회 호출 → final 결과 == batch 결과 (dict 동일성)
- 인자 순서 (closed_trades, equity_snapshot, initial_cash) 회귀
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from tickweaver.analytics.metrics import (
    compute_metrics,
    compute_metrics_incremental,
)
from tickweaver.analytics.trades import Trade
from tickweaver.core.types import Side


# ─────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────
def _ts(hour: int) -> pd.Timestamp:
    return pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=hour)


def _equity(values: list[float]) -> pd.DataFrame:
    """tz-aware DatetimeIndex 의 equity DataFrame. 1h 간격."""
    idx = pd.DatetimeIndex([_ts(i) for i in range(len(values))])
    return pd.DataFrame({"equity": values}, index=idx)


def _trade(entry_hour: int, exit_hour: int, pnl: float, side: Side = Side.BUY) -> Trade:
    """간단 trade. price/qty 는 metric 계산에 무관 (pnl 만 보면 됨)."""
    return Trade(
        entry_ts=_ts(entry_hour),
        exit_ts=_ts(exit_hour),
        side=side,
        qty=1.0,
        entry_price=100.0,
        exit_price=100.0 + pnl,
        fee=0.0,
        pnl=pnl,
        first_entry_price=100.0,
    )


# ─────────────────────────────────────────────────────────
# 기본 동치 — batch vs incremental 위임 확인
# ─────────────────────────────────────────────────────────
def test_incremental_delegates_to_batch_identical_dict() -> None:
    """compute_metrics_incremental 의 결과는 compute_metrics 와 dict 단위로 동일.

    인자 순서 차이 (incremental=(trades, equity, cash) vs batch=(equity, trades,
    cash)) 만 다르고, 내부적으로 같은 함수에 위임해야 한다.
    """
    equity = _equity([10_000.0, 10_050.0, 10_120.0, 10_080.0, 10_200.0])
    trades = [_trade(1, 2, +70.0), _trade(3, 4, +50.0)]

    batch = compute_metrics(equity, trades, initial_cash=10_000.0)
    incremental = compute_metrics_incremental(trades, equity, initial_cash=10_000.0)

    assert batch.keys() == incremental.keys()
    for k in batch:
        if isinstance(batch[k], float):
            assert batch[k] == incremental[k], f"{k} differs: {batch[k]} vs {incremental[k]}"
        else:
            assert batch[k] == incremental[k], f"{k}: {batch[k]!r} vs {incremental[k]!r}"


# ─────────────────────────────────────────────────────────
# Progressive ≡ Batch — final-step 부동소수점 정확 동일
# ─────────────────────────────────────────────────────────
def _assert_metrics_exact(a: dict, b: dict) -> None:
    """dict floating-point exact 비교 (NaN 양쪽 모두인 경우 동치 처리)."""
    assert a.keys() == b.keys()
    for k in a:
        va, vb = a[k], b[k]
        if isinstance(va, float) and isinstance(vb, float):
            if math.isnan(va) and math.isnan(vb):
                continue
            assert va == vb, f"{k}: {va!r} vs {vb!r}"
        else:
            assert va == vb, f"{k}: {va!r} vs {vb!r}"


def test_progressive_final_step_equals_batch_zero_trades() -> None:
    """trade 0 — equity 만 흐를 때 final-step 호출이 batch 와 동일."""
    equity = _equity([10_000.0, 10_010.0, 10_005.0, 10_020.0])
    trades: list[Trade] = []

    # 진행 중 호출 — equity 슬라이스로 N 번
    for n in range(1, len(equity) + 1):
        progressive = compute_metrics_incremental(
            trades, equity.iloc[:n], initial_cash=10_000.0
        )
        assert isinstance(progressive, dict)  # 매 호출 stateless

    final_progressive = compute_metrics_incremental(trades, equity, 10_000.0)
    batch = compute_metrics(equity, trades, 10_000.0)
    _assert_metrics_exact(final_progressive, batch)


def test_progressive_final_step_equals_batch_single_trade() -> None:
    """trade 1 건 close — final 호출 == batch."""
    equity = _equity([10_000.0, 10_050.0, 10_100.0, 10_080.0])
    trades = [_trade(1, 2, +100.0)]

    # progressive: 매 시점 trades_so_far slice + equity slice
    for n in range(1, len(equity) + 1):
        trades_so_far = [t for t in trades if t.exit_ts <= equity.index[n - 1]]
        _ = compute_metrics_incremental(
            trades_so_far, equity.iloc[:n], initial_cash=10_000.0
        )

    final_progressive = compute_metrics_incremental(trades, equity, 10_000.0)
    batch = compute_metrics(equity, trades, 10_000.0)
    _assert_metrics_exact(final_progressive, batch)


def test_progressive_final_step_equals_batch_multiple_adds_cycle() -> None:
    """다수 trade — add → close → reverse → close 같은 사이클."""
    # 5 closed trades. equity 는 trade close 시점에 변함.
    equity = _equity(
        [10_000.0, 10_080.0, 10_050.0, 10_180.0, 10_140.0, 10_240.0, 10_310.0]
    )
    trades = [
        _trade(1, 1, +80.0),
        _trade(2, 2, -30.0),
        _trade(3, 3, +130.0),
        _trade(4, 4, -40.0),
        _trade(5, 5, +100.0),
    ]

    # 매 trade close 마다 progressive 호출 — viz 패널의 실제 사용 패턴
    for closed_n in range(0, len(trades) + 1):
        trades_so_far = trades[:closed_n]
        equity_so_far = equity.iloc[: closed_n + 2]  # close + 약간 buffer
        _ = compute_metrics_incremental(
            trades_so_far, equity_so_far, initial_cash=10_000.0
        )

    final_progressive = compute_metrics_incremental(trades, equity, 10_000.0)
    batch = compute_metrics(equity, trades, 10_000.0)
    _assert_metrics_exact(final_progressive, batch)


def test_progressive_final_step_equals_batch_drawdown_scenario() -> None:
    """peak → trough drawdown 시나리오 — MDD / calmar 계산 정확도."""
    # equity: 상승 → 큰 폭 하락 → 부분 회복. MDD 가 명확히 잡힘.
    equity = _equity(
        [10_000.0, 11_000.0, 12_000.0, 10_500.0, 9_000.0, 9_500.0, 10_200.0]
    )
    trades = [
        _trade(2, 3, -1_500.0),
        _trade(4, 4, -500.0),
        _trade(5, 6, +700.0),
    ]
    final_progressive = compute_metrics_incremental(trades, equity, 10_000.0)
    batch = compute_metrics(equity, trades, 10_000.0)
    _assert_metrics_exact(final_progressive, batch)
    # 추가 sanity — drawdown 음수
    assert batch["max_drawdown"] < 0
    # win_rate 1/3
    assert batch["win_rate"] == pytest.approx(1.0 / 3.0)


def test_progressive_final_step_equals_batch_winning_streak_inf_pf() -> None:
    """모두 winning trades — profit_factor +inf, win_rate=1.0."""
    equity = _equity([10_000.0, 10_100.0, 10_250.0, 10_400.0])
    trades = [
        _trade(1, 1, +100.0),
        _trade(2, 2, +150.0),
        _trade(3, 3, +150.0),
    ]
    final_progressive = compute_metrics_incremental(trades, equity, 10_000.0)
    batch = compute_metrics(equity, trades, 10_000.0)
    _assert_metrics_exact(final_progressive, batch)
    assert batch["win_rate"] == 1.0
    assert batch["profit_factor"] == float("inf")
    assert batch["n_trades"] == 3


# ─────────────────────────────────────────────────────────
# Statelessness — 같은 입력이면 항상 같은 결과
# ─────────────────────────────────────────────────────────
def test_incremental_is_pure_function_no_hidden_state() -> None:
    """동일 인자로 N 번 호출 → 매번 동일 dict (no hidden state)."""
    equity = _equity([10_000.0, 10_120.0, 10_080.0])
    trades = [_trade(1, 2, +80.0)]

    results = [
        compute_metrics_incremental(trades, equity, 10_000.0) for _ in range(5)
    ]
    for r in results[1:]:
        _assert_metrics_exact(r, results[0])


def test_incremental_empty_equity_returns_initial_cash() -> None:
    """edge case — equity_curve 가 비었으면 final_equity=initial_cash."""
    empty = pd.DataFrame(columns=["equity"]).astype({"equity": "float64"})
    out = compute_metrics_incremental([], empty, initial_cash=10_000.0)
    assert out["final_equity"] == 10_000.0
    assert out["n_trades"] == 0
    assert out["total_return"] == 0.0


# ─────────────────────────────────────────────────────────
# 1-row equity_snapshot — streaming 첫 tick KPI 호출 안전성
# ─────────────────────────────────────────────────────────
# engine-dev P1-fix (task #8, 옵션 A): `_compute_from_equity_and_trades` 의
# CAGR 블록에 `len(equity) < 2 or n_seconds <= 0` 가드 추가 — 분기 시
# `cagr = total_return` 폴백. HTML batch 출력은 N>=2 라 char-for-char 동일.
#
# 본 두 케이스는 그 fix 가 streaming 첫 tick 호출 경로(1-row equity)에서
# 예외 없이 자연스러운 KPI 값을 돌려준다는 회귀 가드.


def test_incremental_one_row_equity_does_not_overflow() -> None:
    """1-row equity_snapshot 호출이 예외 없이 자연스러운 값을 돌려준다.

    streaming KPI 패널이 첫 tick 직후 호출하는 합법 경로. 옵션 A fix 적용
    후 OverflowError 없음 + `cagr == total_return` 폴백 동작.
    """
    idx = pd.DatetimeIndex([_ts(0)])
    equity = pd.DataFrame({"equity": [10_500.0]}, index=idx)
    out = compute_metrics_incremental([], equity, initial_cash=10_000.0)
    assert out["final_equity"] == 10_500.0
    assert out["total_return"] == pytest.approx(0.05)
    # 옵션 A 폴백: 1-row 일 때 cagr 는 total_return 와 동일.
    assert out["cagr"] == out["total_return"]


def test_incremental_one_row_equity_loss_does_not_overflow() -> None:
    """대칭 케이스 — 1-row equity 가 손실 측이어도 동일하게 안전.

    fix 전엔 (final/initial)<1 ** large → 0.0 수렴해 우연히 overflow 만
    피했지만 cagr 값은 -1.0 으로 무의미했음. fix 후엔 cagr=total_return.
    """
    idx = pd.DatetimeIndex([_ts(0)])
    equity = pd.DataFrame({"equity": [9_500.0]}, index=idx)
    out = compute_metrics_incremental([], equity, initial_cash=10_000.0)
    assert out["final_equity"] == 9_500.0
    assert out["total_return"] == pytest.approx(-0.05)
    assert out["cagr"] == out["total_return"]
