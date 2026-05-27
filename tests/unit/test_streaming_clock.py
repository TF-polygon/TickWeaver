"""streaming-viz unit #4 — playback state machine (pure, headless).

Covers goal §3.A "스트리밍 상태머신":
- Pause → tick consumption stops; Resume → resumes.
- speed change → per-frame consumption rate changes (fractional + high speeds).
- drag ON/OFF → auto-follow flag flips.
"""

from __future__ import annotations

from tickweaver.viz.streaming import StreamClock


# ── pause / resume ─────────────────────────────────────────────────────────
def test_pause_stops_consumption():
    c = StreamClock(speed=1.0)
    c.pause()
    assert c.paused
    assert [c.ticks_this_frame() for _ in range(5)] == [0, 0, 0, 0, 0]


def test_resume_resumes_consumption():
    c = StreamClock(speed=1.0)
    c.pause()
    c.ticks_this_frame()
    c.resume()
    assert not c.paused
    assert c.ticks_this_frame() == 1


def test_toggle_pause_flips_and_reports():
    c = StreamClock()
    assert c.toggle_pause() is True and c.paused
    assert c.toggle_pause() is False and not c.paused


def test_paused_does_not_accumulate_no_resume_burst():
    # speed 1, paused for 5 frames, then resumed → next frame yields 1, not 6
    c = StreamClock(speed=1.0)
    c.pause()
    for _ in range(5):
        c.ticks_this_frame()
    c.resume()
    assert c.ticks_this_frame() == 1


# ── speed ──────────────────────────────────────────────────────────────────
def test_speed_2x_consumes_two_per_frame():
    c = StreamClock(speed=2.0)
    assert [c.ticks_this_frame() for _ in range(3)] == [2, 2, 2]


def test_high_speed_16x():
    c = StreamClock(speed=16.0)
    assert c.ticks_this_frame() == 16


def test_fractional_speed_accumulates():
    # 0.25x → one tick every 4 frames (0,0,0,1 ...)
    c = StreamClock(speed=0.25)
    got = [c.ticks_this_frame() for _ in range(8)]
    assert got == [0, 0, 0, 1, 0, 0, 0, 1]
    assert sum(got) == 2   # 0.25 * 8


def test_speed_change_midstream_takes_effect():
    c = StreamClock(speed=1.0)
    assert c.ticks_this_frame() == 1
    c.set_speed(4.0)
    assert c.speed == 4.0
    assert c.ticks_this_frame() == 4


def test_set_speed_clamps_negative_to_zero():
    c = StreamClock(speed=1.0)
    c.set_speed(-3.0)
    assert c.speed == 0.0
    assert [c.ticks_this_frame() for _ in range(3)] == [0, 0, 0]


# ── drag toggle ↔ auto-follow ──────────────────────────────────────────────
def test_drag_off_means_auto_follow():
    c = StreamClock()
    assert not c.drag_on
    assert c.auto_follow is True


def test_drag_on_disables_auto_follow():
    c = StreamClock()
    c.set_drag(True)
    assert c.drag_on
    assert c.auto_follow is False
    c.set_drag(False)
    assert c.auto_follow is True
