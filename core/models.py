"""Data models for the Pomodoro timer.

All models are plain dataclasses with to_dict / from_dict for JSON
serialization. They hold no Qt dependencies so the core logic stays
testable in isolation.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


def _new_id() -> str:
    return str(uuid.uuid4())


def _now_iso() -> str:
    return datetime.now().isoformat()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@dataclass
class Settings:
    focus_minutes: int = 25
    short_break_minutes: int = 5
    long_break_minutes: int = 15
    pomodoros_before_long_break: int = 4
    auto_start_next: bool = False
    display_mode: str = "mmss"  # "mmss" | "minutes_only"

    def to_dict(self) -> dict:
        return {
            "focus_minutes": self.focus_minutes,
            "short_break_minutes": self.short_break_minutes,
            "long_break_minutes": self.long_break_minutes,
            "pomodoros_before_long_break": self.pomodoros_before_long_break,
            "auto_start_next": self.auto_start_next,
            "display_mode": self.display_mode,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Settings":
        return cls(
            focus_minutes=int(d.get("focus_minutes", 25)),
            short_break_minutes=int(d.get("short_break_minutes", 5)),
            long_break_minutes=int(d.get("long_break_minutes", 15)),
            pomodoros_before_long_break=int(d.get("pomodoros_before_long_break", 4)),
            auto_start_next=bool(d.get("auto_start_next", False)),
            display_mode=str(d.get("display_mode", "mmss")),
        )


# ---------------------------------------------------------------------------
# Task
# ---------------------------------------------------------------------------

@dataclass
class Task:
    title: str
    estimated_pomodoros: int = 1
    actual_pomodoros: int = 0
    status: str = "todo"  # "todo" | "in_progress" | "done"
    id: str = field(default_factory=_new_id)
    created_at: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "estimated_pomodoros": self.estimated_pomodoros,
            "actual_pomodoros": self.actual_pomodoros,
            "status": self.status,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=str(d.get("id", _new_id())),
            title=str(d.get("title", "Untitled")),
            estimated_pomodoros=int(d.get("estimated_pomodoros", 1)),
            actual_pomodoros=int(d.get("actual_pomodoros", 0)),
            status=str(d.get("status", "todo")),
            created_at=str(d.get("created_at", _now_iso())),
        )


# ---------------------------------------------------------------------------
# PomodoroRecord
# ---------------------------------------------------------------------------

@dataclass
class PomodoroRecord:
    started_at: str
    ended_at: str
    phase: str = "focus"  # MVP: always "focus"
    task_id: Optional[str] = None
    completed: bool = True
    id: str = field(default_factory=_new_id)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "phase": self.phase,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "completed": self.completed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PomodoroRecord":
        return cls(
            id=str(d.get("id", _new_id())),
            task_id=d.get("task_id"),
            phase=str(d.get("phase", "focus")),
            started_at=str(d.get("started_at", _now_iso())),
            ended_at=str(d.get("ended_at", _now_iso())),
            completed=bool(d.get("completed", True)),
        )
