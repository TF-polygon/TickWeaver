"""tickweaver Protocol / ABC 정의 — `core/` 외 다른 모듈은 이 시그니처만 의존한다."""

from __future__ import annotations

from abc import ABC
from typing import Callable, Protocol, runtime_checkable

import numpy as np
import pandas as pd

from tickweaver.core.types import (
    Fill,
    OHLCBar,
    Order,
    Position,
    Tick,
)


@runtime_checkable
class DataLoader(Protocol):
    """외부 데이터를 표준 OHLCV (P4) DataFrame 으로 반환."""

    def load(
        self,
        symbol: str,
        timeframe: str,
        since: pd.Timestamp | None = None,
        until: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        ...


@runtime_checkable
class TickGenerator(Protocol):
    """OHLCBar 한 개 -> 합성 tick 시퀀스 (C1~C7 만족)."""

    name: str

    def generate(
        self,
        bar: OHLCBar,
        n_ticks: int,
        rng: np.random.Generator,
    ) -> list[Tick]:
        ...


@runtime_checkable
class Broker(Protocol):
    """주문 라우팅 인터페이스. backtest_broker / (archived) ccxt_broker."""

    def submit(self, order: Order) -> str:
        ...

    def cancel(self, order_id: str) -> bool:
        ...

    def positions(self) -> dict[str, Position]:
        ...

    def set_fill_callback(self, cb: Callable[[Fill], None]) -> None:
        ...

    def on_market_event(self, tick: Tick) -> list[Fill]:
        ...


class Strategy(ABC):
    """레지스트리 모드 전략의 ABC. 파일 모드 전략은 file_strategy.FileStrategy 가 어댑터."""

    def setup(self, context, broker) -> None:  # noqa: ANN001
        ...

    def on_start(self) -> None: ...

    def on_bar(self, bar: OHLCBar) -> None: ...

    def on_tick(self, tick: Tick) -> None: ...

    def on_fill(self, fill: Fill) -> None: ...

    def on_stop(self) -> None: ...
