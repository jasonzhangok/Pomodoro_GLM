"""Pure-Python timer engine for the Pomodoro timer.

The engine is deliberately Qt-free so it can be unit tested in isolation.
The host (QTimer) calls :meth:`tick` once per second; the engine computes
the remaining time from an absolute end timestamp to avoid cumulative
drift, and emits callbacks when interesting things happen.

Responsibilities:
- hold current phase and remaining seconds
- start / pause / resume / reset / skip
- drive phase transitions via :class:`PhaseStateMachine`
- record completed focus sessions through callbacks

Callbacks (all optional, all keyword-callable):
- on_tick(remaining_seconds: int)
- on_phase_change(phase: Phase, duration_seconds: int)
- on_focus_completed(task_id: Optional[str])
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from .models import Settings
from .phases import Phase, PhaseStateMachine


@dataclass
class TimerEngine:
    settings: Settings
    state_machine: PhaseStateMachine = field(init=False)
    running: bool = field(init=False, default=False)
    end_timestamp: Optional[float] = field(init=False, default=None)
    remaining_seconds: int = field(init=False, default=0)
    current_task_id: Optional[str] = field(init=False, default=None)
    # start time of the current phase, for record bookkeeping
    phase_started_at: Optional[float] = field(init=False, default=None)

    # callbacks
    on_tick: Optional[Callable[[int], None]] = None
    on_phase_change: Optional[Callable[[Phase, int], None]] = None
    on_focus_completed: Optional[Callable[[Optional[str]], None]] = None

    def __post_init__(self) -> None:
        self.state_machine = PhaseStateMachine(self.settings)
        self.remaining_seconds = self.state_machine.current_duration_seconds()
        self.phase_started_at = time.time()

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------
    def _emit_tick(self) -> None:
        if self.on_tick:
            self.on_tick(self.remaining_seconds)

    def _emit_phase_change(self) -> None:
        if self.on_phase_change:
            self.on_phase_change(
                self.state_machine.current_phase,
                self.state_machine.current_duration_seconds(),
            )

    def _emit_focus_completed(self) -> None:
        if self.on_focus_completed:
            self.on_focus_completed(self.current_task_id)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------
    def start(self) -> None:
        """Start the timer for the current phase (idempotent if running)."""
        if self.running:
            return
        self.running = True
        self.end_timestamp = time.time() + self.remaining_seconds
        self._emit_tick()

    def pause(self) -> None:
        """Pause the timer, freezing the remaining seconds."""
        if not self.running:
            return
        # recompute remaining from the absolute end timestamp
        self.remaining_seconds = max(0, int(self.end_timestamp - time.time()))
        self.running = False
        self.end_timestamp = None
        self._emit_tick()

    def resume(self) -> None:
        """Resume from a paused state. Alias for start()."""
        if self.running:
            return
        self.start()

    def reset(self) -> None:
        """Reset the current phase to its full duration, stopped."""
        self.running = False
        self.end_timestamp = None
        self.remaining_seconds = self.state_machine.current_duration_seconds()
        self.phase_started_at = time.time()
        self._emit_tick()
        self._emit_phase_change()

    def skip(self) -> None:
        """Skip the current phase and advance to the next one.

        If the skipped phase was a focus session, the focus-completed
        callback fires with completed=False semantics handled by the caller
        via record bookkeeping (we only emit on_focus_completed when a
        focus phase actually completes naturally; skips just advance).
        """
        # Just advance the state machine and start the next phase fresh.
        self.state_machine.advance()
        self.running = False
        self.end_timestamp = None
        self.remaining_seconds = self.state_machine.current_duration_seconds()
        self.phase_started_at = time.time()
        self._emit_tick()
        self._emit_phase_change()
        # Honor auto-start setting for the new phase
        if self.settings.auto_start_next:
            self.start()

    def tick(self) -> None:
        """Called once per second by the host timer.

        Computes remaining from the absolute end timestamp to avoid drift.
        If the phase ends, fires the appropriate callbacks and either
        auto-starts the next phase or stops.
        """
        if not self.running:
            return
        now = time.time()
        if self.end_timestamp is None:
            return
        self.remaining_seconds = max(0, int(self.end_timestamp - now))
        self._emit_tick()
        if self.remaining_seconds <= 0:
            self._on_phase_complete()

    # ------------------------------------------------------------------
    # phase completion
    # ------------------------------------------------------------------
    def _on_phase_complete(self) -> None:
        """Handle end-of-phase: record focus if applicable, then advance."""
        phase = self.state_machine.current_phase
        if phase == Phase.FOCUS:
            # A focus session completed naturally.
            self._emit_focus_completed()
        # Advance to next phase
        self.state_machine.advance()
        new_duration = self.state_machine.current_duration_seconds()
        self.remaining_seconds = new_duration
        self.phase_started_at = time.time()
        self._emit_phase_change()
        # Auto-start next phase or stop
        if self.settings.auto_start_next:
            self.running = True
            self.end_timestamp = time.time() + self.remaining_seconds
            self._emit_tick()
        else:
            self.running = False
            self.end_timestamp = None

    # ------------------------------------------------------------------
    # task binding
    # ------------------------------------------------------------------
    def bind_task(self, task_id: Optional[str]) -> None:
        self.current_task_id = task_id

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------
    @property
    def current_phase(self) -> Phase:
        return self.state_machine.current_phase

    def current_duration_seconds(self) -> int:
        return self.state_machine.current_duration_seconds()
