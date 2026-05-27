"""data/ — 외부 데이터 -> 표준 OHLCV (P4) 게이트.

현 단계 active 로더: ccxt_loader (외부 데이터 진입), parquet_loader (내부 캐시).
csv_loader / binance_zip_loader 는 frozen (D10).
"""
