"""scripts/diagnose_fills.py - inspect where fills land relative to OHLCV bars.

For a given strategy, take the latest reports/<strategy>_<ts>/ and for each
fill check:
  - Does fill_timestamp match a bar boundary (== some bar.close_ts)?
  - Is fill_price equal to the next-bar.open (slippage-tolerant)?
  - Is fill_price strictly inside the wick (not equal to open or close)?

Output reveals whether tick-synthesis is being USED in fill placement, or
if all fills are landing at bar boundaries (the latter is normal for
strategies that only use on_bar + market orders, like rsi_mean_reversion).

Usage:
    python scripts/diagnose_fills.py rsi_mean_reversion
    python scripts/diagnose_fills.py ema_market_sl_tp
    python scripts/diagnose_fills.py rsi_mean_reversion --max 30
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

REPORTS_DIR = Path("reports")
PRICE_TOL_REL = 5e-4   # 0.05% - tolerates 2bps default slippage with margin


def almost_eq(a: float, b: float) -> bool:
    return abs(a - b) <= max(1e-9, PRICE_TOL_REL * abs(b))


def main(strategy: str, max_rows: int) -> int:
    runs = sorted(
        REPORTS_DIR.glob(f"{strategy}_*"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not runs:
        print(f"[ERR] No reports/{strategy}_* found. Run a backtest first:")
        print(f"      python scripts/run_backtest.py --strategy {strategy}")
        return 1

    run = runs[0]
    print(f"=== analyzing {run} ===\n")

    fills_path = run / "fills.csv"
    if not fills_path.exists():
        print(f"[ERR] {fills_path} not found.")
        return 1
    fills = pd.read_csv(fills_path)  # timestamps parsed below (mixed precision)
    if fills.empty:
        print("[INFO] no fills in this run.")
        return 0

    snap = json.loads((run / "config_snapshot.json").read_text(encoding="utf-8"))
    src = Path(snap["source"])
    if not src.exists():
        print(f"[ERR] source not found: {src}")
        return 1
    df = pd.read_parquet(src)

    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    fills["timestamp"] = pd.to_datetime(fills["timestamp"], utc=True, format="ISO8601")

    bar_close_set = set(df.index)

    print(
        f"{'#':>3}  {'fill_ts':<28}  {'side':<5}  {'fill_px':>11}  "
        f"{'next.open':>11}  {'next.close':>11}  "
        f"{'==open':<7}  {'==close':<8}  {'boundary':<9}  inside_wick"
    )
    print("-" * 130)

    n = 0
    n_at_boundary = 0
    n_eq_next_open = 0
    n_eq_signal_close = 0
    n_inside_wick = 0
    show_n = min(len(fills), max_rows)

    for i, row in fills.iterrows():
        fill_ts = row["timestamp"]
        fill_px = float(row["price"])
        side = str(row["side"])
        n += 1

        is_boundary = fill_ts in bar_close_set

        # Bar whose first tick fills this order: smallest bar_close > fill_ts
        later = df.index[df.index > fill_ts]
        next_bar_ts = later[0] if len(later) > 0 else df.index[-1]
        next_bar = df.loc[next_bar_ts]

        # Signal bar: the bar whose close == fill_ts (only if boundary)
        signal_close = None
        if is_boundary:
            sig = df.loc[fill_ts]
            signal_close = float(sig["close"])

        eq_next_open = almost_eq(fill_px, float(next_bar["open"]))
        eq_signal_close = (signal_close is not None and almost_eq(fill_px, signal_close))
        in_range = (
            float(next_bar["low"]) - 1e-9 <= fill_px <= float(next_bar["high"]) + 1e-9
        )
        eq_next_close = almost_eq(fill_px, float(next_bar["close"]))
        inside_wick = in_range and not eq_next_open and not eq_next_close

        if is_boundary:
            n_at_boundary += 1
        if eq_next_open:
            n_eq_next_open += 1
        if eq_signal_close:
            n_eq_signal_close += 1
        if inside_wick:
            n_inside_wick += 1

        if i < show_n:
            print(
                f"{i:>3}  {fill_ts}  {side:<5}  {fill_px:>11.4f}  "
                f"{float(next_bar['open']):>11.4f}  {float(next_bar['close']):>11.4f}  "
                f"{str(eq_next_open):<7}  {str(eq_next_close):<8}  "
                f"{str(is_boundary):<9}  {inside_wick}"
            )

    if len(fills) > show_n:
        print(f"... ({len(fills) - show_n} more rows; pass --max {len(fills)} to see all)")

    pct = lambda x: f"{x}/{n}  ({100 * x / n:5.1f}%)"
    print("\n=== summary ===")
    print(f"  fill_ts == some bar boundary (== bar.close_ts)  : {pct(n_at_boundary)}")
    print(f"  fill_px ~= next_bar.open  (slippage-tolerant)    : {pct(n_eq_next_open)}")
    print(f"  fill_px ~= signal_bar.close                       : {pct(n_eq_signal_close)}")
    print(f"  fill_px strictly inside wick (not open, not close): {pct(n_inside_wick)}")

    print("\n=== interpretation ===")
    if n_at_boundary == n and n_eq_next_open == n:
        print("  ALL fills at bar boundary, ALL prices ~= next bar's open.")
        print("  -> Strategy uses ONLY on_bar + market orders. Tick synthesis runs")
        print("     every bar but its sub-bar prices are not consulted for fills.")
        print("     This is the expected pattern for rsi_mean_reversion.")
    elif n_inside_wick > 0:
        print(f"  {n_inside_wick} fills land strictly inside a wick (price != O, != C).")
        print("  -> Tick synthesis IS firing fills at sub-bar prices.")
        print("     Strategy is using on_tick or LIMIT/STOP intra-bar.")
    else:
        print("  Mixed pattern. Inspect rows above to understand individual fills.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("strategy", help="strategy name (e.g. rsi_mean_reversion)")
    ap.add_argument("--max", type=int, default=20, help="max rows to print (default 20)")
    args = ap.parse_args()
    sys.exit(main(args.strategy, args.max))
