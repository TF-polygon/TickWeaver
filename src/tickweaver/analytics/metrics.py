"""성과 지표 — Sharpe / Sortino / MDD / Calmar / win_rate / profit_factor."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from tickweaver.analytics.trades import Trade


def _periods_per_year_from_index(idx: pd.DatetimeIndex) -> float:
    if len(idx) < 2:
        return 252.0
    diffs = idx.to_series().diff().dropna()
    median_sec = float(diffs.dt.total_seconds().median())
    if median_sec <= 0:
        return 252.0
    return 365.25 * 24 * 3600 / median_sec


def _compute_from_equity_and_trades(
    equity_curve: pd.DataFrame,
    trades: list[Trade],
    initial_cash: float,
) -> dict[str, Any]:
    """Stateless core: equity curve + closed trades + initial cash → metrics dict.

    Pure function; safe to call repeatedly with partial slices. Both
    :func:`compute_metrics` (batch) and :func:`compute_metrics_incremental`
    (streaming) delegate here, so a progressive N-call final-step result is
    floating-point exact with the batch 1-call result.
    """
    if equity_curve.empty:
        return {
            "final_equity": initial_cash,
            "total_return": 0.0,
            "sharpe": 0.0,
            "sortino": 0.0,
            "max_drawdown": 0.0,
            "calmar": 0.0,
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "cagr": 0.0,
        }

    eq = equity_curve["equity"].astype(float)
    final_equity = float(eq.iloc[-1])
    total_return = (final_equity / initial_cash) - 1.0

    # returns
    ret = eq.pct_change().dropna()

    ppy = _periods_per_year_from_index(equity_curve.index)
    sharpe = 0.0
    sortino = 0.0
    if not ret.empty and ret.std() > 0:
        sharpe = float(ret.mean() / ret.std() * math.sqrt(ppy))
    downside = ret[ret < 0]
    if not downside.empty and downside.std() > 0:
        sortino = float(ret.mean() / downside.std() * math.sqrt(ppy))

    # max drawdown
    running_peak = eq.cummax()
    drawdown = (eq - running_peak) / running_peak
    max_dd = float(drawdown.min()) if not drawdown.empty else 0.0

    # CAGR — guard against degenerate spans (1-row equity / zero-duration index).
    # Annualization is undefined for ≤1 sample, and `years≈0` overflows `**1/years`.
    # Fall back to `total_return` (the only meaningful realized return on a point).
    n_seconds = (equity_curve.index[-1] - equity_curve.index[0]).total_seconds()
    if len(equity_curve) < 2 or n_seconds <= 0:
        cagr = total_return
    else:
        years = n_seconds / (365.25 * 24 * 3600)
        cagr = (final_equity / initial_cash) ** (1.0 / years) - 1.0 if final_equity > 0 else -1.0

    calmar = (cagr / abs(max_dd)) if max_dd < 0 else 0.0

    # trades
    n_trades = len(trades)
    if n_trades > 0:
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        win_rate = len(wins) / n_trades
        gross_profit = sum(t.pnl for t in wins) if wins else 0.0
        gross_loss = abs(sum(t.pnl for t in losses)) if losses else 0.0
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float("inf")
    else:
        win_rate = 0.0
        profit_factor = 0.0

    return {
        "final_equity": final_equity,
        "initial_cash": initial_cash,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "n_trades": n_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
    }


def compute_metrics(
    equity_curve: pd.DataFrame,
    trades: list[Trade],
    initial_cash: float,
) -> dict[str, Any]:
    """Batch metrics (back-compat). Thin wrapper over the stateless core."""
    return _compute_from_equity_and_trades(equity_curve, trades, initial_cash)


def compute_metrics_incremental(
    closed_trades: list[Trade],
    equity_snapshot: pd.DataFrame,
    initial_cash: float,
) -> dict[str, Any]:
    """Stateless progressive caller for streaming / viz panels.

    Same computation as :func:`compute_metrics` but with the streaming-friendly
    argument order ``(closed_trades, equity_snapshot, initial_cash)``. Safe to
    call repeatedly with partial slices; the final-step result (full equity
    curve + all closed trades) is floating-point exact with the batch
    :func:`compute_metrics` call (both delegate to the same stateless core).

    Args:
        closed_trades: Round-trip trades closed so far. Matches
            :func:`tickweaver.analytics.trades.extract_trades` output
            semantics — open positions are excluded by the caller.
        equity_snapshot: Equity curve up to the current tick. May be a
            partial slice; no state is retained between calls.
        initial_cash: Initial cash for return / CAGR calculations.
    """
    return _compute_from_equity_and_trades(equity_snapshot, closed_trades, initial_cash)
