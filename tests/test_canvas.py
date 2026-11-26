import httpx
import pytest

from uniassist.canvas import CanvasAuthError, CanvasClient, CanvasError
from uniassist import mock


def test_pagination_and_normalisation(tz):
    c = mock.mock_canvas(tz)
    a = c.assignments(101)
    assert [x.name for x in a] == ["Assignment 1", "Assignment 2", "Project Report",
                                   "Optional Reading Quiz"]  # 2 pages of 2
    assert a[0].grade == "18" and a[0].submitted
    assert a[1].due_at.isoformat() == "2026-11-27T23:59:59+01:00"  # UTC -> Stockholm
    assert a[3].due_at is None


def test_restricted_course_skipped(tz):
    assert [c.name for c in mock.mock_canvas(tz).courses()] == [
        "Generative AI", "Software Architecture", "MOCK Old Course VT25 Databases"]


def test_bad_token(tz):
    c = CanvasClient(mock.MOCK_BASE, "wrong", tz, transport=mock._canvas_transport())
    with pytest.raises(CanvasAuthError):
        c.courses()


def test_rate_limit_retry(tz):
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        if n["calls"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json=[])

    sleeps = []
    c = CanvasClient("https://x.test", "t", tz, transport=httpx.MockTransport(handler),
                     sleep=sleeps.append)
    assert c.courses() == [] and n["calls"] == 3 and len(sleeps) == 2


def test_rate_limit_gives_up(tz):
    c = CanvasClient("https://x.test", "t", tz, max_retries=1, sleep=lambda s: None,
                     transport=httpx.MockTransport(lambda r: httpx.Response(429)))
    with pytest.raises(CanvasError):
        c.courses()


def test_client_is_read_only(tz):
    assert not any(hasattr(CanvasClient, m) for m in ("post", "put", "delete", "update", "submit"))
