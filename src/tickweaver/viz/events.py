"""Visualization-only event dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class CommentEvent:
    """A single api.comment(text) call propagated to the ChartHook."""

    text: str
    bar_index: int
    timestamp: pd.Timestamp | None = None


# Phase 1 (dev/adv_verbose) — Indicator visualization events


@dataclass(frozen=True)
class IndicatorRegistrationEvent:
    """A single api.bind_indicator(...) registration.

    Args:
        name: Unique line name within the recorder (e.g. "EMA 12", "RSI").
              Multi-value indicators (BB, MACD) decompose into multiple
              registrations, one per sub-line (engine concern, not this event's).
        panel: Logical panel id. "price" overlays on the candlestick axis;
               any other string opens (or reuses) a sub-panel row.
        style: Free-form viz hint dict. Keys recognised by live_window
               include "color", "width", "style" (e.g. "--"). Unknown keys
               are silently ignored by the renderer.
    """

    name: str
    panel: str
    style: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndicatorSampleEvent:
    """One indicator value at one bar.

    Args:
        name: Must match a previous IndicatorRegistrationEvent.name. If no
              registration exists, the recorder auto-creates one with default
              panel="price" (api.plot fallback path).
        bar_index: Engine's bar index at the time of sampling.
        timestamp: Bar close timestamp. None is allowed for tests / early
                   samples that have no anchor yet.
        value: Indicator value as a finite float. NaN/None are silently
               accepted but viewers may skip them.
    """

    name: str
    bar_index: int
    timestamp: pd.Timestamp | None
    value: float


@dataclass
class IndicatorTrack:
    """Recorder-side bundle: one registration + accumulated samples.

    Mutable so EventRecorder.on_indicator_sample can append in place. Not
    frozen because the samples list grows during a run.
    """

    registration: IndicatorRegistrationEvent
    samples: list[IndicatorSampleEvent] = field(default_factory=list)
