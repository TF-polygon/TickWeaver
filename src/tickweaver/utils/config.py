"""설정 dataclass — pydantic 기반 (P10).

BacktestConfig / StrategySpec 만 정의 (LiveConfig 는 archive 와 함께 동결, D11).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from tickweaver.core.types import MarketType


class RunSection(BaseModel):
    initial_cash: float = 10000.0
    market_type: MarketType = MarketType.USDT_M_PERPETUAL


class PeriodSection(BaseModel):
    auto: bool = True
    start: str | None = None
    end: str | None = None


class TickSynthesisSection(BaseModel):
    generator: Literal["uniform", "bridge"] = "uniform"
    n_min: int = 8
    n_max: int = 256
    seed: int = 42


class ExecutionSection(BaseModel):
    fee_bps: float = 5.0
    slippage_bps: float = 2.0


class ReportingSection(BaseModel):
    out_dir: str | None = None
    dump_ticks: int = 0


class LoggingSection(BaseModel):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class BacktestConfig(BaseModel):
    """`configs/backtest/default.yaml` 등의 정적 표현."""

    run: RunSection = Field(default_factory=RunSection)
    period: PeriodSection = Field(default_factory=PeriodSection)
    tick_synthesis: TickSynthesisSection = Field(default_factory=TickSynthesisSection)
    execution: ExecutionSection = Field(default_factory=ExecutionSection)
    reporting: ReportingSection = Field(default_factory=ReportingSection)
    logging: LoggingSection = Field(default_factory=LoggingSection)

    @classmethod
    def load_yaml(cls, path: str | Path) -> "BacktestConfig":
        with open(path, encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        return cls(**data)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class StrategySpec(BaseModel):
    """전략 지정. file 모드 (path) 또는 registry 모드 (name) — xor 강제."""

    path: str | None = None
    params_path: str | None = None
    name: str | None = None

    @model_validator(mode="after")
    def _xor(self):
        has_path = self.path is not None
        has_name = self.name is not None
        if has_path == has_name:
            raise ValueError("StrategySpec: 'path' xor 'name' 중 정확히 하나만 설정해야 합니다.")
        return self
