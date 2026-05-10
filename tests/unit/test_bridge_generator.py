"""BrownianBridgeTickGenerator (M4) — same C1~C7 contract as uniform.

Reuses the bars() strategy idea from test_uniform_generator.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tickweaver.core.exceptions import TickContractError
from tickweaver.core.types import OHLCBar
from tickweaver.tick_synthesis.generator import get_tick_generator, list_tick_generators
from tickweaver.tick_synthesis.validator import validate_ticks


_TIMEFRAMES = ["1m", "15m", "1h", "4h", "1d"]


@st.composite
def bars(draw):
    low = draw(
        st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False)
    )
    high = draw(
        st.floats(min_value=low, max_value=1e6, allow_nan=False, allow_infinity=False)
    )
    o = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    c = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    tf = draw(st.sampled_from(_TIMEFRAMES))
    epoch_hours = draw(st.integers(min_value=0, max_value=24 * 365 * 10))
    ts = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=epoch_hours)
    return OHLCBar(
        timestamp=ts,
        open=o,
        high=high,
        low=low,
        close=c,
        volume=10.0,
        symbol="TEST",
        timeframe=tf,
    )


# ─────────────────────────────────────────────────────────
# 등록 / 조회
# ─────────────────────────────────────────────────────────
def test_bridge_registered():
    assert "bridge" in list_tick_generators()


def test_bridge_distinct_from_uniform():
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=100.0, high=110.0, low=90.0, close=105.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    u = get_tick_generator("uniform").generate(bar, 32, np.random.default_rng(0))
    b = get_tick_generator("bridge").generate(bar, 32, np.random.default_rng(0))
    # endpoints same (C1, C2) but interior path differs
    assert u[0].price == b[0].price == bar.open
    assert u[-1].price == b[-1].price == bar.close
    u_mid = [t.price for t in u[1:-1]]
    b_mid = [t.price for t in b[1:-1]]
    assert u_mid != b_mid


# ─────────────────────────────────────────────────────────
# C1~C6 — 250 examples
# ─────────────────────────────────────────────────────────
@given(
    bar=bars(),
    n=st.integers(min_value=4, max_value=256),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=250, suppress_health_check=[HealthCheck.too_slow])
def test_bridge_C1_to_C6(bar, n, seed):
    gen = get_tick_generator("bridge")
    ticks = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    validate_ticks(bar, ticks, n_min=4, n_max=512)


# ─────────────────────────────────────────────────────────
# C7 — determinism, 200 examples
# ─────────────────────────────────────────────────────────
@given(
    bar=bars(),
    n=st.integers(min_value=4, max_value=256),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_bridge_determinism(bar, n, seed):
    gen = get_tick_generator("bridge")
    a = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    b = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    assert [t.price for t in a] == [t.price for t in b]
    assert [t.timestamp for t in a] == [t.timestamp for t in b]


# ─────────────────────────────────────────────────────────
# Zero-range bars (H == L)
# ─────────────────────────────────────────────────────────
def test_bridge_zero_range():
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=100.0, high=100.0, low=100.0, close=100.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    ticks = get_tick_generator("bridge").generate(bar, 16, np.random.default_rng(0))
    for t in ticks:
        assert t.price == 100.0


# ─────────────────────────────────────────────────────────
# Edge: bar where O == L (touches low at open)
# ─────────────────────────────────────────────────────────
def test_bridge_open_at_low():
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=90.0, high=110.0, low=90.0, close=100.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    ticks = get_tick_generator("bridge").generate(bar, 16, np.random.default_rng(7))
    validate_ticks(bar, ticks, n_min=4, n_max=512)


def test_bridge_close_at_high():
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=100.0, high=110.0, low=90.0, close=110.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    ticks = get_tick_generator("bridge").generate(bar, 16, np.random.default_rng(7))
    validate_ticks(bar, ticks, n_min=4, n_max=512)


# ─────────────────────────────────────────────────────────
# Validation of bad inputs
# ─────────────────────────────────────────────────────────
def test_bridge_rejects_n_below_4():
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=100.0, high=110.0, low=90.0, close=105.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    with pytest.raises(ValueError):
        get_tick_generator("bridge").generate(bar, 3, np.random.default_rng(0))


def test_bridge_rejects_invalid_sigma_factor():
    from tickweaver.tick_synthesis.strategies.bridge import (
        BrownianBridgeTickGenerator,
    )

    with pytest.raises(ValueError):
        BrownianBridgeTickGenerator(sigma_factor=0.0)
    with pytest.raises(ValueError):
        BrownianBridgeTickGenerator(sigma_factor=-1.0)
