"""SeedManager — P3 결정성의 단일 진실.

같은 root seed 에서 SHA256 으로 sub-seed 를 결정적으로 spawn.
같은 (data, config, seed) -> bit-exact 동일 결과를 보장하는 게 목적.
"""

from __future__ import annotations

import hashlib

import numpy as np


class SeedManager:
    """하위 컴포넌트가 root seed 와 충돌 없이 sub-seed 를 받는 헬퍼."""

    def __init__(self, root: int = 0) -> None:
        self._root = int(root) & 0xFFFFFFFF

    @property
    def root(self) -> int:
        return self._root

    def spawn(self, label: str) -> int:
        """label 별로 결정적인 32-bit unsigned int seed 반환."""
        h = hashlib.sha256(f"{self._root}:{label}".encode()).digest()
        return int.from_bytes(h[:4], "big") & 0x7FFFFFFF  # 양수 31bit

    def rng(self, label: str) -> np.random.Generator:
        return np.random.default_rng(self.spawn(label))
