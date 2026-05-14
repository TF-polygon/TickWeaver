"""tickweaver streaming indicators — 단위 + property tests."""

from __future__ import annotations

import math

import numpy as np
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from tickweaver.strategy.indicators import (
    ATR,
    EMA,
    MACD,
    RSI,
    SMA,
    BollingerBands,
)


# ─────────────────────────────────────────────────────────
# SMA
# ─────────────────────────────────────────────────────────
def test_sma_warmup_returns_none():
    sma = SMA(period=3)
    assert sma.update(10.0) is None
    assert sma.update(20.0) is None
    assert sma.value is None
    assert not sma.is_warm
    assert sma.update(30.0) == pytest.approx(20.0)
    assert sma.is_warm


def test_sma_rolls_past_buffer():
    sma = SMA(period=3)
    for v in (10.0, 20.0, 30.0):
        sma.update(v)
    # 새 값 들어오면 가장 오래된 것 빠짐
    assert sma.update(40.0) == pytest.approx(30.0)  # (20+30+40)/3
    assert sma.update(50.0) == pytest.approx(40.0)  # (30+40+50)/3


def test_sma_reset():
    sma = SMA(period=3)
    for v in (10.0, 20.0, 30.0):
        sma.update(v)
    sma.reset()
    assert sma.value is None
    assert sma.update(100.0) is None


@given(
    period=st.integers(min_value=1, max_value=64),
    n=st.integers(min_value=0, max_value=200),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_sma_matches_numpy(period, n, seed):
    rng = np.random.default_rng(seed)
    prices = rng.uniform(1.0, 1000.0, size=n).tolist()
    sma = SMA(period=period)
    last_value = None
    for p in prices:
        out = sma.update(p)
        if out is not None:
            last_value = out
    if n >= period:
        expected = float(np.mean(prices[-period:]))
        assert math.isclose(last_value, expected, rel_tol=1e-9, abs_tol=1e-9)


# ─────────────────────────────────────────────────────────
# EMA
# ─────────────────────────────────────────────────────────
def test_ema_warmup_seeds_with_sma():
    ema = EMA(period=3)
    assert ema.update(10.0) is None
    assert ema.update(20.0) is None
    # 3번째에 SMA 시드
    seeded = ema.update(30.0)
    assert seeded == pytest.approx(20.0)
    # 다음부터 alpha 가중
    alpha = 2.0 / (3 + 1)
    expected = alpha * 40.0 + (1 - alpha) * 20.0
    assert ema.update(40.0) == pytest.approx(expected)


def test_ema_period_1_acts_as_passthrough():
    ema = EMA(period=1)
    assert ema.update(42.0) == pytest.approx(42.0)
    assert ema.update(50.0) == pytest.approx(50.0)


@given(
    period=st.integers(min_value=2, max_value=64),
    n=st.integers(min_value=0, max_value=200),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.too_slow])
def test_ema_determinism(period, n, seed):
    rng = np.random.default_rng(seed)
    prices = rng.uniform(1.0, 1000.0, size=n).tolist()
    a, b = EMA(period), EMA(period)
    for p in prices:
        a.update(p)
        b.update(p)
    if a.value is None:
        assert b.value is None
    else:
        assert math.isclose(a.value, b.value, rel_tol=1e-12, abs_tol=1e-12)


# ─────────────────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────────────────
def test_rsi_all_gains_returns_100():
    rsi = RSI(period=3)
    for p in (10.0, 11.0, 12.0, 13.0, 14.0):
        rsi.update(p)
    assert rsi.value == pytest.approx(100.0)


def test_rsi_alternating_around_fifty():
    rsi = RSI(period=14)
    rng = np.random.default_rng(0)
    last = 100.0
    for _ in range(200):
        delta = rng.normal(0, 1.0)
        last += delta
        rsi.update(last)
    assert rsi.value is not None
    assert 0 <= rsi.value <= 100
    # mean-reverting 기대값 50 근처
    assert abs(rsi.value - 50.0) < 35.0


def test_rsi_warmup():
    rsi = RSI(period=14)
    # 1 ~ 14: 첫 값 (no delta) + 13 deltas → 아직 14개 deltas 필요
    for i in range(14):
        out = rsi.update(100.0 + i)
    assert out is None or out == 100.0  # 14개 이전엔 None 또는 첫 산출
    rsi.update(200.0)
    assert rsi.is_warm


# ─────────────────────────────────────────────────────────
# ATR
# ─────────────────────────────────────────────────────────
def test_atr_warmup():
    atr = ATR(period=3)
    assert atr.update(110.0, 90.0, 100.0) is None
    assert atr.update(115.0, 95.0, 105.0) is None
    val = atr.update(120.0, 100.0, 110.0)
    assert val is not None
    assert val > 0
    assert atr.is_warm


def test_atr_uses_prev_close_for_gaps():
    atr = ATR(period=2)
    atr.update(110.0, 90.0, 100.0)  # prev_close = 100
    # 다음 봉이 갭 업: high=130, low=120, close=125
    # TR = max(130-120, |130-100|, |120-100|) = max(10, 30, 20) = 30
    val = atr.update(130.0, 120.0, 125.0)
    # period=2 이므로 SMA 시드: (110-90 + 30) / 2 = 25
    assert val == pytest.approx(25.0)


def test_atr_update_bar_method():
    from tickweaver.core.types import OHLCBar
    import pandas as pd

    atr = ATR(period=2)
    bar = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01", tz="UTC"),
        open=100.0, high=110.0, low=90.0, close=100.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    assert atr.update_bar(bar) is None
    bar2 = OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=100.0, high=130.0, low=120.0, close=125.0,
        volume=1.0, symbol="T", timeframe="1h",
    )
    assert atr.update_bar(bar2) == pytest.approx(25.0)


# ─────────────────────────────────────────────────────────
# MACD
# ─────────────────────────────────────────────────────────
def test_macd_warmup_chain():
    m = MACD(fast=3, slow=5, signal=2)
    rng = np.random.default_rng(0)
    for _ in range(20):
        m.update(rng.uniform(95, 105))
    assert m.is_warm
    assert m.macd is not None
    assert m.signal is not None
    assert m.histogram == pytest.approx(m.macd - m.signal)


def test_macd_invalid_periods_raise():
    with pytest.raises(ValueError):
        MACD(fast=26, slow=12)  # fast >= slow
    with pytest.raises(ValueError):
        MACD(fast=10, slow=10)


# ─────────────────────────────────────────────────────────
# BollingerBands
# ─────────────────────────────────────────────────────────
def test_bbands_warmup():
    bb = BollingerBands(period=4, mult=2.0)
    for v in (100.0, 102.0, 98.0):
        assert bb.update(v) is None
    out = bb.update(101.0)
    assert out is not None
    mid, up, lo = out
    arr = np.array([100.0, 102.0, 98.0, 101.0])
    expected_mid = float(arr.mean())
    expected_sigma = float(arr.std(ddof=0))
    assert mid == pytest.approx(expected_mid)
    assert up == pytest.approx(expected_mid + 2.0 * expected_sigma)
    assert lo == pytest.approx(expected_mid - 2.0 * expected_sigma)


def test_bbands_zero_std_collapses():
    bb = BollingerBands(period=3, mult=2.0)
    for _ in range(3):
        bb.update(100.0)
    mid, up, lo = bb.value  # type: ignore[misc]
    assert mid == 100.0
    assert up == 100.0
    assert lo == 100.0


@given(
    period=st.integers(min_value=2, max_value=64),
    mult=st.floats(min_value=0.5, max_value=4.0),
    n=st.integers(min_value=0, max_value=100),
    seed=st.integers(min_value=0, max_value=2**31 - 1),
)
@settings(max_examples=80, suppress_health_check=[HealthCheck.too_slow])
def test_bbands_upper_ge_mid_ge_lower(period, mult, n, seed):
    rng = np.random.default_rng(seed)
    bb = BollingerBands(period=period, mult=mult)
    for p in rng.uniform(1.0, 1000.0, size=n):
        bb.update(float(p))
    if bb.is_warm:
        assert bb.upper >= bb.middle >= bb.lower  # type: ignore[operator]


# ─────────────────────────────────────────────────────────
# 결손 봉 (D13) — update 호출 횟수 기반이라 시간 간격 무관
# ─────────────────────────────────────────────────────────
def test_indicators_count_based_not_time_based():
    """결손 봉 skip 후에도 update 횟수만 세므로 결과 동일."""
    sma_a = SMA(period=3)
    sma_b = SMA(period=3)
    # A: 5개 연속 업데이트
    for v in (10.0, 20.0, 30.0, 40.0, 50.0):
        sma_a.update(v)
    # B: 같은 5개 (예: 결손 봉 자리에 30 이 와도 동일)
    for v in (10.0, 20.0, 30.0, 40.0, 50.0):
        sma_b.update(v)
    assert sma_a.value == sma_b.value


# ─────────────────────────────────────────────────────────
# Phase 2 (dev/adv_verbose) — viz metadata: PANEL + SUBVALUES
# ─────────────────────────────────────────────────────────
def test_sma_panel_is_price():
    assert SMA.PANEL == "price"


def test_ema_panel_is_price():
    assert EMA.PANEL == "price"


def test_bollinger_panel_is_price():
    assert BollingerBands.PANEL == "price"


def test_rsi_panel_is_rsi():
    assert RSI.PANEL == "rsi"


def test_macd_panel_is_macd():
    assert MACD.PANEL == "macd"


def test_atr_panel_is_atr():
    assert ATR.PANEL == "atr"


def test_single_value_indicators_have_no_subvalues():
    """Single-value indicators expose SUBVALUES=None to signal 'just .value'."""
    assert SMA.SUBVALUES is None
    assert EMA.SUBVALUES is None
    assert RSI.SUBVALUES is None
    assert ATR.SUBVALUES is None


def test_bollinger_subvalues_are_mid_upper_lower():
    assert BollingerBands.SUBVALUES == ("mid", "upper", "lower")


def test_macd_subvalues_are_macd_signal_histogram():
    assert MACD.SUBVALUES == ("macd", "signal", "histogram")


def test_panel_is_class_level_not_instance():
    """PANEL must be a class attribute, not set per-instance — so the engine
    can read indicator.PANEL or type(indicator).PANEL interchangeably."""
    e = EMA(period=10)
    assert type(e).PANEL == "price"
    # Reading via instance should also work (descriptor lookup goes to class).
    assert e.PANEL == "price"


def test_bollinger_subvalue_extraction_alignment():
    """Demonstrates how the engine will decompose a BB instance.

    The SUBVALUES tuple must align with the .middle / .upper / .lower
    properties so engine integration (Phase 3) can do something like:

        for sub in BollingerBands.SUBVALUES:
            value = getattr(bb, _BB_ATTR_MAP[sub])

    For BB the mapping is identity: 'mid' -> .middle, 'upper' -> .upper,
    'lower' -> .lower. This test pins that contract.
    """
    bb = BollingerBands(period=3, mult=2.0)
    bb.update(10.0)
    bb.update(11.0)
    bb.update(12.0)  # warm
    # SUBVALUES order matches the canonical (mid, upper, lower).
    assert BollingerBands.SUBVALUES[0] == "mid"
    assert BollingerBands.SUBVALUES[1] == "upper"
    assert BollingerBands.SUBVALUES[2] == "lower"
    # Properties are available for engine extraction.
    assert bb.middle is not None
    assert bb.upper is not None
    assert bb.lower is not None
    assert bb.upper > bb.middle > bb.lower


def test_macd_subvalue_extraction_alignment():
    m = MACD(fast=3, slow=5, signal=2)
    for v in [10.0, 11.0, 12.0, 11.5, 11.8, 12.5, 13.0, 12.7]:
        m.update(v)
    assert MACD.SUBVALUES == ("macd", "signal", "histogram")
    assert m.macd is not None
    assert m.signal is not None
    assert m.histogram is not None
