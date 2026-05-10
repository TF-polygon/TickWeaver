"""tickweaver streaming indicators.

All indicators share a common contract:
- update(...) -> latest value (float | tuple | None) and updates internal state
- .value property — None until warm, then the last value
- .is_warm property — bool
- .reset() — clears state for re-use across runs

Notes:
- All indicators are deterministic (P3): same input sequence -> same output.
- ATR uses bar-level data (high, low, close); the rest take a single price.
- Indicators do not assume regular time intervals. Each update() is one bar.
  This makes them safe under D13 (skip-only on missing bars).
"""

from __future__ import annotations

import math
from collections import deque

import numpy as np


# ---------------------------------------------------------------------------
# SMA — Simple Moving Average
# ---------------------------------------------------------------------------
class SMA:
    """Rolling arithmetic mean over the last `period` updates."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"SMA period must be >= 1, got {period}")
        self.period = int(period)
        self._buf: deque[float] = deque(maxlen=self.period)
        self._sum: float = 0.0

    def update(self, price: float) -> float | None:
        price = float(price)
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]  # leftmost will be evicted by maxlen append
        self._buf.append(price)
        self._sum += price
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period

    @property
    def value(self) -> float | None:
        if len(self._buf) < self.period:
            return None
        return self._sum / self.period

    @property
    def is_warm(self) -> bool:
        return len(self._buf) >= self.period

    def reset(self) -> None:
        self._buf.clear()
        self._sum = 0.0


# ---------------------------------------------------------------------------
# EMA — Exponential Moving Average (SMA-seeded, TradingView/MT4 style)
# ---------------------------------------------------------------------------
class EMA:
    """EMA seeded with SMA over the first `period` values, then alpha smoothed."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"EMA period must be >= 1, got {period}")
        self.period = int(period)
        self.alpha = 2.0 / (self.period + 1.0)
        self._buf: list[float] = []
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        price = float(price)
        if self._value is None:
            self._buf.append(price)
            if len(self._buf) >= self.period:
                self._value = sum(self._buf) / self.period
                self._buf = []  # release seed buffer
        else:
            self._value = self.alpha * price + (1.0 - self.alpha) * self._value
        return self._value

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def is_warm(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._buf = []
        self._value = None


# ---------------------------------------------------------------------------
# RSI — Wilders smoothing
# ---------------------------------------------------------------------------
class RSI:
    """Relative Strength Index using Wilder smoothing.

    Warm-up takes period + 1 prices (need `period` deltas). value in [0, 100].
    """

    def __init__(self, period: int = 14) -> None:
        if period < 2:
            raise ValueError(f"RSI period must be >= 2, got {period}")
        self.period = int(period)
        self._prev_price: float | None = None
        self._gains: list[float] = []
        self._losses: list[float] = []
        self._avg_gain: float | None = None
        self._avg_loss: float | None = None
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        price = float(price)
        if self._prev_price is None:
            self._prev_price = price
            return None

        delta = price - self._prev_price
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)
        self._prev_price = price

        if self._avg_gain is None:
            self._gains.append(gain)
            self._losses.append(loss)
            if len(self._gains) >= self.period:
                self._avg_gain = sum(self._gains) / self.period
                self._avg_loss = sum(self._losses) / self.period
                self._gains = []
                self._losses = []
                self._value = self._compute()
        else:
            self._avg_gain = (
                self._avg_gain * (self.period - 1) + gain
            ) / self.period
            self._avg_loss = (
                self._avg_loss * (self.period - 1) + loss
            ) / self.period
            self._value = self._compute()
        return self._value

    def _compute(self) -> float:
        if self._avg_loss is None or self._avg_gain is None:
            return 0.0
        if self._avg_loss == 0.0:
            return 100.0
        rs = self._avg_gain / self._avg_loss
        return 100.0 - 100.0 / (1.0 + rs)

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def is_warm(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._prev_price = None
        self._gains = []
        self._losses = []
        self._avg_gain = None
        self._avg_loss = None
        self._value = None


# ---------------------------------------------------------------------------
# ATR — Average True Range (bar-level)
# ---------------------------------------------------------------------------
class ATR:
    """Wilder-smoothed Average True Range. Uses high/low/close.

    Use update_bar(bar) for OHLCBar, or update(high, low, close).
    """

    def __init__(self, period: int = 14) -> None:
        if period < 1:
            raise ValueError(f"ATR period must be >= 1, got {period}")
        self.period = int(period)
        self._prev_close: float | None = None
        self._buf: list[float] = []
        self._value: float | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        h = float(high)
        l = float(low)
        c = float(close)
        if self._prev_close is None:
            tr = h - l
        else:
            tr = max(h - l, abs(h - self._prev_close), abs(l - self._prev_close))
        self._prev_close = c

        if self._value is None:
            self._buf.append(tr)
            if len(self._buf) >= self.period:
                self._value = sum(self._buf) / self.period
                self._buf = []
        else:
            self._value = (self._value * (self.period - 1) + tr) / self.period
        return self._value

    def update_bar(self, bar) -> float | None:
        return self.update(bar.high, bar.low, bar.close)

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def is_warm(self) -> bool:
        return self._value is not None

    def reset(self) -> None:
        self._prev_close = None
        self._buf = []
        self._value = None


# ---------------------------------------------------------------------------
# MACD — fast EMA - slow EMA, with signal line + histogram
# ---------------------------------------------------------------------------
class MACD:
    """MACD = EMA(fast) - EMA(slow); signal = EMA(signal_period) of MACD."""

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast >= slow:
            raise ValueError(f"MACD requires fast < slow, got fast={fast}, slow={slow}")
        self.fast_period = int(fast)
        self.slow_period = int(slow)
        self.signal_period = int(signal)
        self._fast = EMA(self.fast_period)
        self._slow = EMA(self.slow_period)
        self._signal = EMA(self.signal_period)
        self._macd: float | None = None
        self._hist: float | None = None

    def update(self, price: float) -> float | None:
        self._fast.update(price)
        self._slow.update(price)
        if self._fast.value is None or self._slow.value is None:
            return None
        self._macd = self._fast.value - self._slow.value
        self._signal.update(self._macd)
        if self._signal.value is not None:
            self._hist = self._macd - self._signal.value
        return self._macd

    @property
    def macd(self) -> float | None:
        return self._macd

    @property
    def signal(self) -> float | None:
        return self._signal.value

    @property
    def histogram(self) -> float | None:
        return self._hist

    @property
    def value(self) -> float | None:
        # Convention: value == macd line for compatibility.
        return self._macd

    @property
    def is_warm(self) -> bool:
        return self._hist is not None

    def reset(self) -> None:
        self._fast.reset()
        self._slow.reset()
        self._signal.reset()
        self._macd = None
        self._hist = None


# ---------------------------------------------------------------------------
# BollingerBands — SMA +/- mult * stddev
# ---------------------------------------------------------------------------
class BollingerBands:
    """Bollinger Bands: middle = SMA(period), upper/lower = mid +/- mult * sigma.

    Uses population std (ddof=0), matching TradingView default.
    """

    def __init__(self, period: int = 20, mult: float = 2.0) -> None:
        if period < 2:
            raise ValueError(f"BollingerBands period must be >= 2, got {period}")
        self.period = int(period)
        self.mult = float(mult)
        self._buf: deque[float] = deque(maxlen=self.period)
        self._mid: float | None = None
        self._upper: float | None = None
        self._lower: float | None = None

    def update(self, price: float) -> tuple[float, float, float] | None:
        self._buf.append(float(price))
        if len(self._buf) < self.period:
            return None
        arr = np.fromiter(self._buf, dtype=np.float64, count=len(self._buf))
        mid = float(arr.mean())
        sigma = float(arr.std(ddof=0))
        upper = mid + self.mult * sigma
        lower = mid - self.mult * sigma
        self._mid = mid
        self._upper = upper
        self._lower = lower
        return (mid, upper, lower)

    @property
    def middle(self) -> float | None:
        return self._mid

    @property
    def upper(self) -> float | None:
        return self._upper

    @property
    def lower(self) -> float | None:
        return self._lower

    @property
    def value(self) -> tuple[float, float, float] | None:
        if self._mid is None:
            return None
        return (self._mid, self._upper, self._lower)  # type: ignore[return-value]

    @property
    def is_warm(self) -> bool:
        return self._mid is not None

    def reset(self) -> None:
        self._buf.clear()
        self._mid = None
        self._upper = None
        self._lower = None


__all__ = ["SMA", "EMA", "RSI", "ATR", "MACD", "BollingerBands"]
