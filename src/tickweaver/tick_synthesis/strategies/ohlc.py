"""OhlcTickGenerator — replicate TradingView's bar-fill (broker-emulator) model.

Instead of synthesizing a random intra-bar path, this generator emits exactly the
four OHLC prices in TradingView's documented broker-emulator order, so TickWeaver
fills against the same assumption TradingView uses on historical bars:

    if the high is closer to the open than the low:  O -> H -> L -> C
    otherwise:                                       O -> L -> H -> C

Use this to produce a "bar-resolution" backtest that is directly comparable to a
TradingView strategy run *without* Bar Magnifier. The difference between a
`uniform`/`bridge` run and an `ohlc` run isolates the contribution of the
synthesized intra-bar tick path.

NOTE: this generator always emits 4 ticks (the OHLC corners), so the run config
must set ``n_ticks_min == n_ticks_max == 4`` (the engine validates the tick count
against those bounds).
"""

from __future__ import annotations

import numpy as np

from tickweaver.core.types import OHLCBar, Tick
from tickweaver.tick_synthesis.generator import register_tick_generator
from tickweaver.tick_synthesis.timestamps import distribute_uniform


@register_tick_generator("ohlc")
class OhlcTickGenerator:
    name: str = "ohlc"

    def generate(
        self,
        bar: OHLCBar,
        n_ticks: int,  # ignored — always the 4 OHLC corners
        rng: np.random.Generator,  # unused — this path is deterministic
    ) -> list[Tick]:
        o, h, l, c = bar.open, bar.high, bar.low, bar.close
        # Visit the extreme nearer the open first (TradingView broker-emulator
        # assumption). Ties → high first.
        if (h - o) <= (o - l):
            prices = [o, h, l, c]
        else:
            prices = [o, l, h, c]

        ts_list = distribute_uniform(bar.timestamp, bar.timeframe, 4)
        return [
            Tick(
                timestamp=ts,
                price=float(p),
                bar_index=0,  # caller (engine) sets
                tick_index_in_bar=i,
                symbol=bar.symbol,
            )
            for i, (ts, p) in enumerate(zip(ts_list, prices, strict=True))
        ]
