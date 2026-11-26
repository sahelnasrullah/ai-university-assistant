"""Local desktop notifications (notify-send). Nothing leaves the machine."""
from __future__ import annotations

import shutil
import subprocess


def send(title: str, body: str) -> bool:
    """Show a desktop notification. Returns False if notify-send is unavailable."""
    exe = shutil.which("notify-send")
    if not exe:
        return False
    try:  # argv list, no shell: text from Canvas can never become a command
        subprocess.run([exe, "--app-name=uniassist", "--", title[:100], body[:300]],
                       check=True, timeout=5, capture_output=True)
        return True
    except (subprocess.SubprocessError, OSError):
        return False


TIMER_UNITS = {
    "uniassist-check.service": """[Unit]
Description=uniassist: check Canvas for changes and deadlines

[Service]
Type=oneshot
ExecStart={exe} notify
""",
    "uniassist-check.timer": """[Unit]
Description=Run uniassist check every 30 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=30min

[Install]
WantedBy=timers.target
""",
    "uniassist-briefing.service": """[Unit]
Description=uniassist: morning briefing

[Service]
Type=oneshot
ExecStart={exe} briefing --notify
""",
    "uniassist-briefing.timer": """[Unit]
Description=uniassist morning briefing (weekdays 07:30)

[Timer]
OnCalendar=Mon..Fri 07:30
Persistent=true

[Install]
WantedBy=timers.target
""",
}
