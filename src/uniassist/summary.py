"""Deterministic daily summary (no LLM): today's schedule + deadlines this week."""
from __future__ import annotations

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
