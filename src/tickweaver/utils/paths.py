"""Project path constants.

src/tickweaver/utils/paths.py -> project root is 3 parents up.
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
DATA_DIR: Path = PROJECT_ROOT / "data"
DATA_RAW_DIR: Path = DATA_DIR / "raw"
DATA_PROCESSED_DIR: Path = DATA_DIR / "processed"
TICKS_CACHE_DIR: Path = DATA_DIR / "ticks_cache"
LOGS_DIR: Path = PROJECT_ROOT / "logs"
REPORTS_DIR: Path = PROJECT_ROOT / "reports"
CONFIGS_DIR: Path = PROJECT_ROOT / "configs"
STRATEGIES_DIR: Path = PROJECT_ROOT / "strategies"
DEFAULT_BACKTEST_CONFIG: Path = CONFIGS_DIR / "default.yaml"


def ensure_runtime_dirs() -> None:
    """Create data/, logs/, reports/ dirs needed at runtime."""
    for d in (
        DATA_DIR,
        DATA_RAW_DIR,
        DATA_PROCESSED_DIR,
        TICKS_CACHE_DIR,
        LOGS_DIR,
        REPORTS_DIR,
    ):
        d.mkdir(parents=True, exist_ok=True)


def symbol_to_safe(symbol: str) -> str:
    """BTC/USDT:USDT -> BTC-USDT-USDT (filesystem friendly)."""
    return symbol.replace("/", "-").replace(":", "-")


def _strategies_dir() -> Path:
    """Indirection so tests can monkeypatch STRATEGIES_DIR at runtime."""
    import tickweaver.utils.paths as _self_mod  # late import to read live module attr

    return _self_mod.STRATEGIES_DIR


def resolve_strategy_path(raw):
    """Auto-resolve --strategy argument: strategies/ prefix + auto .py.

    Search order:
      1. Absolute path: use as-is
      2. raw as relative path
      3. raw + .py if missing extension
      4. STRATEGIES_DIR / basename  (only if raw has no path separator)
      5. STRATEGIES_DIR / basename.py

    Examples:
      "rsi_mean_reversion"        -> strategies/rsi_mean_reversion.py
      "rsi_mean_reversion.py"     -> strategies/rsi_mean_reversion.py (or cwd)
      "strategies/rsi.py"         -> strategies/rsi.py
      "/abs/path/x.py"            -> /abs/path/x.py
    """
    raw_path = Path(raw)
    if raw_path.is_absolute():
        if raw_path.exists():
            return raw_path
        raise FileNotFoundError(f"strategy not found: {raw_path}")

    candidates: list[Path] = []
    candidates.append(raw_path)
    if raw_path.suffix != ".py":
        candidates.append(raw_path.with_suffix(".py"))

    raw_str = str(raw_path).replace("\\", "/")
    has_separator = "/" in raw_str
    if not has_separator:
        sdir = _strategies_dir()
        sub = sdir / raw_path.name
        candidates.append(sub)
        if sub.suffix != ".py":
            candidates.append(sub.with_suffix(".py"))

    seen: set[str] = set()
    unique: list[Path] = []
    for c in candidates:
        key = str(c)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    for c in unique:
        if c.exists():
            return c

    raise FileNotFoundError(
        "strategy not found. tried:\n  - "
        + "\n  - ".join(str(c) for c in unique)
        + f"\nhint: place your .py file under {_strategies_dir()}/, "
        "or pass an absolute path."
    )
