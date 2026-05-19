"""BacktestEngine - single-threaded loop:
feed -> tick synthesis -> strategy -> broker -> equity.

Lookahead protection (plan.md S.10): for each bar t we run

    1. synthesize ticks for the current bar
    2. for each tick: broker.on_market_event (fill pending orders), strategy.on_tick
    3. strategy.on_bar(current bar)  <- orders submitted here fill from
                                        the FIRST tick of the NEXT bar

Visualization hook (plan_viz.md V1, D19): an optional ChartHook observes
events without affecting backtest determinism (V2). NullHook by default.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd

from tickweaver.core.types import (
    Fill,
    OHLCBar,
    StrategyContext,
    Tick,
)
from tickweaver.data.feeds.replay_feed import ReplayFeed
from tickweaver.execution.backtest_broker import BacktestBroker
from tickweaver.strategy.api import StrategyAPI
from tickweaver.strategy.file_strategy import FileStrategy
from tickweaver.tick_synthesis.constraints import clamp_n_ticks
from tickweaver.tick_synthesis.validator import validate_ticks
from tickweaver.utils.logger import get_logger
from tickweaver.utils.seed import SeedManager

if TYPE_CHECKING:
    from tickweaver.viz.hook import ChartHook

_LOG = get_logger("engine")


@dataclass
class TickSummary:
    """For the report's Tick Synthesis (proof) section (M6.3)."""

    generator: str
    seed: int
    n_min: int
    n_max: int
    n_bars: int
    n_ticks_total: int
    avg_ticks_per_bar: float
    sample_bar_indices: list[int] = field(default_factory=list)


@dataclass
class BacktestResult:
    equity_curve: pd.DataFrame
    fills: list[Fill]
    tick_summary: TickSummary
    sample_ticks: pd.DataFrame | None
    config_snapshot: dict[str, Any]
    final_equity: float
    initial_cash: float


class BacktestEngine:
    def __init__(
        self,
        df: pd.DataFrame,
        broker: BacktestBroker,
        strategy: FileStrategy,
        api: StrategyAPI,
        context: StrategyContext,
        generator,  # TickGenerator
        seed_manager: SeedManager,
        n_min: int = 8,
        n_max: int = 256,
        dump_ticks: int = 0,
        config_snapshot: dict[str, Any] | None = None,
        show_progress: bool = True,
        chart_hook: "ChartHook | None" = None,
    ) -> None:
        self.df = df
        self.broker = broker
        self.strategy = strategy
        self.api = api
        self.context = context
        self.generator = generator
        self.seed_manager = seed_manager
        self.n_min = int(n_min)
        self.n_max = int(n_max)
        self.dump_ticks = int(dump_ticks)
        self.config_snapshot = config_snapshot or {}
        self.show_progress = bool(show_progress)
        # ChartHook (V1 non-invasive). Lazy import to keep core GUI-free.
        if chart_hook is None:
            from tickweaver.viz.hook import NullHook

            chart_hook = NullHook()
        self.chart_hook = chart_hook

    def run(self) -> BacktestResult:
        feed = ReplayFeed(self.df)
        n_bars = len(feed)
        if n_bars == 0:
            raise ValueError("empty OHLCV - cannot run backtest")

        # Per-bar tick count RNG
        n_target_rng = self.seed_manager.rng("n_target")

        # Strategy lifecycle
        self.strategy.load(self.api, self.context)
        self.strategy.call_on_init()

        # Hook: on_init (V6 - same call regardless of viz on/off)
        self.chart_hook.on_init()

        # Wire broker fills -> chart_hook.on_fill
        prev_cb = getattr(self.broker, "_fill_callback", None)

        def _on_fill(fill: Fill) -> None:
            if prev_cb is not None:
                try:
                    prev_cb(fill)
                except Exception:
                    pass
            self.chart_hook.on_fill(fill)
            # Phase F4.4 fix: notify the strategy so that on_fill-driven
            # state machines (e.g. future_demo's grid-crossing phases) can
            # advance immediately when a broker fill happens.
            self.strategy.call_on_fill(fill)

        self.broker.set_fill_callback(_on_fill)

        equity_rows: list[tuple[pd.Timestamp, float]] = []
        n_ticks_total = 0

        # Pick sample bars for dump_ticks (deterministic)
        sample_bar_indices: list[int] = []
        if self.dump_ticks > 0:
            k = min(self.dump_ticks, n_bars)
            r = random.Random(self.seed_manager.spawn("dump_ticks_pick"))
            sample_bar_indices = sorted(r.sample(range(n_bars), k))
        sample_rows: list[dict[str, Any]] = []

        # Build the bar iterator (optionally with tqdm progress bar)
        bar_events = feed.iter_bars()
        bars_iter = enumerate(bar_events)
        progress_bar = None
        if self.show_progress:
            try:
                from tqdm import tqdm

                progress_bar = tqdm(
                    bars_iter,
                    total=n_bars,
                    unit="bar",
                    leave=True,
                    disable=None,
                    bar_format="{percentage:3.0f}% {bar}| {n_fmt}/{total_fmt} [{elapsed}, {rate_fmt}{postfix}]",
                )
                bars_iter = progress_bar
            except ImportError:
                progress_bar = None

        try:
            for bar_idx, ev in bars_iter:
                bar: OHLCBar = ev.bar
                self.context.bar_index = bar_idx
                self.context.now = bar.timestamp
                # Keep StrategyAPI bar context in sync for api.comment() and
                # api.plot() / api._sample_indicators() (Phase 3).
                if hasattr(self.api, "_set_bar_context"):
                    self.api._set_bar_context(bar_idx, bar.timestamp)
                elif hasattr(self.api, "_set_bar_index"):
                    self.api._set_bar_index(bar_idx)

                # 1. synthesize ticks
                n_target = int(n_target_rng.integers(self.n_min, self.n_max + 1))
                n = clamp_n_ticks(n_target, self.n_min, self.n_max)
                bar_rng = self.seed_manager.rng(f"bar:{bar_idx}")
                ticks_raw = self.generator.generate(bar, n_ticks=n, rng=bar_rng)

                ticks: list[Tick] = [
                    replace(t, bar_index=bar_idx, tick_index_in_bar=i)
                    for i, t in enumerate(ticks_raw)
                ]

                validate_ticks(bar, ticks, n_min=self.n_min, n_max=self.n_max)
                n_ticks_total += len(ticks)

                # 2. each tick - fill pending orders + strategy.on_tick + chart_hook.on_tick
                for t in ticks:
                    self.broker.on_market_event(t)
                    self.chart_hook.on_tick(t)
                    self.strategy.call_on_tick(t)

                # bar-end equity sample
                equity_rows.append((bar.timestamp, self.broker.equity))

                # dump_ticks
                if bar_idx in sample_bar_indices:
                    for t in ticks:
                        sample_rows.append(
                            {
                                "timestamp": t.timestamp,
                                "price": t.price,
                                "bar_index": bar_idx,
                                "tick_index_in_bar": t.tick_index_in_bar,
                            }
                        )

                # 3. on_bar (after the bar closed)
                self.strategy.call_on_bar(bar)
                # Sample bound indicators after the strategy had a chance to
                # update them inside on_bar. (Phase 3: viz indicator tracks.)
                if hasattr(self.api, "_sample_indicators"):
                    self.api._sample_indicators(bar_idx, bar.timestamp)
                self.chart_hook.on_bar(bar, bar_idx)

                # progress postfix every 100 bars
                if progress_bar is not None and (bar_idx % 100 == 0):
                    progress_bar.set_postfix_str(f"equity={self.broker.equity:.0f}")

            if progress_bar is not None:
                progress_bar.set_postfix_str(f"equity={self.broker.equity:.0f}")
        finally:
            if progress_bar is not None:
                progress_bar.close()

        self.strategy.call_on_deinit()
        # Hook: on_deinit
        self.chart_hook.on_deinit(self.broker.equity)

        # Assemble result
        eq_df = pd.DataFrame(equity_rows, columns=["timestamp", "equity"]).set_index(
            "timestamp"
        )
        if eq_df.index.tz is None:
            eq_df.index = eq_df.index.tz_localize("UTC")

        sample_df: pd.DataFrame | None = None
        if sample_rows:
            sample_df = pd.DataFrame(sample_rows).set_index("timestamp")

        ts = TickSummary(
            generator=getattr(self.generator, "name", "unknown"),
            seed=self.seed_manager.root,
            n_min=self.n_min,
            n_max=self.n_max,
            n_bars=n_bars,
            n_ticks_total=n_ticks_total,
            avg_ticks_per_bar=n_ticks_total / max(n_bars, 1),
            sample_bar_indices=sample_bar_indices,
        )

        return BacktestResult(
            equity_curve=eq_df,
            fills=self.broker.fills(),
            tick_summary=ts,
            sample_ticks=sample_df,
            config_snapshot=self.config_snapshot,
            final_equity=self.broker.equity,
            initial_cash=self.broker.initial_cash,
        )
