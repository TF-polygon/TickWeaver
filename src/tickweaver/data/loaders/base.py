"""로더 공용 헬퍼."""

from __future__ import annotations

import pandas as pd


def slice_period(
    df: pd.DataFrame,
    since: pd.Timestamp | None,
    until: pd.Timestamp | None,
) -> pd.DataFrame:
    """[since, until) 범위로 자르기. None 이면 끝까지."""
    if since is not None:
        df = df[df.index >= since]
    if until is not None:
        df = df[df.index < until]
    return df


def assert_symbol_timeframe_match(df: pd.DataFrame, symbol: str, timeframe: str) -> None:
    """attrs 가 있으면 일치 확인. 없으면 skip (캐시 미부착 케이스 허용)."""
    a = df.attrs
    if "symbol" in a and a["symbol"] != symbol:
        raise ValueError(f"symbol mismatch: cache={a['symbol']!r} vs request={symbol!r}")
    if "timeframe" in a and a["timeframe"] != timeframe:
        raise ValueError(
            f"timeframe mismatch: cache={a['timeframe']!r} vs request={timeframe!r}"
        )
