"""run_backtest -- config + strategy path -> BacktestResult.

The yaml config (configs/<env>.yaml) fully defines:
  - capital / market mode / leverage
  - data source (exchange / symbol / timeframe / start_date / end_date)
  - execution costs / tick synthesis / reporting / logging

Strategy code (strategies/<name>.py) owns trading parameters as module
constants. No json side-files.

Data loading is automatic: the runner reads cfg.data and calls CcxtLoader.
First run downloads; subsequent runs hit the disk cache. To pre-fetch data
explicitly use scripts/download_data.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from tickweaver.core.types import StrategyContext
from tickweaver.data.loaders.ccxt_loader import CcxtLoader
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
    DEFAULT_BACKTEST_CONFIG,
    REPORTS_DIR,
    ensure_runtime_dirs,
    to_rel_path,
)
from tickweaver.utils.seed import SeedManager

if TYPE_CHECKING:
    from tickweaver.viz.hook import ChartHook

_LOG = get_logger("runner")


_MODE_TO_MARKET = {
    "spot": "spot",
    "futures": "swap",   # USDT-M perpetual via CCXT default
}


def _slice_period(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    """Slice OHLCV to [start, end). Both are YYYY-MM-DD; treated as UTC."""
    s = pd.Timestamp(start)
    if s.tzinfo is None:
        s = s.tz_localize("UTC")
    e = pd.Timestamp(end)
    if e.tzinfo is None:
        e = e.tz_localize("UTC")
    return df[(df.index >= s) & (df.index < e)]


def _resolve_out_dir(strategy_path: Path, override: str | Path | None) -> Path:
    if override is not None:
        return Path(override)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return REPORTS_DIR / f"{strategy_path.stem}_{ts}"


def _load_data_from_config(cfg: BacktestConfig) -> tuple[pd.DataFrame, CcxtLoader]:
    """Resolve OHLCV from cfg.data via CcxtLoader (cache first, fetch if needed).

    Returns the loader too so the caller can reuse it for symbol precision
    (Polish C) without building a second client.
    """
    market_type = _MODE_TO_MARKET.get(cfg.run.mode, "swap")
    loader = CcxtLoader(exchange=cfg.data.exchange, market_type=market_type)
    df = loader.load(
        symbol=cfg.data.symbol,
        timeframe=cfg.data.timeframe,
        since=cfg.data.start_date,
        until=cfg.data.end_date,
    )
    df = _slice_period(df, cfg.data.start_date, cfg.data.end_date)
    return df, loader


def run_backtest(
    *,
    strategy_path: str | Path,
    out_dir: str | Path | None = None,
    config_path: str | Path | None = None,
    dump_ticks: int | None = None,
    generator_override: str | None = None,
    show_progress: bool = True,
    chart_hook: "ChartHook | None" = None,
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

    # Data: cache-first via CcxtLoader, sliced to [start_date, end_date).
    df, loader = _load_data_from_config(cfg)
    validate_ohlcv_schema(df)
    validate_ohlcv_integrity(df)

    if df.empty:
        raise ValueError(
            f"no bars after period slice {cfg.data.start_date} ~ {cfg.data.end_date}. "
            f"Check the date range or the exchange/symbol/timeframe in {cfg_path}."
        )

    symbol = cfg.data.symbol
    timeframe = cfg.data.timeframe
    exchange = cfg.data.exchange
    _LOG.info(
        "data_loaded",
        rows=len(df),
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        start=df.index.min().strftime("%Y-%m-%d"),
        end=df.index.max().strftime("%Y-%m-%d"),
    )

    strategy_p = Path(strategy_path)
    strategy = FileStrategy(strategy_p)

    fee_model = (
        BpsFeeModel(cfg.execution.fee_bps) if cfg.execution.fee_bps > 0 else NoFee()
    )
    slippage = build_slippage(cfg.execution.slippage_bps)
    # Polish C: 종목별 가격/qty 정밀도를 CCXT market info 에서 자동 추출
    # (디스크 캐시 → 1회 fetch → fallback). broker / api 가 같은 qty_step 을
    # 공유 (Issue 1 의 dust epsilon = qty_step * 1.5). price_decimals 는 viz
    # 의 가격 표기에 쓰여 chart_hook 으로 주입.
    precision = loader.get_symbol_precision(symbol)
    qty_step = precision.qty_step
    broker = BacktestBroker(
        symbol=symbol,
        initial_cash=cfg.run.initial_capital,
        fee_model=fee_model,
        slippage_model=slippage,
        mode=cfg.run.mode,
        leverage=cfg.run.leverage,
        qty_step=qty_step,
    )
    api = StrategyAPI(
        broker=broker,
        symbol=symbol,
        qty_step=qty_step,
        console_log=not show_progress,
        chart_hook=chart_hook,
    )

    # Inject metadata into LiveChartHook-shaped hooks so the viz layer can
    # render symbol/timeframe in titles + description without re-parsing cfg.
    if chart_hook is not None:
        if hasattr(chart_hook, "symbol") and not getattr(chart_hook, "symbol"):
            chart_hook.symbol = symbol
        if hasattr(chart_hook, "timeframe") and not getattr(chart_hook, "timeframe"):
            chart_hook.timeframe = timeframe
        # Phase V7: initial_cash for the description pane's PnL row.
        if hasattr(chart_hook, "initial_cash"):
            chart_hook.initial_cash = float(cfg.run.initial_capital)
        # Issue 4 Step 4: leverage for the position table's Margin (USDT) column.
        if hasattr(chart_hook, "leverage"):
            chart_hook.leverage = float(cfg.run.leverage)
        # Polish C: 종목별 가격 정밀도 — position table / hover tooltip 가격 표기.
        if hasattr(chart_hook, "price_decimals"):
            chart_hook.price_decimals = int(precision.price_decimals)

    context = StrategyContext(
        symbol=symbol,
        timeframe=timeframe,
        market_type=_MODE_TO_MARKET.get(cfg.run.mode, "swap"),
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
        n_min=cfg.tick_synthesis.n_ticks_min,
        n_max=cfg.tick_synthesis.n_ticks_max,
        dump_ticks=cfg.reporting.dump_ticks,
        show_progress=show_progress,
        chart_hook=chart_hook,
        config_snapshot={
            "config": cfg.to_dict(),
            "strategy_path": str(strategy_p.resolve()),
            "config_path": str(cfg_path.resolve()),
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
        out_dir=to_rel_path(out),
        final_equity=round(result.final_equity, 1),
        initial_cash=result.initial_cash,
        n_fills=len(result.fills),
    )
    return result
