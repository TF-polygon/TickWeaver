"""HTML 리포트 — 단일 self-contained html (이미지는 PNG 첨부)."""

from __future__ import annotations

import html
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from tickweaver.analytics.equity_curve import plot_equity, plot_sample_ticks
from tickweaver.analytics.metrics import compute_metrics
from tickweaver.analytics.trades import extract_trades, trades_to_df
from tickweaver.engine.backtest_engine import BacktestResult


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>tickweaver report</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; margin: 24px; max-width: 1100px; }}
  h1 {{ color: #2A6FDB; border-bottom: 2px solid #2A6FDB; padding-bottom: 6px; }}
  h2 {{ color: #444; margin-top: 28px; }}
  table {{ border-collapse: collapse; margin: 8px 0 16px 0; }}
  th, td {{ padding: 6px 12px; border: 1px solid #ddd; text-align: left; font-size: 14px; }}
  th {{ background: #f4f6fa; }}
  .metric-table td:nth-child(2) {{ font-family: 'Consolas', monospace; text-align: right; }}
  .small {{ color: #888; font-size: 12px; }}
  img {{ max-width: 100%; border: 1px solid #eee; border-radius: 4px; }}
</style>
</head>
<body>
<h1>tickweaver — backtest report</h1>
<p class="small">strategy: <code>{strategy}</code><br>
source: <code>{source}</code><br>
config: <code>{config}</code></p>

<h2>Metrics</h2>
{metrics_table}

<h2>Equity curve</h2>
<img src="equity_curve.png" alt="equity curve">

<h2>Tick Synthesis (proof)</h2>
{tick_summary_table}
{sample_ticks_block}

<h2>Trades</h2>
<p>총 {n_trades} 건 (상위 50 건 표시)</p>
{trades_table}

</body>
</html>
"""


def _metrics_table(metrics: dict[str, Any]) -> str:
    rows = []
    pretty = {
        "final_equity": "Final Equity",
        "initial_cash": "Initial Cash",
        "total_return": "Total Return",
        "cagr": "CAGR",
        "sharpe": "Sharpe",
        "sortino": "Sortino",
        "max_drawdown": "Max Drawdown",
        "calmar": "Calmar",
        "n_trades": "Trades",
        "win_rate": "Win rate",
        "profit_factor": "Profit factor",
    }
    for k, label in pretty.items():
        v = metrics.get(k, "")
        if isinstance(v, float):
            if k in ("total_return", "cagr", "max_drawdown", "win_rate"):
                v_str = f"{v * 100:+.2f}%"
            elif k == "profit_factor" and v == float("inf"):
                v_str = "inf"
            else:
                v_str = f"{v:.4f}"
        else:
            v_str = str(v)
        rows.append(f"<tr><td>{label}</td><td>{v_str}</td></tr>")
    return "<table class='metric-table'>" + "\n".join(rows) + "</table>"


def _tick_summary_table(ts) -> str:
    d = asdict(ts)
    rows = []
    for k, v in d.items():
        if isinstance(v, float):
            v_str = f"{v:.2f}"
        else:
            v_str = str(v)
        rows.append(f"<tr><td>{html.escape(k)}</td><td>{html.escape(v_str)}</td></tr>")
    return "<table class='metric-table'>" + "\n".join(rows) + "</table>"


def _trades_table(trades_df: pd.DataFrame) -> str:
    if trades_df.empty:
        return "<p class='small'>(체결된 trade 없음)</p>"
    head = trades_df.head(50)
    return head.to_html(index=False, classes="trades", border=0)


def save_report(result: BacktestResult, out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 가공
    trades = extract_trades(result.fills)
    trades_df = trades_to_df(trades)
    metrics = compute_metrics(result.equity_curve, trades, result.initial_cash)

    # 데이터 산출물
    result.equity_curve.to_parquet(out_dir / "equity.parquet")
    if not trades_df.empty:
        trades_df.to_parquet(out_dir / "trades.parquet")
    # Raw fills (csv for inspectability) — used by scripts/diagnose_fills.py.
    if result.fills:
        fills_rows = []
        for f in result.fills:
            fills_rows.append(
                {
                    "order_id": f.order_id,
                    "symbol": f.symbol,
                    "side": f.side.value if hasattr(f.side, "value") else str(f.side),
                    "qty": float(f.qty),
                    "price": float(f.price),
                    "fee": float(f.fee),
                    "timestamp": f.timestamp.isoformat(),
                    "pnl_realized": float(f.pnl_realized),
                }
            )
        pd.DataFrame(fills_rows).to_csv(out_dir / "fills.csv", index=False)
    with open(out_dir / "metrics.json", "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2, default=str)
    with open(out_dir / "tick_summary.json", "w", encoding="utf-8") as f:
        json.dump(asdict(result.tick_summary), f, ensure_ascii=False, indent=2)
    if result.sample_ticks is not None and not result.sample_ticks.empty:
        result.sample_ticks.to_parquet(out_dir / "sample_ticks.parquet")

    # 플롯
    plot_equity(result.equity_curve, out_dir / "equity_curve.png")
    if result.sample_ticks is not None and not result.sample_ticks.empty:
        plot_sample_ticks(result.sample_ticks, out_dir / "sample_tick_paths.png")

    # HTML
    snap = result.config_snapshot
    sample_block = ""
    if result.sample_ticks is not None and not result.sample_ticks.empty:
        sample_block = '<img src="sample_tick_paths.png" alt="sample tick paths">'

    html_content = _HTML_TEMPLATE.format(
        strategy=html.escape(str(snap.get("strategy_path", ""))),
        source=html.escape(str(snap.get("source", ""))),
        config=html.escape(json.dumps(snap.get("config", {}), ensure_ascii=False)[:200] + "..."),
        metrics_table=_metrics_table(metrics),
        tick_summary_table=_tick_summary_table(result.tick_summary),
        sample_ticks_block=sample_block,
        n_trades=metrics.get("n_trades", 0),
        trades_table=_trades_table(trades_df),
    )
    (out_dir / "report.html").write_text(html_content, encoding="utf-8")

    return metrics
