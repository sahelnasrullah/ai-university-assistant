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
    ("lecture", r"lecture|föreläsning|forelasning|\bfl\b"),
    ("lab", r"\blab|laboration"),
    ("seminar", r"seminar"),
    ("exercise", r"exercise|övning|ovning|tutorial"),
    ("exam", r"exam|tenta|tentamen"),
]


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
    cal = Calendar.from_ical(data)
    events = []
    for c in cal.walk("VEVENT"):
        start = to_aware(c.decoded("DTSTART"), tz)
        end = to_aware(c.decoded("DTEND"), tz) if c.get("DTEND") else start
        title = str(c.get("SUMMARY", "")).strip()
        desc = str(c.get("DESCRIPTION", ""))
        events.append(Event(
            start=start, end=end, title=title,
            course=_field(desc, "course", "kurs", "kurskod"),
            type=(_field(desc, "type", "typ", "aktivitetstyp") or "").lower()
                 or guess_type(f"{title} {desc}"),
            location=str(c.get("LOCATION", "")).strip() or None,
            description=desc,
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
        def fetch() -> str:
            try:
                r = httpx.Client(transport=self.transport, timeout=20).get(self.ics_url)
                r.raise_for_status()
            except httpx.HTTPError as e:
                raise RuntimeError(f"Could not fetch the schedule URL ({e.__class__.__name__}).") from e
            return r.text
        text = self.cache.get_or_fetch(f"ics|{self.ics_url}", fetch) if self.cache else fetch()
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
