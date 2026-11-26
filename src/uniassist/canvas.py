"""Read-only Canvas REST client (Instructure API).

Only GET requests are possible: there is no method for writing. Handles
pagination (Link headers), rate limits (429 / 403 'Rate Limit Exceeded'),
and maps error responses to clear exceptions.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

from .cache import Cache
from .timeutil import parse_dt


class CanvasError(Exception):
    pass


class CanvasAuthError(CanvasError):
    pass


@dataclass
class Course:
    id: int
    name: str
    code: str
    term: str | None = None
    current_grade: str | None = None
    current_score: float | None = None
    final_grade: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None

    @property
    def term_key(self) -> tuple[int, int] | None:
        """(year, 0=spring/1=autumn) parsed from names like 'DV2658 HT26 lp2 ...' or 'V25'."""
        m = _TERM.search(self.name) or _TERM.search(self.code)
        if not m:
            return None
        return 2000 + int(m.group(2)), 1 if m.group(1).upper().startswith("H") else 0

    def is_current(self, now: datetime) -> bool:
        """Canvas keeps every course ever taken. Current = this term or later.
        Courses with no term in the name (e.g. programme info) are kept."""
        if self.end_at and self.end_at < now:
            return False
        key = self.term_key
        if key is None:
            return True
        return key >= (now.year, 1 if now.month >= 7 else 0)


@dataclass
class Assignment:
    id: int
    course_id: int
    name: str
    due_at: datetime | None
    points_possible: float | None
    submitted: bool
    grade: str | None
    score: float | None
    url: str | None = None
    description: str = ""                 # untrusted HTML written by the teacher
    submission_types: list[str] = field(default_factory=list)
    rubric: list[dict] = field(default_factory=list)


@dataclass
class Announcement:
    id: int
    course_id: int
    title: str
    posted_at: datetime | None
    message: str  # untrusted free text


@dataclass
class Module:
    id: int
    course_id: int
    name: str
    items: list[str]


@dataclass
class CalendarEvent:
    id: int
    course_id: int | None
    title: str
    start: datetime | None
    end: datetime | None
    location: str | None
    description: str  # untrusted


@dataclass
class Feedback:
    course_id: int
    assignment_id: int
    score: float | None
    grade: str | None
    late: bool
    missing: bool
    excused: bool
    graded_at: datetime | None
    comments: list[dict]  # [{author, text(untrusted), at}]


@dataclass
class Page:
    title: str
    slug: str
    updated_at: datetime | None
    body: str = ""  # untrusted


@dataclass
class FileInfo:
    name: str
    size: int | None
    updated_at: datetime | None
    url: str | None


_TERM = re.compile(r"\b(HT|VT|H|V)(\d{2})\b", re.I)
_NEXT = re.compile(r'<([^>]+)>;\s*rel="next"')


class CanvasClient:
    def __init__(self, base_url: str, token: str, tz, cache: Cache | None = None,
                 transport: httpx.BaseTransport | None = None, max_retries: int = 3,
                 sleep=time.sleep):
        self.base_url = base_url.rstrip("/")
        self.tz = tz
        self.cache = cache or Cache(None, 0)
        self.max_retries = max_retries
        self._sleep = sleep
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
            transport=transport,
        )

    # ---- low level -------------------------------------------------------
    def _get_page(self, url: str, params: Any = None) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            try:
                r = self._http.get(url, params=params)
            except httpx.HTTPError as e:
                raise CanvasError(f"Network error talking to Canvas: {e.__class__.__name__}") from e
            limited = r.status_code == 429 or (
                r.status_code == 403 and "rate limit" in r.text.lower())
            if limited and attempt < self.max_retries:
                self._sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code == 401:
                raise CanvasAuthError("Canvas rejected the token (401). It may be expired or revoked.")
            if r.status_code == 403:
                raise CanvasError("Canvas denied access (403) to this resource.")
            if r.status_code == 404:
                raise CanvasError("Canvas resource not found (404).")
            if r.status_code >= 400:
                raise CanvasError(f"Canvas error {r.status_code}.")
            return r
        raise CanvasError("Canvas rate limit: gave up after retries.")

    def _get_all(self, path: str, params: list[tuple[str, str]] | None = None) -> list[dict]:
        params = list(params or []) + [("per_page", "100")]

        def fetch() -> list[dict]:
            out: list[dict] = []
            r = self._get_page(path, params)
            out.extend(r.json())
            while (m := _NEXT.search(r.headers.get("Link", ""))):
                r = self._get_page(m.group(1))  # absolute URL incl. query
                out.extend(r.json())
            return out

        key = f"{self.base_url}|{path}|{sorted(params)}"
        return self.cache.get_or_fetch(key, fetch)

    def _get_one(self, path: str, params: list[tuple[str, str]] | None = None) -> dict:
        key = f"{self.base_url}|{path}|{sorted(params or [])}"
        return self.cache.get_or_fetch(key, lambda: self._get_page(path, params).json())

    @property
    def fetched_at(self) -> datetime | None:
        return self.cache.last_fetch_at() if hasattr(self.cache, "last_fetch_at") else None

    # ---- high level ------------------------------------------------------
    def courses(self) -> list[Course]:
        raw = self._get_all("/api/v1/courses", [
            ("enrollment_state", "active"), ("include[]", "total_scores"),
            ("include[]", "term")])
        out = []
        for c in raw:
            if c.get("access_restricted_by_date") or "name" not in c:
                continue
            enr = next((e for e in c.get("enrollments", []) if e.get("type") == "student"), {})
            out.append(Course(
                id=c["id"], name=c["name"], code=c.get("course_code") or c["name"],
                term=(c.get("term") or {}).get("name"),
                current_grade=enr.get("computed_current_grade"),
                current_score=enr.get("computed_current_score"),
                final_grade=enr.get("computed_final_grade"),
                start_at=parse_dt((c.get("term") or {}).get("start_at") or c.get("start_at"), self.tz),
                end_at=parse_dt(c.get("end_at") or (c.get("term") or {}).get("end_at"), self.tz),
            ))
        return out

    def assignments(self, course_id: int) -> list[Assignment]:
        raw = self._get_all(f"/api/v1/courses/{course_id}/assignments", [
            ("include[]", "submission"), ("order_by", "due_at")])
        out = []
        for a in raw:
            sub = a.get("submission") or {}
            out.append(Assignment(
                id=a["id"], course_id=course_id, name=a["name"],
                due_at=parse_dt(a.get("due_at"), self.tz),
                points_possible=a.get("points_possible"),
                submitted=bool(sub.get("submitted_at")),
                grade=sub.get("grade") if sub.get("workflow_state") == "graded" else None,
                score=sub.get("score") if sub.get("workflow_state") == "graded" else None,
                url=a.get("html_url"),
                description=a.get("description") or "",
                submission_types=a.get("submission_types") or [],
                rubric=[{"criterion": r.get("description", ""), "points": r.get("points")}
                        for r in (a.get("rubric") or [])],
            ))
        return out

    def announcements(self, course_id: int) -> list[Announcement]:
        raw = self._get_all("/api/v1/announcements",
                            [("context_codes[]", f"course_{course_id}")])
        return [Announcement(
            id=a["id"], course_id=course_id, title=a.get("title", ""),
            posted_at=parse_dt(a.get("posted_at"), self.tz),
            message=a.get("message") or "") for a in raw]

    def modules(self, course_id: int) -> list[Module]:
        raw = self._get_all(f"/api/v1/courses/{course_id}/modules", [("include[]", "items")])
        return [Module(id=m["id"], course_id=course_id, name=m["name"],
                       items=[i.get("title", "") for i in m.get("items", [])]) for m in raw]

    # ---- extra read-only endpoints ---------------------------------------
    def calendar_events(self, course_ids: list[int], start: datetime, end: datetime) -> list[CalendarEvent]:
        out: list[CalendarEvent] = []
        for i in range(0, len(course_ids), 10):  # Canvas allows max 10 context codes
            codes = [("context_codes[]", f"course_{c}") for c in course_ids[i:i + 10]]
            raw = self._get_all("/api/v1/calendar_events", codes + [
                ("type", "event"), ("start_date", start.date().isoformat()),
                ("end_date", end.date().isoformat())])
            for e in raw:
                cc = str(e.get("context_code", ""))
                out.append(CalendarEvent(
                    id=e["id"], course_id=int(cc.removeprefix("course_")) if cc.startswith("course_") else None,
                    title=e.get("title", ""), start=parse_dt(e.get("start_at"), self.tz),
                    end=parse_dt(e.get("end_at"), self.tz), location=e.get("location_name") or None,
                    description=e.get("description") or ""))
        return sorted(out, key=lambda x: x.start or datetime.max.replace(tzinfo=self.tz))

    def missing_submissions(self) -> list[Assignment]:
        raw = self._get_all("/api/v1/users/self/missing_submissions")
        return [Assignment(
            id=a["id"], course_id=a.get("course_id", 0), name=a["name"],
            due_at=parse_dt(a.get("due_at"), self.tz), points_possible=a.get("points_possible"),
            submitted=False, grade=None, score=None, url=a.get("html_url"),
            description=a.get("description") or "",
            submission_types=a.get("submission_types") or []) for a in raw]

    def todo(self) -> list[dict]:
        out = []
        for t in self._get_all("/api/v1/users/self/todo"):
            a = t.get("assignment") or {}
            out.append({"type": t.get("type"), "course_id": t.get("course_id"),
                        "name": a.get("name") or t.get("title"),
                        "due_at": parse_dt(a.get("due_at"), self.tz), "url": t.get("html_url")})
        return out

    def feedback(self, course_id: int, assignment_id: int) -> Feedback:
        s = self._get_one(f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/self",
                          [("include[]", "submission_comments")])
        return Feedback(
            course_id=course_id, assignment_id=assignment_id, score=s.get("score"),
            grade=s.get("grade") if s.get("workflow_state") == "graded" else None,
            late=bool(s.get("late")), missing=bool(s.get("missing")), excused=bool(s.get("excused")),
            graded_at=parse_dt(s.get("graded_at"), self.tz),
            comments=[{"author": c.get("author_name", ""), "text": c.get("comment", ""),
                       "at": c.get("created_at")} for c in s.get("submission_comments", [])])

    def syllabus(self, course_id: int) -> str:
        c = self._get_one(f"/api/v1/courses/{course_id}", [("include[]", "syllabus_body")])
        return c.get("syllabus_body") or ""

    def pages(self, course_id: int) -> list[Page]:
        raw = self._get_all(f"/api/v1/courses/{course_id}/pages")
        return [Page(title=p.get("title", ""), slug=p.get("url", ""),
                     updated_at=parse_dt(p.get("updated_at"), self.tz)) for p in raw]

    def page(self, course_id: int, slug: str) -> Page:
        p = self._get_one(f"/api/v1/courses/{course_id}/pages/{slug}")
        return Page(title=p.get("title", ""), slug=slug,
                    updated_at=parse_dt(p.get("updated_at"), self.tz), body=p.get("body") or "")

    def files(self, course_id: int) -> list[FileInfo]:
        raw = self._get_all(f"/api/v1/courses/{course_id}/files", [("sort", "updated_at"), ("order", "desc")])
        return [FileInfo(name=f.get("display_name", ""), size=f.get("size"),
                         updated_at=parse_dt(f.get("updated_at"), self.tz), url=f.get("url"))
                for f in raw]

    def teachers(self, course_id: int) -> list[str]:
        raw = self._get_all(f"/api/v1/courses/{course_id}/users", [("enrollment_type[]", "teacher")])
        return [u.get("name", "") for u in raw]
