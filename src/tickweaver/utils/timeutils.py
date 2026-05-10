"""UTC 시간 관련 헬퍼 (P9 — UTC Everywhere)."""

from __future__ import annotations

import pandas as pd

# CCXT 표준 timeframe -> milliseconds
_TF_MS: dict[str, int] = {
    "1m": 60_000,
    "3m": 3 * 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "30m": 30 * 60_000,
    "1h": 60 * 60_000,
    "2h": 2 * 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "6h": 6 * 60 * 60_000,
    "8h": 8 * 60 * 60_000,
    "12h": 12 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
    "3d": 3 * 24 * 60 * 60_000,
    "1w": 7 * 24 * 60 * 60_000,
}


def timeframe_to_ms(tf: str) -> int:
    """`'1h'` -> 3_600_000."""
    if tf not in _TF_MS:
        raise ValueError(f"unknown timeframe: {tf!r}. supported: {sorted(_TF_MS.keys())}")
    return _TF_MS[tf]


def parse_iso_utc(s: str | pd.Timestamp | None) -> pd.Timestamp | None:
    """ISO 문자열 또는 Timestamp -> UTC tz-aware Timestamp. None -> None."""
    if s is None:
        return None
    if isinstance(s, pd.Timestamp):
        ts = s
    else:
        ts = pd.Timestamp(s)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts


def to_utc_index(idx: pd.Index) -> pd.DatetimeIndex:
    """임의의 datetime-like Index 를 UTC tz-aware DatetimeIndex 로 변환."""
    di = pd.DatetimeIndex(idx)
    if di.tz is None:
        di = di.tz_localize("UTC")
    else:
        di = di.tz_convert("UTC")
    return di
