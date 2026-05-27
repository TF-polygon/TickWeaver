"""streaming-viz unit #3 — auto Y-rescale (pure, headless).

Covers goal §3.A "자동 리스케일": the visible Y window always contains every
visible candle (tall "장봉" included) with padding, when drag is OFF; when
drag is ON the user keeps Y control (no auto change).
"""

from __future__ import annotations

from tickweaver.viz.streaming import auto_y_range, fit_y_range


def _contains(rng, lo, hi) -> bool:
    ymin, ymax = rng
    return ymin <= lo and hi <= ymax


# ── fit_y_range ────────────────────────────────────────────────────────────
def test_fit_contains_all_visible_with_padding():
    lows = [98.0, 99.0, 97.0, 100.0]
    highs = [102.0, 103.0, 101.0, 104.0]
    ymin, ymax = fit_y_range(lows, highs)
    assert ymin < min(lows)        # padded strictly below
    assert ymax > max(highs)       # padded strictly above
    for lo, hi in zip(lows, highs):
        assert _contains((ymin, ymax), lo, hi)


def test_fit_tall_bar_is_fully_contained():
    # one 장봉 dwarfs the rest; it must still fit inside the range
    lows = [99.0, 100.0, 60.0, 101.0]    # bar[2] = tall
    highs = [101.0, 102.0, 145.0, 103.0]
    rng = fit_y_range(lows, highs)
    assert _contains(rng, 60.0, 145.0)   # tall bar contained
    assert rng[0] < 60.0 and rng[1] > 145.0


def test_fit_boundary_tie_contained():
    # a bar whose high ties the current max and low ties the current min
    lows = [90.0, 95.0, 90.0]
    highs = [110.0, 105.0, 110.0]
    rng = fit_y_range(lows, highs)
    assert _contains(rng, 90.0, 110.0)
    assert rng[0] < 90.0 and rng[1] > 110.0


def test_fit_zero_span_is_non_degenerate():
    # all candles flat at one price (e.g. a single-tick opening frame)
    rng = fit_y_range([100.0, 100.0], [100.0, 100.0])
    ymin, ymax = rng
    assert ymin < 100.0 < ymax       # not a zero-height window


def test_fit_padding_scales_with_span():
    narrow = fit_y_range([100.0], [102.0], pad_frac=0.10)   # span 2
    wide = fit_y_range([100.0], [120.0], pad_frac=0.10)     # span 20
    narrow_pad = (102.0 - narrow[1])   # negative magnitude check via below
    # padding above = ymax - hi
    assert abs((narrow[1] - 102.0) - 0.2) < 1e-9
    assert abs((wide[1] - 120.0) - 2.0) < 1e-9


# ── auto_y_range (drag gate) ────────────────────────────────────────────────
def test_auto_drag_off_returns_fit():
    lows = [98.0, 60.0]
    highs = [102.0, 145.0]
    rng = auto_y_range(lows, highs, drag_on=False)
    assert rng is not None
    assert _contains(rng, 60.0, 145.0)


def test_auto_drag_on_returns_none():
    # drag ON → user controls Y; auto-rescale must not override
    rng = auto_y_range([98.0], [102.0], drag_on=True)
    assert rng is None


def test_auto_empty_returns_none():
    assert auto_y_range([], [], drag_on=False) is None
