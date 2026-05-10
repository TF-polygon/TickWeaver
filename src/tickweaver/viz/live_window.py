"""finplot-based replay viewer (Phase 4.2 + viz tune-up).

Single mode:
    show_replay() - all data shown at once (post-hoc).

Trading model: SPOT only. Buy / Sell are the only sides we render.

X-axis snap (finplot category-axis fix):
  finplot maps each candle timestamp to a category index. Sub-bar fill
  timestamps (e.g. 04:04:05.45 inside an hourly bar at 04:00) do not exist
  in that index, so without a fix finplot scatters them into "between" slots
  that drift away from the candles. We snap each fill_ts to the close_ts of
  the candle that contains it, preserving fill_price (y) precision -- a wick
  fill still lands inside the wick visually, just snapped to the bar's column.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from tickweaver.viz.recorder import EventRecorder


# Dark navy palette
_BG = "#0F1A2E"
_PLOT_BG = "#0F1A2E"
_FG = "#cfcfcf"

# Candle colors
_BULL = "#26A69A"
_BEAR = "#EF5350"

# Spot order markers
_BUY = "#2196F3"     # blue ">"
_SELL = "#FF9800"    # orange "<"

# Pair connecting line (Buy -> Sell, blue dashed)
_PAIR = "#2196F3"

# Marker styling (viz tune-up)
_MARKER_SIZE = 7
_MARKER_OUTLINE = "#FFFFFF"
_MARKER_OUTLINE_WIDTH = 1.0


def _build_ohlc_df(recorder: "EventRecorder") -> pd.DataFrame:
    if not recorder.bars:
        return pd.DataFrame(columns=["open", "close", "high", "low"])
    rows = []
    idx = []
    for _, bar in recorder.bars:
        idx.append(bar.timestamp)
        rows.append(
            {
                "open": float(bar.open),
                "close": float(bar.close),
                "high": float(bar.high),
                "low": float(bar.low),
            }
        )
    return pd.DataFrame(rows, index=pd.DatetimeIndex(idx))


def _snap_to_candle(fill_ts, candle_index: pd.DatetimeIndex) -> pd.Timestamp:
    """Map a fill timestamp to the close_ts of the candle that contains it.

    Bar B has close_ts at index i. Its ticks span (B-1.close_ts, B.close_ts].
    For boundary fills (fill_ts == prev candle close_ts), the tick is the FIRST
    tick of the next bar -> snap forward to that next bar's close_ts.
    """
    ft = pd.Timestamp(fill_ts)
    pos = candle_index.searchsorted(ft, side="right")
    if pos >= len(candle_index):
        pos = len(candle_index) - 1
    return candle_index[pos]


def _snap_list(fill_ts_list, candle_index: pd.DatetimeIndex) -> list:
    return [_snap_to_candle(t, candle_index) for t in fill_ts_list]


def _apply_dark_theme(fplt) -> None:
    fplt.foreground = _FG
    fplt.background = _BG
    fplt.odd_plot_background = _PLOT_BG
    fplt.candle_bull_color = _BULL
    fplt.candle_bull_body_color = _BULL
    fplt.candle_bear_color = _BEAR
    fplt.candle_bear_body_color = _BEAR
    try:
        fplt.cross_hair_color = "#888888"
    except Exception:
        pass


def _draw_pair_line(fplt, ax, x0, y0, x1, y1, color: str) -> None:
    try:
        fplt.add_line(
            (x0, y0), (x1, y1),
            color=color, width=1, style="--", ax=ax, interactive=False,
        )
    except TypeError:
        fplt.add_line((x0, y0), (x1, y1), color=color, width=1, ax=ax, interactive=False)


def _split_buy_sell(recorder: "EventRecorder"):
    """Return (buy_x, buy_y, sell_x, sell_y)."""
    buy_x: list = []
    buy_y: list = []
    sell_x: list = []
    sell_y: list = []
    for f in recorder.fills:
        side_value = f.side.value if hasattr(f.side, "value") else str(f.side)
        if side_value == "buy":
            buy_x.append(f.timestamp)
            buy_y.append(float(f.price))
        else:
            sell_x.append(f.timestamp)
            sell_y.append(float(f.price))
    return buy_x, buy_y, sell_x, sell_y


def _trades(recorder: "EventRecorder") -> list:
    if not recorder.fills:
        return []
    try:
        from tickweaver.analytics.trades import extract_trades

        return extract_trades(recorder.fills)
    except Exception:
        return []


def _style_marker(item, fill_color: str) -> None:
    """Apply white outline + smaller size on a finplot scatter symbol item.

    Best-effort: if the underlying object is not a pyqtgraph PlotDataItem,
    fall back to defaults silently.
    """
    try:
        import pyqtgraph as pg

        if hasattr(item, "setSymbolSize"):
            item.setSymbolSize(_MARKER_SIZE)
        if hasattr(item, "setSymbolPen"):
            item.setSymbolPen(pg.mkPen(_MARKER_OUTLINE, width=_MARKER_OUTLINE_WIDTH))
        if hasattr(item, "setSymbolBrush"):
            item.setSymbolBrush(pg.mkBrush(fill_color))
    except Exception:
        pass


def show_replay(
    recorder: "EventRecorder",
    symbol: str = "",
    timeframe: str = "",
    block: bool = True,
) -> None:
    """Open a finplot window with the full backtest result drawn at once."""
    try:
        import finplot as fplt
    except ImportError as e:
        raise RuntimeError(
            "finplot is not installed. Run: pip install -r requirements-viz.txt"
        ) from e

    df = _build_ohlc_df(recorder)
    if df.empty:
        raise RuntimeError("No bars captured - cannot open replay viewer.")

    candle_index: pd.DatetimeIndex = df.index

    _apply_dark_theme(fplt)
    title = f"{symbol} {timeframe}".strip() or "tickweaver replay"
    ax = fplt.create_plot(title, maximize=False, init_zoom_periods=200)

    fplt.candlestick_ochl(df[["open", "close", "high", "low"]], ax=ax)

    # Pair lines - snap both endpoints to candle indices.
    for t in _trades(recorder):
        e_x = _snap_to_candle(pd.Timestamp(t.entry_ts), candle_index)
        x_x = _snap_to_candle(pd.Timestamp(t.exit_ts), candle_index)
        _draw_pair_line(
            fplt, ax,
            e_x, float(t.entry_price),
            x_x, float(t.exit_price),
            _PAIR,
        )

    # Buy / Sell markers - x snapped to candle, y kept at fill_price.
    bx, by, sx, sy = _split_buy_sell(recorder)
    if bx:
        bx_snap = _snap_list(bx, candle_index)
        s = pd.Series(by, index=pd.DatetimeIndex(bx_snap))
        item = fplt.plot(s, style=">", color=_BUY, ax=ax, legend="Buy")
        _style_marker(item, _BUY)
    if sx:
        sx_snap = _snap_list(sx, candle_index)
        s = pd.Series(sy, index=pd.DatetimeIndex(sx_snap))
        item = fplt.plot(s, style="<", color=_SELL, ax=ax, legend="Sell")
        _style_marker(item, _SELL)

    # Comment label
    if recorder.comments:
        last_text = recorder.comments[-1].text
        try:
            fplt.add_legend(last_text, ax=ax)
        except Exception:
            pass

    fplt.show(qt_exec=block)
