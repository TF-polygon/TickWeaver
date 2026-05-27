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
    build_balance_by_close,
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
_SPEED_STEPS = (1.0, 2.0, 8.0, 64.0, 128.0, 256.0)
_SPEED_DEFAULT_IDX = 4   # 128.0x

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

    table_widget = PositionTableWidget(
        rows=[], price_decimals=price_decimals, show_fees=False,
    )
    # Content-fit width as the splitter's initial size (not fixed — the user can
    # drag the table|curve handle). A minimum keeps it from collapsing away.
    _table_w = table_widget.fit_width_to_contents(fix=False)
    table_widget.setMinimumWidth(60)

    # ── balance curve (realized balance after each closed trade) ────────
    # X = close count (1 point per closed position, X=0 = start at
    # initial_cash); the curve fills the width left of the table. No Y-axis
    # labels — a hover tooltip reports the exact value / trade / date / PnL.
    initial_cash = float(getattr(recorder, "initial_cash", 0.0) or 0.0)
    curve_widget = pg.PlotWidget()
    curve_widget.setBackground(lw._BG)
    _cp = curve_widget.getPlotItem()
    _cp.setTitle("Balance / closed trades", color=lw._FG, size="9pt")
    _cp.showGrid(x=True, y=True, alpha=0.12)
    _cp.setMouseEnabled(x=False, y=False)
    _cp.hideButtons()
    _cp.hideAxis("left")                    # hide Y-axis unit labels
    _bx = _cp.getAxis("bottom")
    _bx.setPen(pg.mkPen(lw._BORDER))
    _bx.setTextPen(pg.mkPen(lw._FG))
    if initial_cash > 0:
        _cp.addItem(
            pg.InfiniteLine(
                pos=initial_cash, angle=0,
                pen=pg.mkPen("#5A6B85", style=QtCore.Qt.PenStyle.DashLine),
            )
        )
    # line only (straight segments between close points); X is the close index.
    balance_item = curve_widget.plot([0], [initial_cash], pen=pg.mkPen(lw._BULL, width=1.5))

    # hover tooltip: trade #, date, balance, PnL at the nearest close point.
    # A QLabel overlay (child of the plot widget), NOT a scene TextItem — a
    # TextItem is clipped to the viewbox, so near the top the box vanished.
    # The label is clamped inside the widget and raised, so it stays readable
    # regardless of cursor height.
    _curve = {"pts": [{"trade_no": 0, "timestamp": None, "pnl": None,
                       "balance": initial_cash}]}
    _curve_tip = QtWidgets.QLabel(curve_widget)
    _curve_tip.setStyleSheet(
        "QLabel { background-color: rgba(20,20,20,235); color: #FFFFFF; "
        "border: 1px solid #B4B4B4; padding: 4px 6px; "
        "font-family: Consolas, monospace; font-size: 11px; }"
    )
    _curve_tip.setVisible(False)

    def _on_curve_hover(scene_pos) -> None:
        try:
            if not _cp.sceneBoundingRect().contains(scene_pos):
                _curve_tip.setVisible(False)
                return
            xi = int(round(_cp.vb.mapSceneToView(scene_pos).x()))
            pts = _curve["pts"]
            if xi < 0 or xi >= len(pts):
                _curve_tip.setVisible(False)
                return
            d = pts[xi]
            if d["trade_no"] == 0:
                txt = f"start\nBalance {d['balance']:,.2f}"
            else:
                ts = pd.Timestamp(d["timestamp"]).strftime("%Y-%m-%d %H:%M")
                txt = (
                    f"Trade #{d['trade_no']}\n{ts}\n"
                    f"Balance {d['balance']:,.2f}\nPnL {d['pnl']:+,.2f}"
                )
            _curve_tip.setText(txt)
            _curve_tip.adjustSize()
            # place near the cursor, then clamp inside the widget so the whole
            # box stays visible (no clipping when the curve/cursor is high).
            vp = curve_widget.mapFromScene(scene_pos)
            x = int(vp.x()) + 12
            y = int(vp.y()) - _curve_tip.height() - 8
            x = max(0, min(x, curve_widget.width() - _curve_tip.width()))
            y = max(0, min(y, curve_widget.height() - _curve_tip.height()))
            _curve_tip.move(x, y)
            _curve_tip.setVisible(True)
            _curve_tip.raise_()
        except Exception:
            _curve_tip.setVisible(False)

    try:
        curve_widget.scene().sigMouseMoved.connect(_on_curve_hover)
    except Exception as e:
        print(f"[viz] balance hover wiring failed: {type(e).__name__}: {e}")

    # Hide the tooltip when the cursor leaves the curve widget — sigMouseMoved
    # stops firing on leave, so without this the box would freeze at its last
    # spot. An event filter on the viewport catches the Leave event.
    class _LeaveHider(QtCore.QObject):
        def eventFilter(self, _obj, ev):
            if ev.type() == QtCore.QEvent.Type.Leave:
                _curve_tip.setVisible(False)
            return False

    _leave_hider = _LeaveHider()
    curve_widget._leave_hider = _leave_hider   # keep a strong ref
    curve_widget.viewport().installEventFilter(_leave_hider)
    curve_widget.installEventFilter(_leave_hider)

    # White-bordered container so the curve reads as distinct from the window
    # and the table on its left (the right-edge inset is applied in the layout).
    curve_box = QtWidgets.QFrame()
    curve_box.setObjectName("curveBox")
    curve_box.setStyleSheet(
        "QFrame#curveBox { border: 1px solid #FFFFFF; background-color: %s; }"
        % lw._BG
    )
    _cbl = QtWidgets.QVBoxLayout(curve_box)
    _cbl.setContentsMargins(1, 1, 1, 1)
    _cbl.addWidget(curve_widget)

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
    _pair_items: list = []   # drawn line items, tracked so Replay can clear them

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

    def _update_balance(revealed_fills) -> None:
        # one point per closed trade; X = close index (0 = start at initial).
        try:
            pts = build_balance_by_close(
                revealed_fills, initial_cash, leverage=leverage,
                bar_timestamps=candle_index,
            )
            _curve["pts"] = pts
            balance_item.setData(
                list(range(len(pts))), [p["balance"] for p in pts]
            )
        except Exception as e:
            print(f"[viz] balance curve update skipped: {type(e).__name__}: {e}")

    def _reveal() -> None:
        now = replayer.current_tick_ts
        fc = revealed_count(fill_ts_sorted, now)
        if fc != _seen["fills"]:
            _seen["fills"] = fc
            revealed = recorder.fills[:fc]
            _update_markers(revealed)
            _update_table(revealed)
            _update_balance(revealed)
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
                _line = lw._draw_pair_line(
                    fplt, price_ax,
                    _x_of(e_ts), float(e_p),
                    _x_of(x_ts), float(x_p),
                    color,
                )
                if _line is not None:
                    _pair_items.append(_line)
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

    def _reset_replay() -> None:
        """Replay from the start: rewind the data and clear every drawn layer."""
        replayer.reset()
        for arr in (col_o, col_c, col_h, col_l):
            arr[:] = [_nan] * n_index
        _redraw_from[0] = 0
        for it in _pair_items:
            try:
                price_ax.removeItem(it)
            except Exception:
                pass
        _pair_items.clear()
        _pairs_drawn[0] = 0
        _seen["fills"] = -1
        for k in _seen["lines"]:
            _seen["lines"][k] = -1
        _state["ended"] = False
        replayer.advance()                 # re-seed the first bar
        _sync_cols()
        cs_item.update_data(_full_df())
        clock.resume()
        _reveal()                          # clears markers / table / curve to start
        _follow_view()
        _fit_y_to_visible_x()

    def _on_action() -> None:
        # When the replay has ended the button is a Replay (restart); otherwise
        # it toggles Pause/Resume.
        if _state["ended"]:
            _reset_replay()
            pause_btn.setText("⏸  Pause")
            return
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

    pause_btn.clicked.connect(_on_action)
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
            pause_btn.setText("↻  Replay")   # click to replay from the start

    fplt.timer_callback(update, tick_interval_s)

    # ── window assembly (chart | controls | [table | balance curve]) ───
    wrapper, app = _wrap_streaming_window(
        fplt, QtWidgets, QtCore, controls, table_widget, curve_box,
        _table_w, win_title,
    )
    if wrapper is not None and app is not None:
        wrapper.show()
        lw._bring_window_to_front(wrapper)
        if block:
            app.exec()
    else:
        fplt.show(qt_exec=block)


def _wrap_streaming_window(
    fplt, QtWidgets, QtCore, controls, table_widget, curve_box, table_w, title: str
):
    """Reparent the finplot chart under a QMainWindow.

    Layout: a single vertical splitter handle separates the chart from a lower
    pane that stacks the fixed-height controls bar over a horizontal splitter
    [position table | balance curve]. The vertical handle resizes chart vs
    table+curve (controls stay put); the horizontal handle lets the user set
    the table/curve width split. Returns (wrapper, app) or (None, None)."""
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

        # bottom pane: position table | balance curve in a HORIZONTAL splitter
        # so the user can drag the width split. Table starts at its content
        # width; curve takes the rest and gets extra on window resize. Wrapped
        # in a container whose right margin insets the curve from the edge.
        bottom_split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal)
        bottom_split.addWidget(table_widget)
        bottom_split.addWidget(curve_box)
        bottom_split.setStretchFactor(0, 0)   # table keeps its width
        bottom_split.setStretchFactor(1, 1)   # curve absorbs extra space
        bottom_split.setHandleWidth(6)
        curve_box.setMinimumWidth(120)
        try:
            total = max(int(table_w) + 400, int(table_w) + 120)
            bottom_split.setSizes([int(table_w), total - int(table_w)])
        except Exception:
            pass

        bottom = QtWidgets.QWidget()
        bl = QtWidgets.QHBoxLayout(bottom)
        bl.setContentsMargins(0, 2, 8, 4)
        bl.setSpacing(0)
        bl.addWidget(bottom_split)

        # Group the controls bar + bottom into one lower pane so the splitter
        # has a SINGLE handle (chart vs lower). The controls bar keeps a fixed
        # height; dragging the handle resizes only the chart and the
        # table+curve, never the Pause/Speed/Drag row in between.
        controls.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Fixed,
        )
        lower = QtWidgets.QWidget()
        lower_l = QtWidgets.QVBoxLayout(lower)
        lower_l.setContentsMargins(0, 0, 0, 0)
        lower_l.setSpacing(0)
        lower_l.addWidget(controls, stretch=0)
        lower_l.addWidget(bottom, stretch=1)

        splitter = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical, wrapper)
        splitter.addWidget(chart_widget)
        splitter.addWidget(lower)
        splitter.setStretchFactor(0, 6)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([500, 260])
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
