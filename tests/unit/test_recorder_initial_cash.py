"""Phase V7 — recorder.initial_cash propagation."""

from __future__ import annotations

from tickweaver.viz.recorder import EventRecorder


def test_recorder_default_initial_cash_is_zero():
    rec = EventRecorder()
    assert rec.initial_cash == 0.0


def test_recorder_initial_cash_is_settable():
    rec = EventRecorder()
    rec.initial_cash = 10_000.0
    assert rec.initial_cash == 10_000.0
