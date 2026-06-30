"""Entry point for the Pomodoro timer.

Assembles the store, timer engine, main window, and tray icon, then runs
the Qt event loop.

Run:
    python app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the project root is on sys.path so `from core...` works when run
# from anywhere (e.g. double-clicking or via a launcher).
_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from core.models import Settings
from core.timer_engine import TimerEngine
from data.store import Store
from ui.main_window import MainWindow
from ui.tray import TrayController


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Pomodoro_GLM")
    app.setQuitOnLastWindowClosed(False)  # keep running when window is closed (tray mode)

    # --- Data layer ---
    store = Store()
    settings: Settings = store.get_settings()

    # --- Core engine ---
    engine = TimerEngine(settings=settings)

    # --- UI ---
    window = MainWindow(engine=engine, store=store)

    # --- Tray ---
    tray = TrayController(engine=engine, app=app)
    tray_available = tray.setup()

    # Wire tray signals
    def toggle_window():
        if window.isVisible():
            window.hide()
        else:
            window.show()
            window.raise_()
            window.activateWindow()

    tray.toggle_window_requested.connect(toggle_window)
    tray.quit_requested.connect(app.quit)

    # Show the window on launch if the tray isn't available (rare on macOS).
    if not tray_available:
        window.show()
    else:
        # Start with the window visible.
        window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
