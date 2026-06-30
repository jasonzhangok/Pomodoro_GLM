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

from datetime import datetime
from typing import Optional

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

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


class TaskRowWidget(QFrame):
    """A single task row: checkbox, title, pomodoro count, action buttons."""

    def __init__(self, task: Task, on_start, on_edit, on_delete, on_toggle_done, parent=None):
        super().__init__(parent)
        self.task = task
        self.setObjectName("TaskRow")
        self.setFrameShape(QFrame.Shape.NoFrame)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Done checkbox
        self.done_btn = QPushButton("☐")
        self.done_btn.setCheckable(True)
        self.done_btn.setChecked(task.status == "done")
        self.done_btn.setFixedWidth(32)
        self.done_btn.clicked.connect(lambda: on_toggle_done(task))
        layout.addWidget(self.done_btn)

        # Title + count
        info = QVBoxLayout()
        info.setSpacing(0)
        self.title_label = QLabel(task.title)
        self.title_label.setObjectName("TaskTitle")
        count_text = f"{task.actual_pomodoros}/{task.estimated_pomodoros}"
        self.count_label = QLabel(count_text)
        self.count_label.setObjectName("TaskCount")
        info.addWidget(self.title_label)
        info.addWidget(self.count_label)
        layout.addLayout(info, stretch=1)

        # Action buttons
        self.start_btn = QPushButton("▶")
        self.start_btn.setFixedWidth(32)
        self.start_btn.clicked.connect(lambda: on_start(task))
        layout.addWidget(self.start_btn)

        self.edit_btn = QPushButton("✏")
        self.edit_btn.setFixedWidth(32)
        self.edit_btn.clicked.connect(lambda: on_edit(task))
        layout.addWidget(self.edit_btn)

        self.del_btn = QPushButton("🗑")
        self.del_btn.setFixedWidth(32)
        self.del_btn.clicked.connect(lambda: on_delete(task))
        layout.addWidget(self.del_btn)

        self._refresh_state()

    def _refresh_state(self):
        done = self.task.status == "done"
        if done:
            self.done_btn.setText("☑")
            self.title_label.setStyleSheet("color: gray; text-decoration: line-through;")
        else:
            self.done_btn.setText("☐")
            self.title_label.setStyleSheet("")

    def refresh(self, task: Task):
        self.task = task
        self.title_label.setText(task.title)
        self.count_label.setText(f"{task.actual_pomodoros}/{task.estimated_pomodoros}")
        self._refresh_state()


class AddTaskDialog(QFrame):
    """Inline add-task form: title input + estimated pomodoros + add button."""

    def __init__(self, on_add, parent=None):
        super().__init__(parent)
        self.setObjectName("AddTaskForm")
        self.on_add = on_add

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self.title_input = QLineEdit()
        self.title_input.setPlaceholderText("新任务标题…")
        self.title_input.returnPressed.connect(self._submit)
        layout.addWidget(self.title_input, stretch=1)

        self.spin = QSpinBox()
        self.spin.setRange(1, 99)
        self.spin.setValue(1)
        self.spin.setPrefix("🍅×")
        layout.addWidget(self.spin)

        self.add_btn = QPushButton("+ 添加")
        self.add_btn.clicked.connect(self._submit)
        layout.addWidget(self.add_btn)

    def _submit(self):
        title = self.title_input.text().strip()
        if not title:
            return
        est = self.spin.value()
        self.on_add(title, est)
        self.title_input.clear()
        self.spin.setValue(1)


class EditTaskDialog(QWidget):
    """Modal-ish dialog for editing a task's title and estimated pomodoros."""

    def __init__(self, task: Task, on_save, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑任务")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.task = task
        self.on_save = on_save

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("任务标题:"))
        self.title_input = QLineEdit(task.title)
        layout.addWidget(self.title_input)

        layout.addWidget(QLabel("预估番茄数:"))
        self.spin = QSpinBox()
        self.spin.setRange(1, 99)
        self.spin.setValue(task.estimated_pomodoros)
        layout.addWidget(self.spin)

        btn_layout = QHBoxLayout()
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.close)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        self.resize(300, 180)

    def _save(self):
        new_title = self.title_input.text().strip()
        if not new_title:
            return
        self.task.title = new_title
        self.task.estimated_pomodoros = self.spin.value()
        self.on_save(self.task)
        self.close()


class FocusModeOverlay(QWidget):
    """Borderless fullscreen overlay showing only the big countdown."""

    def __init__(self, get_remaining_text, get_phase_label, parent=None):
        super().__init__(parent)
        self.setWindowTitle("专注模式")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet("background-color: #1e1e1e;")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("color: white; font-size: 180px; font-weight: bold;")
        layout.addWidget(self.time_label)

        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("color: #aaa; font-size: 24px;")
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
        self.engine = engine
        self.store = store
        self.current_task_id: Optional[str] = None
        self.focus_overlay: Optional[FocusModeOverlay] = None
        self._previous_phase: Optional[Phase] = None

        # Wire engine callbacks
        self.engine.on_tick = self._on_engine_tick
        self.engine.on_phase_change = self._on_engine_phase_change
        self.engine.on_focus_completed = self._on_engine_focus_completed

        self.setWindowTitle("番茄钟")
        self.resize(420, 640)
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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # --- Timer block ---
        self.time_label = QLabel()
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.time_label.setStyleSheet("font-size: 64px; font-weight: bold;")
        root.addWidget(self.time_label)

        self.phase_label = QLabel()
        self.phase_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.phase_label.setStyleSheet("font-size: 14px; color: #666;")
        root.addWidget(self.phase_label)

        # --- Control buttons ---
        ctrl = QHBoxLayout()
        ctrl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.clicked.connect(self._on_start_clicked)
        ctrl.addWidget(self.start_btn)

        self.reset_btn = QPushButton("↻ 重置")
        self.reset_btn.clicked.connect(self._on_reset_clicked)
        ctrl.addWidget(self.reset_btn)

        self.skip_btn = QPushButton("⏭ 跳过")
        self.skip_btn.clicked.connect(self._on_skip_clicked)
        ctrl.addWidget(self.skip_btn)

        root.addLayout(ctrl)

        # Focus mode button
        focus_row = QHBoxLayout()
        focus_row.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.focus_btn = QPushButton("⛶ 专注模式")
        self.focus_btn.clicked.connect(self._on_focus_mode_clicked)
        focus_row.addWidget(self.focus_btn)
        root.addLayout(focus_row)

        # --- Separator ---
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #ccc;")
        root.addWidget(sep)

        # --- Task list block ---
        task_header = QHBoxLayout()
        task_header.addWidget(QLabel("今日任务"))
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
        self.task_list_layout = QVBoxLayout(self.task_list_container)
        self.task_list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.task_list_layout.setSpacing(2)

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
            empty.setStyleSheet("color: #999;")
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
        """Fire macOS notifications on phase transitions, then refresh UI."""
        old = self._previous_phase

        if phase == Phase.SHORT_BREAK:
            # Focus completed → short break
            mins = self.store.get_settings().short_break_minutes
            notify("专注完成！", f"短休 {mins} 分钟 🎉")
        elif phase == Phase.LONG_BREAK:
            # Focus completed → long break
            mins = self.store.get_settings().long_break_minutes
            notify("专注完成！", f"长休 {mins} 分钟 🎉")
        elif phase == Phase.FOCUS:
            if old == Phase.SHORT_BREAK:
                notify("休息结束", "开始下一个专注")
            elif old == Phase.LONG_BREAK:
                notify("长休结束", "开始新周期")

        self._previous_phase = phase
        self._refresh_phase_label()
        self._refresh_controls()
        self._refresh_time_display()

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
        self._refresh_time_display()

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
            parent=None,
        )
        self.focus_overlay.showFullScreen()
        self.focus_overlay.refresh()

    # ------------------------------------------------------------------
    # task list handlers
    # ------------------------------------------------------------------
    def _on_add_task_clicked(self):
        self.add_form.setVisible(not self.add_form.isVisible())

    def _on_add_task_submit(self, title: str, estimated: int):
        task = Task(title=title, estimated_pomodoros=estimated)
        self.store.add_task(task)
        self._refresh_task_list()

    def _on_task_start(self, task: Task):
        # Bind this task as the current focus task
        self.current_task_id = task.id
        self.engine.bind_task(task.id)
        # Ensure timer is running
        if not self.engine.running:
            self.engine.start()
        self._refresh_controls()
        self._refresh_phase_label()

    def _on_task_edit(self, task: Task):
        dlg = EditTaskDialog(task=task, on_save=self._on_task_edit_save, parent=self)
        dlg.show()

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
    # cleanup
    # ------------------------------------------------------------------
    def closeEvent(self, event):
        # Timers are lightweight; keep them running so the display stays
        # fresh even when the window is hidden (tray-only mode).
        # They'll be cleaned up when the app quits.
        if self.focus_overlay is not None:
            self.focus_overlay.close()
        super().closeEvent(event)
