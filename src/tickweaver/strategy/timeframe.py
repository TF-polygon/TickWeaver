"""Phase V3 — Multi-timeframe helpers for strategies.

BarAggregator
    Accumulates M1 OHLCBar instances into a higher-timeframe bar (M15, H1,
    D1, ...) and emits a completed bar when the target boundary is reached.

OHLCBar.timestamp follows ccxt convention: it is the open_ts of the bar.
A bar's close_ts = open_ts + source_tf. With M1 input the close_ts is
open_ts + 1 minute. The target boundary is reached when close_ts lands on
the target tick (e.g. minute % 15 == 0 for M15).
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.types import OHLCBar


class BarAggregator:
    """Resample M1 bars into N-minute bars.

    Args:
        target_minutes: 15 (M15), 60 (H1), 240 (4H), 1440 (D1), ...

    Usage in a strategy:
        agg = BarAggregator(target_minutes=15)
        def on_bar(bar):   # bar is M1
            m15 = agg.update(bar)
            if m15 is not None:
                # m15 is a fully-formed M15 OHLCBar with same symbol
                indicator.update(m15.close)
    """

    def __init__(self, target_minutes: int, source_minutes: int = 1) -> None:
        if target_minutes < 1:
            raise ValueError(
                f"BarAggregator target_minutes must be >= 1, got {target_minutes}"
            )
        if source_minutes < 1:
            raise ValueError(
                f"BarAggregator source_minutes must be >= 1, got {source_minutes}"
            )
        if target_minutes % source_minutes != 0:
            raise ValueError(
                f"target_minutes ({target_minutes}) must be a multiple of "
                f"source_minutes ({source_minutes})"
            )
        self.target_minutes = int(target_minutes)
        self.source_minutes = int(source_minutes)

        self._open: float | None = None
        self._high: float | None = None
        self._low: float | None = None
        self._close: float | None = None
        self._volume: float = 0.0
        self._first_ts: pd.Timestamp | None = None
        self._symbol: str | None = None
        self._last_completed: OHLCBar | None = None

    def update(self, bar: OHLCBar) -> OHLCBar | None:
        """Accumulate one source bar. Return the completed N-min bar when
        its boundary is reached, else None."""
        # Begin a new window if empty.
        if self._first_ts is None:
            self._first_ts = bar.timestamp
            self._open = float(bar.open)
            self._high = float(bar.high)
            self._low = float(bar.low)
            self._close = float(bar.close)
            self._volume = float(bar.volume)
            self._symbol = bar.symbol
        else:
            self._high = max(self._high, float(bar.high))
            self._low = min(self._low, float(bar.low))
            self._close = float(bar.close)
            self._volume += float(bar.volume)

        if self._is_target_boundary(bar.timestamp):
            completed = OHLCBar(
                timestamp=self._first_ts,
                open=self._open,
                high=self._high,
                low=self._low,
                close=self._close,
                volume=self._volume,
                symbol=self._symbol or bar.symbol,
                timeframe=f"{self.target_minutes}m",
            )
            self._last_completed = completed
            self._first_ts = None
            self._open = None
            self._high = None
            self._low = None
            self._close = None
            self._volume = 0.0
            self._symbol = None
            return completed
        return None

    def _is_target_boundary(self, open_ts: pd.Timestamp) -> bool:
        """True if `open_ts` is the last source bar of an N-minute window.

        close_ts = open_ts + source_minutes. Boundary when close_ts lands on
        a target tick (minute % target == 0 inside the hour, hour % (target/60)
        == 0 for hourly multiples, etc.).
        """
        close_ts = open_ts + pd.Timedelta(minutes=self.source_minutes)
        t = self.target_minutes
        if t < 60:
            return close_ts.minute % t == 0
        elif t < 1440:
            # Multiples of an hour: 60, 120, 180, 240 (4H), 360, 480, 720, ...
            if close_ts.minute != 0:
                return False
            return close_ts.hour % (t // 60) == 0
        else:
            # Day or longer (1440 = D1, 10080 = W1 unsupported here).
            return close_ts.hour == 0 and close_ts.minute == 0

    @property
    def last_completed(self) -> OHLCBar | None:
        """Most recently emitted N-min bar (or None before first emit)."""
        return self._last_completed

    @property
    def pending(self) -> OHLCBar | None:
        """Snapshot of the currently-accumulating bar (or None if empty).

        Useful for strategies that want a live preview before the window
        completes. The pending bar's timestamp is the window start.
        """
        if self._first_ts is None:
            return None
        return OHLCBar(
            timestamp=self._first_ts,
            open=self._open or 0.0,
            high=self._high or 0.0,
            low=self._low or 0.0,
            close=self._close or 0.0,
            volume=self._volume,
            symbol=self._symbol or "",
            timeframe=f"{self.target_minutes}m",
        )

    def reset(self) -> None:
        self._open = None
        self._high = None
        self._low = None
        self._close = None
        self._volume = 0.0
        self._first_ts = None
        self._symbol = None
        self._last_completed = None
