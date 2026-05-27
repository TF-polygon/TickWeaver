"""supertrend.py - SuperTrend flip entry with swing-low/high SL and 1.5R TP.

Logic (very simple, no trade filters):
  - SuperTrend flips bearish -> bullish  => go Long.
        SL = most recent confirmed swing low (pivot low).
        TP = entry + 1.5 * (entry - SL).
  - SuperTrend flips bullish -> bearish  => go Short (futures).
        SL = most recent confirmed swing high (pivot high).
        TP = entry - 1.5 * (SL - entry).

Entries are taken on bar close only when flat (the order fills on the next
bar's first tick). Exits are SL/TP, checked on every synthesized tick at the
actual price the wick reaches (same pattern as ema_market_sl_tp.py).

A "swing low/high" is a pivot confirmed by SWING_LOOKBACK bars on each side,
so it lags by that many bars and never peeks at future data.

Short entries need a futures config (mode != spot). Run e.g.:
  python scripts/run_backtest.py --strategy supertrend --config futures.yaml --viz --stream

Trading parameters (edit here to tune):
"""

from typing import TYPE_CHECKING

from tickweaver.strategy.indicators import SuperTrend

if TYPE_CHECKING:
    # Type stubs for IDE / linter only — FileStrategy injects these at runtime.
    from tickweaver.core.types import (
        Fill,
        OHLCBar,
        OrderType,
        PositionSide,
        Side,
        StrategyContext,
        Tick,
    )
    from tickweaver.strategy.api import StrategyAPI

    api: StrategyAPI
    context: StrategyContext


# ── trading parameters (module constants) ───────────────────
ST_PERIOD = 10          # SuperTrend ATR length
ST_MULT = 3.0           # SuperTrend ATR multiplier
SWING_LOOKBACK = 2      # bars on each side to confirm a pivot (swing) low/high
TP_R = 1.5              # take-profit = TP_R * risk (entry-to-SL distance)
SIZE_PCT = 0.2          # 0.2 = 20% of available cash per entry


# ── state (engine reload calls on_init to reset) ────────────
st = None
prev_dir = None

_highs: list = []       # rolling bar highs (for pivot detection)
_lows: list = []        # rolling bar lows
last_pivot_low = None   # most recent confirmed swing low
last_pivot_high = None  # most recent confirmed swing high

pending_sl = None       # SL captured at signal, applied after the entry fills
entry_price = None
sl_price = None
tp_price = None
side = None             # "long" / "short" while in a position, else None


def on_init() -> None:
    global st, prev_dir, _highs, _lows, last_pivot_low, last_pivot_high
    global pending_sl, entry_price, sl_price, tp_price, side
    st = SuperTrend(period=ST_PERIOD, multiplier=ST_MULT)
    prev_dir = None
    _highs = []
    _lows = []
    last_pivot_low = None
    last_pivot_high = None
    pending_sl = None
    entry_price = None
    sl_price = None
    tp_price = None
    side = None


def _update_swings(bar: "OHLCBar") -> None:
    """Append this bar, then confirm a pivot SWING_LOOKBACK bars back.

    A pivot low at the centre bar c is a low that is the minimum of the
    [c-k, c+k] window; the pivot high is the symmetric maximum. Confirmed
    using closed bars only (no lookahead).
    """
    global last_pivot_low, last_pivot_high
    _highs.append(float(bar.high))
    _lows.append(float(bar.low))
    k = SWING_LOOKBACK
    if len(_lows) < 2 * k + 1:
        return
    c = len(_lows) - 1 - k   # centre of the just-completed window
    if _lows[c] == min(_lows[c - k : c + k + 1]):
        last_pivot_low = _lows[c]
    if _highs[c] == max(_highs[c - k : c + k + 1]):
        last_pivot_high = _highs[c]


def on_bar(bar: "OHLCBar") -> None:
    """SuperTrend flip detection on bar close. Order fills next bar tick 1."""
    global prev_dir, pending_sl

    st.update_bar(bar)
    _update_swings(bar)

    if not st.is_warm:
        prev_dir = st.direction
        return

    # Two-tone SuperTrend overlay (only takes effect with --viz): the line is
    # Lime while bullish (buy regime) and Red while bearish (sell regime). Two
    # separate lines, each NaN in the other regime so they read as one line
    # that changes colour at every flip.
    api.plot(
        "SuperTrend Up",
        st.value if st.direction == 1 else float("nan"),
        color="#00FF00",
    )
    api.plot(
        "SuperTrend Dn",
        st.value if st.direction == -1 else float("nan"),
        color="#FF0000",
    )

    cur_dir = st.direction
    buy_flip = prev_dir == -1 and cur_dir == 1
    sell_flip = prev_dir == 1 and cur_dir == -1
    prev_dir = cur_dir

    if not api.is_flat():
        return

    if buy_flip and last_pivot_low is not None and last_pivot_low < bar.close:
        size = api.size_from_cash_pct(SIZE_PCT, bar.close)
        if size > 0:
            api.market_buy(size)
            pending_sl = last_pivot_low
            api.comment(f"ST buy @ {bar.close:.4f}  SL(swing low) {pending_sl:.4f}")
    elif sell_flip and last_pivot_high is not None and last_pivot_high > bar.close:
        size = api.size_from_cash_pct(SIZE_PCT, bar.close)
        if size > 0:
            api.market_sell(size)
            pending_sl = last_pivot_high
            api.comment(f"ST sell @ {bar.close:.4f}  SL(swing high) {pending_sl:.4f}")


def on_tick(tick: "Tick") -> None:
    """Per-tick SL/TP enforcement. Runs AFTER the broker fills on this tick."""
    global entry_price, sl_price, tp_price, side, pending_sl

    if api.is_flat():
        entry_price = sl_price = tp_price = side = pending_sl = None
        return

    # First tick after the entry fills: lock entry + compute SL/TP from the
    # swing level captured at the signal bar.
    if entry_price is None:
        pos = api.position()
        entry_price = float(pos.entry_price)
        side = "long" if pos.side.value == "long" else "short"
        sl_price = pending_sl
        if side == "long":
            tp_price = entry_price + TP_R * (entry_price - sl_price)
        else:
            tp_price = entry_price - TP_R * (sl_price - entry_price)
        api.comment(
            f"entry={entry_price:.4f} sl={sl_price:.4f} tp={tp_price:.4f} ({side})"
        )

    # SL first (conservative), then TP.
    if side == "long":
        if tick.price <= sl_price:
            api.close_position()
            api.comment(f"SL hit @ {tick.price:.4f}")
        elif tick.price >= tp_price:
            api.close_position()
            api.comment(f"TP hit @ {tick.price:.4f}")
    else:  # short
        if tick.price >= sl_price:
            api.close_position()
            api.comment(f"SL hit @ {tick.price:.4f}")
        elif tick.price <= tp_price:
            api.close_position()
            api.comment(f"TP hit @ {tick.price:.4f}")


def on_deinit() -> None:
    api.log("supertrend finished", final_equity=round(api.equity, 2))
