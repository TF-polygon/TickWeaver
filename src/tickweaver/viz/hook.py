"""ChartHook ABC - read-only observer of backtest events.

Design principles (plan_viz.md):
- V1 (Engine non-invasive): BacktestEngine accepts an optional ChartHook.
  None or NullHook means no observation overhead.
- V2 (Determinism preservation): hook methods MUST NOT mutate state that
  backtest depends on. Hooks are read-only observers.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tickweaver.core.types import Fill, OHLCBar, Tick


class ChartHook(ABC):
    """Abstract base for visualization observers."""

    @abstractmethod
    def on_init(self) -> None: ...

    @abstractmethod
    def on_bar(self, bar: "OHLCBar", bar_index: int) -> None: ...

    @abstractmethod
    def on_tick(self, tick: "Tick") -> None: ...

    @abstractmethod
    def on_fill(self, fill: "Fill") -> None: ...

    @abstractmethod
    def on_comment(self, text: str, bar_index: int) -> None: ...

    @abstractmethod
    def on_deinit(self, final_equity: float) -> None: ...


class NullHook(ChartHook):
    """No-op hook. Default when viz is disabled."""

    def on_init(self) -> None:
        pass

    def on_bar(self, bar, bar_index):
        pass

    def on_tick(self, tick):
        pass

    def on_fill(self, fill):
        pass

    def on_comment(self, text, bar_index):
        pass

    def on_deinit(self, final_equity):
        pass
