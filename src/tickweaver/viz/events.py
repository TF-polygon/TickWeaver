"""Visualization-only event dataclasses."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class CommentEvent:
    """A single api.comment(text) call propagated to the ChartHook."""

    text: str
    bar_index: int
    timestamp: pd.Timestamp | None = None
