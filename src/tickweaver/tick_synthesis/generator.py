"""TickGenerator 레지스트리."""

from __future__ import annotations

from typing import Callable

_REGISTRY: dict[str, type] = {}


def register_tick_generator(name: str) -> Callable[[type], type]:
    """`@register_tick_generator("uniform")` 으로 클래스 등록."""

    def deco(cls: type) -> type:
        if name in _REGISTRY:
            raise ValueError(f"tick generator already registered: {name}")
        cls.name = name  # type: ignore[attr-defined]
        _REGISTRY[name] = cls
        return cls

    return deco


def get_tick_generator(name: str):
    """name 에 등록된 generator 인스턴스 반환."""
    if name not in _REGISTRY:
        raise KeyError(
            f"unknown tick generator: {name!r}. registered: {sorted(_REGISTRY.keys())}"
        )
    return _REGISTRY[name]()


def list_tick_generators() -> list[str]:
    return sorted(_REGISTRY.keys())
