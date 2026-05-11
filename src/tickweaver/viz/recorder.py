"""EventRecorder - in-memory ChartHook implementation.

Records every backtest event into deque/list for post-run analysis or testing.
Has no GUI dependency. Used as a baseline for V2 determinism regression
(viz=Recorder must produce the same final_equity as viz=None).
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING

from tickweaver.viz.events import CommentEvent
from tickweaver.viz.hook import ChartHook

if TYPE_CHECKING:
    from tickweaver.core.types import Fill, OHLCBar, Tick


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
