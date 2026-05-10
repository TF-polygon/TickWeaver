"""validate_ticks (C1~C6) 단위 테스트."""

from __future__ import annotations

import pandas as pd
import pytest

from tickweaver.core.exceptions import TickContractError
from tickweaver.core.types import OHLCBar, Tick
from tickweaver.tick_synthesis.validator import validate_ticks


def _bar(o=100.0, h=110.0, l=90.0, c=105.0) -> OHLCBar:
    return OHLCBar(
        timestamp=pd.Timestamp("2024-01-01 01:00:00", tz="UTC"),
        open=o,
        high=h,
        low=l,
        close=c,
        volume=10.0,
        symbol="TEST",
        timeframe="1h",
    )


def _ticks(prices: list[float]) -> list[Tick]:
    base = pd.Timestamp("2024-01-01 00:00:00", tz="UTC")
    return [
        Tick(timestamp=base + pd.Timedelta(seconds=i), price=p, bar_index=0, tick_index_in_bar=i)
        for i, p in enumerate(prices)
    ]


# ─────────────────────────────────────────────────────────
# Valid case
# ─────────────────────────────────────────────────────────
def test_valid_ticks_pass():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    prices = [100.0, 90.0, 110.0, 95.0, 105.0]  # C1=100, C2=105, min=90=L, max=110=H
    validate_ticks(bar, _ticks(prices), n_min=4, n_max=256)


def test_zero_range_passes():
    bar = _bar(o=100.0, h=100.0, l=100.0, c=100.0)
    validate_ticks(bar, _ticks([100.0] * 8), n_min=4, n_max=256)


# ─────────────────────────────────────────────────────────
# C1 — first == open
# ─────────────────────────────────────────────────────────
def test_C1_violation_raises():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    bad = [99.0, 90.0, 110.0, 95.0, 105.0]  # first != open
    with pytest.raises(TickContractError, match="C1"):
        validate_ticks(bar, _ticks(bad))


# ─────────────────────────────────────────────────────────
# C2 — last == close
# ─────────────────────────────────────────────────────────
def test_C2_violation_raises():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    bad = [100.0, 90.0, 110.0, 95.0, 106.0]  # last != close
    with pytest.raises(TickContractError, match="C2"):
        validate_ticks(bar, _ticks(bad))


# ─────────────────────────────────────────────────────────
# C5 — out-of-range
# ─────────────────────────────────────────────────────────
def test_C5_below_low_raises():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    bad = [100.0, 89.0, 110.0, 95.0, 105.0]  # 89 < L=90
    with pytest.raises(TickContractError, match="C5"):
        validate_ticks(bar, _ticks(bad))


def test_C5_above_high_raises():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    bad = [100.0, 90.0, 111.0, 95.0, 105.0]  # 111 > H=110
    with pytest.raises(TickContractError, match="C5"):
        validate_ticks(bar, _ticks(bad))


# ─────────────────────────────────────────────────────────
# C3 — min must equal low (not higher)
# ─────────────────────────────────────────────────────────
def test_C3_violation_raises():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    bad = [100.0, 95.0, 110.0, 96.0, 105.0]  # min=95 != L=90
    with pytest.raises(TickContractError, match="C3"):
        validate_ticks(bar, _ticks(bad))


# ─────────────────────────────────────────────────────────
# C4 — max must equal high
# ─────────────────────────────────────────────────────────
def test_C4_violation_raises():
    bar = _bar(o=100.0, h=110.0, l=90.0, c=105.0)
    bad = [100.0, 90.0, 109.0, 95.0, 105.0]  # max=109 != H=110
    with pytest.raises(TickContractError, match="C4"):
        validate_ticks(bar, _ticks(bad))


# ─────────────────────────────────────────────────────────
# C6 — n out of [n_min, n_max]
# ─────────────────────────────────────────────────────────
def test_C6_too_few_raises():
    bar = _bar()
    with pytest.raises(TickContractError, match="C6"):
        validate_ticks(bar, _ticks([100.0, 105.0]), n_min=4, n_max=256)


def test_C6_too_many_raises():
    bar = _bar()
    prices = [100.0] + [95.0] * 4 + [90.0, 110.0] + [100.0] * 4 + [105.0]
    # 12 prices but n_max=8
    with pytest.raises(TickContractError, match="C6"):
        validate_ticks(bar, _ticks(prices), n_min=4, n_max=8)
