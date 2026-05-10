"""C1~C7 계약 검증 — 깨지면 TickContractError raise (P6)."""

from __future__ import annotations

import math

import numpy as np

from tickweaver.core.exceptions import TickContractError
from tickweaver.core.types import OHLCBar, Tick

_REL_TOL = 1e-9
_ABS_TOL = 1e-9


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


def validate_ticks(
    bar: OHLCBar,
    ticks: list[Tick],
    *,
    n_min: int = 4,
    n_max: int = 256,
) -> None:
    """C1~C6 검증. C7 (결정성) 은 verify_determinism 에서 별도."""
    n = len(ticks)
    # C6
    if not (n_min <= n <= n_max):
        raise TickContractError(
            f"C6: n out of [{n_min},{n_max}], got {n} (bar ts={bar.timestamp})"
        )
    if n < 2:
        raise TickContractError(f"need at least 2 ticks, got {n}")

    prices = np.array([t.price for t in ticks], dtype=np.float64)

    # C1
    if not _close(prices[0], bar.open):
        raise TickContractError(f"C1 violated: ticks[0]={prices[0]} vs O={bar.open}")
    # C2
    if not _close(prices[-1], bar.close):
        raise TickContractError(f"C2 violated: ticks[-1]={prices[-1]} vs C={bar.close}")
    # C5
    p_min = float(prices.min())
    p_max = float(prices.max())
    if p_min < bar.low - _ABS_TOL:
        raise TickContractError(f"C5 violated: min(ticks)={p_min} < L={bar.low}")
    if p_max > bar.high + _ABS_TOL:
        raise TickContractError(f"C5 violated: max(ticks)={p_max} > H={bar.high}")
    # C3
    if not _close(p_min, bar.low):
        raise TickContractError(f"C3 violated: min(ticks)={p_min} vs L={bar.low}")
    # C4
    if not _close(p_max, bar.high):
        raise TickContractError(f"C4 violated: max(ticks)={p_max} vs H={bar.high}")


def verify_determinism(
    generator,
    bar: OHLCBar,
    n: int,
    seed: int,
) -> None:
    """같은 (bar, n, seed) 두 번 -> bit-exact 동일 (C7)."""
    rng_a = np.random.default_rng(seed)
    rng_b = np.random.default_rng(seed)
    a = generator.generate(bar, n_ticks=n, rng=rng_a)
    b = generator.generate(bar, n_ticks=n, rng=rng_b)
    if [t.price for t in a] != [t.price for t in b]:
        raise TickContractError("C7 violated: non-deterministic generator output")
