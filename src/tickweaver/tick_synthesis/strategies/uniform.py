"""UniformTickGenerator — M2 default. plan.md §6.1."""

from __future__ import annotations

import numpy as np

from tickweaver.core.types import OHLCBar, Tick
from tickweaver.tick_synthesis.constraints import synthesize_prices_uniform
from tickweaver.tick_synthesis.generator import register_tick_generator
from tickweaver.tick_synthesis.timestamps import distribute_uniform


@register_tick_generator("uniform")
class UniformTickGenerator:
    name: str = "uniform"

    def generate(
        self,
        bar: OHLCBar,
        n_ticks: int,
        rng: np.random.Generator,
    ) -> list[Tick]:
        prices = synthesize_prices_uniform(
            o=bar.open, h=bar.high, l=bar.low, c=bar.close, n=n_ticks, rng=rng
        )
        ts_list = distribute_uniform(bar.timestamp, bar.timeframe, n_ticks)
        return [
            Tick(
                timestamp=ts,
                price=float(p),
                bar_index=0,  # caller (engine) 가 set
                tick_index_in_bar=i,
                symbol=bar.symbol,
            )
            for i, (ts, p) in enumerate(zip(ts_list, prices, strict=True))
        ]
