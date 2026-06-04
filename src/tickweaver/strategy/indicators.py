"""tickweaver streaming indicators.

All indicators share a common contract:
- update(...) -> latest value (float | tuple | None) and updates internal state
- .value property — None until warm, then the last value
- .is_warm property — bool
- .reset() — clears state for re-use across runs

Viz metadata (Phase 2, dev/adv_verbose):
- PANEL: class variable, "price" for overlay-on-candlestick indicators
         (SMA / EMA / BollingerBands) or a unique panel id for sub-panels
         (RSI / MACD / ATR). The engine reads this when api.bind_indicator(...)
         is called without an explicit panel= override.
- SUBVALUES: None for single-value indicators (.value is a scalar). For
         multi-value indicators, a tuple of sub-line names that the engine
         decomposes into separate IndicatorRegistrationEvents.
         BollingerBands → ('middle', 'upper', 'lower')
         MACD          → ('macd', 'signal', 'histogram')

         Sub-names MUST equal the corresponding attribute name on the
         indicator instance — the engine reads them via getattr(...).

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
# Indicator — shared streaming-indicator base
# ---------------------------------------------------------------------------
class Indicator:
    """Common contract for all streaming indicators (see module docstring).

    Single-value indicators store their latest result in ``self._value`` and
    inherit ``value`` / ``is_warm`` unchanged. Multi-value or state-based
    indicators (BollingerBands, Stochastic, Pivot, HARSI) override these. Every
    subclass implements its own ``update(...)`` and ``reset()``.

    ``PANEL`` / ``SUBVALUES`` are viz metadata; subclasses override them only
    when they differ from the defaults below.
    """

    PANEL: str = "price"
    SUBVALUES: tuple[str, ...] | None = None

    _value: float | None = None

    @property
    def value(self) -> float | None:
        return self._value

    @property
    def is_warm(self) -> bool:
        return self._value is not None


# ---------------------------------------------------------------------------
# SMA — Simple Moving Average
# ---------------------------------------------------------------------------
class SMA(Indicator):
    """Rolling arithmetic mean over the last `period` updates."""

    def __init__(self, period: int) -> None:
        if period < 1:
            raise ValueError(f"SMA period must be >= 1, got {period}")
        self.period = int(period)
        self._buf: deque[float] = deque(maxlen=self.period)
        self._sum: float = 0.0
        self._value: float | None = None

    def update(self, price: float) -> float | None:
        price = float(price)
        if len(self._buf) == self.period:
            self._sum -= self._buf[0]  # leftmost will be evicted by maxlen append
        self._buf.append(price)
        self._sum += price
        if len(self._buf) < self.period:
            return None
        self._value = self._sum / self.period
        return self._value

    def reset(self) -> None:
        self._buf.clear()
        self._sum = 0.0
        self._value = None


# ---------------------------------------------------------------------------
# EMA — Exponential Moving Average (SMA-seeded, TradingView/MT4 style)
# ---------------------------------------------------------------------------
class EMA(Indicator):
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

    def reset(self) -> None:
        self._buf = []
        self._value = None


# ---------------------------------------------------------------------------
# RSI — Wilders smoothing
# ---------------------------------------------------------------------------
class RSI(Indicator):
    """Relative Strength Index using Wilder smoothing.

    Warm-up takes period + 1 prices (need `period` deltas). value in [0, 100].
    """

    PANEL = "rsi"

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
class ATR(Indicator):
    """Wilder-smoothed Average True Range. Uses high/low/close.

    Use update_bar(bar) for OHLCBar, or update(high, low, close).
    """

    PANEL = "atr"

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

    def reset(self) -> None:
        self._prev_close = None
        self._buf = []
        self._value = None


# ---------------------------------------------------------------------------
# SuperTrend — ATR bands trend filter (bar-level)
# ---------------------------------------------------------------------------
class SuperTrend(Indicator):
    """SuperTrend trend filter built on ATR.

    Standard algorithm: basic bands = hl2 ± multiplier * ATR, carried forward
    into "final" bands, with the trend line snapping to the lower band while
    bullish and the upper band while bearish.

    - .value     — the SuperTrend line (overlay on price; PANEL='price').
    - .direction — +1 while bullish (uptrend), -1 while bearish. A change in
                   direction is the signal: -1 -> +1 is a buy, +1 -> -1 a sell.

    Use update_bar(bar) for an OHLCBar, or update(high, low, close).
    """

    def __init__(self, period: int = 10, multiplier: float = 3.0) -> None:
        if period < 1:
            raise ValueError(f"SuperTrend period must be >= 1, got {period}")
        if multiplier <= 0:
            raise ValueError(f"SuperTrend multiplier must be > 0, got {multiplier}")
        self.period = int(period)
        self.multiplier = float(multiplier)
        self._atr = ATR(self.period)
        self._prev_close: float | None = None
        self._final_upper: float | None = None
        self._final_lower: float | None = None
        self._value: float | None = None
        self._dir: int | None = None

    def update(self, high: float, low: float, close: float) -> float | None:
        h, l, c = float(high), float(low), float(close)
        atr = self._atr.update(h, l, c)
        if atr is None:
            self._prev_close = c
            return None

        hl2 = (h + l) / 2.0
        basic_upper = hl2 + self.multiplier * atr
        basic_lower = hl2 - self.multiplier * atr

        if self._value is None:
            # First computable bar — seed bands + direction from close vs hl2.
            self._final_upper = basic_upper
            self._final_lower = basic_lower
            if c > hl2:
                self._dir, self._value = 1, basic_lower
            else:
                self._dir, self._value = -1, basic_upper
            self._prev_close = c
            return self._value

        prev_close = self._prev_close
        prev_fu = self._final_upper
        prev_fl = self._final_lower

        # Carry-forward rule: tighten bands unless price has broken through.
        final_upper = (
            basic_upper if (basic_upper < prev_fu or prev_close > prev_fu) else prev_fu
        )
        final_lower = (
            basic_lower if (basic_lower > prev_fl or prev_close < prev_fl) else prev_fl
        )

        if self._value == prev_fu:
            # Was bearish (line on upper band): flip up if close breaks above.
            if c > final_upper:
                self._dir, self._value = 1, final_lower
            else:
                self._dir, self._value = -1, final_upper
        else:
            # Was bullish (line on lower band): flip down if close breaks below.
            if c < final_lower:
                self._dir, self._value = -1, final_upper
            else:
                self._dir, self._value = 1, final_lower

        self._final_upper = final_upper
        self._final_lower = final_lower
        self._prev_close = c
        return self._value

    def update_bar(self, bar) -> float | None:
        return self.update(bar.high, bar.low, bar.close)

    @property
    def direction(self) -> int | None:
        return self._dir

    def reset(self) -> None:
        self._atr.reset()
        self._prev_close = None
        self._final_upper = None
        self._final_lower = None
        self._value = None
        self._dir = None


# ---------------------------------------------------------------------------
# MACD — fast EMA - slow EMA, with signal line + histogram
# ---------------------------------------------------------------------------
class MACD(Indicator):
    """MACD = EMA(fast) - EMA(slow); signal = EMA(signal_period) of MACD."""

    PANEL = "macd"
    SUBVALUES: tuple[str, ...] | None = ("macd", "signal", "histogram")

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9) -> None:
        if fast >= slow:
            raise ValueError(f"MACD requires fast < slow, got fast={fast}, slow={slow}")
        self.fast_period = int(fast)
        self.slow_period = int(slow)
        self.signal_period = int(signal)
        self._fast = EMA(self.fast_period)
        self._slow = EMA(self.slow_period)
        self._signal = EMA(self.signal_period)
        self._value: float | None = None  # the MACD line
        self._hist: float | None = None

    def update(self, price: float) -> float | None:
        self._fast.update(price)
        self._slow.update(price)
        if self._fast.value is None or self._slow.value is None:
            return None
        self._value = self._fast.value - self._slow.value
        self._signal.update(self._value)
        if self._signal.value is not None:
            self._hist = self._value - self._signal.value
        return self._value

    @property
    def macd(self) -> float | None:
        # Convention: value == macd line for compatibility.
        return self._value

    @property
    def signal(self) -> float | None:
        return self._signal.value

    @property
    def histogram(self) -> float | None:
        return self._hist

    @property
    def is_warm(self) -> bool:
        return self._hist is not None

    def reset(self) -> None:
        self._fast.reset()
        self._slow.reset()
        self._signal.reset()
        self._value = None
        self._hist = None


# ---------------------------------------------------------------------------
# BollingerBands — SMA +/- mult * stddev
# ---------------------------------------------------------------------------
class BollingerBands(Indicator):
    """Bollinger Bands: middle = SMA(period), upper/lower = mid +/- mult * sigma.

    Uses population std (ddof=0), matching TradingView default.
    """

    SUBVALUES: tuple[str, ...] | None = ("middle", "upper", "lower")

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


__all__ = ["SMA", "EMA", "RSI", "ATR", "SuperTrend", "MACD", "BollingerBands"]


# ---------------------------------------------------------------------------
# Stochastic Oscillator (Phase V2.1, Vulture porting)
# ---------------------------------------------------------------------------
class Stochastic(Indicator):
    """Stochastic Oscillator with double smoothing (MT4-compatible).

    raw_K(t) = (close - LL_n) / (HH_n - LL_n) * 100
    K(t)     = SMA(raw_K, k_smooth)
    D(t)     = SMA(K,     d_smooth)

    Default parameters (14, 3, 3) match MT4 iStochastic(14, 3, 3, MODE_SMA).
    K is exposed as .value for the convention.
    """

    PANEL = "stoch"
    SUBVALUES = ("K", "D")

    def __init__(self, period: int = 14, k_smooth: int = 3, d_smooth: int = 3) -> None:
        if period < 1 or k_smooth < 1 or d_smooth < 1:
            raise ValueError(
                f"Stochastic periods must be >= 1, got "
                f"period={period} k_smooth={k_smooth} d_smooth={d_smooth}"
            )
        self.period = int(period)
        self.k_smooth = int(k_smooth)
        self.d_smooth = int(d_smooth)
        self._highs: deque[float] = deque(maxlen=self.period)
        self._lows: deque[float] = deque(maxlen=self.period)
        self._raw_k_buf: deque[float] = deque(maxlen=self.k_smooth)
        self._k_buf: deque[float] = deque(maxlen=self.d_smooth)
        self._K: float | None = None
        self._D: float | None = None

    def update(
        self, high: float, low: float, close: float
    ) -> tuple[float | None, float | None]:
        self._highs.append(float(high))
        self._lows.append(float(low))
        if len(self._highs) < self.period:
            return None, None

        hh = max(self._highs)
        ll = min(self._lows)
        if hh - ll < 1e-12:
            raw_k = 50.0
        else:
            raw_k = (float(close) - ll) / (hh - ll) * 100.0

        self._raw_k_buf.append(raw_k)
        if len(self._raw_k_buf) < self.k_smooth:
            return None, None

        K = sum(self._raw_k_buf) / self.k_smooth
        self._K = K

        self._k_buf.append(K)
        if len(self._k_buf) < self.d_smooth:
            return K, None

        D = sum(self._k_buf) / self.d_smooth
        self._D = D
        return K, D

    @property
    def K(self) -> float | None:
        return self._K

    @property
    def D(self) -> float | None:
        return self._D

    @property
    def value(self) -> float | None:
        return self._K

    @property
    def is_warm(self) -> bool:
        return self._K is not None and self._D is not None

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._raw_k_buf.clear()
        self._k_buf.clear()
        self._K = None
        self._D = None


# ---------------------------------------------------------------------------
# Pivot (swing high/low, Phase V2.2 Vulture porting)
# ---------------------------------------------------------------------------
class Pivot(Indicator):
    """Swing-point pivot indicator (Williams fractal style).

    `period=N` means a bar's high (or low) is a confirmed pivot once N bars
    before AND N bars after are all strictly lower (or higher). This means a
    pivot is identified with N-bar delay.

    Vulture uses this to track:
      - is_higher_low()  : last pivot low > second-last pivot low (uptrend)
      - is_lower_high()  : last pivot high < second-last pivot high (downtrend)
    """

    def __init__(self, period: int = 5) -> None:
        if period < 1:
            raise ValueError(f"Pivot period must be >= 1, got {period}")
        self.period = int(period)
        win = 2 * self.period + 1
        self._highs: deque[float] = deque(maxlen=win)
        self._lows: deque[float] = deque(maxlen=win)
        self._last_pivot_high: float | None = None
        self._second_pivot_high: float | None = None
        self._last_pivot_low: float | None = None
        self._second_pivot_low: float | None = None

    def update(self, high: float, low: float) -> None:
        self._highs.append(float(high))
        self._lows.append(float(low))
        win = 2 * self.period + 1
        if len(self._highs) < win:
            return
        mid = self.period
        mid_high = self._highs[mid]
        mid_low = self._lows[mid]
        # pivot high check
        left_h = list(self._highs)[:mid]
        right_h = list(self._highs)[mid + 1 :]
        if all(h < mid_high for h in left_h) and all(h < mid_high for h in right_h):
            if self._last_pivot_high != mid_high:
                self._second_pivot_high = self._last_pivot_high
                self._last_pivot_high = mid_high
        # pivot low check
        left_l = list(self._lows)[:mid]
        right_l = list(self._lows)[mid + 1 :]
        if all(l > mid_low for l in left_l) and all(l > mid_low for l in right_l):
            if self._last_pivot_low != mid_low:
                self._second_pivot_low = self._last_pivot_low
                self._last_pivot_low = mid_low

    @property
    def last_pivot_high(self) -> float | None:
        return self._last_pivot_high

    @property
    def second_pivot_high(self) -> float | None:
        return self._second_pivot_high

    @property
    def last_pivot_low(self) -> float | None:
        return self._last_pivot_low

    @property
    def second_pivot_low(self) -> float | None:
        return self._second_pivot_low

    def is_higher_low(self) -> bool:
        """Vulture _pivot_low: latest pivot low is strictly above the previous
        pivot low → confirmed uptrend in swing lows."""
        if self._last_pivot_low is None or self._second_pivot_low is None:
            return False
        return self._last_pivot_low > self._second_pivot_low

    def is_lower_high(self) -> bool:
        """Vulture _pivot_high: latest pivot high is strictly below the
        previous pivot high → confirmed downtrend in swing highs."""
        if self._last_pivot_high is None or self._second_pivot_high is None:
            return False
        return self._last_pivot_high < self._second_pivot_high

    @property
    def value(self) -> float | None:
        """Convention: expose the most recent pivot low (overlay marker)."""
        return self._last_pivot_low

    @property
    def is_warm(self) -> bool:
        return (
            self._last_pivot_low is not None
            and self._last_pivot_high is not None
        )

    def reset(self) -> None:
        self._highs.clear()
        self._lows.clear()
        self._last_pivot_high = None
        self._second_pivot_high = None
        self._last_pivot_low = None
        self._second_pivot_low = None


# ---------------------------------------------------------------------------
# HARSI — Heikin Ashi RSI (Phase V2.3, Vulture porting)
# ---------------------------------------------------------------------------
class HARSI(Indicator):
    """Pine Script 1:1 port of JayRogers' "HARSI Dot Signal".

    Streams three close/high/low RSI of `harsi_len` (zero-median, value-50),
    plus a fourth RSI of `rsi_len` on the OHLC4 source for the overlay line.
    Builds a Heikin Ashi-style candle from those zrsi streams.

    .dot_signal() returns 'long' / 'short' / None per the original Pine logic.
    .harsi_long / .harsi_short are Vulture's M15 booleans.
    """

    PANEL = "harsi"
    SUBVALUES = (
        "ha_open",
        "ha_high",
        "ha_low",
        "ha_close",
        "overlay",
    )

    def __init__(
        self,
        rsi_len: int = 7,
        harsi_len: int = 14,
        smoothing: int = 7,
        mode: bool = True,
    ) -> None:
        if rsi_len < 2 or harsi_len < 2 or smoothing < 1:
            raise ValueError(
                f"HARSI requires rsi_len/harsi_len >= 2, smoothing >= 1; "
                f"got {rsi_len}/{harsi_len}/{smoothing}"
            )
        self.rsi_len = int(rsi_len)
        self.harsi_len = int(harsi_len)
        self.smoothing = int(smoothing)
        self.mode = bool(mode)

        # Four RSI streams (Wilder smoothing matches Pine ta.rsi).
        self._rsi_close = RSI(period=self.harsi_len)
        self._rsi_high = RSI(period=self.harsi_len)
        self._rsi_low = RSI(period=self.harsi_len)
        self._rsi_plot = RSI(period=self.rsi_len)

        # f_rsi mode=True smoothed accumulator.
        self._smoothed: float | None = None
        # Previous zrsi(close) for f_rsiHeikinAshi _openRSI.
        self._prev_close_zrsi: float | None = None
        # Previous HA open/close (used in the open recursion).
        self._prev_open_HA: float | None = None
        self._prev_close_HA: float | None = None
        # Bar counter for the i_smoothing init window.
        self._bar_count: int = 0

        # Public-ish state for dot_signal.
        self._ha_open: float | None = None
        self._ha_high: float | None = None
        self._ha_low: float | None = None
        self._ha_close: float | None = None
        self._RSI_overlay: float | None = None
        self._prev_overlay: float | None = None

    def update(
        self, open_: float, high: float, low: float, close: float
    ) -> tuple[float | None, float | None, float | None, float | None, float | None]:
        # Drive each Wilder RSI on its respective price stream.
        close_rsi = self._rsi_close.update(float(close))
        high_rsi = self._rsi_high.update(float(high))
        low_rsi = self._rsi_low.update(float(low))
        ohlc4 = (float(open_) + float(high) + float(low) + float(close)) / 4.0
        plot_rsi = self._rsi_plot.update(ohlc4)

        if (
            close_rsi is None
            or high_rsi is None
            or low_rsi is None
            or plot_rsi is None
        ):
            self._bar_count += 1
            return (None, None, None, None, None)

        # f_zrsi = rsi - 50 (zero-median)
        close_zrsi = close_rsi - 50.0
        high_zrsi = high_rsi - 50.0
        low_zrsi = low_rsi - 50.0
        plot_zrsi = plot_rsi - 50.0

        # f_rsi (mode=True: 2-tap recursive smoothing of plot zrsi)
        if self.mode:
            if self._smoothed is None:
                self._smoothed = plot_zrsi
            else:
                self._smoothed = (self._smoothed + plot_zrsi) / 2.0
            RSI_overlay = self._smoothed
        else:
            RSI_overlay = plot_zrsi

        # f_rsiHeikinAshi
        open_RSI = (
            self._prev_close_zrsi if self._prev_close_zrsi is not None else close_zrsi
        )
        high_RSI = max(high_zrsi, low_zrsi)
        low_RSI = min(high_zrsi, low_zrsi)
        close_HA = (open_RSI + high_RSI + low_RSI + close_zrsi) / 4.0

        # HA open: first i_smoothing bars use (openRSI + closeRSI)/2; then the
        # recursive open formula.
        if self._prev_open_HA is None or self._bar_count < self.smoothing:
            open_HA = (open_RSI + close_zrsi) / 2.0
        else:
            open_HA = (
                self._prev_open_HA * self.smoothing + self._prev_close_HA
            ) / (self.smoothing + 1)

        high_HA = max(high_RSI, max(open_HA, close_HA))
        low_HA = min(low_RSI, min(open_HA, close_HA))

        # Roll forward.
        self._prev_close_zrsi = close_zrsi
        self._prev_open_HA = open_HA
        self._prev_close_HA = close_HA
        self._bar_count += 1

        self._prev_overlay = self._RSI_overlay
        self._ha_open = open_HA
        self._ha_high = high_HA
        self._ha_low = low_HA
        self._ha_close = close_HA
        self._RSI_overlay = RSI_overlay

        return (open_HA, high_HA, low_HA, close_HA, RSI_overlay)

    @property
    def ha_open(self) -> float | None:
        return self._ha_open

    @property
    def ha_high(self) -> float | None:
        return self._ha_high

    @property
    def ha_low(self) -> float | None:
        return self._ha_low

    @property
    def ha_close(self) -> float | None:
        return self._ha_close

    @property
    def overlay(self) -> float | None:
        return self._RSI_overlay

    @property
    def value(self) -> float | None:
        return self._RSI_overlay

    @property
    def is_warm(self) -> bool:
        return (
            self._ha_open is not None
            and self._ha_close is not None
            and self._RSI_overlay is not None
        )

    def dot_signal(self) -> str | None:
        """Return 'long' / 'short' / None per the Pine Script if/else ladder."""
        O = self._ha_open
        C = self._ha_close
        RSI = self._RSI_overlay
        if O is None or C is None or RSI is None:
            return None
        if O < C:
            if O < RSI and RSI < C:
                return "long"
            if RSI < O:
                return "short"
            if C < RSI:
                return "long"
            if C > RSI:
                return "short"
        elif O > C:
            if O > RSI and RSI > C:
                return "short"
            if RSI > O:
                return "long"
            if C < RSI:
                return "long"
            if C > RSI:
                return "short"
        return None

    @property
    def harsi_long(self) -> bool:
        """Vulture _harsi_long:
            haOpen < haClose AND prevOverlay < currOverlay
            AND ((O < RSI < C) OR (C < RSI))
        """
        if (
            self._ha_open is None
            or self._ha_close is None
            or self._RSI_overlay is None
            or self._prev_overlay is None
        ):
            return False
        O, C, RSI = self._ha_open, self._ha_close, self._RSI_overlay
        if not (O < C):
            return False
        if not (self._prev_overlay < RSI):
            return False
        return (O < RSI < C) or (C < RSI)

    @property
    def harsi_short(self) -> bool:
        """Vulture _harsi_short (mirror)."""
        if (
            self._ha_open is None
            or self._ha_close is None
            or self._RSI_overlay is None
            or self._prev_overlay is None
        ):
            return False
        O, C, RSI = self._ha_open, self._ha_close, self._RSI_overlay
        if not (O > C):
            return False
        if not (self._prev_overlay > RSI):
            return False
        return (O > RSI > C) or (C > RSI)

    def reset(self) -> None:
        self._rsi_close.reset()
        self._rsi_high.reset()
        self._rsi_low.reset()
        self._rsi_plot.reset()
        self._smoothed = None
        self._prev_close_zrsi = None
        self._prev_open_HA = None
        self._prev_close_HA = None
        self._bar_count = 0
        self._ha_open = None
        self._ha_high = None
        self._ha_low = None
        self._ha_close = None
        self._RSI_overlay = None
        self._prev_overlay = None
