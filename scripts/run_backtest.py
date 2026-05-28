"""scripts/run_backtest.py - tickweaver backtest CLI.

The yaml config (configs/<env>.yaml) fully defines the environment.
The strategy .py owns trading parameters. No json side-files.

Usage:
    python scripts/run_backtest.py --strategy rsi_mean_reversion
    python scripts/run_backtest.py --strategy rsi_mean_reversion --config btc_4h.yaml
    python scripts/run_backtest.py --strategy ema_market_sl_tp --viz

--config accepts:
    - bare filename like "btc_4h.yaml"  -> resolved under configs/
    - path with separator              -> used as given
    - absolute path                    -> used as given
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT / "src"))

import typer  # noqa: E402

from tickweaver.engine.runner import run_backtest  # noqa: E402
from tickweaver.utils.paths import CONFIGS_DIR, resolve_strategy_path  # noqa: E402

app = typer.Typer(add_completion=False, help="tickweaver backtest runner")


def _resolve_config_path(raw: str | Path | None) -> Path | None:
    """Resolve --config argument with configs/ default prefix.

    Rules:
      - None: caller (runner) uses DEFAULT_BACKTEST_CONFIG
      - absolute path: used as given
      - contains path separator: used as given (relative to cwd)
      - bare filename (e.g. "btc_4h.yaml"): looked up under configs/
    """
    if raw is None:
        return None
    p = Path(raw)
    if p.is_absolute():
        return p
    s = str(raw)
    if "/" in s or "\\" in s:
        return p
    # bare filename -> configs/
    return CONFIGS_DIR / p


@app.command()
def main(
    strategy: str = typer.Option(
        ...,
        "--strategy",
        "-s",
        help="strategy name / .py / strategies/.py / abs path. "
             "Auto-resolves under strategies/ when no separator.",
    ),
    config: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help="backtest yaml. bare filename resolves under configs/. "
             "Defaults to configs/default.yaml.",
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        "-o",
        help="output dir; defaults to reports/<strategy>_<UTC ts>/",
    ),
    dump_ticks: int = typer.Option(
        0,
        "--dump-ticks",
        help="dump synthesized ticks for N sample bars",
    ),
    no_progress: bool = typer.Option(
        False,
        "--no-progress",
        help="disable tqdm progress bar (auto-disabled on non-tty)",
    ),
    viz: bool = typer.Option(
        False,
        "--viz",
        help="open a finplot replay window after the backtest finishes "
             "(requires: pip install -r requirements-viz.txt)",
    ),
    stream: bool = typer.Option(
        False,
        "--stream",
        help="with --viz, replay the backtest as a live streaming animation "
             "(candles grow tick by tick, with playback controls) instead of "
             "the static all-at-once replay. No effect without --viz.",
    ),
) -> None:
    """Run a backtest. Optionally open a replay viewer with --viz (static) or
    --viz --stream (streaming animation)."""
    resolved_strategy = resolve_strategy_path(strategy)
    resolved_config = _resolve_config_path(config)

    if stream and not viz:
        typer.echo("NOTE: --stream has no effect without --viz; ignoring.")

    chart_hook = None
    if viz:
        try:
            from tickweaver.viz import LiveChartHook, StreamingChartHook
        except ImportError as e:
            typer.echo(
                f"ERROR: failed to import viz module: {e}\n"
                "Install with: pip install -r requirements-viz.txt"
            )
            raise typer.Exit(code=2)
        hook_cls = StreamingChartHook if stream else LiveChartHook
        # auto_show=False: hook 의 on_deinit 가 finplot 윈도우를 자동 오픈하지
        # 않도록. 윈도우 오픈은 run_backtest() 반환 후 result.equity_curve 를
        # attach 한 다음 명시적으로 chart_hook.show() 로 처리 — viz 의 KPI 패널
        # 이 broker.equity 시계열(=HTML batch 와 동일 source) 을 사용하게 됨.
        chart_hook = hook_cls(symbol="", timeframe="", block=True, auto_show=False)

    result = run_backtest(
        strategy_path=resolved_strategy,
        out_dir=out_dir,
        config_path=resolved_config,
        dump_ticks=dump_ticks,
        show_progress=not no_progress,
        chart_hook=chart_hook,
    )
    typer.echo(
        f"\nfinal_equity = {result.final_equity:.2f} "
        f"(initial = {result.initial_cash:.2f}, "
        f"return = {(result.final_equity / result.initial_cash - 1.0) * 100:+.2f}%)"
    )

    # Viz 윈도우 오픈 — broker.equity 시계열을 hook 에 주입해서 viz 패널의
    # equity-derived metric 이 HTML batch 와 동일 source 를 보도록. show() 는
    # 사용자가 윈도우를 닫을 때까지 blocking.
    if chart_hook is not None:
        chart_hook.attach_equity_curve(result.equity_curve)
        chart_hook.show()


if __name__ == "__main__":
    app()
