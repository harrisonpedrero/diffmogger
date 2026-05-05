from __future__ import annotations

import shutil
import subprocess


LOCAL_NOTIFICATION_TITLE = "Diffmogger"
LOCAL_NOTIFICATION_SOUND = "Glass"


def _applescript_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def send_local_notification(
    *,
    title: str = LOCAL_NOTIFICATION_TITLE,
    subtitle: str,
    body: str,
    enabled: bool = True,
    dry_run: bool = False,
) -> dict[str, object]:
    if not enabled:
        return {
            "enabled": False,
            "ok": True,
            "sent": False,
            "dry_run": dry_run,
            "status": "disabled",
            "detail": "local desktop notifications disabled",
        }
    if dry_run:
        return {
            "enabled": True,
            "ok": True,
            "sent": False,
            "dry_run": True,
            "status": "dry_run",
            "detail": "local desktop notification dry run",
        }

    osascript = shutil.which("osascript")
    if not osascript:
        return {
            "enabled": True,
            "ok": False,
            "sent": False,
            "dry_run": False,
            "status": "LOCAL_NOTIFICATION_FAILED",
            "detail": "osascript not found on PATH",
        }
    script = (
        f'display notification "{_applescript_quote(body)}" '
        f'with title "{_applescript_quote(title)}" '
        f'subtitle "{_applescript_quote(subtitle)}" '
        f'sound name "{_applescript_quote(LOCAL_NOTIFICATION_SOUND)}"'
    )
    try:
        result = subprocess.run(
            [osascript, "-e", script],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "enabled": True,
            "ok": False,
            "sent": False,
            "dry_run": False,
            "status": "LOCAL_NOTIFICATION_FAILED",
            "detail": str(exc),
        }
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or f"osascript exited {result.returncode}").strip()
        return {
            "enabled": True,
            "ok": False,
            "sent": False,
            "dry_run": False,
            "status": "LOCAL_NOTIFICATION_FAILED",
            "detail": detail[:500],
        }
    return {
        "enabled": True,
        "ok": True,
        "sent": True,
        "dry_run": False,
        "status": "sent",
        "detail": "macOS desktop notification delivered",
    }
