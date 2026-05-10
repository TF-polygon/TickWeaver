"""BrownianBridgeTickGenerator (M4) — log-space GBM bridge + reflective + post-hoc H/L touch.

plan.md S.6.2 algorithm:
  1. log_O, log_C, log_L, log_H = log of OHLC
  2. sigma = (log_H - log_L) * sigma_factor  (default 0.5)
  3. standard BB at points i/(n-1) for i in [0..n-1] with endpoints (log_O, log_C):
        bridge_i  = BM_i - (i/(n-1)) * BM_{n-1}
        log_p_i   = log_O + t_norm_i * (log_C - log_O) + sigma * bridge_i
  4. exp() -> prices
  5. reflective barrier into [L, H] (max 6 passes), then final clip
  6. enforce prices[0] = O, prices[-1] = C  (C1, C2)
  7. interior argmax -> H if max < H,  interior argmin -> L if min > L  (C3, C4)
  8. validator passes (caller verifies via validate_ticks)

D16: only compare_runs.py compares uniform vs bridge. Regular backtests use one or the other.
"""

from __future__ import annotations

import math

import numpy as np

from tickweaver.core.types import OHLCBar, Tick
from tickweaver.tick_synthesis.generator import register_tick_generator
from tickweaver.tick_synthesis.timestamps import distribute_uniform


_EPS = 1e-12


@register_tick_generator("bridge")
class BrownianBridgeTickGenerator:
    """Log-space Brownian bridge with reflective barrier and post-hoc H/L touch."""

    name: str = "bridge"

    def __init__(self, sigma_factor: float = 0.5, max_reflect_passes: int = 6) -> None:
        if sigma_factor <= 0:
            raise ValueError(f"sigma_factor must be > 0, got {sigma_factor}")
        self.sigma_factor = float(sigma_factor)
        self.max_reflect_passes = int(max_reflect_passes)

    def generate(
        self,
        bar: OHLCBar,
        n_ticks: int,
        rng: np.random.Generator,
    ) -> list[Tick]:
        n = int(n_ticks)
        if n < 4:
            raise ValueError(f"n must be >= 4, got {n}")

        O, H, L, C = bar.open, bar.high, bar.low, bar.close
        if H < L:
            raise ValueError(f"high<low: {H} < {L}")
        if not (L <= O <= H and L <= C <= H):
            raise ValueError(f"O/C outside [L,H]: O={O}, H={H}, L={L}, C={C}")

        ts_list = distribute_uniform(bar.timestamp, bar.timeframe, n)

        # Zero-range bar: collapse all prices to O
        if H == L:
            prices = np.full(n, O, dtype=np.float64)
            return self._make_ticks(prices, ts_list, bar.symbol)

        # 1. log space
        log_O = math.log(O)
        log_C = math.log(C)
        log_L = math.log(L)
        log_H = math.log(H)
        sigma = (log_H - log_L) * self.sigma_factor

        # 2. brownian motion + bridge
        # increments scaled by 1/sqrt(n-1), cumsum -> BM. BM[0] forced to 0.
        scale = 1.0 / math.sqrt(max(n - 1, 1))
        increments = rng.normal(0.0, 1.0, size=n).astype(np.float64) * scale
        increments[0] = 0.0
        bm = np.cumsum(increments)
        bm_end = float(bm[-1])

        t_norm = np.linspace(0.0, 1.0, n, dtype=np.float64)
        bridge_arr = bm - t_norm * bm_end

        # 3. log prices along the deterministic linear interpolation + sigma * bridge
        log_p = log_O + t_norm * (log_C - log_O) + sigma * bridge_arr

        # 4. exp -> prices
        prices = np.exp(log_p).astype(np.float64)

        # 5. reflective barrier inside [L, H], then final clip
        for _ in range(self.max_reflect_passes):
            below = prices < L
            above = prices > H
            if not below.any() and not above.any():
                break
            prices = np.where(below, 2.0 * L - prices, prices)
            prices = np.where(above, 2.0 * H - prices, prices)
        prices = np.clip(prices, L, H)

        # 6. enforce C1, C2
        prices[0] = O
        prices[-1] = C

        # 7. enforce C3, C4 — interior touch L/H if not already
        if n >= 4:
            interior = prices[1:-1]
            cur_min = float(prices.min())
            cur_max = float(prices.max())

            need_low = cur_min > L + _EPS
            need_high = cur_max < H - _EPS

            if need_low or need_high:
                min_local = int(np.argmin(interior))
                max_local = int(np.argmax(interior))
                if need_low and need_high and min_local == max_local:
                    # interior values were all equal; pick a different slot for H
                    max_local = (min_local + 1) % (n - 2)
                if need_low:
                    prices[1 + min_local] = L
                if need_high:
                    prices[1 + max_local] = H

        return self._make_ticks(prices, ts_list, bar.symbol)

    @staticmethod
    def _make_ticks(prices, ts_list, symbol: str) -> list[Tick]:
        return [
            Tick(
                timestamp=ts,
                price=float(p),
                bar_index=0,
                tick_index_in_bar=i,
                symbol=symbol,
            )
            for i, (ts, p) in enumerate(zip(ts_list, prices))
        ]
