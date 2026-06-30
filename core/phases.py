"""Phase definitions and the Pomodoro cycle state machine.

The cycle is:  focus -> short_break -> focus -> short_break -> ...
after N focus sessions (N = pomodoros_before_long_break), the next break is
long_break, then the focus counter resets.

This module is pure logic with no Qt dependency, so it can be unit tested
in isolation.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .models import Settings


class Phase(str, Enum):
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


@dataclass
class PhaseInfo:
    """A snapshot of the current cycle position."""
    phase: Phase
    focus_count_in_cycle: int  # number of focus sessions completed in the current cycle (0..N-1)
    duration_seconds: int


class PhaseStateMachine:
    """Tracks the current phase and computes the next phase.

    The state machine is intentionally simple: it only knows the current
    phase and how many focus sessions have been completed in the current
    cycle. Transitions are driven externally by the TimerEngine.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.current_phase: Phase = Phase.FOCUS
        # completed focus sessions in the current cycle
        self.completed_focus_in_cycle: int = 0

    # ------------------------------------------------------------------
    # Duration helpers
    # ------------------------------------------------------------------
    def duration_for(self, phase: Phase) -> int:
        if phase == Phase.FOCUS:
            return self.settings.focus_minutes * 60
        if phase == Phase.SHORT_BREAK:
            return self.settings.short_break_minutes * 60
        if phase == Phase.LONG_BREAK:
            return self.settings.long_break_minutes * 60
        raise ValueError(f"Unknown phase: {phase}")

    def current_duration_seconds(self) -> int:
        return self.duration_for(self.current_phase)

    # ------------------------------------------------------------------
    # Transitions
    # ------------------------------------------------------------------
    def next_phase(self) -> Phase:
        """Compute the next phase after the current one ends.

        Rules:
        - After a focus session: if we just completed the Nth focus, the
          next break is long_break; otherwise short_break.
        - After any break: next is focus.
        """
        if self.current_phase == Phase.FOCUS:
            # We are about to complete a focus session.
            will_complete_n = self.completed_focus_in_cycle + 1
            if will_complete_n >= self.settings.pomodoros_before_long_break:
                return Phase.LONG_BREAK
            return Phase.SHORT_BREAK
        # After break -> focus
        return Phase.FOCUS

    def advance(self) -> Phase:
        """Move to the next phase and update cycle counters.

        Returns the new current phase.
        """
        nxt = self.next_phase()
        if self.current_phase == Phase.FOCUS:
            # Completing a focus session.
            self.completed_focus_in_cycle += 1
            if nxt == Phase.LONG_BREAK:
                # Long break marks end of cycle; reset counter after the break.
                pass
        if self.current_phase == Phase.LONG_BREAK:
            # Exiting a long break resets the cycle.
            self.completed_focus_in_cycle = 0
        self.current_phase = nxt
        return nxt

    def reset(self) -> None:
        """Reset back to the start of a fresh cycle (focus)."""
        self.current_phase = Phase.FOCUS
        self.completed_focus_in_cycle = 0

    def info(self) -> PhaseInfo:
        return PhaseInfo(
            phase=self.current_phase,
            focus_count_in_cycle=self.completed_focus_in_cycle,
            duration_seconds=self.current_duration_seconds(),
        )
