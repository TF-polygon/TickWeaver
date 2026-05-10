"""수수료 모델 (P7)."""

from __future__ import annotations

from typing import Protocol


class FeeModel(Protocol):
    def fee(self, price: float, qty: float) -> float: ...


class NoFee:
    def fee(self, price: float, qty: float) -> float:
        return 0.0


class BpsFeeModel:
    """basis-point 비례 수수료 (1 bp = 0.01%)."""

    def __init__(self, bps: float = 5.0) -> None:
        self.bps = float(bps)

    def fee(self, price: float, qty: float) -> float:
        notional = abs(price * qty)
        return notional * (self.bps / 10000.0)
