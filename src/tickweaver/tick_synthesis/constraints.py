"""Tick 가격 합성 헬퍼 (C1~C7 제약을 만족하는 가격 시퀀스 생성)."""

from __future__ import annotations

import numpy as np


def clamp_n_ticks(n_target: int, n_min: int, n_max: int) -> int:
    """n_target 을 [n_min, n_max] 안으로 자르되 항상 >= 4."""
    n = max(int(n_target), int(n_min))
    n = min(n, int(n_max))
    return max(n, 4)


def synthesize_prices_uniform(
    o: float,
    h: float,
    l: float,
    c: float,
    n: int,
    rng: np.random.Generator,
) -> np.ndarray:
    """uniform 알고리즘 (M2, default).

    1. n >= 4 (caller 가 보장)
    2. zero-range (H==L): 모든 가격 = O 로 통일
    3. interior = U(L, H, n-4)
    4. middle = shuffle([L, H, *interior])  ← 길이 n-2
    5. P = [O] + middle + [C]               ← 길이 n
    """
    if h < l:
        raise ValueError(f"high<low: {h} < {l}")
    if not (l <= o <= h and l <= c <= h):
        raise ValueError(f"open/close out of [low, high]: O={o}, H={h}, L={l}, C={c}")
    if n < 4:
        raise ValueError(f"n must be >= 4, got {n}")

    if h == l:
        return np.full(n, o, dtype=np.float64)

    interior_count = n - 4
    if interior_count > 0:
        interior = rng.uniform(low=l, high=h, size=interior_count).astype(np.float64)
    else:
        interior = np.empty(0, dtype=np.float64)

    middle = np.empty(n - 2, dtype=np.float64)
    middle[: interior_count] = interior
    middle[interior_count] = l
    middle[interior_count + 1] = h
    rng.shuffle(middle)

    prices = np.empty(n, dtype=np.float64)
    prices[0] = o
    prices[1 : n - 1] = middle
    prices[n - 1] = c
    return prices
