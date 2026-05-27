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
    fit_y_range,
    revealed_count,
)

if TYPE_CHECKING:
    from tickweaver.viz.recorder import EventRecorder

# Auto-follow X window width (bars). Bounds per-frame paint via finplot LOD.
VISIBLE_BARS = 150
# Timer cadence. One fire consumes StreamClock.ticks_this_frame() ticks.
DEFAULT_TICK_INTERVAL_S = 0.03

# Discrete speed steps for the slider = ticks consumed per frame. Low end
# (0.25x) is for watching a single candle form; high end (256x) replays a
# long backtest (a real run is ~hundreds of ticks/bar) quickly. Default is
# 128x so a full run plays at a brisk pace; drag the slider down to study a
# single candle forming.
_SPEED_STEPS = (0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 64.0, 128.0, 256.0)
_SPEED_DEFAULT_IDX = 9   # 128.0x

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
    # We own the price view while auto-following; finplot autorange must not
    # fight us. Sub-panels (rsi/macd/...) instead keep Y auto-fit to the
    # visible window so their indicator lines stay framed as the replay
    # scrolls (mirrors live_window's multi-panel handling).
    price_ax.vb.disableAutoRange()
    price_ax.vb.setMouseEnabled(x=False, y=False)   # drag OFF by default
    for _sub_ax in sub_axes.values():
        try:
            _sub_ax.vb.enableAutoRange(axis="y", enable=True)
            _sub_ax.vb.setAutoVisible(y=True)
        except Exception:
            pass

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

    # ── indicator lines (finplot-managed via fplt.plot) ────────────────
    # Raw pg.PlotDataItems don't render on a sub-panel that has no datasrc of
    # its own. fplt.plot creates the sub-panel datasrc, links its X to price,
    # and returns an item with update_data.
    #
    # Each line is built over the FULL candle timeline (one row per bar, NaN
    # where there is no sample / not yet revealed). This is load-bearing: a
    # line's datasrc length must always equal the candle datasrc length. If it
    # were shorter (e.g. indexed only by its own sample timestamps), every
    # indicator update_data would make finplot re-clamp the X range to that
    # shorter xlen and the next candle update_data would restore it — a periodic
    # left-right jitter, once per revealed sample. connect='finite' hides NaN.
    # line_items[name] = (item, samples, ts_sorted) with samples=[(x, ts, v)].
    line_items: dict[str, tuple] = {}
    for panel in order:
        ax = price_ax if panel == "price" else sub_axes.get(panel)
        if ax is None:
            continue
        for i, track in enumerate(grouped.get(panel, [])):
            name = track.registration.name
            color = lw._resolve_line_color(track, panel, i)
            style = track.registration.style or {}
            samples: list = []
            for s in track.samples:
                if s.timestamp is None:
                    continue
                ts = pd.Timestamp(s.timestamp)
                samples.append((_x_of(ts), ts, float(s.value)))
            if not samples:
                continue
            ts_sorted = [ts for _, ts, _ in samples]
            full_vals = [_nan] * n_index
            for xi, _, v in samples:
                full_vals[xi] = v
            kwargs: dict = {"color": color, "width": style.get("width", 1), "ax": ax}
            if style.get("style") is not None:
                kwargs["style"] = style["style"]
            series = pd.Series(full_vals, index=candle_index)
            try:
                item = fplt.plot(series, **kwargs)
            except TypeError:
                item = fplt.plot(series, color=color, ax=ax)
            line_items[name] = (item, samples, ts_sorted)

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

    # Pair (entry→exit) dotted lines — same as the static viewer. Each pair is
    # drawn at the moment its CLOSE arrow appears (its exit fill's timestamp is
    # reached), so the connecting line shows up together with the close marker
    # that explains it. FIFO-matched, one line per entry fill, coloured by the
    # entry side (long = blue, short = red).
    _pairs = lw._make_pair_lines(recorder.fills)
    _pairs.sort(key=lambda p: pd.Timestamp(p[2]))   # ascending by exit ts
    _pair_exit_ts = [pd.Timestamp(p[2]) for p in _pairs]
    _pairs_drawn = [0]

    # ── reveal state (lines created full above; first _reveal masks to 0) ──
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
        for name, (item, samples, ts_sorted) in line_items.items():
            sc = revealed_count(ts_sorted, now)
            if sc != _seen["lines"][name]:
                _seen["lines"][name] = sc
                # revealed samples sit at their bar position; the rest are NaN
                # (hidden) — full candle-length frame keeps the X range stable.
                masked = [_nan] * n_index
                for j in range(sc):
                    xi, _, v = samples[j]
                    masked[xi] = v
                try:
                    item.update_data(pd.Series(masked, index=candle_index))
                except Exception as e:
                    print(f"[viz] indicator update skipped ({name}): "
                          f"{type(e).__name__}: {e}")

        # pair lines: draw each entry→exit connector when its close is revealed
        pc = revealed_count(_pair_exit_ts, now)
        if pc != _pairs_drawn[0]:
            for k in range(_pairs_drawn[0], pc):
                p = _pairs[k]
                e_ts, e_p, x_ts, x_p = p[0], p[1], p[2], p[3]
                entry_side = p[4] if len(p) > 4 else "buy"
                color = lw._PAIR_LONG if entry_side == "buy" else lw._PAIR_SHORT
                lw._draw_pair_line(
                    fplt, price_ax,
                    _x_of(e_ts), float(e_p),
                    _x_of(x_ts), float(x_p),
                    color,
                )
            _pairs_drawn[0] = pc

    # Constant-width follow window: the X span never changes, so candles keep
    # the same size from the very first bars (no early over-zoom). A right
    # margin leaves a gap between the live (forming) bar and the chart edge.
    follow_window = min(VISIBLE_BARS, n_index)
    right_margin = max(8, round(follow_window * 0.10))

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

    def _fit_y_to_visible_x() -> None:
        """Drag ON: fit Y to the candles inside the *current* X view.

        finplot's FinViewBox manages Y via its own update_y_zoom (not pyqtgraph
        autorange), and keeps Y frozen while panning — so enabling autorange was
        ineffective. Instead we read the visible X range and set Y to fit the
        candles in it ourselves, on every X change (pan/zoom) and every frame.
        """
        if not clock.drag_on:
            return
        bars = replayer.all_bars
        if not bars:
            return
        try:
            vr = price_ax.vb.viewRect()
            lo_i = max(0, int(math.floor(vr.left())))
            hi_i = min(len(bars) - 1, int(math.ceil(vr.right())))
        except Exception:
            return
        if hi_i < lo_i:
            return
        vis = bars[lo_i:hi_i + 1]
        ymin, ymax = fit_y_range([b.low for b in vis], [b.high for b in vis])
        try:
            fplt.set_y_range(ymin, ymax, ax=price_ax)
        except Exception:
            pass

    # Re-fit Y whenever the user pans / wheel-zooms X (drag ON), even while
    # paused. _fit_y_to_visible_x is a no-op when drag is OFF.
    try:
        price_ax.vb.sigXRangeChanged.connect(lambda *_: _fit_y_to_visible_x())
    except Exception as e:
        print(f"[viz] X-range Y-follow wiring failed: {type(e).__name__}: {e}")

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
        vb = price_ax.vb
        try:
            # X is the user's to pan / wheel-zoom when ON; Y is always driven by
            # us (auto-follow when OFF, fit-to-visible-X when ON), so keep the
            # mouse off Y and finplot's own Y autorange off in both modes.
            vb.setMouseEnabled(x=on, y=False)
        except Exception:
            pass
        if on:
            _fit_y_to_visible_x()   # fit Y to whatever is on screen right now
        else:
            _follow_view()          # snap back to following the current bar

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
            _follow_view()          # drag OFF: follow X + fit Y
            _fit_y_to_visible_x()   # drag ON: keep Y fit as the live edge grows
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
