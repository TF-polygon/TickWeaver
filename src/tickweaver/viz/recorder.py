"""EventRecorder - in-memory ChartHook implementation.

Records every backtest event into deque/list for post-run analysis or testing.
Has no GUI dependency. Used as a baseline for V2 determinism regression
(viz=Recorder must produce the same final_equity as viz=None).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from tickweaver.viz.events import (
    CommentEvent,
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
    IndicatorTrack,
)
from tickweaver.viz.hook import ChartHook

if TYPE_CHECKING:
    from tickweaver.core.types import Fill, OHLCBar, Tick


# Default panel used when api.plot(...) (or a stray on_indicator_sample) fires
# before an explicit on_indicator_register. Matches the most common case:
# overlay onto the candlestick axis.
_DEFAULT_PANEL = "price"


class EventRecorder(ChartHook):
    """Capture all backtest events in memory.

    Args:
        max_ticks: tick deque maxlen. None means unbounded (warning: memory).
                   Default 100_000 fits ~8760 bars * ~10 ticks/bar of recent ticks.
    """

    def __init__(self, max_ticks: int | None = 100_000) -> None:
        self.bars: list[tuple[int, "OHLCBar"]] = []
        self.fills: list["Fill"] = []
        self.comments: list[CommentEvent] = []
        self.ticks: deque["Tick"] = deque(maxlen=max_ticks)
        # Phase 1: indicator tracks keyed by indicator name.
        self.indicators: dict[str, IndicatorTrack] = {}
        # Phase V7: initial cash injected by the engine (or runner) before run.
        # show_replay uses it to display the correct PnL in the description pane.
        self.initial_cash: float = 0.0
        # Issue 4 Step 4: leverage injected by runner. Used by show_replay to
        # compute Margin (USDT) = price * qty / leverage for the position table.
        self.leverage: float = 1.0
        self._final_equity: float | None = None
        self._init_called: bool = False
        self._deinit_called: bool = False

    def on_init(self) -> None:
        self._init_called = True

    def on_bar(self, bar, bar_index) -> None:
        self.bars.append((bar_index, bar))

    def on_tick(self, tick) -> None:
        self.ticks.append(tick)

    def on_fill(self, fill) -> None:
        self.fills.append(fill)

    def on_comment(self, text, bar_index) -> None:
        ts = None
        if self.bars:
            ts = self.bars[-1][1].timestamp
        self.comments.append(
            CommentEvent(text=str(text), bar_index=int(bar_index), timestamp=ts)
        )

    def on_deinit(self, final_equity) -> None:
        self._final_equity = float(final_equity)
        self._deinit_called = True

    # ---- Phase 1: indicator visualization ----
    def on_indicator_register(self, registration: IndicatorRegistrationEvent) -> None:
        """Register an indicator track. Last-write-wins for duplicate names.

        Existing samples (if any) are preserved across re-registration so
        strategies may refresh style hints mid-run without losing history.
        """
        existing = self.indicators.get(registration.name)
        if existing is None:
            self.indicators[registration.name] = IndicatorTrack(
                registration=registration, samples=[]
            )
        else:
            # Preserve samples list identity; only swap the registration.
            existing.registration = registration

    def on_indicator_sample(self, sample: IndicatorSampleEvent) -> None:
        """Append a sample. Auto-creates a default track if name is unseen.

        The auto-create path supports api.plot(...) where a strategy may emit
        values without a prior bind_indicator(...).
        """
        track = self.indicators.get(sample.name)
        if track is None:
            auto_reg = IndicatorRegistrationEvent(
                name=sample.name, panel=_DEFAULT_PANEL, style={}
            )
            track = IndicatorTrack(registration=auto_reg, samples=[])
            self.indicators[sample.name] = track
        track.samples.append(sample)

    @property
    def final_equity(self) -> float | None:
        return self._final_equity

    @property
    def n_bars(self) -> int:
        return len(self.bars)

    @property
    def n_fills(self) -> int:
        return len(self.fills)

    @property
    def n_comments(self) -> int:
        return len(self.comments)

    @property
    def n_ticks(self) -> int:
        return len(self.ticks)

    @property
    def n_indicators(self) -> int:
        return len(self.indicators)
