"""run_backtest - config + strategy path + source path -> BacktestResult.

D17: only --strategy is required; everything else has defaults.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from tickweaver.core.types import StrategyContext
from tickweaver.data.loaders.parquet_loader import read_parquet_with_attrs
from tickweaver.data.schema import validate_ohlcv_integrity, validate_ohlcv_schema
from tickweaver.engine.backtest_engine import BacktestEngine, BacktestResult
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.execution.fees import BpsFeeModel, NoFee
from tickweaver.execution.slippage import build_slippage
from tickweaver.strategy.api import StrategyAPI
from tickweaver.strategy.file_strategy import FileStrategy
from tickweaver.tick_synthesis.generator import get_tick_generator
from tickweaver.utils.config import BacktestConfig
from tickweaver.utils.logger import configure_logging, get_logger
from tickweaver.utils.paths import (
    DATA_PROCESSED_DIR,
    DEFAULT_BACKTEST_CONFIG,
    REPORTS_DIR,
    ensure_runtime_dirs,
)
from tickweaver.utils.seed import SeedManager

_LOG = get_logger("runner")


def find_default_source() -> Path | None:
    if not DATA_PROCESSED_DIR.exists():
        return None
    candidates = sorted(
        DATA_PROCESSED_DIR.rglob("*.parquet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return candidates[0] if candidates else None


def _resolve_out_dir(strategy_path: Path, override: str | Path | None) -> Path:
    if override is not None:
        return Path(override)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPORTS_DIR / f"{strategy_path.stem}_{ts}"


def _slice_period(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    if start is not None:
        s = pd.Timestamp(start)
        if s.tzinfo is None:
            s = s.tz_localize("UTC")
        df = df[df.index >= s]
    if end is not None:
        e = pd.Timestamp(end)
        if e.tzinfo is None:
            e = e.tz_localize("UTC")
        df = df[df.index < e]
    return df


def run_backtest(
    *,
    strategy_path: str | Path,
    out_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    source: str | Path | None = None,
    params_path: str | Path | None = None,
    dump_ticks: int | None = None,
    auto_period: bool = True,
    generator_override: str | None = None,
    show_progress: bool = True,
) -> BacktestResult:
    ensure_runtime_dirs()

    cfg_path = Path(config_path or DEFAULT_BACKTEST_CONFIG)
    if not cfg_path.exists():
        raise FileNotFoundError(
            f"config not found: {cfg_path}. default is {DEFAULT_BACKTEST_CONFIG}"
        )
    cfg = BacktestConfig.load_yaml(cfg_path)
    if dump_ticks is not None:
        cfg.reporting.dump_ticks = int(dump_ticks)
    if generator_override is not None:
        cfg.tick_synthesis.generator = generator_override  # type: ignore[assignment]

    configure_logging(cfg.logging.level)

    src_path: Path | None
    if source is not None:
        src_path = Path(source)
    else:
        src_path = find_default_source()
        if src_path is None:
            raise FileNotFoundError(
                "no data file found. run download_data.py first, or pass --source."
            )

    if not src_path.exists():
        raise FileNotFoundError(f"source not found: {src_path}")

    df = read_parquet_with_attrs(src_path)
    validate_ohlcv_schema(df)
    validate_ohlcv_integrity(df)

    if not (cfg.period.auto and auto_period):
        df = _slice_period(df, cfg.period.start, cfg.period.end)

    if df.empty:
        raise ValueError(f"no bars in source after period filter: {src_path}")

    symbol = df.attrs.get("symbol", "UNKNOWN")
    timeframe = df.attrs.get("timeframe", "1h")
    exchange = df.attrs.get("exchange", "unknown")
    _LOG.info(
        "data_loaded",
        rows=len(df),
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        start=str(df.index.min()),
        end=str(df.index.max()),
    )

    strategy_p = Path(strategy_path)
    strategy = FileStrategy(strategy_p, params_path=params_path)

    fee_model = (
        BpsFeeModel(cfg.execution.fee_bps) if cfg.execution.fee_bps > 0 else NoFee()
    )
    slippage = build_slippage(cfg.execution.slippage_bps)
    broker = BacktestBroker(
        symbol=symbol,
        initial_cash=cfg.run.initial_cash,
        fee_model=fee_model,
        slippage_model=slippage,
    )
    # When progress bar is on, silence strategy api.log to keep tqdm clean.
    api = StrategyAPI(broker=broker, symbol=symbol, console_log=not show_progress)

    context = StrategyContext(
        symbol=symbol,
        timeframe=timeframe,
        market_type=cfg.run.market_type,
    )

    generator = get_tick_generator(cfg.tick_synthesis.generator)
    seed_mgr = SeedManager(root=cfg.tick_synthesis.seed)

    engine = BacktestEngine(
        df=df,
        broker=broker,
        strategy=strategy,
        api=api,
        context=context,
        generator=generator,
        seed_manager=seed_mgr,
        n_min=cfg.tick_synthesis.n_min,
        n_max=cfg.tick_synthesis.n_max,
        dump_ticks=cfg.reporting.dump_ticks,
        show_progress=show_progress,
        config_snapshot={
            "config": cfg.to_dict(),
            "strategy_path": str(strategy_p.resolve()),
            "params_path": str(params_path) if params_path else None,
            "source": str(src_path.resolve()),
        },
    )
    result = engine.run()

    out = _resolve_out_dir(strategy_p, out_dir or cfg.reporting.out_dir)
    out.mkdir(parents=True, exist_ok=True)

    from tickweaver.analytics.report import save_report

    save_report(result, out_dir=out)

    with open(out / "config_snapshot.json", "w", encoding="utf-8") as f:
        json.dump(result.config_snapshot, f, ensure_ascii=False, indent=2)

    _LOG.info(
        "backtest_done",
        out_dir=str(out),
        final_equity=result.final_equity,
        initial_cash=result.initial_cash,
        n_fills=len(result.fills),
    )
    return result
