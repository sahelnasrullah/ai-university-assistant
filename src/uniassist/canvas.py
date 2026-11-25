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
