"""Schedule source. The student provides the schedule; no TimeEdit dependency.

Three ways to supply it (all optional, merged):
  1. a local .ics file          (uniassist schedule import FILE.ics)
  2. an iCal URL (secret)       (uniassist auth set -> ical_url)
  3. manual entries, stored in  ~/.config/uniassist/schedule.json
                                (uniassist schedule add ...)
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import httpx
from icalendar import Calendar

from .config import CONFIG_DIR
from .timeutil import parse_dt, to_aware

MANUAL_FILE = CONFIG_DIR / "schedule.json"
ICS_FILE = CONFIG_DIR / "schedule.ics"

_TYPES = [
    ("lecture", r"lecture|föreläsning|forelasning|lektion|\bfl\b"),
    ("lab", r"\blab|laboration"),
    ("seminar", r"seminar"),
    ("exercise", r"exercise|övning|ovning|tutorial"),
    ("exam", r"exam|tenta|tentamen|salsskrivning"),
    ("presentation", r"presentation"),
]

_CODE = re.compile(r"\b[A-Z]{2}\d{4}\b")
_TE_CODE = re.compile(r"^([A-Z]{2}\d{4})(?:-[HV]T?\d{2}-LP\d+)?$")
_HOLIDAYS = re.compile(r"julafton|juldagen|annandag|nyårs|trettonda|påsk|midsommar|långfredag|"
                       r"kristi|första maj|nationaldag|alla helgon", re.I)


def event_codes(e: "Event") -> list[str]:
    """Course codes (e.g. DV2658) mentioned by an event."""
    return sorted(set(_CODE.findall(f"{e.course or ''} {e.title}")))


def parse_timeedit_title(title: str) -> tuple[str | None, str | None, str | None]:
    """TimeEdit titles look like 'DV2658-H26-LP2, ABC, Föreläsning, DVAMI22h, ...'.
    Returns (course codes, activity word, readable title) or (None, None, None)."""
    parts = [p.strip() for p in title.split(",") if p.strip()]
    codes = [m.group(1) for p in parts if (m := _TE_CODE.match(p))]
    if not codes:
        return None, None, None
    activity = next((p for p in parts if guess_type(p)), None)
    return ", ".join(dict.fromkeys(codes)), activity, " / ".join(dict.fromkeys(codes)) + (
        f" {activity}" if activity else "")


@dataclass
class Event:
    start: datetime
    end: datetime
    title: str
    course: str | None = None
    type: str | None = None
    location: str | None = None
    description: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start"], d["end"] = self.start.isoformat(), self.end.isoformat()
        return d


def guess_type(text: str) -> str | None:
    for name, pat in _TYPES:
        if re.search(pat, text, re.I):
            return name
    return None


def _field(desc: str, *names: str) -> str | None:
    for n in names:
        m = re.search(rf"^\s*{n}\s*[:=]\s*(.+)$", desc, re.I | re.M)
        if m:
            return m.group(1).strip()
    return None


def parse_ics(data: bytes | str, tz) -> list[Event]:
    try:
        cal = Calendar.from_ical(data)
    except ValueError as e:
        raise ScheduleError("That is not a valid iCal (.ics) file.") from e
    events = []
    for c in cal.walk("VEVENT"):
        start = to_aware(c.decoded("DTSTART"), tz)
        end = to_aware(c.decoded("DTEND"), tz) if c.get("DTEND") else start
        title = str(c.get("SUMMARY", "")).strip()
        desc = str(c.get("DESCRIPTION", ""))
        te_course, te_activity, te_title = parse_timeedit_title(title)
        etype = ((_field(desc, "type", "typ", "aktivitetstyp") or "").lower()
                 or (guess_type(te_activity) if te_activity else None) or guess_type(f"{title} {desc}"))
        if not te_course and _HOLIDAYS.search(title):
            etype = "holiday"
        note = next((ln.strip() for ln in desc.splitlines() if ln.strip() and not ln.startswith("ID ")), "")
        loc = str(c.get("LOCATION", "")).strip() or None
        if loc is None and re.search(r"online", title, re.I):
            loc = "Online"
        events.append(Event(
            start=start, end=end, title=(f"{te_title} – {note}" if te_title and note else te_title or title),
            course=_field(desc, "course", "kurs", "kurskod") or te_course,
            type=etype, location=loc, description=desc,
        ))
    return events


def load_manual(tz, path: Path = MANUAL_FILE) -> list[Event]:
    if not path.exists():
        return []
    out = []
    for e in json.loads(path.read_text()):
        out.append(Event(
            start=parse_dt(e["start"], tz), end=parse_dt(e["end"], tz),
            title=e.get("title", ""), course=e.get("course"), type=e.get("type"),
            location=e.get("location"), description=e.get("description", "")))
    return out


def add_manual(event: Event, path: Path | None = None) -> None:
    path = path or MANUAL_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else []
    data.append(event.to_dict())
    path.write_text(json.dumps(data, indent=2))


def import_ics(src: Path, dest: Path = ICS_FILE) -> int:
    """Copy a user-supplied .ics into the config dir (validates it first)."""
    from .timeutil import get_tz
    n = len(parse_ics(Path(src).read_bytes(), get_tz()))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(src).read_bytes())
    return n


class ScheduleError(Exception):
    """The schedule source is unreachable or not an iCal file."""


class Schedule:
    def __init__(self, tz, ics_url: str | None = None, ics_file: Path | None = ICS_FILE,
                 manual_file: Path | None = MANUAL_FILE, cache=None,
                 transport: httpx.BaseTransport | None = None):
        self.tz = tz
        self.ics_url = ics_url
        self.ics_file = ics_file
        self.manual_file = manual_file
        self.cache = cache
        self.transport = transport

    def _from_url(self) -> list[Event]:
        def get(url: str) -> str:
            try:
                r = httpx.Client(transport=self.transport, timeout=20, follow_redirects=True).get(url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise ScheduleError(f"Could not fetch the schedule URL ({e.__class__.__name__}).") from e
            return r.text

        def fetch() -> str:
            text = get(self.ics_url)
            if not text.lstrip().startswith("BEGIN:VCALENDAR"):
                # TimeEdit view links end in .html; the same link ending in .ics is the calendar file
                if self.ics_url.split("?")[0].endswith(".html"):
                    alt = self.ics_url.replace(".html", ".ics", 1)
                    text = get(alt)
                if not text.lstrip().startswith("BEGIN:VCALENDAR"):
                    raise ScheduleError(
                        "The schedule link is a web page, not an iCal file. In TimeEdit use "
                        "'Subscribe' and copy the .ics link, or export the file and run "
                        "`uniassist schedule import FILE.ics`.")
            return text
        text = self.cache.get_or_fetch(f"ics|{self.ics_url}", fetch) if self.cache else fetch()
        if not str(text).lstrip().startswith("BEGIN:VCALENDAR"):
            text = fetch()          # a bad entry cached by an older run: ignore it and refetch
        return parse_ics(text, self.tz)

    def configured(self) -> bool:
        return bool(self.ics_url or (self.ics_file and self.ics_file.exists())
                    or (self.manual_file and self.manual_file.exists()))

    def events(self) -> list[Event]:
        evs: list[Event] = []
        if self.ics_file and self.ics_file.exists():
            evs += parse_ics(self.ics_file.read_bytes(), self.tz)
        if self.ics_url:
            evs += self._from_url()
        if self.manual_file:
            evs += load_manual(self.tz, self.manual_file)
        return sorted(evs, key=lambda e: e.start)

    def between(self, start: datetime, end: datetime) -> list[Event]:
        return [e for e in self.events() if e.end > start and e.start < end]
