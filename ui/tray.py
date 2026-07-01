"""System tray icon for the Pomodoro timer.

The tray icon lives in the macOS menu bar and shows the live countdown
rendered as text (e.g. ``🍅 18:32``). Left-click toggles the main window
visibility; right-click opens a context menu with timer controls.
"""
from __future__ import annotations

from typing import Callable, Optional

from PyQt6.QtCore import QObject, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QFont, QImage, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from core.phases import Phase
from core.timer_engine import TimerEngine


PHASE_EMOJI = {
    Phase.FOCUS: "🍅",
    Phase.SHORT_BREAK: "☕",
    Phase.LONG_BREAK: "🌿",
}


def _render_tray_icon(text: str) -> QPixmap:
    """Render text into a QPixmap suitable for the tray icon.

    On macOS the menu bar is dark, so we draw white text on a transparent
    background. The image is sized to fit comfortably in the menu bar.
    """
    font = QFont()
    font.setPointSize(13)
    font.setBold(True)

    # Use a temporary painter to measure the text.
    tmp = QPixmap(1, 1)
    painter = QPainter(tmp)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    width = metrics.horizontalAdvance(text) + 6
    height = metrics.height() + 4
    painter.end()

    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)
    painter.end()
    return pixmap


class TrayController(QObject):
    """Owns the QSystemTrayIcon and wires it to the engine + main window.

    Signals:
        toggle_window_requested: emitted on left-click; the app should
            toggle the main window visibility.
        quit_requested: emitted when the user selects "退出".
    """

    toggle_window_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, engine: TimerEngine, app: QApplication):
        super().__init__()
        self.engine = engine
        self.app = app
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._action_start_pause: Optional[QAction] = None

        # Refresh the tray icon periodically.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(500)
        self._refresh_timer.timeout.connect(self._refresh_icon)
        self._refresh_timer.start()

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------
    def setup(self) -> bool:
        """Create the tray icon. Returns False if the tray is unavailable."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False

        self._tray = QSystemTrayIcon()
        self._tray.setToolTip("番茄钟")

        # Context menu
        self._menu = QMenu()

        self._action_start_pause = QAction("▶ 开始", self._menu)
        self._action_start_pause.triggered.connect(self._on_start_pause)
        self._menu.addAction(self._action_start_pause)

        self._action_skip = QAction("⏭ 跳过", self._menu)
        self._action_skip.triggered.connect(self._on_skip)
        self._menu.addAction(self._action_skip)

        self._action_reset = QAction("↻ 重置", self._menu)
        self._action_reset.triggered.connect(self._on_reset)
        self._menu.addAction(self._action_reset)

        self._menu.addSeparator()

        self._action_show = QAction("显示主窗口", self._menu)
        self._action_show.triggered.connect(self.toggle_window_requested.emit)
        self._menu.addAction(self._action_show)

        self._action_quit = QAction("退出", self._menu)
        self._action_quit.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(self._action_quit)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

        self._refresh_icon()
        self._tray.show()
        return True

    # ------------------------------------------------------------------
    # icon refresh
    # ------------------------------------------------------------------
    def _refresh_icon(self):
        if self._tray is None:
            return
        # Show only the countdown (no emoji) for clarity in the menu bar.
        remaining = self.engine.remaining_seconds
        minutes = remaining // 60
        seconds = remaining % 60
        text = f"{minutes:02d}:{seconds:02d}"
        self._tray.setIcon(QIcon(_render_tray_icon(text)))
        # Update start/pause label
        if self._action_start_pause is not None:
            if self.engine.running:
                self._action_start_pause.setText("⏸ 暂停")
            else:
                self._action_start_pause.setText("▶ 开始")

    # ------------------------------------------------------------------
    # tray event handlers
    # ------------------------------------------------------------------
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason):
        # Left-click on macOS triggers "Trigger"
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_window_requested.emit()

    def _on_start_pause(self):
        if self.engine.running:
            self.engine.pause()
        else:
            self.engine.start()
        self._refresh_icon()

    def _on_skip(self):
        self.engine.skip()
        self._refresh_icon()

    def _on_reset(self):
        self.engine.reset()
        self._refresh_icon()

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------
    def cleanup(self):
        self._refresh_timer.stop()
        if self._tray is not None:
            self._tray.hide()
