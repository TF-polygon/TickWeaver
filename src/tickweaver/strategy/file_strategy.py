"""FileStrategy — `.py` 동적 로드 + JSON 페어링 + 모듈 globals 주입.

D8 / M6.4. 사용자가 `strategies/my_alpha.py` 를 작성하면, 본 클래스가:
1. 모듈을 동적으로 import 하고
2. `<my_alpha>.json` 이 있으면 ParamsView 로 페어링
3. 모듈 globals 에 api / params / context 주입
4. on_init / on_bar / on_tick / on_fill / on_deinit 디스패치
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

from tickweaver.core.exceptions import StrategyError
from tickweaver.core.types import Fill, OHLCBar, StrategyContext, Tick
from tickweaver.strategy.api import ParamsView, StrategyAPI


class FileStrategy:
    """ABC 상속 안 함 — 어댑터로만 동작 (registry 모드 와 공존)."""

    def __init__(self, path: str | Path, params_path: str | Path | None = None) -> None:
        self.path = Path(path).resolve()
        if not self.path.exists():
            raise StrategyError(f"strategy file not found: {self.path}")
        self._params_path = self._resolve_params_path(params_path)
        self._module: ModuleType | None = None
        self._params: ParamsView | None = None

    @staticmethod
    def _resolve_params_path(params_path: str | Path | None) -> Path | None:
        if params_path is not None:
            p = Path(params_path)
            if not p.exists():
                raise StrategyError(f"params file not found: {p}")
            return p
        return None

    def _auto_pair_params(self, strategy_path: Path) -> Path | None:
        candidate = strategy_path.with_suffix(".json")
        return candidate if candidate.exists() else None

    def load(self, api: StrategyAPI, context: StrategyContext) -> None:
        """모듈 import + globals 주입. on_init 호출은 별도."""
        spec = importlib.util.spec_from_file_location(
            f"_user_strategy_{self.path.stem}", self.path
        )
        if spec is None or spec.loader is None:
            raise StrategyError(f"cannot import strategy: {self.path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        params_path = self._params_path or self._auto_pair_params(self.path)
        params_data: dict[str, Any] = {}
        if params_path is not None:
            with open(params_path, encoding="utf-8") as f:
                raw = json.load(f) or {}
            params_data = {k: v for k, v in raw.items() if not k.startswith("_")}
        params = ParamsView(params_data)

        # 모듈 globals 에 주입
        module.api = api  # type: ignore[attr-defined]
        module.params = params  # type: ignore[attr-defined]
        module.context = context  # type: ignore[attr-defined]

        # 사용자 모듈에서 자주 쓰는 enums 도 주입 (편의)
        from tickweaver.core.types import (  # local import 로 circular 회피
            OrderType,
            PositionSide,
            Side,
        )

        module.Side = Side  # type: ignore[attr-defined]
        module.OrderType = OrderType  # type: ignore[attr-defined]
        module.PositionSide = PositionSide  # type: ignore[attr-defined]

        self._module = module
        self._params = params

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
        except Exception as e:  # 사용자 코드 에러는 명확히 wrap
            raise StrategyError(f"error in {self.path.name}::{name}: {e}") from e
