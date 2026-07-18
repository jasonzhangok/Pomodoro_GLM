"""JSON-backed persistence for the Pomodoro timer.

Storage layout (single file):
    data/data.json

The file is written atomically: we write to a temporary file in the same
directory and then ``os.replace`` it over the real file. This avoids
leaving a half-written file if the process is interrupted.

Import/export is simply a copy of this JSON file. Import validates the
top-level schema (``settings`` / ``tasks`` / ``records`` keys and the
expected field types); invalid data is rejected with a ``ValueError``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from core.models import PomodoroRecord, Settings, Task


# Resolve paths relative to the project root (one level up from data/).
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_SETTINGS_PATH = _PROJECT_ROOT / "data" / "default_settings.json"
_DATA_PATH = _PROJECT_ROOT / "data" / "data.json"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

_REQUIRED_TASK_FIELDS = {"id", "title", "estimated_pomodoros", "actual_pomodoros", "status", "created_at"}
_REQUIRED_RECORD_FIELDS = {"id", "task_id", "phase", "started_at", "ended_at", "completed"}
_REQUIRED_SETTINGS_FIELDS = {
    "focus_minutes", "short_break_minutes", "long_break_minutes",
    "pomodoros_before_long_break", "auto_start_next", "display_mode",
}


def _validate_schema(data: dict) -> None:
    """Raise ValueError if the data dict is not a valid store document.

    Note: ``task_type``, ``task_date``, and ``completed_at`` are optional
    on disk to preserve backwards compatibility with tasks created before
    those fields existed. :meth:`Task.from_dict` fills in defaults.
    """
    if not isinstance(data, dict):
        raise ValueError("Top-level JSON must be an object.")

    for key in ("settings", "tasks", "records"):
        if key not in data:
            raise ValueError(f"Missing required key: '{key}'")

    settings = data["settings"]
    if not isinstance(settings, dict):
        raise ValueError("'settings' must be an object.")
    for f in _REQUIRED_SETTINGS_FIELDS:
        if f not in settings:
            raise ValueError(f"Missing setting: '{f}'")

    tasks = data["tasks"]
    if not isinstance(tasks, list):
        raise ValueError("'tasks' must be a list.")
    for i, t in enumerate(tasks):
        if not isinstance(t, dict):
            raise ValueError(f"tasks[{i}] must be an object.")
        missing = _REQUIRED_TASK_FIELDS - set(t.keys())
        if missing:
            raise ValueError(f"tasks[{i}] missing fields: {missing}")

    records = data["records"]
    if not isinstance(records, list):
        raise ValueError("'records' must be a list.")
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            raise ValueError(f"records[{i}] must be an object.")
        missing = _REQUIRED_RECORD_FIELDS - set(r.keys())
        if missing:
            raise ValueError(f"records[{i}] missing fields: {missing}")


# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

def _load_default_settings() -> dict:
    if _DEFAULT_SETTINGS_PATH.exists():
        with open(_DEFAULT_SETTINGS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    # Fallback if the bundled default file is missing.
    return {
        "focus_minutes": 25,
        "short_break_minutes": 5,
        "long_break_minutes": 15,
        "pomodoros_before_long_break": 4,
        "auto_start_next": False,
        "display_mode": "mmss",
    }


def _empty_document() -> dict:
    return {
        "settings": _load_default_settings(),
        "tasks": [],
        "records": [],
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class Store:
    """High-level read/write access to the JSON data file.

    The store loads the entire document into memory on first access and
    keeps it cached. Mutating methods (add_task, update_task, etc.) update
    the cache and persist atomically to disk.
    """

    def __init__(self, data_path: Optional[Path] = None):
        self.data_path = Path(data_path) if data_path else _DATA_PATH
        self._doc: Optional[dict] = None

    # ------------------------------------------------------------------
    # loading
    # ------------------------------------------------------------------
    def load(self) -> dict:
        """Load the data document, creating a default one if absent."""
        if self._doc is not None:
            return self._doc
        if not self.data_path.exists():
            self._doc = _empty_document()
            self._save_raw(self._doc)
            return self._doc
        with open(self.data_path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        _validate_schema(doc)
        self._doc = doc
        return doc

    def reload(self) -> dict:
        """Force a fresh read from disk (discards cached state)."""
        self._doc = None
        return self.load()

    # ------------------------------------------------------------------
    # settings
    # ------------------------------------------------------------------
    def get_settings(self) -> Settings:
        doc = self.load()
        return Settings.from_dict(doc["settings"])

    def save_settings(self, settings: Settings) -> None:
        doc = self.load()
        doc["settings"] = settings.to_dict()
        self._save_raw(doc)
        self._doc = doc

    # ------------------------------------------------------------------
    # tasks
    # ------------------------------------------------------------------
    def get_tasks(self) -> list[Task]:
        doc = self.load()
        return [Task.from_dict(t) for t in doc["tasks"]]

    def add_task(self, task: Task) -> None:
        doc = self.load()
        doc["tasks"].append(task.to_dict())
        self._save_raw(doc)
        self._doc = doc

    def update_task(self, task: Task) -> None:
        doc = self.load()
        for i, t in enumerate(doc["tasks"]):
            if t["id"] == task.id:
                doc["tasks"][i] = task.to_dict()
                self._save_raw(doc)
                self._doc = doc
                return
        raise ValueError(f"Task not found: {task.id}")

    def delete_task(self, task_id: str) -> None:
        doc = self.load()
        doc["tasks"] = [t for t in doc["tasks"] if t["id"] != task_id]
        self._save_raw(doc)
        self._doc = doc

    # ------------------------------------------------------------------
    # records
    # ------------------------------------------------------------------
    def get_records(self) -> list[PomodoroRecord]:
        doc = self.load()
        return [PomodoroRecord.from_dict(r) for r in doc["records"]]

    def add_record(self, record: PomodoroRecord) -> None:
        doc = self.load()
        doc["records"].append(record.to_dict())
        self._save_raw(doc)
        self._doc = doc

    # ------------------------------------------------------------------
    # import / export
    # ------------------------------------------------------------------
    def export_to(self, path: Path) -> None:
        """Export the current document to an arbitrary path."""
        doc = self.load()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)

    def import_from(self, path: Path) -> None:
        """Import a document from an arbitrary path, replacing current data.

        Validates schema before committing. On success, the in-memory cache
        is replaced and the data file is overwritten atomically.
        """
        with open(path, "r", encoding="utf-8") as f:
            doc = json.load(f)
        _validate_schema(doc)
        self._save_raw(doc)
        self._doc = doc

    # ------------------------------------------------------------------
    # internal save
    # ------------------------------------------------------------------
    def _save_raw(self, doc: dict) -> None:
        """Write the document atomically to disk."""
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.data_path.with_suffix(".json.tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.data_path)
