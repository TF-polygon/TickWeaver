"""finplot-based replay viewer (Phase 4 + 5, dark theme, spot trading).

Two modes:
    show_replay()    - all data shown at once (post-hoc, default)
    show_streaming() - all data plotted but viewport moves one bar per tick

Trading model: SPOT only. Buy / Sell are the only sides we render.
Future trading mode (long/short open/close) is a future extension.
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
    """Return (buy_series, sell_series) of (ts, price) lists."""
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


def _plot_full(fplt, ax, df: pd.DataFrame, recorder: "EventRecorder") -> None:
    """Render the candlestick + markers + pair lines + comment.

    Used by both show_replay and show_streaming. The streaming mode then
    only animates the viewport on top of this fully-drawn chart.
    """
    fplt.candlestick_ochl(df[["open", "close", "high", "low"]], ax=ax)

    # Pair lines (round-trip Buy -> Sell)
    for t in _trades(recorder):
        _draw_pair_line(
            fplt, ax,
            pd.Timestamp(t.entry_ts), float(t.entry_price),
            pd.Timestamp(t.exit_ts), float(t.exit_price),
            _PAIR,
        )

    # Buy / Sell markers
    bx, by, sx, sy = _split_buy_sell(recorder)
    if bx:
        s = pd.Series(by, index=pd.DatetimeIndex(bx))
        fplt.plot(s, style=">", color=_BUY, width=2, ax=ax, legend="Buy")
    if sx:
        s = pd.Series(sy, index=pd.DatetimeIndex(sx))
        fplt.plot(s, style="<", color=_SELL, width=2, ax=ax, legend="Sell")

    # Comment label
    if recorder.comments:
        last_text = recorder.comments[-1].text
        try:
            fplt.add_legend(last_text, ax=ax)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Mode 1: post-hoc replay (all at once)
# ---------------------------------------------------------------------------
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

    _apply_dark_theme(fplt)
    title = f"{symbol} {timeframe}".strip() or "tickweaver replay"
    ax = fplt.create_plot(title, maximize=False, init_zoom_periods=200)
    _plot_full(fplt, ax, df, recorder)
    fplt.show(qt_exec=block)


# ---------------------------------------------------------------------------
# Mode 2: streaming (viewport shifts one bar per tick)
# ---------------------------------------------------------------------------
def show_streaming(
    recorder: "EventRecorder",
    symbol: str = "",
    timeframe: str = "",
    interval_ms: int = 100,
    bars_per_view: int = 80,
    block: bool = True,
) -> None:
    """Same chart as show_replay but viewport advances one bar every interval.

    Args:
        recorder: EventRecorder.
        symbol / timeframe: window title hints.
        interval_ms: milliseconds between viewport advances. 100ms = 10 bars/sec.
        bars_per_view: how many bars are visible in the viewport at once.
        block: if True, wait until the user closes the window.

    Implementation:
        - All data is plotted up front (deterministic, simple, thread-safe).
        - A QTimer advances the viewport one bar at a time so the user sees
          bars 'arriving' at the right edge.
        - Mouse drag still works (default finplot pan/zoom is preserved).
    """
    try:
        import finplot as fplt
    except ImportError as e:
        raise RuntimeError(
            "finplot is not installed. Run: pip install -r requirements-viz.txt"
        ) from e

    df = _build_ohlc_df(recorder)
    if df.empty:
        raise RuntimeError("No bars captured - cannot open streaming viewer.")

    _apply_dark_theme(fplt)
    title_suffix = " (streaming)" if bars_per_view < len(df) else ""
    title = (f"{symbol} {timeframe}".strip() or "tickweaver streaming") + title_suffix
    ax = fplt.create_plot(title, maximize=False, init_zoom_periods=bars_per_view)
    _plot_full(fplt, ax, df, recorder)

    n = len(df)
    state = {"i": min(bars_per_view, n), "stopped": False}

    def _set_viewport(end_idx: int) -> None:
        """Set X range to [end_idx - bars_per_view, end_idx]."""
        if end_idx <= 0:
            return
        start_idx = max(0, end_idx - bars_per_view)
        x_start = pd.Timestamp(df.index[start_idx]).value / 1e9
        x_end_ts = df.index[min(end_idx, n - 1)]
        x_end = pd.Timestamp(x_end_ts).value / 1e9
        # Try the various viewport APIs finplot exposes
        try:
            ax.set_visible_range(x_start, x_end)  # newer finplot
            return
        except (AttributeError, TypeError):
            pass
        try:
            ax.vb.setXRange(x_start, x_end, padding=0)  # pyqtgraph viewbox
            return
        except Exception:
            pass

    # Initial viewport
    _set_viewport(state["i"])

    def _step():
        if state["stopped"]:
            return
        if state["i"] >= n:
            state["stopped"] = True
            return
        state["i"] += 1
        _set_viewport(state["i"])

    try:
        fplt.timer_callback(_step, interval_ms / 1000.0)
    except Exception:
        # If finplot lacks timer_callback, fall back to a static replay.
        pass

    fplt.show(qt_exec=block)
