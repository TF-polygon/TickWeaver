"""Equity curve 플롯 helpers (matplotlib)."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless

import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402


def plot_equity(equity_curve: pd.DataFrame, out_path: Path) -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

    eq = equity_curve["equity"]
    axes[0].plot(eq.index, eq.values, color="#2A6FDB", linewidth=1.2)
    axes[0].set_title("Equity Curve")
    axes[0].set_ylabel("equity")
    axes[0].grid(alpha=0.3)

    peak = eq.cummax()
    drawdown = (eq - peak) / peak
    axes[1].fill_between(eq.index, drawdown.values, 0, color="#D9534F", alpha=0.5)
    axes[1].set_title("Drawdown")
    axes[1].set_ylabel("drawdown")
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)


def plot_sample_ticks(sample_ticks: pd.DataFrame, out_path: Path) -> None:
    """샘플 봉의 합성 tick 경로 시각화 (M6.3)."""
    fig, ax = plt.subplots(figsize=(10, 5))
    if sample_ticks is not None and not sample_ticks.empty:
        for bar_idx, group in sample_ticks.groupby("bar_index"):
            ax.plot(
                group.index,
                group["price"].values,
                marker="o",
                markersize=2.5,
                linewidth=0.8,
                label=f"bar #{bar_idx}",
            )
        ax.legend(loc="best", fontsize=8)
    ax.set_title("Sample synthesized tick paths")
    ax.set_ylabel("price")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
