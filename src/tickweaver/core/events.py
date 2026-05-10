"""이벤트 dataclass — feed/engine 간 메시지 형태."""

from __future__ import annotations

from dataclasses import dataclass

from tickweaver.core.types import Fill, OHLCBar, Order, Tick


@dataclass(frozen=True)
class BarEvent:
    bar: OHLCBar


@dataclass(frozen=True)
class TickEvent:
    tick: Tick


@dataclass(frozen=True)
class OrderEvent:
    order: Order


@dataclass(frozen=True)
class FillEvent:
    fill: Fill


@dataclass(frozen=True)
class CancelEvent:
    order_id: str
