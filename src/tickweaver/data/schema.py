"""표준 OHLCV 스키마 (P4) 정의 + 검증.

표준:
  type    : pd.DataFrame
  index   : pd.DatetimeIndex (tz='UTC', name='timestamp', 단조 증가, unique)
  columns : open, high, low, close, volume   (모두 float64)
  attrs   : {symbol, timeframe, exchange, source_uri}

검증 정책 (D13):
  - 봉 결손/중복 자체는 raise 가 아닌 skip 으로 처리됨 (normalizers.py 에서 dedup, gap 은 그대로 통과)
  - 단, 타입/컬럼/값 무결성 (high<low, 음수 등) 위반은 raise (P6)
"""

from __future__ import annotations

import pandas as pd

from tickweaver.core.exceptions import OHLCIntegrityError, OHLCSchemaError

REQUIRED_COLUMNS: tuple[str, ...] = ("open", "high", "low", "close", "volume")
INDEX_NAME: str = "timestamp"


def validate_ohlcv_schema(df: pd.DataFrame) -> None:
    """컬럼 / 인덱스 / dtype / tz 검증. 위반 시 OHLCSchemaError raise (P6)."""
    if not isinstance(df, pd.DataFrame):
        raise OHLCSchemaError(f"expected DataFrame, got {type(df).__name__}")

    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise OHLCSchemaError(f"missing columns: {missing}")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise OHLCSchemaError(f"index must be DatetimeIndex, got {type(df.index).__name__}")

    if df.index.tz is None:
        raise OHLCSchemaError("index must be tz-aware (UTC)")

    if str(df.index.tz) not in ("UTC", "tzutc()", "UTC+00:00"):
        raise OHLCSchemaError(f"index tz must be UTC, got {df.index.tz}")

    if df.index.name != INDEX_NAME:
        raise OHLCSchemaError(f"index name must be {INDEX_NAME!r}, got {df.index.name!r}")

    for c in REQUIRED_COLUMNS:
        if not pd.api.types.is_float_dtype(df[c]):
            raise OHLCSchemaError(f"column {c!r} must be float dtype, got {df[c].dtype}")

    if not df.index.is_monotonic_increasing:
        raise OHLCSchemaError("index must be monotonic increasing")

    if not df.index.is_unique:
        raise OHLCSchemaError("index must be unique (drop_duplicates first)")


def validate_ohlcv_integrity(df: pd.DataFrame) -> None:
    """값 무결성 검증 (high>=low, 음수 가격 없음 등). gap 은 검사 안 함 (D13)."""
    if (df["high"] < df["low"]).any():
        bad = df[df["high"] < df["low"]].index[:5].tolist()
        raise OHLCIntegrityError(f"high < low at: {bad}")

    for c in ("open", "high", "low", "close"):
        if (df[c] <= 0).any():
            bad = df[df[c] <= 0].index[:5].tolist()
            raise OHLCIntegrityError(f"non-positive {c} at: {bad}")

    if (df["volume"] < 0).any():
        bad = df[df["volume"] < 0].index[:5].tolist()
        raise OHLCIntegrityError(f"negative volume at: {bad}")


def attach_attrs(
    df: pd.DataFrame,
    *,
    symbol: str,
    timeframe: str,
    exchange: str,
    source_uri: str = "",
) -> pd.DataFrame:
    """표준 attrs 부착."""
    df.attrs.update(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "exchange": exchange,
            "source_uri": source_uri,
        }
    )
    return df
