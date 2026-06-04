"""TradingView parity-verification harness.

Compares TickWeaver backtest reports against certified TradingView (PineScript)
exports within a documented tolerance. See ``parity/compare.py`` for the shared
comparison contract used across the parity track.
"""

from __future__ import annotations
