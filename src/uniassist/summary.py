"""Deterministic daily summary (no LLM): today's schedule + deadlines this week."""
from __future__ import annotations

from .schedule import ScheduleError
from .tools import Context, get_schedule, get_upcoming_assignments


def daily_summary(ctx: Context) -> str:
    lines = []
    sched = get_schedule(ctx, date_range="today") if ctx.schedule else {"status": "not_configured"}
    lines.append("Today's schedule:")
    if sched["status"] == "ok":
        lines += [f"  {e['start']} - {e['end']}  {e['title']}"
                  + (f" ({e['location']})" if e["location"] else "") for e in sched["events"]]
    else:
        lines.append(f"  {sched.get('message', 'nothing scheduled')}")
    lines.append("Deadlines (next 7 days):")
    if ctx.canvas:
        a = get_upcoming_assignments(ctx, days=7)
        if a["status"] == "ok":
            lines += [f"  {x['due']}  {x['course']}: {x['assignment']}" for x in a["upcoming"]]
            lines += [f"  OVERDUE {x['due']}  {x['course']}: {x['assignment']}"
                      for x in a["overdue_unsubmitted"]]
            if not a["upcoming"] and not a["overdue_unsubmitted"]:
                lines.append("  none")
        else:
            lines.append(f"  {a['message']}")
    else:
        lines.append("  Canvas is not linked.")
    return "\n".join(lines)


def briefing(ctx: Context) -> str:
    """Morning briefing: today, deadlines, what to start first, clashes."""
    from .planner import find_clashes, prioritise
    lines = [daily_summary(ctx)]
    if ctx.canvas:
        top = prioritise(ctx, days=14)[:3]
        if top:
            lines.append("Start with:")
            lines += [f"  {i}. {t['assignment']} ({t['course'].split()[0]}): {t['why']}"
                      for i, t in enumerate(top, 1)]
        clashes = find_clashes(ctx, days=7)
        if clashes:
            lines.append("Watch out:")
            lines += [f"  ! {c['message']}" for c in clashes[:4]]
    return "\n".join(lines)


def week_overview(ctx: Context, hours_per_day: float = 3.0) -> str:
    """Seven days: classes, deadlines and the planned study hours per day."""
    from datetime import timedelta
    from .planner import collect_tasks, make_plan
    now = ctx.now()
    tasks = collect_tasks(ctx, days=7, overdue_days=0) if ctx.canvas else []
    plan = {d["date"]: d for d in make_plan(ctx, 7, hours_per_day)["days"]} if ctx.canvas else {}
    lines = []
    for i in range(7):
        day = (now + timedelta(days=i)).date()
        lines.append(f"{day:%a %Y-%m-%d}")
        if ctx.schedule and ctx.schedule.configured():
            from .timeutil import day_bounds
            s, e = day_bounds(day, now.tzinfo)
            try:
                lines += [f"   class   {x.start:%H:%M}-{x.end:%H:%M} {x.title}" for x in ctx.events_between(s, e)]
            except ScheduleError:
                pass
        lines += [f"   DUE     {t.due:%H:%M} {t.name} ({t.course.split()[0]})" for t in tasks if t.due.date() == day]
        p = plan.get(day.isoformat())
        if p:
            lines.append(f"   study   {p['total_hours']:g} h planned: "
                         + ", ".join(f"{x['assignment']} {x['hours']:g}h" for x in p["sessions"]))
    return "\n".join(lines)
