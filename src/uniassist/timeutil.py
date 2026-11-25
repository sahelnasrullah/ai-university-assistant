"""Time handling. All user-facing times are in the configured time zone."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DEFAULT_TZ = "Europe/Stockholm"


def get_tz(name: str = DEFAULT_TZ) -> ZoneInfo:
    return ZoneInfo(name)


def parse_dt(value: str | None, tz: ZoneInfo) -> datetime | None:
    """Parse an ISO-8601 string (Canvas uses '...Z') into an aware datetime in tz."""
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def to_aware(value: date | datetime, tz: ZoneInfo) -> datetime:
    """Normalise iCal values (date, naive, or aware) to an aware datetime in tz."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz)
        return value.astimezone(tz)
    return datetime.combine(value, time.min, tzinfo=tz)


def fmt(dt: datetime | None) -> str | None:
    """Human/LLM friendly, unambiguous: 'Fri 2026-11-27 23:59 (CET)'."""
    if dt is None:
        return None
    return dt.strftime("%a %Y-%m-%d %H:%M (%Z)")


def day_bounds(d: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(d, time.min, tzinfo=tz)
    return start, start + timedelta(days=1)


def named_range(name: str, now: datetime) -> tuple[datetime, datetime]:
    """Resolve 'today', 'tomorrow', 'this_week', 'next_week' (weeks start Monday)."""
    tz = now.tzinfo
    today = now.date()
    if name == "today":
        return day_bounds(today, tz)
    if name == "tomorrow":
        return day_bounds(today + timedelta(days=1), tz)
    monday = today - timedelta(days=today.weekday())
    if name == "this_week":
        s = datetime.combine(monday, time.min, tzinfo=tz)
        return s, s + timedelta(days=7)
    if name == "next_week":
        s = datetime.combine(monday + timedelta(days=7), time.min, tzinfo=tz)
        return s, s + timedelta(days=7)
    raise ValueError(f"unknown range: {name}")
