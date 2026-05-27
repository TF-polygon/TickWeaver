"""finplot-based *streaming* replay viewer (--viz --stream).

Unlike live_window.show_replay (static post-hoc, everything drawn at once),
this viewer replays the recorded tick stream from start to finish: each candle
grows from its open (body), leaves a wick trail, recolors bull/bear by
current-vs-open, then finalizes and the next bar begins. Fill markers,
indicator sub-panels and the position-history table reveal in step with the
progress.

All replay/decision logic lives in the pure, unit-tested viz.streaming module
(TickReplayer, StreamClock, auto_y_range, revealed_count). This file is the
Qt/finplot wiring only — finplot + PyQt are imported lazily so the headless
code paths (tests / CI without Qt) never pull GUI deps.

Controls (bottom bar):
- Pause / Resume button — freezes / resumes tick consumption.
- horizontal speed slider — 0.25x .. 16x (audio-controller style).
- Drag toggle — ON: free pan/zoom while streaming; OFF (default): the view
  auto-follows the forming candle and auto-rescales Y so a 장봉 stays on screen.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pandas as pd

from tickweaver.viz import live_window as lw
from tickweaver.viz.streaming import (
    StreamClock,
    TickReplayer,
    auto_y_range,
    revealed_count,
)

if TYPE_CHECKING:
    from tickweaver.viz.recorder import EventRecorder

# Auto-follow X window width (bars). Bounds per-frame paint via finplot LOD.
VISIBLE_BARS = 150
# Timer cadence. One fire consumes StreamClock.ticks_this_frame() ticks.
DEFAULT_TICK_INTERVAL_S = 0.03

# Discrete speed steps for the slider = ticks consumed per frame. Low end
# (0.25x) is for watching a single candle form; high end (128x) replays a
# long backtest (a real run is ~hundreds of ticks/bar) in reasonable time.
_SPEED_STEPS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0)
_SPEED_DEFAULT_IDX = 2   # 1.0x

# 4-way intent marker specs (shape, color) — mirrors live_window.
_MARKER_SPECS = (
    ("open_long", "^", lw._OPEN_LONG_COLOR),
    ("close_long", "v", lw._CLOSE_LONG_COLOR),
    ("open_short", "v", lw._OPEN_SHORT_COLOR),
    ("close_short", "^", lw._CLOSE_SHORT_COLOR),
)
# pyqtgraph triangle symbols: 't1' points up (^), 't' points down (v).
_PG_SYMBOL = {"^": "t1", "v": "t"}


def show_streaming_replay(
    recorder: "EventRecorder",
    symbol: str = "",
    timeframe: str = "",
    block: bool = True,
    tick_interval_s: float = DEFAULT_TICK_INTERVAL_S,
) -> None:
    """Open the streaming replay window and play the recorded tick stream."""
    try:
        import finplot as fplt
        import pyqtgraph as pg
        from pyqtgraph.Qt import QtCore, QtWidgets
    except ImportError as e:
        raise RuntimeError(
            "Visualization extras not installed. "
            "Run: pip install -r requirements-viz.txt"
        ) from e

    if not recorder.bars:
        raise RuntimeError("No bars captured - cannot open streaming viewer.")
    if not recorder.ticks:
        raise RuntimeError(
            "No ticks captured - streaming needs the full tick record "
            "(StreamingChartHook records with max_ticks=None)."
        )

    full_bars = [bar for _, bar in recorder.bars]
    candle_index = pd.DatetimeIndex([b.timestamp for b in full_bars])
    n_index = len(candle_index)
    price_decimals = int(getattr(recorder, "price_decimals", 2) or 2)
    leverage = float(getattr(recorder, "leverage", 1.0) or 1.0)

    def _x_of(ts) -> int:
        """Category-index x for a timestamp = the containing bar's position."""
        pos = int(candle_index.searchsorted(pd.Timestamp(ts), side="left"))
        return max(0, min(pos, n_index - 1))

    replayer = TickReplayer(recorder.ticks, recorder.bars)
    clock = StreamClock(speed=_SPEED_STEPS[_SPEED_DEFAULT_IDX])

    # ── chart scaffold (price + indicator sub-panels) ──────────────────
    lw._apply_dark_theme(fplt)
    win_title = f"{symbol} {timeframe}".strip() or "tickweaver streaming"
    grouped = lw._group_indicators_by_panel(recorder)
    order = lw._panel_order(grouped)
    n_rows = len(order)

    if n_rows == 1:
        price_ax = fplt.create_plot(
            win_title, maximize=False, init_zoom_periods=VISIBLE_BARS
        )
        sub_axes: dict[str, Any] = {}
    else:
        axes = fplt.create_plot(
            win_title, rows=n_rows, maximize=False, init_zoom_periods=VISIBLE_BARS
        )
        if not isinstance(axes, (list, tuple)):
            axes = (axes,)
        price_ax = axes[0]
        sub_axes = {pid: axes[i] for i, pid in enumerate(order) if i > 0}

    # Full fixed X timeline: every bar slot exists up front (OHLC = NaN until
    # the replay reaches it). This keeps finplot's time axis stable and avoids
    # its tiny-datasrc tick-label bug on the first frames. It's also the
    # standard finplot realtime pattern: fixed timeline, fill data in place.
    import math

    _nan = math.nan
    col_o = [_nan] * n_index
    col_c = [_nan] * n_index
    col_h = [_nan] * n_index
    col_l = [_nan] * n_index
    _redraw_from = [0]   # first bar index whose OHLC may still change

    def _sync_cols() -> None:
        # Completed bars are frozen; only the current bar (and any just-finalized
        # ones) change — rewrite from the last completed boundary onward.
        for b in replayer.all_bars[_redraw_from[0]:]:
            i = b.bar_index
            col_o[i], col_c[i], col_h[i], col_l[i] = b.open, b.close, b.high, b.low
        _redraw_from[0] = len(replayer.completed_bars)

    def _full_df() -> pd.DataFrame:
        return pd.DataFrame(
            {"open": col_o, "close": col_c, "high": col_h, "low": col_l},
            index=candle_index,
        )

    # Seed with the first tick so there is a candle to grow.
    replayer.advance()
    _sync_cols()
    cs_item = fplt.candlestick_ochl(_full_df(), ax=price_ax)
    # We own the view while auto-following; finplot autorange must not fight us.
    price_ax.vb.disableAutoRange()
    price_ax.vb.setMouseEnabled(x=False, y=False)   # drag OFF by default

    # ── marker scatter items (one per intent, grown via setData) ───────
    marker_items: dict[str, Any] = {}
    for key, shape, color in _MARKER_SPECS:
        si = pg.ScatterPlotItem(
            symbol=_PG_SYMBOL[shape],
            size=lw._MARKER_SIZE,
            brush=pg.mkBrush(color),
            pen=pg.mkPen(lw._MARKER_OUTLINE, width=lw._MARKER_OUTLINE_WIDTH),
        )
        si.setZValue(50)
        price_ax.addItem(si)
        marker_items[key] = si

    # ── indicator line items + precomputed (ts, x, y) per track ────────
    # line_items[name] = (PlotDataItem, ts_sorted, xs, ys)
    line_items: dict[str, tuple] = {}
    for panel in order:
        ax = price_ax if panel == "price" else sub_axes.get(panel)
        if ax is None:
            continue
        for i, track in enumerate(grouped.get(panel, [])):
            name = track.registration.name
            color = lw._resolve_line_color(track, panel, i)
            style = track.registration.style or {}
            pen = pg.mkPen(color, width=style.get("width", 1))
            pdi = pg.PlotDataItem(pen=pen)
            ax.addItem(pdi)
            ts_sorted: list = []
            xs: list[int] = []
            ys: list[float] = []
            for s in track.samples:
                if s.timestamp is None:
                    continue
                ts = pd.Timestamp(s.timestamp)
                ts_sorted.append(ts)
                xs.append(_x_of(ts))
                ys.append(float(s.value))
            line_items[name] = (pdi, ts_sorted, xs, ys)

    # ── panel borders + titles (static decoration, same as live_window) ─
    lw._decorate_panel_border(price_ax)
    lw._add_corner_label(price_ax, symbol or "", anchor="topleft")
    for pid, ax in sub_axes.items():
        lw._decorate_panel_border(ax)
        lw._add_corner_label(ax, pid.upper(), anchor="topleft")

    # ── position table (empty; grows as fills reveal) ──────────────────
    from tickweaver.analytics.positions import build_position_history
    from tickweaver.viz.position_table import PositionTableWidget

    table_widget = PositionTableWidget(rows=[], price_decimals=price_decimals)

    # Precompute fill timestamps (ascending) for reveal bisect.
    fill_ts_sorted = [pd.Timestamp(f.timestamp) for f in recorder.fills]

    # ── reveal state ───────────────────────────────────────────────────
    _seen = {"fills": -1, "lines": {name: -1 for name in line_items}}

    def _update_markers(revealed_fills) -> None:
        groups = lw._classify_fills_by_intent(revealed_fills)
        for key, _shape, _color in _MARKER_SPECS:
            pts = groups.get(key, [])
            xs = [_x_of(ts) for ts, _ in pts]
            ys = [float(p) for _, p in pts]
            marker_items[key].setData(xs, ys)

    def _update_table(revealed_fills) -> None:
        try:
            rows = build_position_history(
                revealed_fills, leverage=leverage, bar_timestamps=candle_index
            )
            table_widget.set_rows(rows)
        except Exception as e:
            print(f"[viz] streaming table update skipped: {type(e).__name__}: {e}")

    def _reveal() -> None:
        now = replayer.current_tick_ts
        fc = revealed_count(fill_ts_sorted, now)
        if fc != _seen["fills"]:
            _seen["fills"] = fc
            revealed = recorder.fills[:fc]
            _update_markers(revealed)
            _update_table(revealed)
        for name, (pdi, ts_sorted, xs, ys) in line_items.items():
            sc = revealed_count(ts_sorted, now)
            if sc != _seen["lines"][name]:
                _seen["lines"][name] = sc
                pdi.setData(xs[:sc], ys[:sc])

    # Constant-width follow window: the X span never changes, so candles keep
    # the same size from the very first bars (no early over-zoom). A right
    # margin leaves a gap between the live (forming) bar and the chart edge.
    follow_window = min(VISIBLE_BARS, n_index)
    right_margin = max(3, round(follow_window * 0.04))

    def _follow_view() -> None:
        if not clock.auto_follow:
            return
        bars = replayer.all_bars
        n = len(bars)
        x1 = n + right_margin           # gap to the right of the live bar
        x0 = x1 - follow_window         # fixed width (no clamp) → constant size
        try:
            price_ax.vb.setXRange(x0, x1, padding=0)
        except Exception:
            pass
        vis = bars[max(0, n - follow_window):]
        rng = auto_y_range(
            [b.low for b in vis], [b.high for b in vis], drag_on=clock.drag_on
        )
        if rng is not None:
            fplt.set_y_range(rng[0], rng[1], ax=price_ax)

    # initial paint
    _reveal()
    _follow_view()

    # ── controls bar ───────────────────────────────────────────────────
    pause_btn = QtWidgets.QPushButton("⏸  Pause")
    speed_label = QtWidgets.QLabel(f"{clock.speed:g}x")
    speed_slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
    speed_slider.setMinimum(0)
    speed_slider.setMaximum(len(_SPEED_STEPS) - 1)
    speed_slider.setValue(_SPEED_DEFAULT_IDX)
    speed_slider.setFixedWidth(220)
    speed_slider.setToolTip("playback speed")
    drag_chk = QtWidgets.QCheckBox("Drag (pan/zoom)")

    def _on_pause() -> None:
        paused = clock.toggle_pause()
        pause_btn.setText("▶  Resume" if paused else "⏸  Pause")

    def _on_speed(idx: int) -> None:
        clock.set_speed(_SPEED_STEPS[idx])
        speed_label.setText(f"{clock.speed:g}x")

    def _on_drag(state: int) -> None:
        on = drag_chk.isChecked()
        clock.set_drag(on)
        try:
            price_ax.vb.setMouseEnabled(x=on, y=on)
        except Exception:
            pass
        if not on:
            _follow_view()   # snap back to following the current bar

    pause_btn.clicked.connect(_on_pause)
    speed_slider.valueChanged.connect(_on_speed)
    drag_chk.stateChanged.connect(_on_drag)

    controls = QtWidgets.QWidget()
    cl = QtWidgets.QHBoxLayout(controls)
    cl.setContentsMargins(8, 4, 8, 4)
    cl.addWidget(pause_btn)
    cl.addSpacing(16)
    cl.addWidget(QtWidgets.QLabel("Speed"))
    cl.addWidget(speed_slider)
    cl.addWidget(speed_label)
    cl.addSpacing(16)
    cl.addWidget(drag_chk)
    cl.addStretch(1)
    controls.setStyleSheet(
        f"background-color: {lw._DESC_BG}; color: {lw._FG}; "
        f"font-family: Consolas, monospace; font-size: 11px;"
    )

    # ── timer loop ─────────────────────────────────────────────────────
    _state = {"ended": False}

    def update() -> None:
        n = clock.ticks_this_frame()
        advanced = False
        for _ in range(n):
            if not replayer.advance():
                break
            advanced = True
        if advanced:
            _sync_cols()
            cs_item.update_data(_full_df())
            _reveal()
            _follow_view()
        if replayer.done and not _state["ended"]:
            _state["ended"] = True
            clock.pause()
            pause_btn.setText("✓  Replay ended")

    fplt.timer_callback(update, tick_interval_s)

    # ── window assembly (chart | controls | table) ─────────────────────
    wrapper, app = _wrap_streaming_window(
        fplt, QtWidgets, QtCore, controls, table_widget, win_title
    )
    if wrapper is not None and app is not None:
        wrapper.show()
        lw._bring_window_to_front(wrapper)
        if block:
            app.exec()
    else:
        fplt.show(qt_exec=block)


def _wrap_streaming_window(
    fplt, QtWidgets, QtCore, controls, table_widget, title: str
):
    """Reparent the finplot chart under a QMainWindow with a controls bar and
    the position table. Returns (wrapper, app) or (None, None) on failure."""
    try:
        fplt.refresh()
    except Exception as e:
        print(f"[viz] fplt.refresh() warning: {type(e).__name__}: {e}")

    wins = getattr(fplt, "windows", None)
    if not wins:
        print("[viz] streaming wrapper skipped: fplt.windows empty")
        return None, None
    chart_widget = wins[-1]
    if chart_widget is None:
        return None, None

    try:
        wrapper = QtWidgets.QMainWindow()
        wrapper.setWindowTitle(title)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, wrapper)
        splitter.addWidget(chart_widget)
        splitter.addWidget(controls)
        splitter.addWidget(table_widget)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 0)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([520, 40, 200])
        splitter.setHandleWidth(4)

        wrapper.setCentralWidget(splitter)
        wrapper.resize(1040, 720)

        # ESC closes the whole window (reuse live_window's app-level filter).
        try:
            app_for_filter = QtWidgets.QApplication.instance()
            if app_for_filter is not None:
                _filter = lw._EscCloseFilter(wrapper)
                wrapper._esc_filter = _filter  # type: ignore[attr-defined]
                app_for_filter.installEventFilter(_filter)
        except Exception as e:
            print(f"[viz] ESC filter wiring failed: {type(e).__name__}: {e}")

        try:
            wins.remove(chart_widget)
        except ValueError:
            pass

        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
        return wrapper, app
    except Exception as e:
        print(f"[viz] streaming wrapper failed: {type(e).__name__}: {e}")
        return None, None
