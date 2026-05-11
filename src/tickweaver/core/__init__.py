"""core/ - Protocol/ABC, dataclass, exceptions. lowest dependency."""

from tickweaver.core.exceptions import (
    TickweaverError,
    OHLCSchemaError,
    OHLCIntegrityError,
    TickContractError,
    StrategyError,
    OrderError,
    ConfigError,
)
from tickweaver.core.types import (
    Side,
    OrderType,
    PositionSide,
    MarketType,
    OHLCBar,
    Tick,
    Order,
    Fill,
    Position,
    StrategyContext,
)

__all__ = [
    "TickweaverError",
    "OHLCSchemaError",
    "OHLCIntegrityError",
    "TickContractError",
    "StrategyError",
    "OrderError",
    "ConfigError",
    "Side",
    "OrderType",
    "PositionSide",
    "MarketType",
    "OHLCBar",
    "Tick",
    "Order",
    "Fill",
    "Position",
    "StrategyContext",
]
