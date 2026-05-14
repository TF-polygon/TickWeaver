"""Compact custom logger - stdlib logging based, zero external deps.

Format:
    2026-05-13 17:10:00 [info] [ccxt_loader] cache_hit path=... rows=4368
                              ^cyan          ^event    ^key=value pairs

The `component` bound via get_logger("name") appears as a cyan-bracketed
prefix in front of the event name. Keyword args to .info()/.warning()/etc.
become key=value pairs after the event.

Self-contained: no structlog dependency. The logger never freezes its
config because the formatter runs at log-call time, after configure_logging
has registered the handler on the root logger.
"""

from __future__ import annotations

import logging
import sys
from typing import Any


# ─── ANSI escape codes ────────────────────────────────────────
_CYAN = "\033[36m"
_GRAY = "\033[37m"
_GREEN = "\033[32m"
_YELLOW = "\033[33m"
_RED = "\033[31m"
_RESET = "\033[0m"

_LEVEL_COLORS = {
    "DEBUG": _GRAY,
    "INFO": _GREEN,
    "WARNING": _YELLOW,
    "ERROR": _RED,
    "CRITICAL": _RED,
}


def _format_value(v: Any) -> str:
    """Render a value for the key=value tail. Strings are unquoted for compactness."""
    if isinstance(v, str):
        return v
    return str(v)


class _CompactFormatter(logging.Formatter):
    """Format: '<ts> [<level>] [<component>] <event> k1=v1 k2=v2 ...'"""

    def format(self, record: logging.LogRecord) -> str:
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        level = record.levelname.lower()
        level_colored = f"{_LEVEL_COLORS.get(record.levelname, '')}{level}{_RESET}"

        # Extras passed via extra={"_tw_extras": {...}} from _LoggerAdapter
        extras = getattr(record, "_tw_extras", None)
        if not isinstance(extras, dict):
            extras = {}
        component = extras.pop("_tw_component", None)

        event = record.getMessage()
        kv = " ".join(f"{k}={_format_value(v)}" for k, v in extras.items())

        prefix = f"{_CYAN}[{component}]{_RESET} " if component else ""
        line = f"{ts} [{level_colored}] {prefix}{event}"
        if kv:
            line += "  " + kv
        return line


def configure_logging(level: str = "INFO") -> None:
    """Install the compact formatter on the root logger. Idempotent.

    Removes pre-existing root handlers so structlog or basicConfig leftovers
    do not interleave with our output.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_CompactFormatter())

    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(log_level)


class _LoggerAdapter:
    """Thin wrapper around stdlib Logger.

    - Binds a component name at construction (shown as cyan prefix)
    - Accepts arbitrary kwargs on .info/.warning/etc. which become k=v tail

    All work happens at log-call time, so even if the adapter is created at
    module load (before configure_logging), the formatter takes effect once
    configure_logging has been called.
    """

    def __init__(self, name: str | None = None) -> None:
        self._logger = logging.getLogger("tickweaver")
        self._component = name

    def _log(self, level: int, event: str, **kwargs: Any) -> None:
        extras = dict(kwargs)
        if self._component:
            extras["_tw_component"] = self._component
        self._logger.log(level, event, extra={"_tw_extras": extras})

    def debug(self, event: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, **kwargs)

    def info(self, event: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, **kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, **kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, **kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        self._log(logging.CRITICAL, event, **kwargs)


def get_logger(name: str | None = None) -> _LoggerAdapter:
    """Return a logger bound to the optional component name."""
    return _LoggerAdapter(name)
