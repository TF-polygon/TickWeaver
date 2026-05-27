"""tickweaver visualization (verbose mode).

V7 (Headless friendly): GUI deps (PyQt6, pyqtgraph, finplot) are lazy-imported.
The core hook + recorder work without any GUI library installed.
"""

from tickweaver.viz.events import (
    CommentEvent,
    IndicatorRegistrationEvent,
    IndicatorSampleEvent,
    IndicatorTrack,
)
from tickweaver.viz.hook import ChartHook, NullHook
from tickweaver.viz.recorder import EventRecorder

# LiveChartHook / StreamingChartHook import finplot lazily inside on_deinit;
# safe to import here.
from tickweaver.viz.live_chart_hook import LiveChartHook, StreamingChartHook

__all__ = [
    "ChartHook",
    "NullHook",
    "EventRecorder",
    "LiveChartHook",
    "StreamingChartHook",
    "CommentEvent",
    "IndicatorRegistrationEvent",
    "IndicatorSampleEvent",
    "IndicatorTrack",
]
