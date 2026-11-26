"""Deterministic planning helpers: priority ranking, clash detection, workload plan.

No LLM involved. Effort figures are rough estimates (labelled as such): Canvas does
not know how long work takes.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .schedule import ScheduleError
from .timeutil import fmt
from .tools import Context, active_courses

_LIGHT = re.compile(r"survey|quiz|evaluation|reflection|checklist|enk[äa]t", re.I)


@dataclass
class Task:
    course: str
    name: str
    due: datetime
    points: float | None
    hours: float
    url: str | None = None

    def to_dict(self) -> dict:
        return {"course": self.course, "assignment": self.name, "due": fmt(self.due),
                "points": self.points, "est_hours": self.hours}


def estimate_hours(name: str, points: float | None) -> float:
    if _LIGHT.search(name) and not (points and points >= 20):
        return 0.5
    if points is None or points <= 0:
        return 3.0
    if points >= 50:
        return 8.0
    if points >= 20:
        return 4.0
    return 3.0


def collect_tasks(ctx: Context, days: int = 21, overdue_days: int = 7) -> list[Task]:
    """Unsubmitted assignments due within [now - overdue_days, now + days] in current courses."""
    if not ctx.canvas:
        return []
    now = ctx.now()
    lo, hi = now - timedelta(days=overdue_days), now + timedelta(days=days)
    out = []
    for c in active_courses(ctx):
        for a in ctx.canvas.assignments(c.id):
            if a.due_at and not a.submitted and lo <= a.due_at <= hi:
                out.append(Task(c.name, a.name, a.due_at, a.points_possible,
                                estimate_hours(a.name, a.points_possible), a.url))
    return sorted(out, key=lambda t: t.due)


def prioritise(ctx: Context, days: int = 21) -> list[dict]:
    """Rank by slack: time left minus the time needed (assuming ~3 productive hours/day)."""
    now = ctx.now()
    ranked = []
    for t in collect_tasks(ctx, days):
        hours_left = (t.due - now).total_seconds() / 3600
        slack_days = hours_left / 24 - t.hours / 3
        reasons = []
        if hours_left < 0:
            reasons.append(f"overdue by {abs(hours_left) / 24:.1f} days")
        elif hours_left < 48:
            reasons.append(f"due in {hours_left:.0f} h")
        else:
            reasons.append(f"due in {hours_left / 24:.0f} days")
        reasons.append(f"about {t.hours:g} h of work (estimate)")
        if t.points and t.points >= 20:
            reasons.append(f"worth {t.points:g} points")
        ranked.append((slack_days, {**t.to_dict(), "slack_days": round(slack_days, 1),
                                     "why": "; ".join(reasons)}))
    ranked.sort(key=lambda x: x[0])
    return [d for _, d in ranked]


def _events_between(ctx: Context, start: datetime, end: datetime):
    """Class times, or [] if there is no usable schedule (planning then ignores classes)."""
    if not (ctx.schedule and ctx.schedule.configured()):
        return []
    try:
        return ctx.events_between(start, end)
    except ScheduleError:
        return []


def find_clashes(ctx: Context, days: int = 14) -> list[dict]:
    now = ctx.now()
    end = now + timedelta(days=days)
    tasks = [t for t in collect_tasks(ctx, days, 0)]
    out = []
    by_day: dict[date, list[Task]] = {}
    for t in tasks:
        by_day.setdefault(t.due.date(), []).append(t)
    for d, ts in sorted(by_day.items()):
        if len(ts) >= 2:
            out.append({"kind": "deadline_cluster", "date": d.isoformat(),
                        "message": f"{len(ts)} deadlines on {d:%a %Y-%m-%d}: "
                                   + ", ".join(f"{t.name} ({t.course.split()[0]})" for t in ts)})
        busy = sum((e.end - e.start).total_seconds() / 3600 for e in _events_between(
            ctx, datetime.combine(d, time.min, tzinfo=now.tzinfo),
            datetime.combine(d, time.max, tzinfo=now.tzinfo)))
        if busy >= 3:
            out.append({"kind": "deadline_on_busy_day", "date": d.isoformat(),
                        "message": f"{d:%a %Y-%m-%d} has a deadline and {busy:.1f} h of scheduled classes."})
    evs = _events_between(ctx, now, end)
    for a, b in zip(evs, evs[1:]):
        if b.start < a.end:
            out.append({"kind": "schedule_overlap", "date": a.start.date().isoformat(),
                        "message": f"'{a.title}' and '{b.title}' overlap on {a.start:%a %Y-%m-%d %H:%M}."})
    return out


def make_plan(ctx: Context, days: int = 14, hours_per_day: float = 3.0) -> dict:
    """Spread each task's estimated hours over the days before it is due.
    Earliest deadline first, never more than hours_per_day (minus class time) per day."""
    now = ctx.now()
    today = now.date()
    tasks = [t for t in collect_tasks(ctx, days, 0)]
    cap: dict[date, float] = {}
    for i in range(days + 1):
        d = today + timedelta(days=i)
        classes = sum((e.end - e.start).total_seconds() / 3600 for e in _events_between(
            ctx, datetime.combine(d, time.min, tzinfo=now.tzinfo),
            datetime.combine(d, time.max, tzinfo=now.tzinfo)))
        cap[d] = max(0.0, hours_per_day - classes * 0.5) if d.weekday() < 5 else hours_per_day / 2
        if d == today:  # only the rest of today (study window ends 22:00) is usable
            cap[d] *= min(1.0, max(0.0, (22 - now.hour - now.minute / 60) / 14))
    plan: dict[date, list[dict]] = {}
    short = []
    for t in tasks:
        due_day = t.due.date() if t.due.time() > time(12, 0) else t.due.date() - timedelta(days=1)
        window = [today + timedelta(days=i) for i in range((due_day - today).days + 1)
                  if today + timedelta(days=i) in cap]
        if not window:
            short.append({**t.to_dict(), "missing_hours": t.hours})
            continue
        spread = window[-max(1, math.ceil(t.hours / 1.5)):]      # start a few days before the deadline
        remaining = t.hours
        # first pass: even spread over the chosen days; second pass: use any earlier free time
        for pool, share in ((spread, max(0.5, t.hours / len(spread))), (window, remaining)):
            for d in pool:
                if remaining <= 0:
                    break
                give = min(share, cap[d], remaining)
                give = math.floor(give * 2) / 2                   # half-hour steps
                if give > 0:
                    day = plan.setdefault(d, [])
                    same = next((x for x in day if x["assignment"] == t.name and x["course"] == t.course), None)
                    if same:
                        same["hours"] += give
                    else:
                        day.append({"assignment": t.name, "course": t.course, "hours": give})
                    cap[d] -= give
                    remaining -= give
            share = remaining
        if remaining > 0.01:
            short.append({**t.to_dict(), "missing_hours": round(remaining, 1)})
    return {"hours_per_day": hours_per_day,
            "days": [{"date": d.isoformat(), "sessions": s, "total_hours": sum(x["hours"] for x in s)}
                     for d, s in sorted(plan.items())],
            "not_enough_time": short,
            "note": "Estimates only: hours per task are guesses from the name and points."}
