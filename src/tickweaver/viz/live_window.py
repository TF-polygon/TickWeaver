"""finplot-based replay viewer (Phase 4.2 + Phase 4 + Phase 5.1 dev/adv_verbose).

Single mode:
    show_replay() - all data shown at once (post-hoc).

Trading model: SPOT only. Buy / Sell are the only sides we render.

Layout (Phase 4 + Phase 5.1):
- 'price' panel is row 0 (the candlestick axis). PANEL='price' indicators
  (EMA / SMA / BollingerBands) are overlaid here.
- Each other panel id (rsi / macd / atr / ...) gets its own sub-row.
- Each panel ax shows a left-top title (symbol for price; panel id for
  sub-panels) and a right-top crosshair readout (OHLC for price, current
  indicator values for sub-panels).
- The main window's central widget is split vertically: chart area on top,
  a read-only description panel at the bottom that lists run summary and
  the indicator legend.

X-axis snap (finplot category-axis fix):
  finplot maps each candle timestamp to a category index. Sub-bar fill
  timestamps (e.g. 04:04:05.45 inside an hourly bar at 04:00) do not exist
  in that index, so without a fix finplot scatters them into "between" slots
  that drift away from the candles. We snap each fill_ts to the close_ts of
  the candle that contains it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from tickweaver.viz.events import IndicatorTrack
    from tickweaver.viz.recorder import EventRecorder


# Dark navy palette
_BG = "#0F1A2E"
_PLOT_BG = "#0F1A2E"
_FG = "#cfcfcf"
_DESC_BG = "#0B1424"
_BORDER = "#3A4A66"

# Candle colors
_BULL = "#26A69A"
_BEAR = "#EF5350"

# Spot order markers (Buy / Sell) — kept for back-compat with single-axis path.
_BUY = "#2196F3"
_SELL = "#FF9800"

# Phase F3: 4-way intent-aware fill markers (Open/Close x Long/Short).
# Color encodes intent (open/close + direction), shape encodes order side
# (^ for BUY, v for SELL). Combined they read as:
#   ^ blue   = Open Long      (BUY from FLAT)
#   v orange = Close Long     (SELL while LONG)
#   v red    = Open Short     (SELL from FLAT, futures only)
#   ^ teal   = Close Short    (BUY while SHORT, futures only)
_OPEN_LONG_COLOR   = "#2196F3"   # blue
_CLOSE_LONG_COLOR  = "#FF9800"   # orange
_OPEN_SHORT_COLOR  = "#EF5350"   # red
_CLOSE_SHORT_COLOR = "#26A69A"   # teal

# Pair connecting line (entry → close).
# Phase V8b: split by entry side. Long pairs = pure blue (0,0,255), Short
# pairs = pure red (255,0,0). _PAIR remains as a legacy fallback.
_PAIR = "#2196F3"
_PAIR_LONG  = "#0000FF"   # rgb(0, 0, 255)
_PAIR_SHORT = "#FF0000"   # rgb(255, 0, 0)

# Marker styling
_MARKER_SIZE = 7
_MARKER_OUTLINE = "#FFFFFF"
_MARKER_OUTLINE_WIDTH = 1.0

# Auto color palette for indicator lines. Avoids _BUY/_SELL and candle colors.
_INDICATOR_PALETTE = (
    "#FFEB3B",  # yellow
    "#00BCD4",  # cyan
    "#E91E63",  # magenta
    "#9C27B0",  # purple
    "#CDDC39",  # lime
    "#FF5722",  # deep orange-red (distinct from _SELL)
    "#03A9F4",  # light blue (distinct from _BUY)
    "#8BC34A",  # light green (distinct from bull green)
)


# ─────────────────────────────────────────────────────────
# Pure helpers (Phase 4 + 5.1) — unit-tested
# ─────────────────────────────────────────────────────────
def _group_indicators_by_panel(
    recorder: "EventRecorder",
) -> dict[str, list["IndicatorTrack"]]:
    """Group recorder.indicators by panel id, preserving registration order."""
    grouped: dict[str, list["IndicatorTrack"]] = {"price": []}
    for track in recorder.indicators.values():
        panel = track.registration.panel
        grouped.setdefault(panel, []).append(track)
    return grouped


def _panel_order(grouped: dict[str, list]) -> list[str]:
    """Decide row order. 'price' always row 0. Others follow insertion order."""
    rest = [p for p in grouped.keys() if p != "price"]
    return ["price", *rest]


def _assign_default_color(panel: str, line_index: int) -> str:
    """Deterministic color per (panel, line_index)."""
    return _INDICATOR_PALETTE[line_index % len(_INDICATOR_PALETTE)]


def _resolve_line_color(track: "IndicatorTrack", panel: str, line_index: int) -> str:
    style = track.registration.style or {}
    return style.get("color") or _assign_default_color(panel, line_index)


def _build_crosshair_lookup(
    recorder: "EventRecorder",
    grouped: dict[str, list["IndicatorTrack"]],
) -> tuple[
    dict[pd.Timestamp, tuple[float, float, float, float]],
    dict[str, dict[pd.Timestamp, dict[str, float]]],
]:
    """Build fast lookup tables for the crosshair callback.

    Returns:
        (ohlc_lookup, panel_lookup) where:
        - ohlc_lookup[ts] = (open, high, low, close) for each captured bar
        - panel_lookup[panel_id][ts][line_name] = sample value
    """
    ohlc_lookup: dict[pd.Timestamp, tuple[float, float, float, float]] = {}
    for _, bar in recorder.bars:
        ohlc_lookup[bar.timestamp] = (
            float(bar.open),
            float(bar.high),
            float(bar.low),
            float(bar.close),
        )
    panel_lookup: dict[str, dict[pd.Timestamp, dict[str, float]]] = {}
    for panel, tracks in grouped.items():
        ts_map: dict[pd.Timestamp, dict[str, float]] = {}
        for track in tracks:
            name = track.registration.name
            for s in track.samples:
                if s.timestamp is None:
                    continue
                ts = pd.Timestamp(s.timestamp)
                ts_map.setdefault(ts, {})[name] = float(s.value)
        panel_lookup[panel] = ts_map
    return ohlc_lookup, panel_lookup


def _build_description_html(
    *,
    symbol: str,
    timeframe: str,
    period_start: pd.Timestamp | None,
    period_end: pd.Timestamp | None,
    initial_cash: float,
    final_equity: float,
    n_fills: int,
    n_trades: int,
    indicator_specs: list[tuple[str, str, str]],
    marker_specs: list[tuple[str, str, str, int]] | None = None,
) -> str:
    """Render the bottom description pane.

    indicator_specs is a list of (name, panel, color) tuples used to draw a
    colored bullet list of every line on the chart.
    """
    period_str = ""
    if period_start is not None and period_end is not None:
        period_str = (
            f"{pd.Timestamp(period_start).strftime('%Y-%m-%d')} ~ "
            f"{pd.Timestamp(period_end).strftime('%Y-%m-%d')}"
        )

    pnl = final_equity - initial_cash
    pnl_pct = (pnl / initial_cash * 100.0) if initial_cash > 0 else 0.0

    rows = [
        ("Symbol / TF", f"{symbol} {timeframe}".strip()),
        ("Period", period_str),
        ("Initial cash", f"{initial_cash:,.2f}"),
        ("Final equity", f"{final_equity:,.2f}"),
        ("PnL", f"{pnl:,.2f}  ({pnl_pct:+.2f}%)"),
        ("Fills / Trades", f"{n_fills} / {n_trades}"),
    ]

    summary_li = "".join(
        f"<li><b>{label}:</b> {value}</li>" for label, value in rows
    )

    indicator_li = ""
    if indicator_specs:
        items = []
        for name, panel, color in indicator_specs:
            panel_tag = f" <span style='color:#8a98b0;'>[{panel}]</span>"
            items.append(
                f"<li><span style='color:{color};'>&#9632;</span> "
                f"<b>{name}</b>{panel_tag}</li>"
            )
        indicator_li = (
            "<div style='margin-top:6px;'><b>Indicators</b>"
            "<ul style='margin:2px 0 0 16px; padding:0;'>"
            + "".join(items)
            + "</ul></div>"
        )

    # Phase F3 round 2: 4-way marker legend. Each spec is
    # (label, shape, color, count). Shape "^" → ▲ (BUY), "v" → ▼ (SELL).
    marker_li = ""
    if marker_specs:
        items = []
        for label, shape, color, count in marker_specs:
            glyph = "▲" if shape == "^" else "▼"
            items.append(
                f"<li><span style='color:{color}; font-size:13pt;'>{glyph}</span>"
                f"&nbsp;<b>{label}</b>&nbsp;"
                f"<span style='color:#8a98b0;'>({count})</span></li>"
            )
        marker_li = (
            "<div style='margin-top:6px;'><b>Markers</b>"
            "<ul style='margin:2px 0 0 16px; padding:0;'>"
            + "".join(items)
            + "</ul></div>"
        )

    return (
        f"<div style='color:{_FG}; font-family:Consolas,monospace; font-size:11px;'>"
        f"<b>Backtest summary</b>"
        f"<ul style='margin:2px 0 0 16px; padding:0;'>{summary_li}</ul>"
        f"{marker_li}"
        f"{indicator_li}"
        f"</div>"
    )


# ─────────────────────────────────────────────────────────
# Data helpers (Phase 4.2)
# ─────────────────────────────────────────────────────────
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


def _classify_fills_by_intent(fills) -> dict[str, list[tuple]]:
    """Classify each fill as one of {open_long, close_long, open_short,
    close_short} by simulating position state through the fill sequence.

    Returns a dict mapping each intent to a list of ``(timestamp, price)``
    tuples in fill order.

    A reverse fill (SELL with qty > position.qty while LONG, or vice versa)
    emits BOTH a close and an open at the same timestamp / price — that is
    the correct visual story for a futures position flip.
    """
    open_long: list[tuple] = []
    close_long: list[tuple] = []
    open_short: list[tuple] = []
    close_short: list[tuple] = []

    cur_side: str | None = None   # 'long' / 'short' / None
    cur_qty: float = 0.0

    for f in fills:
        side_value = f.side.value if hasattr(f.side, "value") else str(f.side)
        ts = f.timestamp
        price = float(f.price)
        qty = float(f.qty)

        if cur_side is None:
            # Open from FLAT.
            if side_value == "buy":
                cur_side = "long"
                cur_qty = qty
                open_long.append((ts, price))
            else:
                cur_side = "short"
                cur_qty = qty
                open_short.append((ts, price))
            continue

        if cur_side == "long":
            if side_value == "buy":
                # Pyramiding: same side add.
                cur_qty += qty
                open_long.append((ts, price))
            else:
                # SELL while LONG: close (possibly + reverse to short).
                close_long.append((ts, price))
                close_qty = min(cur_qty, qty)
                cur_qty -= close_qty
                if cur_qty <= 1e-12:
                    cur_side = None
                    cur_qty = 0.0
                    leftover = qty - close_qty
                    if leftover > 1e-12:
                        # Position flip — open short with the leftover.
                        cur_side = "short"
                        cur_qty = leftover
                        open_short.append((ts, price))
        else:  # cur_side == "short"
            if side_value == "sell":
                # Pyramiding: same side add.
                cur_qty += qty
                open_short.append((ts, price))
            else:
                # BUY while SHORT: close (possibly + reverse to long).
                close_short.append((ts, price))
                close_qty = min(cur_qty, qty)
                cur_qty -= close_qty
                if cur_qty <= 1e-12:
                    cur_side = None
                    cur_qty = 0.0
                    leftover = qty - close_qty
                    if leftover > 1e-12:
                        cur_side = "long"
                        cur_qty = leftover
                        open_long.append((ts, price))

    return {
        "open_long": open_long,
        "close_long": close_long,
        "open_short": open_short,
        "close_short": close_short,
    }


def _split_buy_sell(recorder: "EventRecorder"):
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


def _make_pair_lines(fills) -> list[tuple]:
    """Phase V8: per-position pair line endpoints from a raw Fill sequence.

    Unlike `extract_trades` (which averages martingale adds into a single
    Trade with a weighted entry price), this helper emits one tuple per
    entry fill — so a martingale cycle with N adds renders as N pair
    lines all sharing the same exit endpoint.

    Matching is FIFO over Side.BUY ↔ Side.SELL queues. Same-side fills
    grow the open queue; opposite-side fills pop FIFO and emit a pair line
    for each matched (open_fill, close_fill, qty) chunk. Surplus leftover
    on the closing fill becomes a new open (reverse) entry.

    Returns: list of (entry_ts, entry_price, exit_ts, exit_price[, side])
    tuples. `side` is the *entry* side string ("buy" for a long, "sell"
    for a short) — used by show_replay to color lines per direction.
    Tests that index by position 0..3 still work; side is at index 4.
    """
    open_longs: list[list] = []   # [ts, price, qty_remaining]
    open_shorts: list[list] = []  # [ts, price, qty_remaining]
    pairs: list[tuple] = []

    for f in fills:
        side = f.side.value if hasattr(f.side, "value") else str(f.side)
        qty = float(f.qty)
        ts = f.timestamp
        price = float(f.price)

        if side == "buy":
            # Close shorts FIFO first; leftover opens a new long.
            while qty > 1e-12 and open_shorts:
                s = open_shorts[0]
                matched = min(s[2], qty)
                pairs.append((s[0], s[1], ts, price, "sell"))
                s[2] -= matched
                qty -= matched
                if s[2] <= 1e-12:
                    open_shorts.pop(0)
            if qty > 1e-12:
                open_longs.append([ts, price, qty])
        else:  # sell — mirror
            while qty > 1e-12 and open_longs:
                lng = open_longs[0]
                matched = min(lng[2], qty)
                pairs.append((lng[0], lng[1], ts, price, "buy"))
                lng[2] -= matched
                qty -= matched
                if lng[2] <= 1e-12:
                    open_longs.pop(0)
            if qty > 1e-12:
                open_shorts.append([ts, price, qty])

    return pairs


def _style_marker(item, fill_color: str) -> None:
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


def _track_to_series(track: "IndicatorTrack") -> pd.Series | None:
    if not track.samples:
        return None
    timestamps = []
    values = []
    for s in track.samples:
        if s.timestamp is None:
            continue
        timestamps.append(pd.Timestamp(s.timestamp))
        values.append(float(s.value))
    if not timestamps:
        return None
    return pd.Series(values, index=pd.DatetimeIndex(timestamps))


def _draw_indicator_lines(
    fplt, ax, tracks: list["IndicatorTrack"], panel: str
) -> list[tuple[str, str]]:
    """Plot every indicator line in `tracks` on `ax`. Returns (name, color) list."""
    spec: list[tuple[str, str]] = []
    for i, t in enumerate(tracks):
        s = _track_to_series(t)
        if s is None:
            continue
        style = t.registration.style or {}
        color = _resolve_line_color(t, panel, i)
        width = style.get("width", 1)
        line_style = style.get("style")
        kwargs: dict = {"color": color, "width": width, "ax": ax}
        if line_style is not None:
            kwargs["style"] = line_style
        try:
            fplt.plot(s, **kwargs)
        except TypeError:
            fplt.plot(s, color=color, ax=ax)
        spec.append((t.registration.name, color))
    return spec


# ─────────────────────────────────────────────────────────
# GUI decoration (Phase 5.1)
# ─────────────────────────────────────────────────────────
def _add_corner_label(
    ax,
    text: str,
    *,
    anchor: str = "topleft",
    size_pt: int = 13,
    weight: int = 700,
) -> Any:
    """Place a fixed TextItem at a corner of `ax`.

    anchor = 'topleft' for static panel titles (BTC/USDT, RSI, ...) — defaults
    to 13pt bold. anchor = 'topright' for crosshair readouts — caller should
    pass size_pt=10, weight=400 and update via setHtml() with mixed colors.
    """
    try:
        import pyqtgraph as pg
    except ImportError:
        return None

    def _html(t: str) -> str:
        return (
            f"<span style='color:{_FG}; font-family:Consolas,monospace; "
            f"font-size:{size_pt}pt; font-weight:{weight};'>{t}</span>"
        )

    try:
        item = pg.TextItem(
            html=_html(text),
            anchor=(0, 0) if anchor == "topleft" else (1, 0),
        )
        # Plain-text setText forwarder that keeps the wrapper font.
        def _set(t: str, _item=item) -> None:
            _item.setHtml(_html(t))
        item.setText = _set  # type: ignore[assignment]

        item.setParentItem(ax.vb)
        if anchor == "topleft":
            item.setPos(8, 4)
        else:
            def _reposition(_):
                try:
                    w = ax.vb.width()
                    item.setPos(w - 8, 4)
                except Exception:
                    item.setPos(0, 4)
            try:
                ax.vb.sigResized.connect(_reposition)
                _reposition(None)
            except Exception:
                item.setPos(0, 4)
        return item
    except Exception:
        return None


def _decorate_panel_border(ax) -> None:
    """Frame the panel with white axes on all 4 sides so each panel is clearly
    boxed (Phase 5.1 fix). Tick values stay only on the bottom + left axes;
    the top + right axes act as a pure border.
    """
    try:
        import pyqtgraph as pg
    except ImportError:
        return
    try:
        ax.vb.setBackgroundColor(_PLOT_BG)
        pen = pg.mkPen("#FFFFFF", width=1)
        # Phase 5.1 round 2: tick values live on right + bottom only.
        # Left + top axes are kept visible (= white border line) but with
        # no tick labels and zero-length ticks, so they read as a pure frame.
        FRAME_ONLY = ("left", "top")
        WITH_VALUES = ("right", "bottom")
        for axis_name in (*FRAME_ONLY, *WITH_VALUES):
            try:
                ax.showAxis(axis_name)
                axis = ax.getAxis(axis_name)
                axis.setPen(pen)
                axis.setTextPen(pen)
                if axis_name in FRAME_ONLY:
                    axis.setStyle(showValues=False, tickLength=0)
            except Exception:
                pass
        try:
            ax.vb.border = pen
            ax.vb.update()
        except Exception:
            pass
    except Exception:
        pass


# Crosshair readout color scheme: keys / labels in gray, values in white.
_LABEL_GRAY = "#8a98b0"
_VALUE_WHITE = "#FFFFFF"


def _format_ohlc_html(ts: pd.Timestamp, ohlc: tuple[float, float, float, float]) -> str:
    o, h, l, c = ohlc
    g, w = _LABEL_GRAY, _VALUE_WHITE
    return (
        f"<span style='color:{g};'>{pd.Timestamp(ts).strftime('%Y-%m-%d %H:%M')}</span>"
        f"&nbsp;&nbsp;<span style='color:{g};'>O</span>&nbsp;<span style='color:{w};'>{o:,.2f}</span>"
        f"&nbsp;&nbsp;<span style='color:{g};'>H</span>&nbsp;<span style='color:{w};'>{h:,.2f}</span>"
        f"&nbsp;&nbsp;<span style='color:{g};'>L</span>&nbsp;<span style='color:{w};'>{l:,.2f}</span>"
        f"&nbsp;&nbsp;<span style='color:{g};'>C</span>&nbsp;<span style='color:{w};'>{c:,.2f}</span>"
    )


def _format_indicator_html(
    ts: pd.Timestamp, panel_values: dict[str, float]
) -> str:
    if not panel_values:
        return ""
    g, w = _LABEL_GRAY, _VALUE_WHITE
    parts = [
        f"<span style='color:{g};'>{name}</span>&nbsp;<span style='color:{w};'>{v:,.2f}</span>"
        for name, v in panel_values.items()
    ]
    return "&nbsp;&nbsp;".join(parts)


def _wrap_readout_html(inner_html: str) -> str:
    """Wrap mixed-color inner HTML in the crosshair font frame."""
    return (
        f"<span style='font-family:Consolas,monospace; font-size:10pt;'>"
        f"{inner_html}</span>"
    )


# Back-compat shims for any external callers / older tests.
def _format_ohlc_label(ts, ohlc) -> str:
    o, h, l, c = ohlc
    return (
        f"{pd.Timestamp(ts).strftime('%Y-%m-%d %H:%M')}  "
        f"O {o:.2f}  H {h:.2f}  L {l:.2f}  C {c:.2f}"
    )


def _format_indicator_label(ts, panel_values: dict[str, float]) -> str:
    if not panel_values:
        return ""
    return "  ".join(f"{n} {v:.2f}" for n, v in panel_values.items())


def _install_crosshair_inspector(
    fplt,
    *,
    price_ax,
    sub_axes: dict[str, Any],
    ohlc_lookup,
    panel_lookup,
    price_label_right,
    sub_labels_right: dict[str, Any],
    candle_index: pd.DatetimeIndex,
) -> None:
    """Wire pyqtgraph's sigMouseMoved to update the right-top crosshair labels.

    finplot's set_mouse_callback(when='hover') is unreliable across versions
    (silent fail, signature drift). pyqtgraph's GraphicsScene.sigMouseMoved
    is the canonical signal and works regardless of finplot's API churn.
    """
    if len(candle_index) == 0:
        return

    def _set_html(label, inner_html: str) -> None:
        if label is None:
            return
        try:
            label.setHtml(_wrap_readout_html(inner_html))
        except Exception:
            pass

    def _x_to_timestamp(x: float) -> pd.Timestamp | None:
        """finplot's x-axis can be either epoch-ns float or a category index.
        Try the nanosecond interpretation first (most common in finplot for
        candlestick_ochl with a DatetimeIndex), then fall back to integer
        category lookup."""
        try:
            ts = pd.Timestamp(int(x), unit="ns", tz="UTC")
            if (
                candle_index[0] - pd.Timedelta(days=365)
                <= ts
                <= candle_index[-1] + pd.Timedelta(days=365)
            ):
                return ts
        except Exception:
            pass
        try:
            i = int(round(x))
            if 0 <= i < len(candle_index):
                return candle_index[i]
        except Exception:
            pass
        return None

    def _on_mouse_moved(scene_pos) -> None:
        try:
            vb = price_ax.vb
            view_point = vb.mapSceneToView(scene_pos)
            ts_raw = _x_to_timestamp(view_point.x())
            if ts_raw is None:
                return
            ts = _snap_to_candle(ts_raw, candle_index)

            ohlc = ohlc_lookup.get(ts)
            if ohlc is not None:
                _set_html(price_label_right, _format_ohlc_html(ts, ohlc))

            for panel_id, label in sub_labels_right.items():
                pv = panel_lookup.get(panel_id, {}).get(ts, {})
                _set_html(label, _format_indicator_html(ts, pv))
        except Exception:
            # Never let a hover hiccup crash the GUI thread.
            pass

    try:
        scene = price_ax.vb.scene()
        scene.sigMouseMoved.connect(_on_mouse_moved)
    except Exception as e:
        print(f"[viz] crosshair wiring failed: {type(e).__name__}: {e}")


class _EscCloseFilter:
    """Application-wide event filter that turns ESC into a wrapper close().

    Implemented as a QObject so it can be installed via
    QApplication.installEventFilter. We subclass QObject lazily because
    importing PyQt at module import would pull GUI deps into headless code
    paths (tests, CI without Qt).
    """

    def __new__(cls, wrapper):
        from pyqtgraph.Qt import QtCore as _QtCore

        class _Impl(_QtCore.QObject):
            def __init__(self, target):
                super().__init__(target)
                self._target = target

            def eventFilter(self, obj, event):
                try:
                    if (
                        event.type() == _QtCore.QEvent.Type.KeyPress
                        and event.key() == _QtCore.Qt.Key.Key_Escape
                    ):
                        self._target.close()
                        return True
                except Exception:
                    pass
                return False

        return _Impl(wrapper)


def _bring_window_to_front(win) -> None:
    """Force the viz window above the terminal that launched the run.

    Plain raise_() + activateWindow() is unreliable on Windows when the
    new window is owned by a different focus-context (the python process
    is "background" to the foreground console). Toggling WindowStaysOnTopHint
    forces the WM to put the window on top, and we immediately turn the hint
    off so the user can still send the window to the back later.
    """
    try:
        from pyqtgraph.Qt import QtCore
    except ImportError:
        return
    try:
        # Step 1: stay-on-top hint forces foreground.
        try:
            win.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, True)
        except (AttributeError, TypeError):
            # Older PyQt: setWindowFlags with the full flag set.
            win.setWindowFlags(
                win.windowFlags() | QtCore.Qt.WindowType.WindowStaysOnTopHint
            )
        win.show()
        win.raise_()
        win.activateWindow()
        # Step 2: drop the hint so user can hide/restack normally afterwards.
        try:
            win.setWindowFlag(QtCore.Qt.WindowType.WindowStaysOnTopHint, False)
        except (AttributeError, TypeError):
            win.setWindowFlags(
                win.windowFlags() & ~QtCore.Qt.WindowType.WindowStaysOnTopHint
            )
        win.show()
    except Exception as e:
        # Foreground promotion is a nicety; never let it break the viz.
        print(f"[viz] bring-to-front failed: {type(e).__name__}: {e}")


def _attach_description_pane(fplt, html: str, table_widget=None):
    """Wrap finplot's chart widget in a QMainWindow with a description pane.

    Returns (wrapper, app) on success or (None, None) on failure.

    Lifecycle (round 3, after AttributeError on win.axs):
        - The caller must invoke fplt.refresh() BEFORE this function so any
          axes / overlay finplot bookkeeping is complete.
        - We then reparent fplt.windows[-1] (a GraphicsLayoutWidget) under our
          own QSplitter + QMainWindow.
        - We REMOVE the chart widget from fplt.windows so finplot will not
          try to refresh / show it again (would crash on win.axs lookup).
        - The caller is responsible for wrapper.show() + app.exec().

    Issue 4 Step 4: `table_widget` (PositionTableWidget) 이 주어지면 하단의
    description 영역을 horizontal splitter (desc | table) 로 wrap. None 이면
    기존처럼 desc 만 표시.
    """
    try:
        from pyqtgraph.Qt import QtCore, QtWidgets
    except ImportError as e:
        print(f"[viz] description pane skipped: PyQt unavailable ({e})")
        return None, None

    wins = getattr(fplt, "windows", None)
    if not wins:
        print("[viz] description pane skipped: fplt.windows is empty")
        return None, None

    chart_widget = wins[-1]
    if chart_widget is None:
        print("[viz] description pane skipped: chart widget is None")
        return None, None

    try:
        wrapper = QtWidgets.QMainWindow()
        try:
            t = chart_widget.windowTitle()
            if t:
                wrapper.setWindowTitle(t)
        except Exception:
            pass

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, wrapper)
        splitter.addWidget(chart_widget)

        desc = QtWidgets.QTextEdit()
        desc.setReadOnly(True)
        desc.setHtml(html)
        desc.setStyleSheet(
            f"QTextEdit {{ background-color: {_DESC_BG}; "
            f"color: {_FG}; "
            f"border-top: 1px solid #FFFFFF; "
            f"padding: 8px 12px; "
            f"font-family: Consolas, monospace; "
            f"font-size: 11px; }}"
        )
        desc.setMinimumHeight(100)

        # Issue 4 Step 4: 하단을 horizontal splitter (desc | table) 로 wrap.
        # table_widget=None 이면 desc 만 추가 (기존 동작).
        if table_widget is not None:
            bottom_pane = QtWidgets.QSplitter(
                QtCore.Qt.Orientation.Horizontal, wrapper
            )
            bottom_pane.addWidget(desc)
            bottom_pane.addWidget(table_widget)
            # desc 1 : table 2 — 표가 더 넓게.
            bottom_pane.setStretchFactor(0, 1)
            bottom_pane.setStretchFactor(1, 2)
            bottom_pane.setHandleWidth(4)
            splitter.addWidget(bottom_pane)
        else:
            splitter.addWidget(desc)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 220 if table_widget is not None else 140])
        splitter.setHandleWidth(4)

        wrapper.setCentralWidget(splitter)
        wrapper.resize(980, 644)

        # ESC closes the entire viz window (Phase 5.1 round 6).
        # Without an application-wide event filter the chart widget's own
        # ESC handler could close just the chart, leaving the description
        # pane stranded in the splitter. We install both:
        #   (1) a QShortcut with ApplicationShortcut context, and
        #   (2) an app-level QObject event filter, so whichever fires first
        #       routes the key to wrapper.close().
        try:
            try:
                from pyqtgraph.Qt import QtGui as _QtGui
                esc_seq = _QtGui.QKeySequence(QtCore.Qt.Key.Key_Escape)
                shortcut = _QtGui.QShortcut(esc_seq, wrapper)
            except Exception:
                shortcut = QtWidgets.QShortcut(
                    QtCore.Qt.Key.Key_Escape, wrapper
                )
            try:
                shortcut.setContext(QtCore.Qt.ShortcutContext.ApplicationShortcut)
            except Exception:
                pass
            shortcut.activated.connect(wrapper.close)
        except Exception as e:
            print(f"[viz] ESC shortcut wiring failed: {type(e).__name__}: {e}")

        # Belt-and-suspenders: application-level event filter.
        try:
            app_for_filter = QtWidgets.QApplication.instance()
            if app_for_filter is not None:
                _filter = _EscCloseFilter(wrapper)
                # Keep a strong reference on the wrapper so the filter is not
                # garbage-collected while the window is alive.
                wrapper._esc_filter = _filter  # type: ignore[attr-defined]
                app_for_filter.installEventFilter(_filter)
        except Exception as e:
            print(f"[viz] ESC event filter wiring failed: {type(e).__name__}: {e}")

        # Detach chart widget from finplot's bookkeeping. Otherwise finplot's
        # refresh/show paths (which expect a FinWindow with .axs) would crash.
        try:
            wins.remove(chart_widget)
        except ValueError:
            pass

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
        return wrapper, app
    except Exception as e:
        print(f"[viz] description pane attach failed: {type(e).__name__}: {e}")
        return None, None


# ─────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────
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
    win_title = f"{symbol} {timeframe}".strip() or "tickweaver replay"

    grouped = _group_indicators_by_panel(recorder)
    order = _panel_order(grouped)
    n_rows = len(order)

    if n_rows == 1:
        price_ax = fplt.create_plot(win_title, maximize=False, init_zoom_periods=200)
        sub_axes: dict[str, Any] = {}
    else:
        axes = fplt.create_plot(
            win_title, rows=n_rows, maximize=False, init_zoom_periods=200
        )
        if not isinstance(axes, (list, tuple)):
            axes = (axes,)
        price_ax = axes[0]
        sub_axes = {pid: axes[i] for i, pid in enumerate(order) if i > 0}

    # fix/zoomin-issue: 멀티패널 X-link zoom-drift 수정 (아래 블록 주석 참조).
    try:
        import pyqtgraph as pg

        _vbs = [price_ax]
        _vbs.extend(sub_axes.values())

        # fix/zoomin-issue 타깃 수정: finplot 의 FinViewBox.linkedViewChanged
        # override 가 linked 패널 X-sync 시 update_y_zoom(X 정수 반올림 + 재zoom)
        # 을 호출 → 멀티패널에서 매 drag/resize 마다 span 이 max_zoom_points(20)
        # 까지 축소된다 (단일 패널은 link 가 없어 정상 pan). pyqtgraph 네이티브
        # linkedViewChanged 로 복원하면 서브패널이 price 의 X 를 반올림/재zoom
        # 없이 그대로 추종 → zoom-drift 제거, pan-together 유지.
        if len(_vbs) > 1:
            for _i, _ax in enumerate(_vbs):
                _vb = getattr(_ax, "vb", None) or getattr(
                    _ax, "getViewBox", lambda: None
                )()
                if _vb is None:
                    continue
                _cls = type(_vb)
                if "linkedViewChanged" in _cls.__dict__:
                    try:
                        _cls.linkedViewChanged = pg.ViewBox.linkedViewChanged
                    except Exception:
                        pass
                # 서브패널(price 외 linked 패널): native X-sync 는 Y 를 안
                # 건드리므로, finplot update_y_zoom 의 Y-fit 을 대신해 pyqtgraph
                # Y auto-fit 을 켠다 → 인디케이터(RSI 등)가 X pan 에 따라 가시
                # 데이터에 맞춰 계속 보이게. price(_i==0)는 제외(Y 안정 유지).
                if _i > 0:
                    try:
                        _vb.enableAutoRange(axis="y", enable=True)
                        _vb.setAutoVisible(y=True)
                    except Exception:
                        pass

    except Exception as _e:
        print(f"[viz] linked-view zoom fix skipped: {type(_e).__name__}: {_e}")

    fplt.candlestick_ochl(df[["open", "close", "high", "low"]], ax=price_ax)

    # Pair lines — Phase V8: one line per *position* (entry fill), not per
    # averaged Trade. A martingale cycle with N adds therefore renders as N
    # dotted lines whose left endpoints (entry fills) differ but whose right
    # endpoints (exit fill) coincide. _make_pair_lines does FIFO matching on
    # the raw Fill sequence so qty splits and reverse fills are handled.
    # V8b: color by entry side — Long pair = pure blue, Short pair = pure red.
    for _pair in _make_pair_lines(recorder.fills):
        e_ts, e_p, x_ts, x_p = _pair[0], _pair[1], _pair[2], _pair[3]
        entry_side = _pair[4] if len(_pair) > 4 else "buy"
        color = _PAIR_LONG if entry_side == "buy" else _PAIR_SHORT
        e_x = _snap_to_candle(pd.Timestamp(e_ts), candle_index)
        x_x = _snap_to_candle(pd.Timestamp(x_ts), candle_index)
        _draw_pair_line(
            fplt, price_ax,
            e_x, float(e_p),
            x_x, float(x_p),
            color,
        )

    # Phase F3: 4-way intent-aware markers (Open/Close x Long/Short).
    # x is snapped to the candle that contains the fill timestamp; y stays
    # at fill_price so a wick fill still lands inside the wick visually.
    #
    # Issue 3 Step 5b: hover tooltip — 위 visual marker 위에 invisible
    # ScatterPlotItem 을 한 layer 더 추가해서 sigHovered 만 받음. tooltip
    # 데이터는 build_marker_tooltips 가 _classify_fills_by_intent 와 동일
    # 매칭 로직으로 생성하므로 두 list 가 1:1 매칭.
    import pyqtgraph as _pg

    # Polish C: 종목별 가격 정밀도 (runner 가 CCXT market info 에서 주입).
    # hover tooltip 의 Entry/Exit 와 position table 의 Entry Price 가 공유.
    _price_decimals = int(getattr(recorder, "price_decimals", 2) or 2)

    intent_groups = _classify_fills_by_intent(recorder.fills)

    # Step 5b: tooltip 데이터 build + TextItem 본체
    _tooltip_data: dict = {
        "open_long": [], "close_long": [],
        "open_short": [], "close_short": [],
    }
    try:
        from tickweaver.analytics.positions import build_marker_tooltips
        _tooltip_lev = float(getattr(recorder, "leverage", 1.0) or 1.0)
        _tooltip_data = build_marker_tooltips(
            recorder.fills, leverage=_tooltip_lev
        )
    except Exception as e:
        print(f"[viz] marker tooltip data skipped: {type(e).__name__}: {e}")

    _tooltip_item = None
    try:
        _tooltip_item = _pg.TextItem(
            "",
            anchor=(0, 1.0),
            color=(255, 255, 255),
            fill=_pg.mkBrush(30, 30, 30, 220),
            border=_pg.mkPen(180, 180, 180),
        )
        _tooltip_item.setZValue(100)
        price_ax.addItem(_tooltip_item)
        _tooltip_item.hide()
    except Exception as e:
        print(f"[viz] tooltip TextItem skipped: {type(e).__name__}: {e}")
        _tooltip_item = None

    _INTENT_LABEL = {
        "open_long":   "Open Long",
        "close_long":  "Close Long",
        "open_short":  "Open Short",
        "close_short": "Close Short",
    }

    def _format_marker_tooltip(info: dict) -> str:
        intent = info["intent"]
        label = _INTENT_LABEL.get(intent, intent)
        ts_str = pd.Timestamp(info["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
        if intent.startswith("open_"):
            return (
                f"Order #{info['order_no']}\n"
                f"{ts_str}\n"
                f"{label}\n"
                f"Margin: {info['margin']:.2f} USDT\n"
                f"Entry:  {info['price']:.{_price_decimals}f}"
            )
        # close_*
        closed = info.get("closed_orders") or []
        if len(closed) <= 1:
            head = f"Order #{closed[0]}" if closed else "Order #?"
            pnl_label = "PnL"
        else:
            head = "Orders " + ", ".join(f"#{n}" for n in closed)
            pnl_label = "PnL Total"
        pnl = info.get("pnl")
        pnl_str = f"{pnl:+.2f}" if pnl is not None else "—"
        return (
            f"{head}\n"
            f"{ts_str}\n"
            f"{label}\n"
            f"{pnl_label}: {pnl_str} USDT\n"
            f"Exit:   {info['price']:.{_price_decimals}f}"
        )

    def _on_marker_hover(_plot, points, _ev):
        if _tooltip_item is None:
            return
        if len(points) == 0:
            _tooltip_item.hide()
            return
        info = points[0].data()
        if not isinstance(info, dict):
            _tooltip_item.hide()
            return
        try:
            _tooltip_item.setText(_format_marker_tooltip(info))
            pos = points[0].pos()
            _tooltip_item.setPos(pos.x(), pos.y())
            _tooltip_item.show()
        except Exception:
            _tooltip_item.hide()

    _marker_specs = (
        ("open_long",   "^", _OPEN_LONG_COLOR),
        ("close_long",  "v", _CLOSE_LONG_COLOR),
        ("open_short",  "v", _OPEN_SHORT_COLOR),
        ("close_short", "^", _CLOSE_SHORT_COLOR),
    )
    for key, shape, color in _marker_specs:
        pts = intent_groups.get(key, [])
        if not pts:
            continue
        xs = [t for t, _ in pts]
        ys = [p for _, p in pts]
        xs_snap = _snap_list(xs, candle_index)
        s = pd.Series(ys, index=pd.DatetimeIndex(xs_snap))
        try:
            item = fplt.plot(s, style=shape, color=color, ax=price_ax)
        except TypeError:
            item = fplt.plot(s, color=color, ax=price_ax)
        _style_marker(item, color)

        # Step 5b: invisible hover scatter — marker 위치에 transparent 점
        # 을 한 겹 더 깔아서 sigHovered 만 받음. visual marker 와 좌표 동일.
        if _tooltip_item is None:
            continue
        tt_data = _tooltip_data.get(key, [])
        if len(pts) != len(tt_data):
            print(
                f"[viz] hover skipped for {key}: marker/tooltip count "
                f"mismatch {len(pts)} vs {len(tt_data)}"
            )
            continue
        try:
            # finplot 의 candle x 축은 정수 bar index. snapped timestamp →
            # int index 로 변환.
            x_indices: list[int] = []
            for snapped_ts in xs_snap:
                pos_idx = candle_index.searchsorted(
                    pd.Timestamp(snapped_ts), side="left"
                )
                pos_idx = max(0, min(int(pos_idx), len(candle_index) - 1))
                x_indices.append(pos_idx)
            hover_item = _pg.ScatterPlotItem(
                x=x_indices,
                y=ys,
                symbol="o",
                size=_MARKER_SIZE * 2,   # marker 보다 큰 hover 영역
                brush=_pg.mkBrush(0, 0, 0, 0),   # transparent
                pen=_pg.mkPen(0, 0, 0, 0),       # transparent
                data=tt_data,
                hoverable=True,
                tip=None,   # pyqtgraph 기본 'x/y/data' 툴팁 끔 — 커스텀 tooltip 만 표시
            )
            hover_item.setZValue(50)
            price_ax.addItem(hover_item)
            hover_item.sigHovered.connect(_on_marker_hover)
        except Exception as e:
            print(
                f"[viz] hover scatter for {key} failed: "
                f"{type(e).__name__}: {e}"
            )

    # Indicator lines per panel. Collect (name, panel, color) for description.
    indicator_specs: list[tuple[str, str, str]] = []
    price_spec = _draw_indicator_lines(fplt, price_ax, grouped.get("price", []), "price")
    for name, color in price_spec:
        indicator_specs.append((name, "price", color))
    for pid, ax in sub_axes.items():
        spec = _draw_indicator_lines(fplt, ax, grouped.get(pid, []), pid)
        for name, color in spec:
            indicator_specs.append((name, pid, color))

    # Phase 5.1 — panel borders + corner labels.
    _decorate_panel_border(price_ax)
    price_label_left = _add_corner_label(price_ax, symbol or "", anchor="topleft")
    price_label_right = _add_corner_label(price_ax, "", anchor="topright", size_pt=10, weight=400)
    sub_labels_right: dict[str, Any] = {}
    for pid, ax in sub_axes.items():
        _decorate_panel_border(ax)
        _add_corner_label(ax, pid.upper(), anchor="topleft")
        sub_labels_right[pid] = _add_corner_label(ax, "", anchor="topright", size_pt=10, weight=400)

    # Crosshair callback wiring.
    ohlc_lookup, panel_lookup = _build_crosshair_lookup(recorder, grouped)
    _install_crosshair_inspector(
        fplt,
        price_ax=price_ax,
        sub_axes=sub_axes,
        ohlc_lookup=ohlc_lookup,
        panel_lookup=panel_lookup,
        price_label_right=price_label_right,
        sub_labels_right=sub_labels_right,
        candle_index=candle_index,
    )

    # Description pane at the bottom of the main window.
    period_start = candle_index.min() if len(candle_index) else None
    period_end = candle_index.max() if len(candle_index) else None
    final_equity = float(recorder.final_equity or 0.0)
    # Phase V7: runner injects initial_cash into the recorder before run.
    initial_cash = float(getattr(recorder, "initial_cash", 0.0))
    n_trades = len(_trades(recorder))
    # Build marker legend from the same intent_groups used to draw markers.
    # Only include intents that actually fired (non-empty list).
    _marker_meta = (
        ("open_long",   "Open Long",   "^", _OPEN_LONG_COLOR),
        ("close_long",  "Close Long",  "v", _CLOSE_LONG_COLOR),
        ("open_short",  "Open Short",  "v", _OPEN_SHORT_COLOR),
        ("close_short", "Close Short", "^", _CLOSE_SHORT_COLOR),
    )
    marker_legend: list[tuple[str, str, str, int]] = []
    for key, label, shape, color in _marker_meta:
        pts = intent_groups.get(key, [])
        if pts:
            marker_legend.append((label, shape, color, len(pts)))

    html = _build_description_html(
        symbol=symbol,
        timeframe=timeframe,
        period_start=period_start,
        period_end=period_end,
        initial_cash=initial_cash,
        final_equity=final_equity,
        n_fills=len(recorder.fills),
        n_trades=n_trades,
        indicator_specs=indicator_specs,
        marker_specs=marker_legend,
    )
    # Issue 4 Step 4: 포지션 히스토리 표 위젯 생성. recorder.fills 와 leverage
    # 를 build_position_history 에 전달. PyQt 미설치 등으로 실패하면 None
    # 으로 두고 _attach_description_pane 이 desc-only 모드로 동작.
    table_widget = None
    try:
        from tickweaver.analytics.positions import build_position_history
        from tickweaver.viz.position_table import PositionTableWidget
        _leverage = float(getattr(recorder, "leverage", 1.0) or 1.0)
        _history_rows = build_position_history(
            recorder.fills,
            leverage=_leverage,
            bar_timestamps=candle_index,
        )
        table_widget = PositionTableWidget(
            rows=_history_rows, price_decimals=_price_decimals
        )
    except Exception as e:
        print(f"[viz] position table skipped: {type(e).__name__}: {e}")
        table_widget = None

    # finplot must finish its internal bookkeeping (axs / overlay_axs /
    # autoscale) BEFORE we reparent the chart widget into our wrapper.
    try:
        fplt.refresh()
    except Exception as e:
        print(f"[viz] fplt.refresh() warning: {type(e).__name__}: {e}")

    wrapper, app = _attach_description_pane(fplt, html, table_widget=table_widget)

    if wrapper is not None and app is not None:
        # Custom show path: we own the QMainWindow lifetime.
        wrapper.show()
        _bring_window_to_front(wrapper)
        if block:
            app.exec()
    else:
        # Fallback: keep the old finplot default windowing if anything failed.
        fplt.show(qt_exec=block)
