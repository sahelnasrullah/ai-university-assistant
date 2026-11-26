"""Change alerts and deadline warnings, based on a local snapshot of Canvas.

First run only records a baseline (no alerts). Later runs report differences:
new assignments, changed due dates, new announcements, newly graded work.
Announcement *titles* are reported; the body is never interpreted.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from .config import CONFIG_DIR
from .timeutil import fmt
from .tools import Context, active_courses, clean_text

SNAPSHOT = CONFIG_DIR / "snapshot.json"
NOTIFIED = CONFIG_DIR / "notified.json"
_IMPORTANT = re.compile(r"moved|cancel|postpone|changed|rescheduled|deadline|extended|room|"
                        r"inställ|flyttad|ändrad|uppskjut|förläng|tenta", re.I)


@dataclass
class Alert:
    key: str          # stable id, used to avoid notifying twice
    kind: str
    title: str
    text: str


def take_snapshot(ctx: Context) -> dict:
    snap = {"assignments": {}, "announcements": {}, "grades": {}}
    for c in active_courses(ctx):
        for a in ctx.canvas.assignments(c.id):
            k = f"{c.id}:{a.id}"
            snap["assignments"][k] = {"course": c.name, "name": a.name,
                                      "due": a.due_at.isoformat() if a.due_at else None}
            if a.grade is not None:
                snap["grades"][k] = {"course": c.name, "name": a.name, "grade": a.grade, "score": a.score}
        for n in ctx.canvas.announcements(c.id):
            snap["announcements"][f"{c.id}:{n.id}"] = {
                "course": c.name, "title": clean_text(n.title, 150),
                "important": bool(_IMPORTANT.search(n.title + " " + clean_text(n.message, 400)))}
    return snap


def diff(old: dict, new: dict) -> list[Alert]:
    out = []
    for k, a in new["assignments"].items():
        o = old["assignments"].get(k)
        short = a["course"].split()[0]
        if o is None:
            out.append(Alert(f"new:{k}", "new_assignment", f"New assignment in {short}",
                             f"{a['name']} (due {a['due'] or 'no date'})"))
        elif o["due"] != a["due"]:
            out.append(Alert(f"due:{k}:{a['due']}", "due_changed", f"Deadline changed in {short}",
                             f"{a['name']}: {o['due'] or 'no date'} -> {a['due'] or 'no date'}"))
    for k, n in new["announcements"].items():
        if k not in old["announcements"]:
            tag = " (mentions a change/deadline)" if n["important"] else ""
            out.append(Alert(f"ann:{k}", "announcement", f"New announcement in {n['course'].split()[0]}",
                             n["title"] + tag))
    for k, g in new["grades"].items():
        if k not in old["grades"]:
            out.append(Alert(f"grade:{k}", "new_grade", f"New grade in {g['course'].split()[0]}",
                             f"{g['name']}: {g['grade']}"))
    return out


def check_changes(ctx: Context, path: Path | None = None) -> tuple[list[Alert], bool]:
    """Returns (alerts, first_run). Updates the snapshot on disk."""
    path = path or SNAPSHOT
    new = take_snapshot(ctx)
    first = not path.exists()
    alerts = [] if first else diff(json.loads(path.read_text()), new)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(new))
    path.chmod(0o600)
    return alerts, first


def deadline_warnings(ctx: Context, within_hours: int = 48) -> list[Alert]:
    from .planner import collect_tasks
    now = ctx.now()
    out = []
    for t in collect_tasks(ctx, days=within_hours // 24 + 1, overdue_days=0):
        left = (t.due - now).total_seconds() / 3600
        if 0 <= left <= within_hours:
            bucket = "3h" if left <= 3 else "24h" if left <= 24 else "48h"
            out.append(Alert(f"warn:{t.url or t.name}:{t.due.isoformat()}:{bucket}", "deadline",
                             f"Due in {left:.0f} h: {t.name}",
                             f"{t.course.split()[0]} · {fmt(t.due)} · not submitted"))
    return out


def only_new(alerts: list[Alert], path: Path | None = None, mark: bool = True) -> list[Alert]:
    """Drop alerts already sent before (so a 30-minute timer does not repeat itself)."""
    path = path or NOTIFIED
    seen = set(json.loads(path.read_text())) if path.exists() else set()
    fresh = [a for a in alerts if a.key not in seen]
    if mark and fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sorted(seen | {a.key for a in fresh})[-500:]))
        path.chmod(0o600)
    return fresh
