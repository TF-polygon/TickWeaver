"""tick_synthesis/ — OHLCBar -> synthesized tick sequence (C1~C7).

Project's core differentiator (D12). uniform vs bridge direct comparison is
compare_runs.py only (D16).
"""

from tickweaver.tick_synthesis.generator import (
    get_tick_generator,
    list_tick_generators,
    register_tick_generator,
)
from tickweaver.tick_synthesis.validator import validate_ticks

# Registration triggers — side-effect imports
from tickweaver.tick_synthesis.strategies import bridge, ohlc, uniform  # noqa: F401

__all__ = [
    "get_tick_generator",
    "list_tick_generators",
    "register_tick_generator",
    "validate_ticks",
]
