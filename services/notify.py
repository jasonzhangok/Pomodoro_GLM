"""macOS native notification support via ``osascript``.

Only displays notifications — no sound, no window flashing — per the
design spec. The caller is responsible for choosing when to notify
(phase transitions).
"""
from __future__ import annotations

import subprocess


def notify(title: str, body: str) -> None:
    """Display a macOS native notification.

    Args:
        title: Notification title.
        body: Notification body text.

    Note:
        On first run, macOS may prompt the user to allow notifications
        from "Script Editor" or the terminal. The user can also pre-allow
        this in System Settings -> Notifications.
    """
    # Escape double quotes in the body to keep the AppleScript valid.
    safe_body = body.replace('"', '\\"')
    safe_title = title.replace('"', '\\"')
    script = (
        f'display notification "{safe_body}" with title "{safe_title}"'
    )
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        # Silently ignore notification failures — they are non-critical.
        pass
