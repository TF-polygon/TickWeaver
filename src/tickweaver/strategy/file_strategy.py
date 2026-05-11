"""FileStrategy - dynamic load of strategies/<name>.py + globals injection.

The engine instantiates this and calls load() then the lifecycle hooks
(on_init / on_bar / on_tick / on_fill / on_deinit). Each hook is optional.

The strategy module receives:
  - api      (StrategyAPI)        order / position / account gateway
  - context  (StrategyContext)    symbol / timeframe / bar_index
  - Side / OrderType / PositionSide (convenience enums)

Trading parameters belong INSIDE the .py as module constants. There is no
json side-file anymore; the yaml config under configs/ defines the backtest
environment, and the .py defines the strategy.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

from tickweaver.core.exceptions import StrategyError
from tickweaver.core.types import Fill, OHLCBar, StrategyContext, Tick
from tickweaver.strategy.api import StrategyAPI


class FileStrategy:
    """Adapter for file-based strategies."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise StrategyError(f"strategy file not found: {self.path}")
        self._module: ModuleType | None = None

    def load(self, api: StrategyAPI, context: StrategyContext) -> None:
        """Import the module + inject globals. on_init is called separately."""
        spec = importlib.util.spec_from_file_location(
            f"_user_strategy_{self.path.stem}", self.path
        )
        if spec is None or spec.loader is None:
            raise StrategyError(f"cannot import strategy: {self.path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        module.api = api          # type: ignore[attr-defined]
        module.context = context  # type: ignore[attr-defined]

        # Convenience enums
        from tickweaver.core.types import OrderType, PositionSide, Side

        module.Side = Side                # type: ignore[attr-defined]
        module.OrderType = OrderType      # type: ignore[attr-defined]
        module.PositionSide = PositionSide  # type: ignore[attr-defined]

        self._module = module

    def call_on_init(self) -> None:
        self._call_optional("on_init")

    def call_on_bar(self, bar: OHLCBar) -> None:
        self._call_optional("on_bar", bar)

    def call_on_tick(self, tick: Tick) -> None:
        self._call_optional("on_tick", tick)

    def call_on_fill(self, fill: Fill) -> None:
        self._call_optional("on_fill", fill)

    def call_on_deinit(self) -> None:
        self._call_optional("on_deinit")

    def _call_optional(self, name: str, *args: Any) -> None:
        if self._module is None:
            raise StrategyError("strategy not loaded; call load() first")
        fn = getattr(self._module, name, None)
        if fn is None:
            return
        if not callable(fn):
            raise StrategyError(f"strategy attribute {name!r} is not callable")
        try:
            fn(*args)
        except Exception as e:
            raise StrategyError(f"error in {self.path.name}::{name}: {e}") from e
