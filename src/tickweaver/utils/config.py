"""Config dataclass (pydantic) for the backtest runner.

The yaml file is the single source of truth for one backtest execution:
  - capital / market mode / leverage
  - data source (exchange + symbol + timeframe + period)
  - execution costs (commission / slippage / spread; all in percent units)
  - tick synthesis (generator / n_ticks_min / n_ticks_max / seed)
  - reporting + logging

Strategy code (strategies/<name>.py) is the OTHER source of truth -- it owns
all trading parameters as module constants. No json side-files anymore.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field


class RunSection(BaseModel):
    initial_capital: float = 10000.0
    mode: Literal["spot", "futures"] = "spot"
    leverage: float = 1.0


class DataSection(BaseModel):
    exchange: str = "binance"
    symbol: str = "BTC/USDT:USDT"
    timeframe: str = "1h"
    start_date: str = "2024-01-01"   # inclusive (YYYY-MM-DD)
    end_date: str = "2024-07-01"     # exclusive (YYYY-MM-DD)


class ExecutionSection(BaseModel):
    """All cost fields use PERCENT units (0.05 = 0.05%)."""

    commission: float = 0.05         # 0.05 == 0.05%
    slippage: float = 0.02
    spread: float = 0.0

    @property
    def fee_bps(self) -> float:
        # internal conversion: % -> bps (1% = 100 bps)
        return float(self.commission) * 100.0

    @property
    def slippage_bps(self) -> float:
        return float(self.slippage) * 100.0

    @property
    def spread_bps(self) -> float:
        return float(self.spread) * 100.0


class TickSynthesisSection(BaseModel):
    generator: Literal["uniform", "bridge"] = "uniform"
    n_ticks_min: int = 8
    n_ticks_max: int = 256
    seed: int = 42


class ReportingSection(BaseModel):
    out_dir: str | None = None       # None -> reports/<strategy>_<UTC ts>/
    dump_ticks: int = 0


class LoggingSection(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class BacktestConfig(BaseModel):
    """Defined by a single yaml file under configs/."""

    run: RunSection = Field(default_factory=RunSection)
    data: DataSection = Field(default_factory=DataSection)
    execution: ExecutionSection = Field(default_factory=ExecutionSection)
    tick_synthesis: TickSynthesisSection = Field(default_factory=TickSynthesisSection)
    reporting: ReportingSection = Field(default_factory=ReportingSection)
    logging: LoggingSection = Field(default_factory=LoggingSection)

    @classmethod
    def load_yaml(cls, path: str | Path) -> "BacktestConfig":
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
