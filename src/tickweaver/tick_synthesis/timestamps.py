"""봉 내부 timestamp 분배 헬퍼."""

from __future__ import annotations

import numpy as np
import pandas as pd

from tickweaver.utils.timeutils import timeframe_to_ms


def distribute_uniform(
    bar_close_ts: pd.Timestamp,
    timeframe: str,
    n: int,
) -> list[pd.Timestamp]:
    """봉의 close timestamp 와 timeframe 으로부터 봉 내부 n 개 tick 시각을 균등 분배.

    가정: bar_close_ts 가 close 시각. open 시각 = close - timeframe.
    n 개 tick 의 timestamp 는 [open, close] 구간을 균등하게 (n-1) 등분 한 점들.
    """
    if n < 2:
        raise ValueError(f"n must be >= 2, got {n}")
    tf_ms = timeframe_to_ms(timeframe)
    open_ts = bar_close_ts - pd.Timedelta(milliseconds=tf_ms)
    fractions = np.linspace(0.0, 1.0, n)
    base_ns = int(open_ts.value)
    span_ns = int(bar_close_ts.value) - base_ns
    out = [pd.Timestamp(base_ns + int(f * span_ns), tz="UTC") for f in fractions]
    return out
