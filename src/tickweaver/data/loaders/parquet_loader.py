"""Parquet read/write — DataFrame.attrs 보존 (pyarrow schema metadata 활용).

현 단계 사용처: data/processed/ 내부 캐시 read/write 만 (D10).
외부에서 받은 임의 parquet 입력은 frozen (§5 future work).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

_ATTRS_META_KEY = b"tickweaver_attrs"


def write_parquet(df: pd.DataFrame, path: str | Path) -> None:
    """attrs 를 schema metadata 에 직렬화해서 함께 저장."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pandas(df, preserve_index=True)
    meta: dict[bytes, bytes] = dict(table.schema.metadata or {})
    meta[_ATTRS_META_KEY] = json.dumps(df.attrs).encode("utf-8")
    table = table.replace_schema_metadata(meta)
    pq.write_table(table, p)


def read_parquet_with_attrs(path: str | Path) -> pd.DataFrame:
    """write_parquet 으로 저장된 파일에서 attrs 까지 복원."""
    p = Path(path)
    table = pq.read_table(p)
    df = table.to_pandas()

    raw = (table.schema.metadata or {}).get(_ATTRS_META_KEY)
    if raw is not None:
        try:
            df.attrs.update(json.loads(raw.decode("utf-8")))
        except Exception:
            pass

    if isinstance(df.index, pd.DatetimeIndex) and df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    return df
