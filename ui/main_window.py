"""Main window for the Pomodoro timer.

Layout:
    ┌────────────────────────────┐
    │         24:59              │  <- big countdown
    │     专注中 · 写设计文档      │  <- phase + bound task
    │                            │
    │  [▶ 开始] [↻ 重置] [⏭ 跳过] │  <- controls
    │  [⛶ 专注模式]              │
    ├────────────────────────────┤
    │  今日任务          [+ 添加] │
    │  ☐ 写设计文档 1/3 [▶][✏][🗑]│  <- task row
    │  ...                      │
    └────────────────────────────┘

The window owns a single QTimer (250ms) that both ticks the TimerEngine
and refreshes the displayed time. This avoids drift from a separate
1-second timer and keeps the UI smooth.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from PyQt6.QtCore import QEvent, QSize, Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor

from core.models import PomodoroRecord, Task
from core.phases import Phase
from core.timer_engine import TimerEngine
from data.store import Store
from services.notify import notify


# Phase display labels (Chinese)
PHASE_LABELS = {
    Phase.FOCUS: "专注中",
    Phase.SHORT_BREAK: "短休息",
    Phase.LONG_BREAK: "长休息",
}


def _parse_iso(s: str) -> datetime:
    """Parse an ISO timestamp string into a datetime object."""
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.now()


def compute_stats(records: list[PomodoroRecord], settings) -> dict:
    """Compute focus stats over four time windows.

    Returns a dict keyed by window name, each containing:
        - count: number of completed focus sessions
        - minutes: total focus minutes (one session = focus_minutes)
    """
    now = datetime.now()
    focus_minutes = settings.focus_minutes
    windows = {
        "12h": now - timedelta(hours=12),
        "1d": now - timedelta(days=1),
        "3d": now - timedelta(days=3),
        "1w": now - timedelta(weeks=1),
    }
    stats = {k: {"count": 0, "minutes": 0} for k in windows}
    for r in records:
        if not r.completed or r.phase != "focus":
            continue
        started = _parse_iso(r.started_at)
        for key, cutoff in windows.items():
            if started >= cutoff:
                stats[key]["count"] += 1
                stats[key]["minutes"] += focus_minutes
    return stats

# Global QSS stylesheet — modern, macOS-inspired
GLOBAL_QSS = """
QWidget {
    font-family: -apple-system, "PingFang SC", "Helvetica Neue", Arial, sans-serif;
    color: #2c2c2c;
}

QMainWindow, QWidget#MainWindow {
    background-color: #f5f5f7;
}

/* Big countdown number */
QLabel#TimeLabel {
    font-size: 72px;
    font-weight: 300;
    color: #1d1d1f;
    padding: 8px;
}

QLabel#PhaseLabel {
    font-size: 15px;
    color: #86868b;
    padding-bottom: 6px;
}

/* Buttons — modern pill style */
QPushButton {
    background-color: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    padding: 8px 16px;
    font-size: 13px;
    color: #1d1d1f;
}
QPushButton:hover {
    background-color: #f0f0f2;
    border-color: #b0b0b5;
}
QPushButton:pressed {
    background-color: #e5e5ea;
}
QPushButton:disabled {
    color: #c7c7cc;
    background-color: #f5f5f7;
    border-color: #e5e5ea;
}

/* Icon-only buttons (square, no padding so the glyph is visible) */
QPushButton#IconBtn {
    padding: 0;
    font-size: 16px;
}
QPushButton#IconBtn:hover {
    background-color: #f0f0f2;
    border-color: #b0b0b5;
}

/* Primary action button (开始) */
QPushButton#PrimaryBtn {
    background-color: #ff3b30;
    border: none;
    color: white;
    font-weight: 500;
}
QPushButton#PrimaryBtn:hover {
    background-color: #ff453a;
}
QPushButton#PrimaryBtn:pressed {
    background-color: #e0342a;
}

/* Ghost / text buttons */
QPushButton#GhostBtn {
    background: transparent;
    border: none;
    color: #86868b;
}
QPushButton#GhostBtn:hover {
    color: #1d1d1f;
}

/* Custom stepper */
QFrame#Stepper {
    border: 1px solid #d2d2d7;
    border-radius: 8px;
    background-color: #ffffff;
}
QPushButton#StepperBtn {
    border: none;
    border-radius: 8px;
    font-size: 18px;
    font-weight: 600;
    padding: 0;
    color: #1d1d1f;
}
QPushButton#StepperBtn:hover {
    background-color: #f0f0f2;
}
QPushButton#StepperBtn:pressed {
    background-color: #e5e5ea;
}
QPushButton#StepperBtn:disabled {
    color: #c7c7cc;
    background-color: #f5f5f7;
}
QLineEdit#StepperValue {
    border: none;
    border-left: 1px solid #e5e5ea;
    border-right: 1px solid #e5e5ea;
    border-radius: 0;
    font-size: 13px;
    font-weight: 500;
    color: #1d1d1f;
    background-color: #ffffff;
    padding: 0 4px;
}
QLineEdit#StepperValue:focus {
    background-color: #f5f5f7;
}

/* Task row card */
QFrame#TaskRow {
    background-color: #ffffff;
    border: 1px solid #e5e5ea;
    border-radius: 10px;
}
QFrame#TaskRow:hover {
    border-color: #d2d2d7;
}

QLabel#TaskTitle {
    font-size: 14px;
    color: #1d1d1f;
}
QLabel#TaskCount {
    font-size: 12px;
    color: #86868b;
}

/* Section header */
QLabel#SectionHeader {
    font-size: 17px;
    font-weight: 600;
    color: #1d1d1f;
}

/* Scroll area */
QScrollArea {
    background: transparent;
    border: none;
}
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}
QScrollBar::handle:vertical {
    background: #d2d2d7;
    border-radius: 4px;
    min-height: 30px;
}
QScrollBar::handle:vertical:hover {
    background: #b0b0b5;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* Line edit / spin box inputs */
QLineEdit, QSpinBox {
    background-color: #ffffff;
    border: 1px solid #d2d2d7;
    border-radius: 6px;
    padding: 6px 8px;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus {
    border: 1px solid #007aff;
}

/* Dialogs */
QDialog {
    background-color: #f5f5f7;
}
"""


def _phase_color(phase: Phase) -> str:
    """Return a hex color for the given phase, used for accents."""
    if phase == Phase.FOCUS:
        return "#ff3b30"
    if phase == Phase.SHORT_BREAK:
        return "#34c759"
    return "#5856d6"  # long break


class TaskRowWidget(QFrame):
    """A single task row: checkbox, title, pomodoro count, action buttons."""

    def __init__(self, task: Task, on_start, on_edit, on_delete, on_toggle_done, parent=None):
        super().__init__(parent)
        self.task = task
        self.setObjectName("TaskRow")
        # Grow/shrink with the parent; never exceed the viewport width.
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Done toggle button (checkbox-like) — fixed, never compressed.
        self.done_btn = QPushButton("☐")
        self.done_btn.setObjectName("IconBtn")
        self.done_btn.setFixedSize(28, 28)
        self.done_btn.clicked.connect(lambda: on_toggle_done(task))
        layout.addWidget(self.done_btn)

        # Title + count — flex middle, takes remaining space.
        info = QVBoxLayout()
        info.setSpacing(2)
        self.title_label = QLabel(task.title)
        self.title_label.setObjectName("TaskTitle")
        # Allow wrapping + eliding so long titles never push buttons out.
        self.title_label.setWordWrap(True)
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)
        count_text = f"🍅 {task.actual_pomodoros}/{task.estimated_pomodoros}"
        self.count_label = QLabel(count_text)
        self.count_label.setObjectName("TaskCount")
        info.addWidget(self.title_label)
        info.addWidget(self.count_label)
        layout.addLayout(info, stretch=1)

        # Action buttons — fixed, never compressed.
        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setObjectName("IconBtn")
        self.start_btn.setFixedSize(64, 32)
        self.start_btn.clicked.connect(lambda: on_start(task))
        layout.addWidget(self.start_btn)

        self.edit_btn = QPushButton("✎ 编辑")
        self.edit_btn.setObjectName("IconBtn")
        self.edit_btn.setFixedSize(64, 32)
        self.edit_btn.clicked.connect(lambda: on_edit(task))
        layout.addWidget(self.edit_btn)

        self.del_btn = QPushButton("✕")
        self.del_btn.setObjectName("IconBtn")
        self.del_btn.setFixedSize(32, 32)
        self.del_btn.setStyleSheet("color: #ff3b30;")
        self.del_btn.clicked.connect(lambda: on_delete(task))
        layout.addWidget(self.del_btn)

        self._refresh_state()

    def _refresh_state(self):
        done = self.task.status == "done"
        if done:
            self.done_btn.setText("☑")
            self.title_label.setStyleSheet("color: #c7c7cc; text-decoration: line-through;")
        else:
            self.done_btn.setText("☐")
            self.title_label.setStyleSheet("")

    def refresh(self, task: Task):
        self.task = task
        self.title_label.setText(task.title)
        self.count_label.setText(f"🍅 {task.actual_pomodoros}/{task.estimated_pomodoros}")
        self._refresh_state()


class Stepper(QFrame):
    """Custom stepper: [−] [🍅 × N] [＋] with inline-editable count."""

    def __init__(self, minimum=1, maximum=20, parent=None):
        super().__init__(parent)
        self.setObjectName("Stepper")
        self._min = minimum
        self._max = maximum
        self._value = minimum
        self._editing = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.minus_btn = QPushButton("−")
        self.minus_btn.setObjectName("StepperBtn")
        self.minus_btn.setFixedSize(32, 32)
        self.minus_btn.clicked.connect(self._decrement)
        layout.addWidget(self.minus_btn)

        self.count_label = QLineEdit()
        self.count_label.setObjectName("StepperValue")
        self.count_label.setReadOnly(False)
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.count_label.setFixedHeight(32)
        self.count_label.textChanged.connect(self._on_text_changed)
        self.count_label.editingFinished.connect(self._on_editing_finished)
        layout.addWidget(self.count_label)

        self.plus_btn = QPushButton("＋")
        self.plus_btn.setObjectName("StepperBtn")
        self.plus_btn.setFixedSize(32, 32)
        self.plus_btn.clicked.connect(self._increment)
        layout.addWidget(self.plus_btn)

        self._refresh()

    def value(self) -> int:
        return self._value

    def setValue(self, val: int) -> None:
        self._value = max(self._min, min(self._max, val))
        self._refresh()

    def _increment(self):
        if self._value < self._max:
            self._value += 1
            self._refresh()

    def _decrement(self):
        if self._value > self._min:
            self._value -= 1
            self._refresh()

    def _on_text_changed(self, text: str):
        """Track the numeric portion but don't reformat while editing.

        If the number exceeds the max, clamp it immediately and reformat.
        """
        digits = text.replace("🍅", "").replace("×", "").replace(" ", "").strip()
        if digits.isdigit():
            parsed = int(digits)
            if parsed > self._max:
                # Clamp immediately and reformat so user sees the cap.
                self._value = self._max
                self._refresh()
            elif parsed >= self._min:
                self._value = parsed
                # Update button enabled states while typing.
                self._update_button_states()

    def _on_editing_finished(self):
        """Reformat display when the user finishes editing (focus lost / Enter)."""
        self._refresh()

    def _update_button_states(self):
        """Enable/disable +/− buttons based on current value."""
        self.minus_btn.setEnabled(self._value > self._min)
        self.plus_btn.setEnabled(self._value < self._max)
        if not self.minus_btn.isEnabled():
            self.minus_btn.setStyleSheet("color: #c7c7cc; background-color: #f5f5f7;")
        else:
            self.minus_btn.setStyleSheet("")
        if not self.plus_btn.isEnabled():
            self.plus_btn.setStyleSheet("color: #c7c7cc; background-color: #f5f5f7;")
        else:
            self.plus_btn.setStyleSheet("")

    def _refresh(self):
        self.count_label.blockSignals(True)
        self.count_label.setText(f"🍅 × {self._value}")
        self.count_label.blockSignals(False)
        self._update_button_states()


class AddTaskDialog(QFrame):
    """Inline add-task form: title input + custom stepper + add button."""

    def __init__(self, on_add, parent=None):
        super().__init__(parent)
        self.setObjectName("AddTaskForm")
        self.on_add = on_add

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        layout.setSpacing(8)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("新任务标题…")
        self.title_input.setFixedHeight(32)
        self.title_input.returnPressed.connect(self._submit)
        layout.addWidget(self.title_input, stretch=1)

        self.stepper = Stepper(minimum=1, maximum=20)
        layout.addWidget(self.stepper)

        self.add_btn = QPushButton("+ 添加")
        self.add_btn.setObjectName("PrimaryBtn")
        self.add_btn.setFixedHeight(32)
        self.add_btn.clicked.connect(self._submit)
        layout.addWidget(self.add_btn)

    def _submit(self):
        title = self.title_input.text().strip()
        if not title:
            return
        est = self.stepper.value()
        self.on_add(title, est)
        self.title_input.clear()
        self.stepper.setValue(1)


class EditTaskDialog(QDialog):
    """Modal dialog for editing a task's title and estimated pomodoros."""

    def __init__(self, task: Task, on_save, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑任务")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(340)
        self.task = task
        self.on_save = on_save

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        title = QLabel("编辑任务")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        layout.addWidget(title)

        layout.addWidget(QLabel("任务标题:"))
        self.title_input = QLineEdit(task.title)
        layout.addWidget(self.title_input)

        layout.addWidget(QLabel("预估番茄数:"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 99)
        self.spin.setValue(task.estimated_pomodoros)
        self.spin.setPrefix("🍅×")
        layout.addWidget(self.spin)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setObjectName("PrimaryBtn")
        save_btn.clicked.connect(self._save)
        btn_layout.addWidget(save_btn)

        layout.addLayout(btn_layout)

    def _save(self):
        new_title = self.title_input.text().strip()
        if not new_title:
            return
        self.task.title = new_title
        self.task.estimated_pomodoros = self.spin.value()
        self.on_save(self.task)
        self.accept()


class FloatingMiniWindow(QWidget):
    """A small, draggable, always-on-top window showing the countdown.

    Frameless + translucent-background so we can draw a rounded card.
    Mouse drag is handled manually via mousePress/mouseMove events so the
    window has no title bar but is still freely movable.
    """

    def __init__(self, get_remaining_text, get_phase_label, get_phase, on_toggle_back, on_toggle_start_pause, parent=None):
        super().__init__(parent)
        self.setWindowTitle("番茄钟 · 悬浮窗")
        # Frameless + always-on-top. NOTE: do NOT add Qt.WindowType.Tool —
        # on macOS that makes the window a panel that auto-hides when the
        # application loses focus (e.g. clicking another app's window).
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(180, 96)

        # Track drag offset
        self._drag_offset = None
        self._on_toggle_back = on_toggle_back
        self._on_toggle_start_pause = on_toggle_start_pause

        # Root container (the visible rounded card)
        self._container = QFrame(self)
        self._container.setStyleSheet(
            "QFrame { background-color: rgba(29,29,31,0.78);"
            " border-radius: 16px; }"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._container)

        layout = QVBoxLayout(self._container)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(4)

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            "color: #ffffff; font-size: 34px; font-weight: 700;"
        )
        layout.addWidget(self.time_label)

        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("color: #e5e5ea; font-size: 12px; font-weight: 500;")
        layout.addWidget(self.phase_label)

        self._get_remaining_text = get_remaining_text
        self._get_phase_label = get_phase_label
        self._get_phase = get_phase

    # ------------------------------------------------------------------
    # dragging
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        event.accept()

    def keyPressEvent(self, event):
        # F toggles back to the main window; Esc just closes the floating window
        if event.key() == Qt.Key.Key_F:
            if self._on_toggle_back is not None:
                self._on_toggle_back()
            return
        # Space toggles start/pause
        if event.key() == Qt.Key.Key_Space:
            if self._on_toggle_start_pause is not None:
                self._on_toggle_start_pause()
            return
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)

    def refresh(self):
        self.time_label.setText(self._get_remaining_text())
        self.phase_label.setText(self._get_phase_label())


class FocusModeOverlay(QWidget):
    """Borderless fullscreen overlay showing only the big countdown."""

    def __init__(self, get_remaining_text, get_phase_label, phase_color="#ff3b30", parent=None):
        super().__init__(parent)
        self.setWindowTitle("专注模式")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("background-color: #1d1d1f;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet(
            "color: #ffffff; font-size: 200px; font-weight: 200;"
        )
        layout.addWidget(self.time_label)

        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("color: #86868b; font-size: 28px;")
        layout.addWidget(self.phase_label)

        self._get_remaining_text = get_remaining_text
        self._get_phase_label = get_phase_label

    def refresh(self):
        self.time_label.setText(self._get_remaining_text())
        self.phase_label.setText(self._get_phase_label())

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class MainWindow(QWidget):
    """The main application window: timer + task list."""

    def __init__(self, engine: TimerEngine, store: Store):
        super().__init__()
        self.setObjectName("MainWindow")
        self.engine = engine
        self.store = store
        self.current_task_id: Optional[str] = None
        self.focus_overlay: Optional[FocusModeOverlay] = None
        self.floating_window: Optional[FloatingMiniWindow] = None
        self._previous_phase: Optional[Phase] = None
        self.tray = None  # set by app.py after tray setup

        # Apply global stylesheet
        self.setStyleSheet(GLOBAL_QSS)

        # Wire engine callbacks
        self.engine.on_tick = self._on_engine_tick
        self.engine.on_phase_change = self._on_engine_phase_change
        self.engine.on_focus_completed = self._on_engine_focus_completed

        self.setWindowTitle("番茄钟")
        self.resize(440, 680)
        self._build_ui()
        self._refresh_task_list()

        # Single refresh timer: ticks the engine and updates the display.
        # 250ms interval keeps the countdown smooth without excessive CPU.
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(250)
        self.refresh_timer.timeout.connect(self._on_refresh_timer)
        self.refresh_timer.start()

        # Initial display
        self._refresh_time_display()
        self._refresh_phase_label()
        self._refresh_controls()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 24)
        root.setSpacing(8)

        # --- Timer block ---
        self.time_label = QLabel()
        self.time_label.setObjectName("TimeLabel")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.time_label)

        self.phase_label = QLabel()
        self.phase_label.setObjectName("PhaseLabel")
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.phase_label)

        # --- Control buttons ---
        ctrl = QHBoxLayout()
        ctrl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ctrl.setSpacing(8)

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setObjectName("PrimaryBtn")
        self.start_btn.setMinimumWidth(100)
        self.start_btn.clicked.connect(self._on_start_clicked)
        ctrl.addWidget(self.start_btn)

        self.reset_btn = QPushButton("↻ 重置")
        self.reset_btn.setMinimumWidth(70)
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        ctrl.addWidget(self.reset_btn)

        self.skip_btn = QPushButton("⏭ 跳过")
        self.skip_btn.setMinimumWidth(70)
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        ctrl.addWidget(self.skip_btn)

        root.addLayout(ctrl)

        # Focus mode button
        focus_row = QHBoxLayout()
        focus_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_btn = QPushButton("⛶ 专注模式")
        self.focus_btn.setObjectName("GhostBtn")
        self.focus_btn.clicked.connect(self._on_focus_mode_clicked)
        focus_row.addWidget(self.focus_btn)
        # Stats button
        self.stats_btn = QPushButton("📊 统计")
        self.stats_btn.clicked.connect(self._on_stats_clicked)
        focus_row.addWidget(self.stats_btn)
        root.addLayout(focus_row)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #e5e5ea; background: #e5e5ea;")
        root.addWidget(sep)

        # --- Task list block ---
        task_header = QHBoxLayout()
        task_header.setContentsMargins(0, 8, 0, 4)
        section_label = QLabel("今日任务")
        section_label.setObjectName("SectionHeader")
        task_header.addWidget(section_label)
        task_header.addStretch()
        self.add_btn = QPushButton("+ 添加")
        self.add_btn.clicked.connect(self._on_add_task_clicked)
        task_header.addWidget(self.add_btn)
        root.addLayout(task_header)

        # Inline add-task form (hidden by default)
        self.add_form = AddTaskDialog(self._on_add_task_submit, self)
        self.add_form.setVisible(False)
        root.addWidget(self.add_form)

        # Scrollable task list
        self.task_list_container = QWidget()
        self.task_list_container.setStyleSheet("background: transparent;")
        self.task_list_layout = QVBoxLayout(self.task_list_container)
        self.task_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.task_list_layout.setSpacing(6)
        self.task_list_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.task_list_container)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        root.addWidget(scroll, stretch=1)

    # ------------------------------------------------------------------
    # task list rendering
    # ------------------------------------------------------------------
    def _refresh_task_list(self):
        # Clear existing rows
        while self.task_list_layout.count():
            item = self.task_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        tasks = self.store.get_tasks()
        if not tasks:
            empty = QLabel("（暂无任务，点击 + 添加）")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #86868b; padding: 40px;")
            self.task_list_layout.addWidget(empty)
            return

        for task in tasks:
            row = TaskRowWidget(
                task=task,
                on_start=self._on_task_start,
                on_edit=self._on_task_edit,
                on_delete=self._on_task_delete,
                on_toggle_done=self._on_task_toggle_done,
                parent=self,
            )
            self.task_list_layout.addWidget(row)

    # ------------------------------------------------------------------
    # timer display
    # ------------------------------------------------------------------
    def _format_remaining(self, remaining_seconds: int) -> str:
        settings = self.store.get_settings()
        if settings.display_mode == "minutes_only":
            minutes = (remaining_seconds + 59) // 60  # ceil
            return str(minutes)
        # mmss
        minutes = remaining_seconds // 60
        seconds = remaining_seconds % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _refresh_time_display(self):
        remaining = self.engine.remaining_seconds
        text = self._format_remaining(remaining)
        self.time_label.setText(text)
        if self.focus_overlay is not None:
            self.focus_overlay.refresh()
        if self.floating_window is not None:
            self.floating_window.refresh()

    def _refresh_phase_label(self):
        phase = self.engine.current_phase
        label = PHASE_LABELS.get(phase, str(phase))
        # Append bound task name if any
        task_name = self._current_task_title()
        if task_name and phase == Phase.FOCUS:
            label += f" · {task_name}"
        self.phase_label.setText(label)

    def _current_task_title(self) -> Optional[str]:
        if not self.current_task_id:
            return None
        tasks = self.store.get_tasks()
        for t in tasks:
            if t.id == self.current_task_id:
                return t.title
        return None

    def _refresh_controls(self):
        if self.engine.running:
            self.start_btn.setText("⏸ 暂停")
        else:
            self.start_btn.setText("▶ 开始")

    # ------------------------------------------------------------------
    # engine callbacks
    # ------------------------------------------------------------------
    def _on_engine_tick(self, remaining: int):
        # The refresh_timer picks up the updated remaining_seconds; nothing to do.
        pass

    def _on_engine_phase_change(self, phase: Phase, duration: int):
        self._refresh_phase_label()
        self._refresh_controls()
        self._refresh_time_display()
        # Notify the user when a phase ends and the next begins.
        # Route through tray.show_message so clicking the notification
        # opens the main window.
        if phase == Phase.FOCUS:
            self._notify("休息结束", "准备开始专注")
        elif phase == Phase.SHORT_BREAK:
            self._notify("专注完成", "该短休息了")
        elif phase == Phase.LONG_BREAK:
            self._notify("周期完成", "该长休息了")

    def _notify(self, title: str, body: str) -> None:
        """Send a notification via osascript (reliable on macOS).

        Note: QSystemTrayIcon.showMessage() does not reliably display
        notifications on macOS, so we use osascript instead.
        """
        notify(title, body)

    def _on_engine_focus_completed(self, task_id: Optional[str]):
        """Record a completed focus session and update the bound task."""
        started_ts = self.engine.phase_started_at or datetime.now().timestamp()
        started = datetime.fromtimestamp(started_ts).isoformat()
        ended = datetime.now().isoformat()
        record = PomodoroRecord(
            phase="focus",
            started_at=started,
            ended_at=ended,
            task_id=task_id,
            completed=True,
        )
        self.store.add_record(record)

        # Increment the bound task's actual_pomodoros
        if task_id:
            tasks = self.store.get_tasks()
            for t in tasks:
                if t.id == task_id:
                    t.actual_pomodoros += 1
                    if t.status == "todo":
                        t.status = "in_progress"
                    self.store.update_task(t)
                    break

        self._refresh_task_list()
        self._refresh_phase_label()

    # ------------------------------------------------------------------
    # QTimer tick
    # ------------------------------------------------------------------
    def _on_refresh_timer(self):
        """Called every 250ms: tick the engine and refresh the display."""
        self.engine.tick()
        self._refresh_controls()
        self._refresh_time_display()

    def showEvent(self, event):
        """Refresh controls when window is shown (tray controls may have changed state)."""
        self._refresh_controls()
        self._refresh_time_display()
        super().showEvent(event)

    # ------------------------------------------------------------------
    # button handlers
    # ------------------------------------------------------------------
    def _on_start_clicked(self):
        if self.engine.running:
            self.engine.pause()
        else:
            self.engine.start()
        self._refresh_controls()
        self._refresh_time_display()

    def _on_reset_clicked(self):
        self.engine.reset()
        self._refresh_controls()
        self._refresh_time_display()
        self._refresh_phase_label()

    def _on_skip_clicked(self):
        self.engine.skip()
        self._refresh_controls()
        self._refresh_time_display()
        self._refresh_phase_label()

    def _on_focus_mode_clicked(self):
        if self.focus_overlay is not None and self.focus_overlay.isVisible():
            self.focus_overlay.close()
            return
        self.focus_overlay = FocusModeOverlay(
            get_remaining_text=lambda: self.time_label.text(),
            get_phase_label=lambda: self.phase_label.text(),
            phase_color=_phase_color(self.engine.current_phase),
            parent=None,
        )
        self.focus_overlay.showFullScreen()
        self.focus_overlay.refresh()

    # ------------------------------------------------------------------
    # floating mini window
    # ------------------------------------------------------------------
    def _toggle_floating_window(self):
        # If floating window exists and is visible -> close it and show main window
        if self.floating_window is not None and self.floating_window.isVisible():
            self.floating_window.close()
            self.floating_window = None
            self.show()
            self.raise_()
            self.activateWindow()
            return
        # Otherwise -> hide main window and show floating window
        self.hide()
        self.floating_window = FloatingMiniWindow(
            get_remaining_text=lambda: self.time_label.text(),
            get_phase_label=lambda: self.phase_label.text(),
            get_phase=lambda: self.engine.current_phase,
            on_toggle_back=self._restore_main_from_floating,
            on_toggle_start_pause=self._on_start_clicked,
            parent=None,
        )
        self.floating_window.show()
        self.floating_window.refresh()
        # Focus the floating window so it receives the F key
        self.floating_window.raise_()
        self.floating_window.activateWindow()
        self.floating_window.setFocus()

    def _restore_main_from_floating(self):
        if self.floating_window is not None:
            self.floating_window.close()
            self.floating_window = None
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event):
        # Toggle floating window with F key
        if event.key() == Qt.Key.Key_F:
            self._toggle_floating_window()
            return
        # Space toggles start/pause
        if event.key() == Qt.Key.Key_Space:
            self._on_start_clicked()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # task list handlers
    # ------------------------------------------------------------------
    def _on_add_task_clicked(self):
        self.add_form.setVisible(not self.add_form.isVisible())
        if self.add_form.isVisible():
            self.add_form.title_input.setFocus()
            # Install event filter to catch clicks outside the form.
            QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, event):
        """Close the add-task form when clicking outside it."""
        if self.add_form.isVisible() and event.type() == QEvent.Type.MouseButtonPress:
            # Map the global click position to the form's coordinate space.
            global_pos = event.globalPosition().toPoint()
            form_pos = self.add_form.mapFromGlobal(global_pos)
            if not self.add_form.rect().contains(form_pos):
                self.add_form.setVisible(False)
                QApplication.instance().removeEventFilter(self)
                return True  # event handled
        return super().eventFilter(obj, event)

    def _on_add_task_submit(self, title: str, estimated: int):
        task = Task(title=title, estimated_pomodoros=estimated)
        self.store.add_task(task)
        self._refresh_task_list()

    def _on_task_start(self, task: Task):
        self.current_task_id = task.id
        self.engine.bind_task(task.id)
        if not self.engine.running:
            self.engine.start()
        self._refresh_controls()
        self._refresh_phase_label()

    def _on_task_edit(self, task: Task):
        dlg = EditTaskDialog(task=task, on_save=self._on_task_edit_save, parent=self)
        dlg.exec()

    def _on_task_edit_save(self, task: Task):
        self.store.update_task(task)
        self._refresh_task_list()
        self._refresh_phase_label()

    def _on_task_delete(self, task: Task):
        reply = QMessageBox.question(
            self,
            "删除任务",
            f"确定删除任务「{task.title}」吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.store.delete_task(task.id)
            if self.current_task_id == task.id:
                self.current_task_id = None
                self.engine.bind_task(None)
            self._refresh_task_list()
            self._refresh_phase_label()

    def _on_task_toggle_done(self, task: Task):
        if task.status == "done":
            task.status = "todo"
        else:
            task.status = "done"
        self.store.update_task(task)
        self._refresh_task_list()

    # ------------------------------------------------------------------
    # stats dialog
    # ------------------------------------------------------------------
    def _on_stats_clicked(self):
        records = self.store.get_records()
        settings = self.store.get_settings()
        stats = compute_stats(records, settings)

        dlg = QDialog(self)
        dlg.setWindowTitle("专注统计")
        dlg.setMinimumWidth(360)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        title = QLabel("📊 专注统计")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        hint = QLabel("每个专注 = {} 分钟".format(settings.focus_minutes))
        hint.setStyleSheet("color: #86868b; font-size: 12px;")
        layout.addWidget(hint)

        # Header row
        header = QHBoxLayout()
        header.addWidget(QLabel("区间"))
        header.addWidget(QLabel("次数"))
        header.addWidget(QLabel("时长"))
        layout.addLayout(header)

        for key in ("12h", "1d", "3d", "1w"):
            row = QHBoxLayout()
            row.addWidget(QLabel(key))
            row.addWidget(QLabel(str(stats[key]["count"])))
            hours = stats[key]["minutes"] / 60
            row.addWidget(QLabel(f"{hours:.1f}h"))
            layout.addLayout(row)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.exec()

    # ------------------------------------------------------------------
    # cleanup
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # Stop timers so nothing keeps running in the background.
        self.refresh_timer.stop()
        if self.focus_overlay is not None:
            self.focus_overlay.close()
        if self.floating_window is not None:
            self.floating_window.close()
        # Quit the whole app so the terminal process exits cleanly.
        QApplication.quit()
        super().closeEvent(event)
