"""tickweaver core dataclass / Enum 정의.

플랜 §3.2 / §5 (`_reference.md` §5) 의 권위 있는 출처.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import pandas as pd


# ─────────────────────────────────────────────────────────
# Enums
# ─────────────────────────────────────────────────────────
class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class PositionSide(str, Enum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


class MarketType(str, Enum):
    SPOT = "spot"
    USDT_M_PERPETUAL = "usdt_m_perpetual"


# ─────────────────────────────────────────────────────────
# Data carriers
# ─────────────────────────────────────────────────────────
@dataclass(frozen=True)
class OHLCBar:
    """단일 OHLCV 봉. timestamp 는 UTC tz-aware, close-time 기준."""

    timestamp: pd.Timestamp
    open: float
    high: float
    low: float
    close: float
    volume: float
    symbol: str
    timeframe: str


@dataclass(frozen=True)
class Tick:
    """봉 내부 합성 tick 한 점."""

    timestamp: pd.Timestamp
    price: float
    bar_index: int
    tick_index_in_bar: int
    symbol: str = ""


# ─────────────────────────────────────────────────────────
# Trading types
# ─────────────────────────────────────────────────────────
@dataclass
class Order:
    """발주된 주문."""

    order_id: str
    client_order_id: str
    symbol: str
    side: Side
    type: OrderType
    qty: float
    price: float | None = None  # LIMIT / STOP_LIMIT 만
    stop_price: float | None = None  # STOP / STOP_LIMIT 만
    created_at: pd.Timestamp | None = None
    status: str = "open"  # open | filled | cancelled


@dataclass
class Fill:
    """주문 체결."""

    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    timestamp: pd.Timestamp
    pnl_realized: float = 0.0


@dataclass
class Position:
    """현재 포지션. side=FLAT 이면 qty=0."""

    symbol: str
    side: PositionSide = PositionSide.FLAT
    qty: float = 0.0
    entry_price: float = 0.0
    mark_price: float = 0.0
    unrealized_pnl: float = 0.0
    liquidation_price: float | None = None

    @property
    def is_flat(self) -> bool:
        return self.side == PositionSide.FLAT or self.qty == 0.0


# ─────────────────────────────────────────────────────────
# Strategy context
# ─────────────────────────────────────────────────────────
@dataclass
class StrategyContext:
    """전략 훅에 함께 주입되는 메타정보 (현재 시점, 심볼/타임프레임 등)."""

    symbol: str
    timeframe: str
    market_type: MarketType = MarketType.USDT_M_PERPETUAL
    bar_index: int = 0
    now: pd.Timestamp | None = None
    extras: dict[str, Any] = field(default_factory=dict)
