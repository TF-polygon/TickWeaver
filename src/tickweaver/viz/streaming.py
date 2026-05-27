"""Streaming replay — pure (headless) logic for the --viz --stream mode.

No Qt / finplot import here: this module is the unit-tested core that the
GUI window (streaming_window.py) drives. It turns a recorded tick stream
into a sequence of growing candles.

Tick invariants relied upon (enforced by the engine + bridge generator):
- ticks arrive in full replay order, grouped by bar_index;
- tick_index_in_bar == 0 is a bar's first tick, whose price == bar.open (C1);
- the last tick of a bar has price == bar.close (C2);
- max / min over a bar's ticks == bar.high / bar.low (C3, C4).

So a bar's candle, built incrementally from its ticks, equals the recorded
OHLCBar once the bar's final tick is consumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

_DEFAULT_PAD_FRAC = 0.08

if TYPE_CHECKING:
    import pandas as pd

    from tickweaver.core.types import OHLCBar, Tick


@dataclass
class PartialBar:
    """A candle being built tick by tick.

    `open` is anchored at the bar's first tick and never moves. `high`/`low`
    track the running extremes of every tick seen so far (open included);
    `close` is the most recent tick's price.
    """

    bar_index: int
    timestamp: "pd.Timestamp"
    open: float
    high: float
    low: float
    close: float

    def update(self, price: float) -> None:
        self.close = price
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price


class TickReplayer:
    """Stateful, single-pass consumer of a recorded tick stream.

    Consume one tick at a time via :meth:`advance`. A new bar begins whenever
    the consumed tick's ``bar_index`` differs from the current bar's, at which
    point the current bar is finalized into :attr:`completed_bars`.

    The candle X anchor is the recorded ``bar.timestamp`` (close-time), the
    same key the static viewer indexes candles / markers by.
    """

    def __init__(
        self,
        ticks: Sequence["Tick"],
        bars: Sequence[tuple[int, "OHLCBar"]],
    ) -> None:
        self._ticks: list["Tick"] = list(ticks)
        self._bar_ts: dict[int, "pd.Timestamp"] = {
            idx: bar.timestamp for idx, bar in bars
        }
        self._pos: int = -1   # index of the last consumed tick
        self._completed: list[PartialBar] = []
        self._current: PartialBar | None = None

    # ── consumption ────────────────────────────────────────────────────
    def advance(self) -> bool:
        """Consume the next tick. Returns False when the stream is exhausted."""
        nxt = self._pos + 1
        if nxt >= len(self._ticks):
            return False
        self._consume(self._ticks[nxt])
        self._pos = nxt
        return True

    def _consume(self, tick: "Tick") -> None:
        price = float(tick.price)
        if self._current is None or tick.bar_index != self._current.bar_index:
            if self._current is not None:
                self._completed.append(self._current)
            ts = self._bar_ts.get(tick.bar_index, tick.timestamp)
            self._current = PartialBar(
                bar_index=int(tick.bar_index),
                timestamp=ts,
                open=price,
                high=price,
                low=price,
                close=price,
            )
        else:
            self._current.update(price)

    # ── state ──────────────────────────────────────────────────────────
    @property
    def done(self) -> bool:
        return self._pos + 1 >= len(self._ticks)

    @property
    def current_bar(self) -> PartialBar | None:
        return self._current

    @property
    def completed_bars(self) -> list[PartialBar]:
        return self._completed

    @property
    def all_bars(self) -> list[PartialBar]:
        if self._current is None:
            return list(self._completed)
        return [*self._completed, self._current]

    @property
    def n_consumed(self) -> int:
        return self._pos + 1


# ── auto Y-rescale (unit #3) ───────────────────────────────────────────────
def fit_y_range(
    lows: Sequence[float],
    highs: Sequence[float],
    pad_frac: float = _DEFAULT_PAD_FRAC,
) -> tuple[float, float]:
    """Y window that contains every visible candle's [low, high] with padding.

    The padding is ``pad_frac`` of the visible span so a tall "장봉" never
    touches the frame edge. A zero span (all candles flat) falls back to a
    price-proportional pad so the window is never degenerate.
    """
    lo = float(min(lows))
    hi = float(max(highs))
    span = hi - lo
    if span > 1e-12:
        pad = span * pad_frac
    else:
        pad = max(abs(hi), abs(lo)) * pad_frac or 1.0
    return lo - pad, hi + pad


def auto_y_range(
    lows: Sequence[float],
    highs: Sequence[float],
    *,
    drag_on: bool,
    pad_frac: float = _DEFAULT_PAD_FRAC,
) -> tuple[float, float] | None:
    """Y range to apply this frame, or None to leave Y untouched.

    Drag ON → the user owns the Y axis (free pan/zoom), so return None.
    Drag OFF (auto-follow) → fit the visible window so the current bar stays
    on screen. Empty input also returns None.
    """
    if drag_on or not lows or not highs:
        return None
    return fit_y_range(lows, highs, pad_frac)
