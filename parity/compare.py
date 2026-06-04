"""Shared parity-comparison harness (TickWeaver vs TradingView).

This module is a CONTRACT: the EMA-cross track and any future parity track map
both sides into ONE normalized aggregate dict and compare with a single
tolerance policy. The normalized keys are the single source of truth:

    initial_cash, final_equity, net_profit, net_profit_pct,
    n_trades, win_rate_pct, profit_factor, max_drawdown_pct

Tolerance policy (MEDIUM): every numeric metric is compared with a relative
percentage tolerance EXCEPT ``n_trades`` which uses an absolute tolerance.

CLI:
    python -m parity.compare --strategy ema_cross \
        --tw-report reports/ema_cross_<ts> \
        --tv-summary parity/reference/ema_cross.tv_summary.sample.csv \
        [--tv-trades parity/reference/ema_cross.tv_trades.sample.csv] \
        [--pct 0.05]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Compare in this order; only keys present in BOTH sides are compared.
NORMALIZED_KEYS: tuple[str, ...] = (
    "initial_cash",
    "final_equity",
    "net_profit",
    "net_profit_pct",
    "n_trades",
    "win_rate_pct",
    "profit_factor",
    "max_drawdown_pct",
)

_EPS = 1e-9


# ─────────────────────────────────────────────────────────
# Dataclasses (contract)
# ─────────────────────────────────────────────────────────
@dataclass
class ParityTolerance:
    pct: float = 0.05  # relative tolerance for value/ratio metrics
    n_trades_abs: int = 1  # absolute tolerance for trade count


@dataclass
class MetricRow:
    name: str
    tw: float
    tv: float
    abs_diff: float
    pct_diff: float
    within_tol: bool


@dataclass
class ParityReport:
    strategy: str
    rows: list[MetricRow] = field(default_factory=list)
    passed: bool = True


# ─────────────────────────────────────────────────────────
# TickWeaver loaders
# ─────────────────────────────────────────────────────────
def load_tw_results(report_dir: Path) -> dict:
    """Load ``metrics.json`` and map it into the normalized aggregate dict."""
    report_dir = Path(report_dir)
    with open(report_dir / "metrics.json", encoding="utf-8") as f:
        m = json.load(f)

    initial_cash = float(m["initial_cash"])
    final_equity = float(m["final_equity"])
    pf = m.get("profit_factor", 0.0)
    profit_factor = float("inf") if _is_inf_like(pf) else float(pf)

    return {
        "initial_cash": initial_cash,
        "final_equity": final_equity,
        "net_profit": final_equity - initial_cash,
        "net_profit_pct": float(m["total_return"]) * 100.0,
        "n_trades": int(m["n_trades"]),
        "win_rate_pct": float(m["win_rate"]) * 100.0,
        "profit_factor": profit_factor,
        "max_drawdown_pct": abs(float(m["max_drawdown"])) * 100.0,
    }


def load_tw_trades(report_dir: Path) -> pd.DataFrame:
    """Load ``trades.parquet`` (raw TickWeaver trade schema)."""
    return pd.read_parquet(Path(report_dir) / "trades.parquet")


# ─────────────────────────────────────────────────────────
# TradingView loaders
# ─────────────────────────────────────────────────────────
def load_tv_summary(csv_path: Path) -> dict:
    """Parse a TradingView "Performance Summary" CSV → normalized dict.

    Resilient to extra rows/columns. Column 0 is the metric label; values are
    read from an ``All USDT`` (value) or ``All %`` (percent) column, matched
    case-insensitively by substring.
    """
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    label_col = df.columns[0]
    usdt_col = _find_col(df, "all usdt") or _find_col(df, "all", exclude="%")
    pct_col = _find_col(df, "all %")

    def val(label_sub: str, *cols: str | None) -> float | None:
        row = _find_row(df, label_col, label_sub)
        if row is None:
            return None
        for col in cols:
            if col is None:
                continue
            v = _to_float(row[col])
            if v is not None:
                return v
        return None

    out: dict = {}
    np_usdt = val("net profit", usdt_col)
    np_pct = val("net profit", pct_col)
    if np_usdt is not None:
        out["net_profit"] = np_usdt
    if np_pct is not None:
        out["net_profit_pct"] = np_pct
    n = val("total closed trades", usdt_col, pct_col)
    if n is not None:
        out["n_trades"] = int(round(n))
    wr = val("percent profitable", pct_col, usdt_col)
    if wr is not None:
        out["win_rate_pct"] = wr
    pf = val("profit factor", usdt_col, pct_col)
    if pf is not None:
        out["profit_factor"] = pf
    dd = val("max drawdown", pct_col, usdt_col)
    if dd is not None:
        out["max_drawdown_pct"] = abs(dd)
    return out


def load_tv_trades(csv_path: Path) -> pd.DataFrame:
    """Parse a TradingView "List of Trades" CSV → normalized round-trip frame.

    Output columns: entry_ts, exit_ts, side, qty, entry_price, exit_price, pnl.
    Two rows per round-trip (entry + exit) are paired by ``Trade #``; the exit
    row carries the realized profit.
    """
    df = pd.read_csv(csv_path, dtype=str).fillna("")
    tnum_col = _find_col(df, "trade #") or df.columns[0]
    type_col = _find_col(df, "type")
    dt_col = _find_col(df, "date/time") or _find_col(df, "date")
    price_col = _find_col(df, "price")
    qty_col = _find_col(df, "contracts") or _find_col(df, "qty")
    profit_col = (
        _find_col(df, "profit usdt")
        or _find_col(df, "net pnl usdt")  # OKX / newer TradingView export header
        or _find_col(df, "net pnl")
        or _find_col(df, "profit")
    )

    trades: dict[str, dict] = {}
    for _, r in df.iterrows():
        tnum = str(r[tnum_col]).strip()
        if not tnum:
            continue
        typ = str(r[type_col]).strip().lower()
        rec = trades.setdefault(tnum, {})
        if "entry" in typ:
            rec["side"] = "short" if "short" in typ else "long"
            rec["entry_ts"] = str(r[dt_col]).strip()
            rec["entry_price"] = _to_float(r[price_col])
            rec["qty"] = _to_float(r[qty_col])
        elif "exit" in typ:
            rec["exit_ts"] = str(r[dt_col]).strip()
            rec["exit_price"] = _to_float(r[price_col])
            rec["pnl"] = _to_float(r[profit_col])

    rows = []
    for tnum in sorted(trades, key=_safe_int):
        rec = trades[tnum]
        rows.append(
            {
                "entry_ts": pd.to_datetime(rec.get("entry_ts"), errors="coerce"),
                "exit_ts": pd.to_datetime(rec.get("exit_ts"), errors="coerce"),
                "side": rec.get("side"),
                "qty": rec.get("qty"),
                "entry_price": rec.get("entry_price"),
                "exit_price": rec.get("exit_price"),
                "pnl": rec.get("pnl"),
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "entry_ts",
            "exit_ts",
            "side",
            "qty",
            "entry_price",
            "exit_price",
            "pnl",
        ],
    )


def aggregate_from_tv_trades(trades: pd.DataFrame, initial_cash: float) -> dict:
    """Derive the normalized aggregate dict from a parsed TradingView List of
    Trades, for when the user exports only "List of Trades" (no Performance
    Summary). ``trades`` is the frame returned by :func:`load_tv_trades`.
    """
    pnl = pd.to_numeric(trades["pnl"], errors="coerce").dropna()
    n = int(len(pnl))
    net = float(pnl.sum())
    wins = pnl[pnl > 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-pnl[pnl <= 0].sum())
    return {
        "initial_cash": float(initial_cash),
        "final_equity": float(initial_cash) + net,
        "net_profit": net,
        "net_profit_pct": (net / initial_cash * 100.0) if initial_cash else 0.0,
        "n_trades": n,
        "win_rate_pct": (len(wins) / n * 100.0) if n else 0.0,
        "profit_factor": (gross_profit / gross_loss) if gross_loss > 0 else float("inf"),
    }


# ─────────────────────────────────────────────────────────
# Comparison
# ─────────────────────────────────────────────────────────
def compare_aggregate(
    tw: dict, tv: dict, tol: ParityTolerance, strategy: str
) -> ParityReport:
    """Compare normalized aggregate dicts → ParityReport.

    Only keys present in BOTH dicts are compared. ``n_trades`` uses the absolute
    tolerance; everything else uses the relative percentage tolerance.
    """
    report = ParityReport(strategy=strategy)
    for key in NORMALIZED_KEYS:
        if key not in tw or key not in tv:
            continue
        tw_v = float(tw[key])
        tv_v = float(tv[key])
        abs_diff, pct_diff, within = _diff(key, tw_v, tv_v, tol)
        report.rows.append(MetricRow(key, tw_v, tv_v, abs_diff, pct_diff, within))
        if not within:
            report.passed = False
    return report


def _diff(
    key: str, tw_v: float, tv_v: float, tol: ParityTolerance
) -> tuple[float, float, bool]:
    # Infinity handling (e.g. profit_factor with zero gross loss).
    tw_inf, tv_inf = math.isinf(tw_v), math.isinf(tv_v)
    if tw_inf or tv_inf:
        if tw_inf and tv_inf and (tw_v > 0) == (tv_v > 0):
            return 0.0, 0.0, True
        return float("inf"), float("inf"), False

    abs_diff = abs(tw_v - tv_v)
    if abs(tv_v) < _EPS:
        pct_diff = 0.0 if abs(tw_v) < _EPS else float("inf")
    else:
        pct_diff = abs_diff / abs(tv_v) * 100.0

    if key == "n_trades":
        within = abs_diff <= tol.n_trades_abs
    else:
        within = (pct_diff / 100.0) <= tol.pct
    return abs_diff, pct_diff, within


# ─────────────────────────────────────────────────────────
# Rendering
# ─────────────────────────────────────────────────────────
def render_markdown(report: ParityReport) -> str:
    lines = [
        f"# Parity report — {report.strategy}",
        "",
        "| Metric | TickWeaver | TradingView | Δ abs | Δ % | OK |",
        "| --- | ---: | ---: | ---: | ---: | :---: |",
    ]
    for row in report.rows:
        lines.append(
            f"| {row.name} | {_fmt(row.tw)} | {_fmt(row.tv)} | "
            f"{_fmt(row.abs_diff)} | {_fmt_pct(row.pct_diff)} | "
            f"{'OK' if row.within_tol else 'X'} |"
        )
    lines.append("")
    lines.append(f"**{'PASS' if report.passed else 'FAIL'}**")
    return "\n".join(lines)


def _fmt(v: float) -> str:
    if isinstance(v, float) and math.isinf(v):
        return "inf"
    if float(v).is_integer():
        return str(int(v))
    return f"{v:.4f}"


def _fmt_pct(v: float) -> str:
    if math.isinf(v):
        return "inf"
    return f"{v:.2f}%"


# ─────────────────────────────────────────────────────────
# Small parsing helpers
# ─────────────────────────────────────────────────────────
def _find_col(df: pd.DataFrame, sub: str, exclude: str | None = None) -> str | None:
    sub = sub.lower()
    for c in df.columns:
        cl = str(c).lower()
        if sub in cl and (exclude is None or exclude not in cl):
            return c
    return None


def _find_row(df: pd.DataFrame, label_col: str, sub: str) -> pd.Series | None:
    sub = sub.lower()
    for _, r in df.iterrows():
        if sub in str(r[label_col]).lower():
            return r
    return None


def _to_float(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace(",", "").replace("%", "").replace("$", "")
    if s == "" or s.lower() in {"nan", "n/a", "none"}:
        return None
    if s in {"∞", "inf", "+inf"}:
        return float("inf")
    try:
        return float(s)
    except ValueError:
        return None


def _is_inf_like(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in {"inf", "infinity", "+inf", "∞"}
    try:
        return math.isinf(float(v))
    except (TypeError, ValueError):
        return False


def _safe_int(s: str) -> int:
    try:
        return int(str(s).strip())
    except ValueError:
        return 0


# ─────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TickWeaver ↔ TradingView parity check")
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--tw-report", required=True, type=Path)
    parser.add_argument("--tv-summary", required=True, type=Path)
    parser.add_argument("--tv-trades", type=Path, default=None)
    parser.add_argument("--pct", type=float, default=0.05)
    args = parser.parse_args(argv)

    # Markdown uses non-ASCII (Δ, —); avoid cp949 crashes on Windows consoles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    tw = load_tw_results(args.tw_report)
    tv = load_tv_summary(args.tv_summary)
    tol = ParityTolerance(pct=args.pct)
    report = compare_aggregate(tw, tv, tol, args.strategy)

    print(render_markdown(report))

    # Optional cross-check: independent round-trip count from the List of Trades,
    # so the user can eyeball it against the summary's Total Closed Trades.
    if args.tv_trades is not None:
        n_listed = len(load_tv_trades(args.tv_trades))
        print(f"\nList of Trades round-trips: {n_listed}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
