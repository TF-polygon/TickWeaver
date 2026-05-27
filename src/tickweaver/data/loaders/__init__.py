"""data/loaders/ — 외부 출처별 로더.

현 단계 active: ccxt_loader (외부 데이터 진입), parquet_loader (내부 캐시).
csv_loader, binance_zip_loader 는 frozen (D10) — 본 패키지에 포함 안 됨.
"""

from tickweaver.data.loaders.ccxt_loader import CcxtLoader
from tickweaver.data.loaders.parquet_loader import (
    read_parquet_with_attrs,
    write_parquet,
)

__all__ = ["CcxtLoader", "read_parquet_with_attrs", "write_parquet"]
