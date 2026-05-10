"""슬리피지 모델 (P7)."""

from __future__ import annotations

from typing import Protocol

from tickweaver.core.types import Side


class SlippageModel(Protocol):
    def adjust(self, price: float, side: Side) -> float: ...


class NoSlippage:
    def adjust(self, price: float, side: Side) -> float:
        return price


class FixedBpsSlippage:
    """체결가를 fixed bps 만큼 불리하게 (BUY: +, SELL: -) 보정."""

    def __init__(self, bps: float = 2.0) -> None:
        self.bps = float(bps)

    def adjust(self, price: float, side: Side) -> float:
        adj = price * (self.bps / 10000.0)
        return price + adj if side == Side.BUY else price - adj


def build_slippage(bps: float) -> SlippageModel:
    return NoSlippage() if bps <= 0 else FixedBpsSlippage(bps)
