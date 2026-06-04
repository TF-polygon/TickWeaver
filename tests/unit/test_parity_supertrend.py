"""SuperTrend parity harness 테스트 — TickWeaver ↔ TradingView 비교 계약 가드.

실데이터(TradingView CSV) 없이 합성 TW report dir + 합성 TV summary CSV 만으로
parity/compare.py 가 SuperTrend 트랙(롱+숏 선물)에서 동작함을 검증한다.

test_parity_compare.py 의 fixture 패턴을 그대로 따른다:
- tmp_path 에 metrics.json + trades.parquet(롱/숏 양쪽 trade 포함) 합성
- 5% 이내로 일치하도록 의도적으로 약간만 다른 TV summary CSV 합성
- compare_aggregate PASS path / FAIL path(한 지표 5% 초과) 검증
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from parity.compare import (
    ParityTolerance,
    compare_aggregate,
    load_tv_summary,
    load_tw_results,
    render_markdown,
)


# ─────────────────────────────────────────────────────────
# Builders
# ─────────────────────────────────────────────────────────
def _write_tw_report(tmp_path: Path, **overrides) -> Path:
    """합성 SuperTrend report dir(metrics.json + trades.parquet) → 경로 반환.

    기본 metrics 는 _write_tv_summary 가 쓰는 TV 값과 5% 이내로 일치하도록
    잡았다(정확히 같은 값이 아니라 '허용오차 내 일치'를 검증). overrides 로 한
    지표를 5% 밖으로 밀어 FAIL-path 를 만든다.
    """
    metrics = {
        "final_equity": 10850.00,   # net_profit 850 vs tv 870 → 2.3%
        "initial_cash": 10000.0,
        "total_return": 0.0850,     # net_profit_pct 8.50 vs tv 8.70 → 2.3%
        "cagr": 0.17,
        "sharpe": 1.10,
        "sortino": 1.40,
        "max_drawdown": -0.0700,    # 7.00% vs tv 7.20% → 2.8%
        "calmar": 2.4,
        "n_trades": 24,             # vs tv 25 → abs 1
        "win_rate": 0.500,          # 50.0% vs tv 49.0% → 2.0%
        "profit_factor": 1.60,      # vs tv 1.58 → 1.3%
    }
    metrics.update(overrides)
    out = tmp_path / "supertrend_report"
    out.mkdir()
    with open(out / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f)
    # Both a long and a short round-trip (SuperTrend is futures long+short).
    df = pd.DataFrame(
        [
            {
                "entry_ts": "2024-02-03T05:00:00",
                "exit_ts": "2024-02-05T11:00:00",
                "side": "long",
                "qty": 0.045,
                "entry_price": 42800.0,
                "exit_price": 44100.0,   # TP hit
                "fee": 3.9,
                "pnl": 58.50,
            },
            {
                "entry_ts": "2024-03-12T18:00:00",
                "exit_ts": "2024-03-13T02:00:00",
                "side": "short",
                "qty": 0.041,
                "entry_price": 49000.0,
                "exit_price": 49800.0,   # SL hit
                "fee": 4.1,
                "pnl": -32.80,
            },
        ]
    )
    df.to_parquet(out / "trades.parquet")
    return out


def _write_tv_summary(tmp_path: Path) -> Path:
    """TradingView "Performance Summary" 형식의 합성 CSV → 경로 반환.

    label / "All USDT" / "All %" 3컬럼만으로 load_tv_summary 가 읽는 행을 채운다.
    """
    csv = (
        ",All USDT,All %\n"
        "Net Profit,870.0,8.70\n"
        "Total Closed Trades,25,\n"
        "Percent Profitable,,49.00\n"
        "Profit Factor,1.58,\n"
        "Max Drawdown,,-7.20\n"
    )
    path = tmp_path / "supertrend.tv_summary.csv"
    path.write_text(csv, encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────
# Fixtures sanity
# ─────────────────────────────────────────────────────────
def test_tw_report_has_long_and_short(tmp_path):
    out = _write_tw_report(tmp_path)
    df = pd.read_parquet(out / "trades.parquet")
    assert set(df["side"]) == {"long", "short"}


def test_tv_summary_parses(tmp_path):
    tv = load_tv_summary(_write_tv_summary(tmp_path))
    assert tv["net_profit"] == 870.0
    assert tv["net_profit_pct"] == 8.70
    assert tv["n_trades"] == 25
    assert tv["win_rate_pct"] == 49.00
    assert tv["profit_factor"] == 1.58
    assert tv["max_drawdown_pct"] == 7.20  # abs() of -7.20%


# ─────────────────────────────────────────────────────────
# compare_aggregate
# ─────────────────────────────────────────────────────────
def test_compare_pass(tmp_path):
    tw = load_tw_results(_write_tw_report(tmp_path))
    tv = load_tv_summary(_write_tv_summary(tmp_path))
    report = compare_aggregate(tw, tv, ParityTolerance(), "supertrend")
    assert report.passed
    md = render_markdown(report)
    assert "PASS" in md
    assert "| Metric |" in md


def test_compare_fail_one_metric_beyond_5pct(tmp_path):
    # net_profit 1500 vs tv 870 → ~72% off → FAIL (other metrics still within
    # tolerance, isolating a single out-of-tolerance metric).
    tw = load_tw_results(_write_tw_report(tmp_path, final_equity=11500.0))
    tv = load_tv_summary(_write_tv_summary(tmp_path))
    report = compare_aggregate(tw, tv, ParityTolerance(), "supertrend")
    assert not report.passed
    assert "FAIL" in render_markdown(report)


def test_compare_fail_n_trades_beyond_abs(tmp_path):
    # n_trades 28 vs tv 25 → abs 3 > 1 → FAIL on the trade-count tolerance.
    tw = load_tw_results(_write_tw_report(tmp_path, n_trades=28))
    tv = load_tv_summary(_write_tv_summary(tmp_path))
    report = compare_aggregate(tw, tv, ParityTolerance(), "supertrend")
    assert not report.passed
