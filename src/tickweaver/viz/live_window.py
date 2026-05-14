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

# Spot order markers (Buy / Sell)
_BUY = "#2196F3"
_SELL = "#FF9800"

# Pair connecting line (Buy -> Sell)
_PAIR = "#2196F3"

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

    return (
        f"<div style='color:{_FG}; font-family:Consolas,monospace; font-size:11px;'>"
        f"<b>Backtest summary</b>"
        f"<ul style='margin:2px 0 0 16px; padding:0;'>{summary_li}</ul>"
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


def _attach_description_pane(fplt, html: str):
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
        splitter.addWidget(desc)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 140])
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

    fplt.candlestick_ochl(df[["open", "close", "high", "low"]], ax=price_ax)

    # Pair lines.
    for t in _trades(recorder):
        e_x = _snap_to_candle(pd.Timestamp(t.entry_ts), candle_index)
        x_x = _snap_to_candle(pd.Timestamp(t.exit_ts), candle_index)
        _draw_pair_line(
            fplt, price_ax,
            e_x, float(t.entry_price),
            x_x, float(t.exit_price),
            _PAIR,
        )

    # Buy / Sell markers — x snapped, y kept at fill_price. No legend.
    bx, by, sx, sy = _split_buy_sell(recorder)
    if bx:
        bx_snap = _snap_list(bx, candle_index)
        s = pd.Series(by, index=pd.DatetimeIndex(bx_snap))
        item = fplt.plot(s, style=">", color=_BUY, ax=price_ax)
        _style_marker(item, _BUY)
    if sx:
        sx_snap = _snap_list(sx, candle_index)
        s = pd.Series(sy, index=pd.DatetimeIndex(sx_snap))
        item = fplt.plot(s, style="<", color=_SELL, ax=price_ax)
        _style_marker(item, _SELL)

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
    initial_cash = 0.0
    n_trades = len(_trades(recorder))
    # Recorder doesn't carry initial_cash; recover from equity if possible.
    # Strategy doesn't pass it through chart hook today, so we just leave 0.0
    # unless the BacktestResult path later wires it through.
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
    )
    # finplot must finish its internal bookkeeping (axs / overlay_axs /
    # autoscale) BEFORE we reparent the chart widget into our wrapper.
    try:
        fplt.refresh()
    except Exception as e:
        print(f"[viz] fplt.refresh() warning: {type(e).__name__}: {e}")

    wrapper, app = _attach_description_pane(fplt, html)

    if wrapper is not None and app is not None:
        # Custom show path: we own the QMainWindow lifetime.
        wrapper.show()
        _bring_window_to_front(wrapper)
        if block:
            app.exec()
    else:
        # Fallback: keep the old finplot default windowing if anything failed.
        fplt.show(qt_exec=block)
