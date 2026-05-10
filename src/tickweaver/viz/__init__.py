"""tickweaver visualization (verbose mode).

V7 (Headless friendly): GUI deps (PyQt6, pyqtgraph, finplot) are lazy-imported.
The core hook + recorder work without any GUI library installed.
"""

from tickweaver.viz.events import CommentEvent
from tickweaver.viz.hook import ChartHook, NullHook
from tickweaver.viz.recorder import EventRecorder

# LiveChartHook imports finplot lazily inside on_deinit; safe to import here.
from tickweaver.viz.live_chart_hook import LiveChartHook

__all__ = [
    "ChartHook",
    "NullHook",
    "EventRecorder",
    "LiveChartHook",
    "CommentEvent",
]
