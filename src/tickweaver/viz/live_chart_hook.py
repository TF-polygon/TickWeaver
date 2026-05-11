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

from tickweaver.viz.recorder import EventRecorder


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
    """

    def __init__(
        self,
        symbol: str = "",
        timeframe: str = "",
        max_ticks: int | None = 100_000,
        block: bool = True,
    ) -> None:
        super().__init__(max_ticks=max_ticks)
        self.symbol = symbol
        self.timeframe = timeframe
        self.block = bool(block)

    def on_deinit(self, final_equity) -> None:
        super().on_deinit(final_equity)
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
        )
