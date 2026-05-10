"""UniformTickGenerator 의 통합 property test (C1~C7).

constraints + timestamps + validator 가 끝단에서 합쳐진 동작을 검증.
hypothesis 600+ 케이스로 fuzz.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tickweaver.core.exceptions import TickContractError
from tickweaver.core.types import OHLCBar
from tickweaver.tick_synthesis.generator import get_tick_generator
from tickweaver.tick_synthesis.validator import validate_ticks


_TIMEFRAMES = ["1m", "15m", "1h", "4h", "1d"]


@st.composite
def bars(draw, *, allow_zero_range: bool = True):
    """Valid OHLCBar 임의 생성."""
    low = draw(
        st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False)
    )
    if allow_zero_range:
        high = draw(
            st.floats(min_value=low, max_value=1e6, allow_nan=False, allow_infinity=False)
        )
    else:
        high = draw(
            st.floats(min_value=low * 1.0001, max_value=1e6, allow_nan=False, allow_infinity=False)
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
# C1~C6 — 250 examples
# ─────────────────────────────────────────────────────────
@given(
    bar=bars(),
    n=st.integers(min_value=4, max_value=256),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=250, suppress_health_check=[HealthCheck.too_slow])
def test_uniform_C1_to_C6(bar, n, seed):
    gen = get_tick_generator("uniform")
    rng = np.random.default_rng(seed)
    ticks = gen.generate(bar, n_ticks=n, rng=rng)
    validate_ticks(bar, ticks, n_min=4, n_max=512)


# ─────────────────────────────────────────────────────────
# C7 — 200 examples
# ─────────────────────────────────────────────────────────
@given(
    bar=bars(),
    n=st.integers(min_value=4, max_value=256),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_uniform_determinism(bar, n, seed):
    gen = get_tick_generator("uniform")
    a = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    b = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    assert [t.price for t in a] == [t.price for t in b]
    assert [t.timestamp for t in a] == [t.timestamp for t in b]


# ─────────────────────────────────────────────────────────
# Timestamps — 100 examples
# ─────────────────────────────────────────────────────────
@given(
    bar=bars(),
    n=st.integers(min_value=4, max_value=128),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100)
def test_uniform_timestamps_within_bar(bar, n, seed):
    gen = get_tick_generator("uniform")
    ticks = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    bar_open = bar.timestamp - pd.Timedelta(
        milliseconds={
            "1m": 60_000,
            "15m": 15 * 60_000,
            "1h": 3_600_000,
            "4h": 4 * 3_600_000,
            "1d": 86_400_000,
        }[bar.timeframe]
    )
    assert ticks[0].timestamp == bar_open
    assert ticks[-1].timestamp == bar.timestamp
    for a, b in zip(ticks, ticks[1:]):
        assert a.timestamp <= b.timestamp


# ─────────────────────────────────────────────────────────
# Symbol propagation
# ─────────────────────────────────────────────────────────
@given(
    bar=bars(),
    n=st.integers(min_value=4, max_value=64),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=50)
def test_uniform_propagates_symbol(bar, n, seed):
    gen = get_tick_generator("uniform")
    ticks = gen.generate(bar, n_ticks=n, rng=np.random.default_rng(seed))
    for t in ticks:
        assert t.symbol == bar.symbol


# ─────────────────────────────────────────────────────────
# 등록 / 조회
# ─────────────────────────────────────────────────────────
def test_registry_contains_uniform():
    from tickweaver.tick_synthesis.generator import list_tick_generators

    assert "uniform" in list_tick_generators()


def test_unknown_generator_raises():
    from tickweaver.tick_synthesis.generator import get_tick_generator

    with pytest.raises(KeyError):
        get_tick_generator("does_not_exist")
