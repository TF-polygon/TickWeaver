"""LiveChartHook - Qt-backed ChartHook (Phase 4, post-hoc replay).

Strategy:
- During backtest, accumulate events in memory (same as EventRecorder).
- On_deinit (backtest finished), open a finplot window showing:
    * candlestick chart of all observed bars
    * fill markers (Buy / Sell)
    * last comment as a legend / overlay
- Window stays open until user closes it.

Threading (V4): post-hoc replay does NOT run finplot during backtest.
The Qt event loop only starts in on_deinit, after the engine has fully exited.
This keeps the backtest itself single-threaded (D14) and lookahead-safe.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from tickweaver.viz.recorder import EventRecorder

if TYPE_CHECKING:
    import pandas as pd


class LiveChartHook(EventRecorder):
    """ChartHook that records events and opens a finplot window on_deinit.

    Inherits from EventRecorder so events are captured (V2 determinism is
    preserved by the parent class). The only added behavior is on_deinit:
    spawn a finplot window for post-hoc visual review.

    Args:
        symbol: symbol label for the window title (filled from runner).
        timeframe: timeframe label.
        max_ticks: tick deque cap (passed to EventRecorder).
        block: if True (default), the backtest waits in finplot.show() until
               the user closes the window. If False, returns immediately.
        auto_show: if True (default, back-compat), :meth:`on_deinit` calls
               :meth:`show` automatically. Set False when the caller (runner,
               tests) wants to open the window explicitly after attaching
               extra data such as the equity curve.
    """

    def __init__(
        self,
        symbol: str = "",
        timeframe: str = "",
        max_ticks: int | None = 100_000,
        block: bool = True,
        auto_show: bool = True,
    ) -> None:
        super().__init__(max_ticks=max_ticks)
        self.symbol = symbol
        self.timeframe = timeframe
        self.block = bool(block)
        self.auto_show = bool(auto_show)
        self.equity_curve: pd.DataFrame | None = None

    def attach_equity_curve(self, eq_df: pd.DataFrame) -> None:
        """Attach the engine's equity curve so the viz window can render KPIs.

        Called by the runner after the backtest finishes and before
        :meth:`show` (either via auto_show or an explicit caller).
        """
        self.equity_curve = eq_df

    def show(self) -> None:
        """Open the post-hoc finplot replay window."""
        # Lazy import - only load Qt/finplot when the user actually opted in
        try:
            from tickweaver.viz.live_window import show_replay
        except ImportError as e:
            raise RuntimeError(
                "Visualization extras not installed. "
                "Run: pip install tickweaver[viz]  "
                "(or: pip install -r requirements-viz.txt)"
            ) from e
        show_replay(
            self,
            symbol=self.symbol,
            timeframe=self.timeframe,
            block=self.block,
            equity_curve=self.equity_curve,
        )

    def on_deinit(self, final_equity) -> None:
        super().on_deinit(final_equity)
        if self.auto_show:
            self.show()


class StreamingChartHook(EventRecorder):
    """ChartHook that records events and opens a *streaming* replay on_deinit.

    Same recording contract as LiveChartHook (V2 determinism preserved by the
    parent EventRecorder), but:

    - records the full tick stream (``max_ticks=None``) so the whole backtest
      can be replayed start to finish, and
    - opens viz.streaming_window.show_streaming_replay instead of the static
      show_replay — candles grow tick by tick, controls + markers + indicators
      + position table update in real time.

    The unbounded tick record is the one cost difference vs the static viewer;
    for very long backtests this grows memory (see goal blocked-condition #2).
    """

    def __init__(
        self,
        symbol: str = "",
        timeframe: str = "",
        block: bool = True,
        auto_show: bool = True,
    ) -> None:
        super().__init__(max_ticks=None)   # full tick record for full replay
        self.symbol = symbol
        self.timeframe = timeframe
        self.block = bool(block)
        self.auto_show = bool(auto_show)
        self.equity_curve: pd.DataFrame | None = None

    def attach_equity_curve(self, eq_df: pd.DataFrame) -> None:
        """Attach the engine's equity curve so the streaming window can render KPIs."""
        self.equity_curve = eq_df

    def show(self) -> None:
        """Open the streaming replay window."""
        try:
            from tickweaver.viz.streaming_window import show_streaming_replay
        except ImportError as e:
            raise RuntimeError(
                "Visualization extras not installed. "
                "Run: pip install tickweaver[viz]  "
                "(or: pip install -r requirements-viz.txt)"
            ) from e
        show_streaming_replay(
            self,
            symbol=self.symbol,
            timeframe=self.timeframe,
            block=self.block,
            equity_curve=self.equity_curve,
        )

    def on_deinit(self, final_equity) -> None:
        super().on_deinit(final_equity)
        if self.auto_show:
            self.show()
