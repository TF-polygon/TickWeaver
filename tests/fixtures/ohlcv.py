"""테스트용 합성 OHLCV — 네트워크 X."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tickweaver.data.normalizers import normalize_ohlcv


def make_synthetic_ohlcv(
    n_bars: int = 500,
    timeframe: str = "1h",
    symbol: str = "BTC/USDT:USDT",
    exchange: str = "synthetic",
    start: str = "2024-01-01",
    seed: int = 0,
    base_price: float = 30000.0,
    drift: float = 0.0001,
    vol: float = 0.005,
) -> pd.DataFrame:
    """간단한 GBM 으로 OHLC 시퀀스 합성. 표준 OHLCV 로 정규화 후 반환."""
    rng = np.random.default_rng(seed)
    log_rets = rng.normal(loc=drift, scale=vol, size=n_bars)
    closes = base_price * np.exp(np.cumsum(log_rets))
    opens = np.empty(n_bars)
    opens[0] = base_price
    opens[1:] = closes[:-1]

    # bar 안의 wiggle
    wiggle = rng.uniform(0.001, 0.008, size=n_bars)
    highs = np.maximum(opens, closes) * (1 + wiggle)
    lows = np.minimum(opens, closes) * (1 - wiggle)
    volumes = rng.uniform(50, 500, size=n_bars)

    tf_ms_map = {"1m": 60_000, "5m": 5 * 60_000, "1h": 3_600_000, "1d": 86_400_000}
    tf_ms = tf_ms_map[timeframe]
    start_ts = pd.Timestamp(start, tz="UTC")
    timestamps = [start_ts + pd.Timedelta(milliseconds=tf_ms * (i + 1)) for i in range(n_bars)]

    df_raw = pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
        }
    )
    df = normalize_ohlcv(
        df_raw,
        symbol=symbol,
        timeframe=timeframe,
        exchange=exchange,
        source_uri="fixtures://synthetic",
        timestamp_col="timestamp",
        timestamp_unit=None,
    )
    return df
