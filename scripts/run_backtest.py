"""scripts/run_backtest.py - D17 simplified CLI.

Only --strategy is required; everything else has defaults.
--strategy auto-resolves: 'rsi_mean_reversion' -> strategies/rsi_mean_reversion.py.

Examples:
    python scripts/run_backtest.py --strategy rsi_mean_reversion
    python scripts/run_backtest.py --strategy strategies/my_alpha.py --out-dir reports/run01
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

import typer  # noqa: E402

from tickweaver.engine.runner import run_backtest  # noqa: E402
from tickweaver.utils.paths import resolve_strategy_path  # noqa: E402

app = typer.Typer(add_completion=False, help="tickweaver backtest runner (D17)")


@app.command()
def main(
    strategy: str = typer.Option(
        ...,
        "--strategy",
        "-s",
        help="strategy: 'rsi' / 'rsi.py' / 'strategies/rsi.py' / abs path. "
             "Auto-resolves under strategies/ if no separator.",
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        "-o",
        help="output dir; defaults to reports/<strategy>_<UTC ts>/",
    ),
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="backtest config yaml; defaults to configs/backtest/default.yaml",
    ),
    source: Path | None = typer.Option(
        None,
        "--source",
        help="OHLCV parquet path; defaults to latest mtime under data/processed/",
    ),
    params: Path | None = typer.Option(
        None,
        "--params",
        help="strategy params .json (defaults to <strategy>.json auto pairing)",
    ),
    dump_ticks: int = typer.Option(
        0,
        "--dump-ticks",
        help="dump synthesized ticks for N sample bars",
    ),
    no_auto_period: bool = typer.Option(
        False,
        "--no-auto-period",
        help="disable auto-period",
    ),
    no_progress: bool = typer.Option(
        False,
        "--no-progress",
        help="disable tqdm progress bar (auto-disabled on non-tty)",
    ),
) -> None:
    """Run a backtest."""
    resolved = resolve_strategy_path(strategy)
    if str(resolved) != strategy:
        typer.echo(f"resolved --strategy: {strategy} -> {resolved}")
    result = run_backtest(
        strategy_path=resolved,
        out_dir=out_dir,
        config_path=config,
        source=source,
        params_path=params,
        dump_ticks=dump_ticks,
        auto_period=not no_auto_period,
        show_progress=not no_progress,
    )
    typer.echo(
        f"\nfinal_equity = {result.final_equity:.2f} "
        f"(initial = {result.initial_cash:.2f}, "
        f"return = {(result.final_equity / result.initial_cash - 1.0) * 100:+.2f}%)"
    )


if __name__ == "__main__":
    app()
