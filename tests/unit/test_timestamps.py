"""tick_synthesis.timestamps — distribute_uniform 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tickweaver.tick_synthesis.timestamps import distribute_uniform
from tickweaver.utils.timeutils import timeframe_to_ms


_TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1d"]


@given(
    tf=st.sampled_from(_TIMEFRAMES),
    n=st.integers(min_value=2, max_value=512),
    epoch_hours=st.integers(min_value=0, max_value=24 * 365 * 10),
)
@settings(max_examples=200)
def test_distribute_uniform_count(tf, n, epoch_hours):
    close = pd.Timestamp("2024-01-01", tz="UTC") + pd.Timedelta(hours=epoch_hours)
    out = distribute_uniform(close, tf, n)
    assert len(out) == n


@given(
    tf=st.sampled_from(_TIMEFRAMES),
    n=st.integers(min_value=2, max_value=256),
)
@settings(max_examples=200)
def test_distribute_uniform_endpoints(tf, n):
    """첫 timestamp = bar open (close - timeframe), 마지막 = bar close."""
    close = pd.Timestamp("2024-06-15 12:00:00", tz="UTC")
    tf_ms = timeframe_to_ms(tf)
    expected_open = close - pd.Timedelta(milliseconds=tf_ms)
    out = distribute_uniform(close, tf, n)
    assert out[0] == expected_open
    assert out[-1] == close


@given(
    tf=st.sampled_from(_TIMEFRAMES),
    n=st.integers(min_value=2, max_value=256),
)
@settings(max_examples=200)
def test_distribute_uniform_monotonic(tf, n):
    close = pd.Timestamp("2024-06-15 12:00:00", tz="UTC")
    out = distribute_uniform(close, tf, n)
    for a, b in zip(out, out[1:]):
        assert a <= b


@given(
    tf=st.sampled_from(_TIMEFRAMES),
    n=st.integers(min_value=2, max_value=256),
)
@settings(max_examples=100)
def test_distribute_uniform_all_utc_tz_aware(tf, n):
    close = pd.Timestamp("2024-06-15 12:00:00", tz="UTC")
    out = distribute_uniform(close, tf, n)
    for ts in out:
        assert ts.tzinfo is not None
        assert str(ts.tz) in ("UTC", "tzutc()", "UTC+00:00")


def test_n_below_two_raises():
    with pytest.raises(ValueError):
        distribute_uniform(pd.Timestamp("2024-01-01", tz="UTC"), "1h", 1)
