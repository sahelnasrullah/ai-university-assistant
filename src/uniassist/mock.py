"""Mock Canvas + schedule + programme, so everything runs without real student data.

The mock serves raw Canvas-shaped JSON through httpx.MockTransport, so the real
CanvasClient code path (pagination, normalisation) is exercised.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from importlib import resources
from pathlib import Path

import httpx

from .canvas import CanvasClient
from .schedule import Schedule
from .programme import Programme
from .timeutil import get_tz

MOCK_BASE = "https://canvas.example"


def mock_now(tz=None) -> datetime:
    """Fixed 'now' so evaluation ground truth is stable."""
    return datetime(2026, 11, 25, 10, 0, tzinfo=tz or get_tz())


def _data_path(name: str) -> Path:
    return Path(str(resources.files("uniassist") / "mockdata" / name))


def _canvas_transport() -> httpx.MockTransport:
    data = json.loads(_data_path("canvas.json").read_text())
    size = data["page_size"]

    def paged(request: httpx.Request, items: list) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        chunk = items[(page - 1) * size: page * size]
        headers = {}
        if page * size < len(items):
            nxt = request.url.copy_with(params=[("page", str(page + 1))])
            headers["Link"] = f'<{nxt}>; rel="next"'
        return httpx.Response(200, json=chunk, headers=headers)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers.get("Authorization") != "Bearer mock-token":
            return httpx.Response(401, json={"errors": [{"message": "Invalid access token."}]})
        if request.method != "GET":
            return httpx.Response(405)
        path = request.url.path
        if path == "/api/v1/courses":
            return paged(request, data["courses"])
        if path == "/api/v1/announcements":
            cid = request.url.params.get("context_codes[]", "").removeprefix("course_")
            return paged(request, data["announcements"].get(cid, []))
        m = re.fullmatch(r"/api/v1/courses/(\d+)/(assignments|modules)", path)
        if m:
            return paged(request, data[m.group(2)].get(m.group(1), []))
        if path == "/api/v1/calendar_events":
            return paged(request, data["calendar_events"])
        if path == "/api/v1/users/self/missing_submissions":
            return paged(request, data["missing"])
        if path == "/api/v1/users/self/todo":
            return paged(request, data["todo"])
        m = re.fullmatch(r"/api/v1/courses/(\d+)", path)
        if m:
            return httpx.Response(200, json={"id": int(m.group(1)),
                                             "syllabus_body": data["syllabus"].get(m.group(1), "")})
        m = re.fullmatch(r"/api/v1/courses/(\d+)/pages", path)
        if m:
            return paged(request, data["pages"].get(m.group(1), []))
        m = re.fullmatch(r"/api/v1/courses/(\d+)/pages/([\w-]+)", path)
        if m:
            body = data["page_bodies"].get(f"{m.group(1)}/{m.group(2)}")
            return httpx.Response(200, json=body) if body else httpx.Response(404)
        m = re.fullmatch(r"/api/v1/courses/(\d+)/files", path)
        if m:
            if m.group(1) in data["files_forbidden"]:
                return httpx.Response(403, json={"errors": [{"message": "unauthorized"}]})
            return paged(request, data["files"].get(m.group(1), []))
        m = re.fullmatch(r"/api/v1/courses/(\d+)/users", path)
        if m:
            return paged(request, data["teachers"].get(m.group(1), []))
        m = re.fullmatch(r"/api/v1/courses/(\d+)/assignments/(\d+)/submissions/self", path)
        if m:
            return httpx.Response(200, json=data["feedback"].get(m.group(2), {"workflow_state": "unsubmitted"}))
        return httpx.Response(404, json={"errors": [{"message": "not found"}]})

    return httpx.MockTransport(handler)


def mock_canvas(tz=None) -> CanvasClient:
    return CanvasClient(MOCK_BASE, "mock-token", tz or get_tz(), transport=_canvas_transport())


def mock_schedule(tz=None) -> Schedule:
    return Schedule(tz or get_tz(), ics_url=None, ics_file=_data_path("schedule.ics"),
                    manual_file=None)


def mock_programme() -> Programme:
    return Programme(_data_path("programme.json"))
