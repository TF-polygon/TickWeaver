"""Parity harness 단위 테스트 — TickWeaver ↔ TradingView 비교 계약 가드.

실데이터(TradingView CSV) 없이 sample fixture + 합성 report dir 만으로
parity/compare.py 의 로더/비교/렌더가 동작함을 검증한다.

커버:
- load_tv_summary: sample → normalized dict
- load_tv_trades: sample → normalized round-trip frame
- load_tw_results: tmp_path 합성 metrics.json → normalized dict
- compare_aggregate: PASS / FAIL(한 지표 5% 초과)
- n_trades 절대 허용오차 ±1 통과 / ±2 실패
- profit_factor inf 처리 (둘 다 inf 통과 / 한쪽만 inf 실패)
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from parity.compare import (
    ParityTolerance,
    compare_aggregate,
    load_tv_summary,
    load_tv_trades,
    load_tw_results,
    render_markdown,
)

_REF = Path(__file__).resolve().parents[2] / "parity" / "reference"
_TV_SUMMARY = _REF / "ema_cross.tv_summary.sample.csv"
_TV_TRADES = _REF / "ema_cross.tv_trades.sample.csv"


# ─────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────
def _write_tw_report(tmp_path: Path, **overrides) -> Path:
    """합성 report dir (metrics.json + trades.parquet) 작성 후 경로 반환.

    기본값은 _TV_SUMMARY (net_profit 572.40 / 5.72% / 41 trades / 44.20% win /
    PF 1.44 / MDD 4.91%) 와 5% 이내로 일치하도록 의도적으로 약간만 다르게
    잡았다 — PASS-path 테스트가 '정확히 같은 값'이 아니라 '허용오차 내 일치'
    를 검증하게 하기 위함. FAIL-path 테스트는 overrides 로 한 지표를 5% 밖으로
    밀어낸다.
    """
    metrics = {
        "final_equity": 10560.00,   # net_profit 560 vs tv 572.40 → 2.2%
        "initial_cash": 10000.0,
        "total_return": 0.0560,     # net_profit_pct 5.60 vs tv 5.72 → 2.1%
        "cagr": 0.05,
        "sharpe": 1.38,
        "sortino": 1.60,
        "max_drawdown": -0.0500,    # 5.00% vs tv 4.91% → 1.8%
        "calmar": 1.0,
        "n_trades": 42,             # vs tv 41 → abs 1
        "win_rate": 0.435,          # 43.5% vs tv 44.20% → 1.6%
        "profit_factor": 1.42,      # vs tv 1.44 → 1.4%
    }
    metrics.update(overrides)
    out = tmp_path / "ema_cross_report"
    out.mkdir()
    with open(out / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f)
    df = pd.DataFrame(
        [
            {
                "entry_ts": "2024-01-15T08:00:00",
                "exit_ts": "2024-01-20T14:00:00",
                "side": "BUY",
                "qty": 0.047,
                "entry_price": 42500.0,
                "exit_price": 43800.0,
                "fee": 4.0,
                "pnl": 61.10,
            }
        ]
    )
    df.to_parquet(out / "trades.parquet")
    return out


# ─────────────────────────────────────────────────────────
# TradingView loaders
# ─────────────────────────────────────────────────────────
def test_load_tv_summary_parses_sample():
    tv = load_tv_summary(_TV_SUMMARY)
    assert tv["net_profit"] == 572.40
    assert tv["net_profit_pct"] == 5.72
    assert tv["n_trades"] == 41
    assert tv["win_rate_pct"] == 44.20
    assert tv["profit_factor"] == 1.44
    assert tv["max_drawdown_pct"] == 4.91  # abs() of -4.91%


def test_load_tv_trades_parses_sample():
    df = load_tv_trades(_TV_TRADES)
    assert list(df.columns) == [
        "entry_ts",
        "exit_ts",
        "side",
        "qty",
        "entry_price",
        "exit_price",
        "pnl",
    ]
    assert len(df) == 3
    assert (df["side"] == "long").all()
    first = df.iloc[0]
    assert first["entry_price"] == 42500.0
    assert first["exit_price"] == 43800.0
    assert first["pnl"] == 61.10
    assert df["pnl"].sum() == round(61.10 - 50.60 + 85.80, 2)


# ─────────────────────────────────────────────────────────
# TickWeaver loader
# ─────────────────────────────────────────────────────────
def test_load_tw_results_normalizes(tmp_path):
    tw = load_tw_results(_write_tw_report(tmp_path))
    assert tw["initial_cash"] == 10000.0
    assert tw["final_equity"] == 10560.00
    assert abs(tw["net_profit"] - 560.00) < 1e-6
    assert abs(tw["net_profit_pct"] - 5.60) < 1e-9
    assert tw["n_trades"] == 42
    assert abs(tw["win_rate_pct"] - 43.5) < 1e-9
    assert tw["profit_factor"] == 1.42
    assert abs(tw["max_drawdown_pct"] - 5.00) < 1e-9


def test_load_tw_results_profit_factor_inf(tmp_path):
    tw = load_tw_results(_write_tw_report(tmp_path, profit_factor=float("inf")))
    assert tw["profit_factor"] == float("inf")


# ─────────────────────────────────────────────────────────
# compare_aggregate
# ─────────────────────────────────────────────────────────
def test_compare_pass(tmp_path):
    tw = load_tw_results(_write_tw_report(tmp_path))
    tv = load_tv_summary(_TV_SUMMARY)
    report = compare_aggregate(tw, tv, ParityTolerance(), "ema_cross")
    assert report.passed
    md = render_markdown(report)
    assert "PASS" in md
    assert "| Metric |" in md


def test_compare_fail_one_metric_beyond_5pct(tmp_path):
    # net_profit 900 vs tv 572.40 → ~57% off → FAIL (all other metrics still
    # within tolerance, so this isolates a single out-of-tolerance metric).
    tw = load_tw_results(_write_tw_report(tmp_path, final_equity=10900.0))
    tv = load_tv_summary(_TV_SUMMARY)
    report = compare_aggregate(tw, tv, ParityTolerance(), "ema_cross")
    assert not report.passed
    assert "FAIL" in render_markdown(report)


def test_n_trades_abs_tolerance():
    tol = ParityTolerance()
    base = {"n_trades": 10}
    # ±1 passes
    r1 = compare_aggregate(base, {"n_trades": 11}, tol, "s")
    assert r1.passed
    # ±2 fails
    r2 = compare_aggregate(base, {"n_trades": 12}, tol, "s")
    assert not r2.passed


def test_profit_factor_inf_handling():
    tol = ParityTolerance()
    # both inf → within tol
    r_both = compare_aggregate(
        {"profit_factor": float("inf")},
        {"profit_factor": float("inf")},
        tol,
        "s",
    )
    assert r_both.passed
    # one inf → not within tol
    r_one = compare_aggregate(
        {"profit_factor": float("inf")},
        {"profit_factor": 9.06},
        tol,
        "s",
    )
    assert not r_one.passed
