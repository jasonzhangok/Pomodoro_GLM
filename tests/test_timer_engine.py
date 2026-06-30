"""Unit tests for the pure-logic TimerEngine and PhaseStateMachine.

Run:
    pytest tests/test_timer_engine.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Ensure project root on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.models import Settings
from core.phases import Phase, PhaseStateMachine
from core.timer_engine import TimerEngine
import core.timer_engine as _engine_mod


# ---------------------------------------------------------------------------
# PhaseStateMachine tests
# ---------------------------------------------------------------------------

class TestPhaseStateMachine:
    def _make(self, **overrides) -> PhaseStateMachine:
        defaults = dict(
            focus_minutes=25,
            short_break_minutes=5,
            long_break_minutes=15,
            pomodoros_before_long_break=4,
        )
        defaults.update(overrides)
        return PhaseStateMachine(Settings(**defaults))

    def test_starts_in_focus(self):
        sm = self._make()
        assert sm.current_phase == Phase.FOCUS
        assert sm.completed_focus_in_cycle == 0

    def test_focus_to_short_break(self):
        sm = self._make()
        # After 1st focus -> short break
        assert sm.next_phase() == Phase.SHORT_BREAK
        sm.advance()
        assert sm.current_phase == Phase.SHORT_BREAK
        assert sm.completed_focus_in_cycle == 1

    def test_full_cycle(self):
        sm = self._make()
        # 4 focus sessions, each followed by a break.
        # Focus 1 -> short break
        sm.advance()  # focus -> short break, count=1
        assert sm.current_phase == Phase.SHORT_BREAK
        sm.advance()  # short break -> focus
        assert sm.current_phase == Phase.FOCUS
        sm.advance()  # focus -> short break, count=2
        assert sm.current_phase == Phase.SHORT_BREAK
        sm.advance()  # -> focus
        sm.advance()  # focus -> short break, count=3
        assert sm.current_phase == Phase.SHORT_BREAK
        sm.advance()  # -> focus
        # 4th focus -> long break
        sm.advance()
        assert sm.current_phase == Phase.LONG_BREAK
        assert sm.completed_focus_in_cycle == 4
        # Long break -> focus, cycle resets
        sm.advance()
        assert sm.current_phase == Phase.FOCUS
        assert sm.completed_focus_in_cycle == 0

    def test_long_break_after_configured_count(self):
        sm = self._make(pomodoros_before_long_break=2)
        sm.advance()  # focus1 -> short break
        sm.advance()  # short -> focus2
        sm.advance()  # focus2 -> long break (since N=2)
        assert sm.current_phase == Phase.LONG_BREAK

    def test_reset(self):
        sm = self._make()
        sm.advance()
        sm.advance()
        sm.reset()
        assert sm.current_phase == Phase.FOCUS
        assert sm.completed_focus_in_cycle == 0

    def test_duration_for_each_phase(self):
        sm = self._make()
        assert sm.duration_for(Phase.FOCUS) == 25 * 60
        assert sm.duration_for(Phase.SHORT_BREAK) == 5 * 60
        assert sm.duration_for(Phase.LONG_BREAK) == 15 * 60


# ---------------------------------------------------------------------------
# TimerEngine tests
# ---------------------------------------------------------------------------

class TestTimerEngine:
    def _make(self, **overrides) -> TimerEngine:
        defaults = dict(
            focus_minutes=25,
            short_break_minutes=5,
            long_break_minutes=15,
            pomodoros_before_long_break=4,
            auto_start_next=False,
            display_mode="mmss",
        )
        defaults.update(overrides)
        return TimerEngine(settings=Settings(**defaults))

    def test_initial_state(self):
        eng = self._make()
        assert eng.running is False
        assert eng.remaining_seconds == 25 * 60
        assert eng.current_phase == Phase.FOCUS

    def test_start_sets_running(self):
        eng = self._make()
        eng.start()
        assert eng.running is True
        assert eng.end_timestamp is not None

    def test_pause_freezes_remaining(self):
        eng = self._make(focus_minutes=1)  # 60s
        eng.start()
        # Force the remaining to a known value by pausing immediately.
        eng.pause()
        assert eng.running is False
        assert eng.remaining_seconds <= 60

    def test_resume_restarts(self):
        eng = self._make(focus_minutes=1)
        eng.start()
        eng.pause()
        eng.resume()
        assert eng.running is True

    def test_reset_restores_full_duration(self):
        eng = self._make(focus_minutes=1)
        eng.start()
        eng.reset()
        assert eng.running is False
        assert eng.remaining_seconds == 60

    def test_skip_advances_phase(self):
        eng = self._make()
        assert eng.current_phase == Phase.FOCUS
        eng.skip()
        assert eng.current_phase == Phase.SHORT_BREAK
        eng.skip()
        assert eng.current_phase == Phase.FOCUS

    def test_tick_decrements_remaining(self):
        eng = self._make(focus_minutes=1)  # 60s
        # Patch time.time so start() sets a deterministic end_timestamp.
        with patch.object(_engine_mod.time, "time", return_value=1000.0):
            eng.start()
        assert eng.end_timestamp == 1060.0
        # Simulate 1 second elapsed: now is 1001, end is 1060 -> remaining 59.
        with patch.object(_engine_mod.time, "time", return_value=1001.0):
            eng.tick()
        assert eng.remaining_seconds == 59

    def test_tick_completes_focus_and_advances_to_short_break(self):
        eng = self._make(focus_minutes=1, short_break_minutes=2)
        eng.start()
        # Force completion: set end_timestamp to the past.
        eng.end_timestamp = 0
        eng.tick()
        assert eng.current_phase == Phase.SHORT_BREAK
        assert eng.remaining_seconds == 2 * 60

    def test_focus_completed_callback_fires(self):
        calls = []
        eng = self._make(focus_minutes=1)
        eng.on_focus_completed = lambda task_id: calls.append(task_id)
        eng.bind_task("task-123")
        eng.start()
        eng.end_timestamp = 0
        eng.tick()
        assert calls == ["task-123"]

    def test_phase_change_callback_fires(self):
        seen = []
        eng = self._make(focus_minutes=1)
        eng.on_phase_change = lambda phase, dur: seen.append((phase, dur))
        eng.start()
        eng.end_timestamp = 0
        eng.tick()
        # Should have fired with the new phase (short break)
        assert any(p == Phase.SHORT_BREAK for p, _ in seen)

    def test_auto_start_next_advances_and_keeps_running(self):
        eng = self._make(focus_minutes=1, short_break_minutes=2, auto_start_next=True)
        eng.start()
        eng.end_timestamp = 0
        eng.tick()
        assert eng.current_phase == Phase.SHORT_BREAK
        assert eng.running is True

    def test_bind_task(self):
        eng = self._make()
        eng.bind_task("abc")
        assert eng.current_task_id == "abc"
        eng.bind_task(None)
        assert eng.current_task_id is None

    def test_full_cycle_engine(self):
        """Verify a full 4-focus cycle ends in long break then resets."""
        eng = self._make(
            focus_minutes=1,
            short_break_minutes=1,
            long_break_minutes=1,
            pomodoros_before_long_break=4,
        )
        # Focus 1 -> short break
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.SHORT_BREAK
        # Short break -> focus 2
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.FOCUS
        # Focus 2 -> short break
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.SHORT_BREAK
        # -> focus 3
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.FOCUS
        # Focus 3 -> short break
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.SHORT_BREAK
        # -> focus 4
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.FOCUS
        # Focus 4 -> long break
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.LONG_BREAK
        # Long break -> focus, cycle resets
        eng.start(); eng.end_timestamp = 0; eng.tick()
        assert eng.current_phase == Phase.FOCUS
