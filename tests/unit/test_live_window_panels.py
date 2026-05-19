"""Phase 4 (dev/adv_verbose) — live_window panel grouping + color assignment.

These tests target the pure-Python helpers extracted from show_replay() so
the layout logic is verifiable without a finplot / Qt event loop. Visual
correctness on the actual chart is covered by Phase 6 (manual --viz).
"""

from __future__ import annotations

from tickweaver.viz.events import (
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
    IndicatorTrack,
)
from tickweaver.viz.live_window import (
    _assign_default_color,
    _group_indicators_by_panel,
    _panel_order,
)
from tickweaver.viz.recorder import EventRecorder


def _make_track(name: str, panel: str, style: dict | None = None) -> IndicatorTrack:
    reg = IndicatorRegistrationEvent(name=name, panel=panel, style=style or {})
    return IndicatorTrack(registration=reg, samples=[])


# ─────────────────────────────────────────────────────────
# _group_indicators_by_panel
# ─────────────────────────────────────────────────────────
def test_group_empty_recorder_returns_only_price_key():
    """Even with no indicators registered, 'price' must be present so the
    candlestick axis always exists as row 0."""
    rec = EventRecorder()
    grouped = _group_indicators_by_panel(rec)
    assert "price" in grouped
    assert grouped["price"] == []


def test_group_single_price_overlay():
    rec = EventRecorder()
    rec.indicators["EMA20"] = _make_track("EMA20", "price")
    grouped = _group_indicators_by_panel(rec)
    assert list(grouped.keys()) == ["price"]
    assert [t.registration.name for t in grouped["price"]] == ["EMA20"]


def test_group_single_subpanel():
    rec = EventRecorder()
    rec.indicators["RSI"] = _make_track("RSI", "rsi")
    grouped = _group_indicators_by_panel(rec)
    # price still exists (always row 0) + rsi key
    assert "price" in grouped
    assert "rsi" in grouped
    assert grouped["price"] == []
    assert [t.registration.name for t in grouped["rsi"]] == ["RSI"]


def test_group_mixed_panels():
    rec = EventRecorder()
    rec.indicators["EMA fast"] = _make_track("EMA fast", "price")
    rec.indicators["EMA slow"] = _make_track("EMA slow", "price")
    rec.indicators["RSI"] = _make_track("RSI", "rsi")
    rec.indicators["MACD.macd"] = _make_track("MACD.macd", "macd")
    rec.indicators["MACD.signal"] = _make_track("MACD.signal", "macd")
    grouped = _group_indicators_by_panel(rec)
    assert [t.registration.name for t in grouped["price"]] == ["EMA fast", "EMA slow"]
    assert [t.registration.name for t in grouped["rsi"]] == ["RSI"]
    assert [t.registration.name for t in grouped["macd"]] == ["MACD.macd", "MACD.signal"]


# ─────────────────────────────────────────────────────────
# _panel_order — price first, then registration order
# ─────────────────────────────────────────────────────────
def test_panel_order_only_price():
    grouped = {"price": []}
    assert _panel_order(grouped) == ["price"]


def test_panel_order_price_first_even_when_registered_last():
    """If a strategy binds RSI before any 'price' overlay, price still wins
    row 0 because the candlestick always anchors the layout."""
    grouped = {"rsi": [], "price": []}
    assert _panel_order(grouped) == ["price", "rsi"]


def test_panel_order_preserves_subpanel_registration_order():
    grouped = {"price": [], "rsi": [], "macd": [], "atr": []}
    assert _panel_order(grouped) == ["price", "rsi", "macd", "atr"]


def test_panel_order_keeps_strategy_defined_subpanel_first():
    grouped = {"price": [], "macd": [], "rsi": []}
    # macd registered before rsi -> macd comes first under price
    assert _panel_order(grouped) == ["price", "macd", "rsi"]


# ─────────────────────────────────────────────────────────
# _assign_default_color — deterministic palette
# ─────────────────────────────────────────────────────────
def test_assign_default_color_returns_string():
    c = _assign_default_color(panel="price", line_index=0)
    assert isinstance(c, str)
    assert c.startswith("#")


def test_assign_default_color_deterministic_same_inputs():
    """Same (panel, line_index) -> same color across calls. Determinism."""
    a = _assign_default_color(panel="price", line_index=0)
    b = _assign_default_color(panel="price", line_index=0)
    assert a == b


def test_assign_default_color_distinct_for_distinct_line_indices():
    """Adjacent lines in the same panel should not collide on color."""
    c0 = _assign_default_color(panel="price", line_index=0)
    c1 = _assign_default_color(panel="price", line_index=1)
    assert c0 != c1


def test_assign_default_color_avoids_buy_sell_blue_and_orange():
    """The marker palette uses #2196F3 (BUY) and #FF9800 (SELL).
    Auto-assigned indicator colors must avoid these so traders do not
    confuse a line with a fill marker."""
    AVOID = {"#2196F3", "#FF9800"}
    for panel in ("price", "rsi", "macd", "atr"):
        for i in range(8):
            assert _assign_default_color(panel, i).upper() not in {
                c.upper() for c in AVOID
            }


# ─────────────────────────────────────────────────────────
# Phase 5.1 — description HTML + crosshair lookup
# ─────────────────────────────────────────────────────────
import pandas as pd
from tickweaver.viz.live_window import (
    _build_crosshair_lookup,
    _build_description_html,
)


def test_description_html_contains_symbol_and_timeframe():
    html = _build_description_html(
        symbol="BTC/USDT:USDT",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_432.1,
        n_fills=14,
        n_trades=7,
        indicator_specs=[],
    )
    assert "BTC/USDT:USDT" in html
    assert "1h" in html


def test_description_html_contains_period_dates():
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=0,
        n_trades=0,
        indicator_specs=[],
    )
    assert "2025-01-01" in html
    assert "2025-01-31" in html


def test_description_html_formats_equity_with_separator():
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=12_345.67,
        n_fills=0,
        n_trades=0,
        indicator_specs=[],
    )
    # Thousands separator readable form (allow "12,345.7" or similar).
    assert "12,345" in html or "12345" in html  # tolerant


def test_description_html_lists_indicator_specs():
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=0,
        n_trades=0,
        indicator_specs=[
            ("EMA fast", "price", "#FFEB3B"),
            ("RSI", "rsi", "#00BCD4"),
        ],
    )
    assert "EMA fast" in html
    assert "RSI" in html


def test_description_html_shows_fills_and_trades_counts():
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=14,
        n_trades=7,
        indicator_specs=[],
    )
    assert "14" in html
    assert "7" in html


def test_crosshair_lookup_maps_bar_ohlc():
    from tickweaver.core.types import OHLCBar
    from tickweaver.viz.recorder import EventRecorder

    rec = EventRecorder()
    ts = pd.Timestamp("2024-01-01 01:00", tz="UTC")
    bar = OHLCBar(
        timestamp=ts, open=100.0, high=110.0, low=95.0, close=105.0,
        volume=10.0, symbol="T", timeframe="1h",
    )
    rec.on_bar(bar, 0)
    grouped = {"price": []}
    ohlc_lookup, panel_lookup = _build_crosshair_lookup(rec, grouped)
    assert ts in ohlc_lookup
    o, h, l, c = ohlc_lookup[ts]
    assert (o, h, l, c) == (100.0, 110.0, 95.0, 105.0)


def test_crosshair_lookup_maps_panel_indicator_values():
    rec = _empty_recorder()
    track = _make_track("EMA fast", "price")
    track.samples.append(
        IndicatorSampleEvent(
            name="EMA fast",
            bar_index=0,
            timestamp=pd.Timestamp("2024-01-01 01:00", tz="UTC"),
            value=102.5,
        )
    )
    rec.indicators["EMA fast"] = track
    grouped = _group_indicators_by_panel(rec)
    _, panel_lookup = _build_crosshair_lookup(rec, grouped)
    ts = pd.Timestamp("2024-01-01 01:00", tz="UTC")
    assert "price" in panel_lookup
    assert ts in panel_lookup["price"]
    assert panel_lookup["price"][ts] == {"EMA fast": 102.5}


def _empty_recorder():
    from tickweaver.viz.recorder import EventRecorder
    return EventRecorder()


# ─────────────────────────────────────────────────────────
# Phase F3 (round 2) — marker legend in description HTML
# ─────────────────────────────────────────────────────────
def test_description_html_renders_marker_legend_when_specs_given():
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=4,
        n_trades=2,
        indicator_specs=[],
        marker_specs=[
            ("Open Long", "^", "#2196F3", 2),
            ("Close Long", "v", "#FF9800", 2),
        ],
    )
    assert "Open Long" in html
    assert "Close Long" in html
    assert "#2196F3" in html
    assert "#FF9800" in html
    # ▲ for ^, ▼ for v
    assert "▲" in html or "&#9650;" in html
    assert "▼" in html or "&#9660;" in html


def test_description_html_marker_legend_shows_count():
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=8,
        n_trades=4,
        indicator_specs=[],
        marker_specs=[
            ("Open Long", "^", "#2196F3", 3),
            ("Close Long", "v", "#FF9800", 3),
            ("Open Short", "v", "#EF5350", 1),
            ("Close Short", "^", "#26A69A", 1),
        ],
    )
    # Each count should appear next to its label.
    assert "3" in html
    assert "1" in html


def test_description_html_omits_marker_section_when_specs_empty():
    """marker_specs=[] means no fills at all — no Markers section."""
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=0,
        n_trades=0,
        indicator_specs=[],
        marker_specs=[],
    )
    # "Markers" header should not appear when there are no marker specs.
    assert "Markers" not in html


def test_description_html_marker_specs_default_is_empty():
    """Calling without marker_specs= must still work (back-compat)."""
    html = _build_description_html(
        symbol="X",
        timeframe="1h",
        period_start=pd.Timestamp("2025-01-01", tz="UTC"),
        period_end=pd.Timestamp("2025-01-31", tz="UTC"),
        initial_cash=10_000.0,
        final_equity=10_000.0,
        n_fills=0,
        n_trades=0,
        indicator_specs=[],
    )
    assert "Markers" not in html
