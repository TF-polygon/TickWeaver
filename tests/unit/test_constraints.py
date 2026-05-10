"""tick_synthesis.constraints — synthesize_prices_uniform / clamp_n_ticks 단위 테스트.

property-based 로 OHLC 가격 + n + seed 의 임의 조합에 대해 보장을 확인.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tickweaver.tick_synthesis.constraints import (
    clamp_n_ticks,
    synthesize_prices_uniform,
)


# ─────────────────────────────────────────────────────────
# OHLC strategy — valid OHLC bars
# ─────────────────────────────────────────────────────────
@st.composite
def ohlc_floats(draw):
    """Valid (O, H, L, C): L <= O, C <= H, all positive."""
    low = draw(
        st.floats(min_value=1.0, max_value=1e6, allow_nan=False, allow_infinity=False)
    )
    high = draw(
        st.floats(min_value=low, max_value=1e6, allow_nan=False, allow_infinity=False)
    )
    o = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    c = draw(st.floats(min_value=low, max_value=high, allow_nan=False))
    return (o, high, low, c)


# ─────────────────────────────────────────────────────────
# clamp_n_ticks
# ─────────────────────────────────────────────────────────
@given(
    n_target=st.integers(min_value=-10, max_value=10000),
    n_min=st.integers(min_value=4, max_value=64),
    n_max=st.integers(min_value=64, max_value=512),
)
@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
def test_clamp_n_ticks_in_range(n_target, n_min, n_max):
    n = clamp_n_ticks(n_target, n_min, n_max)
    assert n >= 4
    assert n_min <= n <= n_max or n == max(n_min, 4)


def test_clamp_floor_at_4():
    assert clamp_n_ticks(2, 1, 100) == 4
    assert clamp_n_ticks(-100, 1, 100) == 4


def test_clamp_respects_min_max():
    assert clamp_n_ticks(50, 8, 256) == 50
    assert clamp_n_ticks(1000, 8, 256) == 256
    assert clamp_n_ticks(5, 8, 256) == 8


# ─────────────────────────────────────────────────────────
# synthesize_prices_uniform — C1, C2, C3, C4, C5 + length
# ─────────────────────────────────────────────────────────
@given(
    ohlc=ohlc_floats(),
    n=st.integers(min_value=4, max_value=256),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=300, suppress_health_check=[HealthCheck.too_slow])
def test_synthesize_prices_uniform_satisfies_C1_C5(ohlc, n, seed):
    o, h, l, c = ohlc
    rng = np.random.default_rng(seed)
    prices = synthesize_prices_uniform(o, h, l, c, n=n, rng=rng)

    # length
    assert len(prices) == n

    # C1
    assert math.isclose(float(prices[0]), o, rel_tol=1e-9, abs_tol=1e-9)
    # C2
    assert math.isclose(float(prices[-1]), c, rel_tol=1e-9, abs_tol=1e-9)
    # C5: 모든 가격이 [L, H]
    assert float(prices.min()) >= l - 1e-9
    assert float(prices.max()) <= h + 1e-9
    # C3, C4: 정확히 L, H 도달
    assert math.isclose(float(prices.min()), l, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(float(prices.max()), h, rel_tol=1e-9, abs_tol=1e-9)


@given(
    o=st.floats(min_value=1.0, max_value=1e6, allow_nan=False),
    n=st.integers(min_value=4, max_value=64),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100)
def test_zero_range_all_equal(o, n, seed):
    """H == L == O == C 인 경우 모든 가격 == O."""
    rng = np.random.default_rng(seed)
    prices = synthesize_prices_uniform(o, o, o, o, n=n, rng=rng)
    assert len(prices) == n
    for p in prices:
        assert p == o


@given(
    ohlc=ohlc_floats(),
    n=st.integers(min_value=4, max_value=64),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=200)
def test_synthesize_determinism(ohlc, n, seed):
    """C7 — 같은 seed -> bit-exact 동일."""
    o, h, l, c = ohlc
    a = synthesize_prices_uniform(o, h, l, c, n=n, rng=np.random.default_rng(seed))
    b = synthesize_prices_uniform(o, h, l, c, n=n, rng=np.random.default_rng(seed))
    assert (a == b).all()


# ─────────────────────────────────────────────────────────
# 잘못된 입력 거부 (P6)
# ─────────────────────────────────────────────────────────
def test_high_lt_low_raises():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        synthesize_prices_uniform(o=100.0, h=99.0, l=101.0, c=100.0, n=10, rng=rng)


def test_open_outside_range_raises():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        synthesize_prices_uniform(o=200.0, h=110.0, l=90.0, c=100.0, n=10, rng=rng)


def test_n_below_four_raises():
    rng = np.random.default_rng(0)
    with pytest.raises(ValueError):
        synthesize_prices_uniform(o=100.0, h=110.0, l=90.0, c=100.0, n=3, rng=rng)
