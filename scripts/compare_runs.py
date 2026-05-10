"""scripts/compare_runs.py — uniform vs bridge comparison (D16 — only here).

Two subcommands:
  preview   : single bar with uniform vs bridge tick paths drawn together (PNG)
  backtest  : same data + strategy, run with both generators, show metrics diff

Examples:
  python scripts/compare_runs.py preview --o 100 --h 110 --l 90 --c 105 --n 64 --seed 42
  python scripts/compare_runs.py backtest --strategy strategies/ema_cross.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import typer  # noqa: E402

from tickweaver.core.types import OHLCBar  # noqa: E402
from tickweaver.engine.runner import run_backtest  # noqa: E402
from tickweaver.tick_synthesis.generator import get_tick_generator  # noqa: E402
from tickweaver.utils.paths import resolve_strategy_path  # noqa: E402

app = typer.Typer(add_completion=False, help="uniform vs bridge comparison (D16)")


@app.command(name="preview")
def preview_cmd(
    o: float = typer.Option(100.0, "--o", help="open"),
    h: float = typer.Option(110.0, "--h", help="high"),
    l: float = typer.Option(90.0, "--l", help="low"),
    c: float = typer.Option(105.0, "--c", help="close"),
    n: int = typer.Option(64, "--n", help="number of ticks"),
    seed: int = typer.Option(42, "--seed"),
    timeframe: str = typer.Option("1h", "--timeframe"),
    out: Path = typer.Option(Path("compare_preview.png"), "--out"),
) -> None:
    """Plot one bar's tick path under both generators side by side."""
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=o, high=h, low=l, close=c,
        volume=1.0, symbol="PREVIEW", timeframe=timeframe,
    )
    u = get_tick_generator("uniform").generate(
        bar, n_ticks=n, rng=np.random.default_rng(seed)
    )
    b = get_tick_generator("bridge").generate(
        bar, n_ticks=n, rng=np.random.default_rng(seed)
    )

    fig, ax = plt.subplots(figsize=(11, 5))
    u_t = [t.timestamp for t in u]
    u_p = [t.price for t in u]
    b_t = [t.timestamp for t in b]
    b_p = [t.price for t in b]
    ax.plot(u_t, u_p, marker="o", markersize=2.5, linewidth=0.8,
            color="#2A6FDB", label="uniform")
    ax.plot(b_t, b_p, marker="o", markersize=2.5, linewidth=0.8,
            color="#D9534F", label="bridge")
    ax.axhline(h, color="#888", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.axhline(l, color="#888", linestyle="--", linewidth=0.5, alpha=0.5)
    ax.set_title(f"uniform vs bridge  (O={o}, H={h}, L={l}, C={c}, n={n}, seed={seed})")
    ax.set_ylabel("price")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out, dpi=110)
    plt.close(fig)
    typer.echo(f"saved {out}")


def _load_metrics(out_dir: Path) -> dict:
    with open(out_dir / "metrics.json", encoding="utf-8") as f:
        return json.load(f)


def _format_diff_row(label: str, u_val, b_val, fmt: str = "{:.4f}") -> str:
    def _f(v):
        if isinstance(v, float):
            return fmt.format(v)
        return str(v)
    return f"  {label:<18}  {_f(u_val):>14}  {_f(b_val):>14}"


@app.command(name="backtest")
def backtest_cmd(
    strategy: Path = typer.Option(..., "--strategy", "-s"),
    config: Path | None = typer.Option(None, "--config", "-c"),
    source: Path | None = typer.Option(None, "--source"),
    params: Path | None = typer.Option(None, "--params"),
    out_root: Path = typer.Option(
        Path("reports"), "--out-root",
        help="root dir; sub-dirs <strategy>_uniform / <strategy>_bridge created",
    ),
) -> None:
    """Run the same strategy twice (uniform / bridge) and print metrics diff."""
    resolved = resolve_strategy_path(strategy)
    if resolved != strategy:
        typer.echo(f"resolved --strategy: {strategy} -> {resolved}")
    stem = Path(resolved).stem
    u_dir = out_root / f"{stem}_uniform"
    b_dir = out_root / f"{stem}_bridge"

    u_res = run_backtest(
        strategy_path=resolved, out_dir=u_dir, config_path=config,
        source=source, params_path=params, generator_override="uniform",
    )
    b_res = run_backtest(
        strategy_path=resolved, out_dir=b_dir, config_path=config,
        source=source, params_path=params, generator_override="bridge",
    )

    u_m = _load_metrics(u_dir)
    b_m = _load_metrics(b_dir)

    typer.echo("")
    typer.echo("metric              uniform        bridge")
    typer.echo("------------------  -------------  -------------")
    for key in (
        "final_equity",
        "total_return",
        "cagr",
        "sharpe",
        "sortino",
        "max_drawdown",
        "calmar",
        "n_trades",
        "win_rate",
        "profit_factor",
    ):
        typer.echo(_format_diff_row(key, u_m.get(key, "-"), b_m.get(key, "-")))

    typer.echo("")
    typer.echo(f"uniform  -> {u_dir}")
    typer.echo(f"bridge   -> {b_dir}")


if __name__ == "__main__":
    app()
