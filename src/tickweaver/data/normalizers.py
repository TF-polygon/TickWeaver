"""임의 DataFrame -> 표준 OHLCV (P4).

D13: 봉 결손은 skip-only — 발견해도 raise 안 함. 보간/resample 일체 비대상.
중복은 drop_duplicates (keep='first').
"""

from __future__ import annotations

from typing import Mapping

import pandas as pd

from tickweaver.core.exceptions import OHLCSchemaError
from tickweaver.data.schema import (
    REQUIRED_COLUMNS,
    attach_attrs,
    validate_ohlcv_integrity,
    validate_ohlcv_schema,
)


def _coerce_timestamp_index(
    df: pd.DataFrame,
    timestamp_col: str | None,
    unit: str | None,
) -> pd.DataFrame:
    """timestamp 컬럼/인덱스 -> tz-aware UTC DatetimeIndex (name='timestamp')."""
    if timestamp_col is not None and timestamp_col in df.columns:
        ts = df[timestamp_col]
        if pd.api.types.is_integer_dtype(ts) or pd.api.types.is_float_dtype(ts):
            ts = pd.to_datetime(ts, unit=unit or "ms", utc=True)
        else:
            ts = pd.to_datetime(ts, utc=True)
        df = df.drop(columns=[timestamp_col]).set_index(ts)
    elif isinstance(df.index, pd.DatetimeIndex):
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        else:
            df.index = df.index.tz_convert("UTC")
    else:
        raise OHLCSchemaError(
            "DataFrame has neither a timestamp column nor a DatetimeIndex"
        )
    df.index.name = "timestamp"
    return df


def normalize_ohlcv(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    exchange: str,
    source_uri: str = "",
    column_mapping: Mapping[str, str] | None = None,
    timestamp_col: str | None = "timestamp",
    timestamp_unit: str | None = "ms",
) -> pd.DataFrame:
    """임의 DataFrame -> 표준 OHLCV.

    Args:
        df: 원본 DataFrame.
        column_mapping: 외부->표준 컬럼명 매핑 (예: {'open_time':'timestamp'}).
        timestamp_col: timestamp 가 들어 있는 컬럼명 ('timestamp' 가 없고 인덱스가 DatetimeIndex 면 None 가능).
        timestamp_unit: int/float timestamp 의 단위 ('ms', 's', 'ns').

    Returns:
        표준 OHLCV DataFrame (검증 통과).
    """
    df = df.copy()

    if column_mapping:
        df = df.rename(columns=dict(column_mapping))

    df = _coerce_timestamp_index(df, timestamp_col, timestamp_unit)

    # 표준 컬럼만 선택 (있는 것만)
    keep = [c for c in REQUIRED_COLUMNS if c in df.columns]
    if len(keep) != len(REQUIRED_COLUMNS):
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        raise OHLCSchemaError(f"after mapping, still missing columns: {missing}")
    df = df[list(REQUIRED_COLUMNS)].astype("float64")

    # D13: 중복은 drop, 결손은 그대로 통과
    df = df[~df.index.duplicated(keep="first")]
    df = df.sort_index()

    df = attach_attrs(
        df,
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        source_uri=source_uri,
    )

    validate_ohlcv_schema(df)
    validate_ohlcv_integrity(df)
    return df
