"""ReplayFeed — 표준 OHLCV DataFrame -> BarEvent 시퀀스.

D13: 결손 봉은 그대로 skip 됨 — DataFrame 의 행만 순서대로 yield 한다.
시간 차로 봉 인덱스를 추정하지 않으므로 timestamp 간격이 일정하지 않아도 OK.
"""

from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from tickweaver.core.events import BarEvent
from tickweaver.core.types import OHLCBar


class ReplayFeed:
    def __init__(self, df: pd.DataFrame) -> None:
        self.df = df
        self.symbol: str = df.attrs.get("symbol", "")
        self.timeframe: str = df.attrs.get("timeframe", "")

    def __len__(self) -> int:
        return len(self.df)

    def iter_bars(self) -> Iterator[BarEvent]:
        symbol = self.symbol
        tf = self.timeframe
        for ts, row in self.df.iterrows():
            bar = OHLCBar(
                timestamp=ts,  # type: ignore[arg-type]
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                symbol=symbol,
                timeframe=tf,
            )
            yield BarEvent(bar=bar)
