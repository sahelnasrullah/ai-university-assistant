from datetime import datetime

from uniassist.schedule import Event, Schedule, add_manual, parse_ics, guess_type
from uniassist import mock


def test_parse_ics_fields(tz):
    evs = mock.mock_schedule(tz).events()
    e = next(x for x in evs if "Lecture 9" in x.title)
    assert e.course == "Generative AI" and e.type == "lecture" and e.location == "J1630"
    assert e.start.hour == 13 and e.start.minute == 15  # 12:15Z -> CET


def test_manual_entries_merge(tz, tmp_path):
    f = tmp_path / "s.json"
    add_manual(Event(datetime(2026, 12, 1, 9, 0, tzinfo=tz), datetime(2026, 12, 1, 10, 0, tzinfo=tz),
                     "Seminar X", "Generative AI", "seminar"), f)
    s = Schedule(tz, ics_file=None, manual_file=f)
    assert s.configured() and s.events()[0].title == "Seminar X"


def test_not_configured(tz, tmp_path):
    assert not Schedule(tz, ics_file=tmp_path / "no.ics", manual_file=tmp_path / "no.json").configured()


def test_guess_type():
    assert guess_type("Föreläsning 3") == "lecture"
    assert guess_type("DV1 Lab 2") == "lab"


# ---- iCal URL handling (found on a real TimeEdit link) ------------------------------------

def _transport(routes):
    import httpx
    return httpx.MockTransport(lambda r: routes[str(r.url).split("?")[0]](r))


def test_timeedit_html_link_is_upgraded_to_ics(tz):
    import httpx
    ics = open(str(mock._data_path("schedule.ics"))).read()
    seen = []

    def html(r):
        seen.append("html")
        return httpx.Response(200, text="<!DOCTYPE html><html>login</html>", headers={"content-type": "text/html"})

    def cal(r):
        seen.append("ics")
        return httpx.Response(200, text=ics, headers={"content-type": "text/calendar"})
    s = Schedule(tz, ics_url="https://cloud.example/bth/ri123.html", ics_file=None, manual_file=None,
                 transport=_transport({"https://cloud.example/bth/ri123.html": html,
                                       "https://cloud.example/bth/ri123.ics": cal}))
    assert len(s.events()) == 4 and seen == ["html", "ics"]


def test_non_calendar_link_gives_clear_error(tz):
    import httpx
    import pytest
    from uniassist.schedule import ScheduleError
    s = Schedule(tz, ics_url="https://x.example/page", ics_file=None, manual_file=None,
                 transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html>no</html>")))
    with pytest.raises(ScheduleError, match="web page, not an iCal"):
        s.events()


def test_bad_cached_entry_is_ignored(tz, tmp_path):
    import httpx
    from uniassist.cache import Cache
    ics = open(str(mock._data_path("schedule.ics"))).read()
    cache = Cache(tmp_path, 300)
    cache.get_or_fetch("ics|https://x.example/a.ics", lambda: "<html>stale junk</html>")
    s = Schedule(tz, ics_url="https://x.example/a.ics", ics_file=None, manual_file=None, cache=cache,
                 transport=httpx.MockTransport(lambda r: httpx.Response(200, text=ics)))
    assert len(s.events()) == 4


def test_tools_report_schedule_errors_instead_of_crashing(ctx, tz):
    import httpx
    from uniassist.tools import get_next_lecture, get_schedule
    from uniassist.summary import briefing
    ctx.schedule = Schedule(tz, ics_url="https://x.example/p", ics_file=None, manual_file=None,
                            transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html/>")))
    assert get_next_lecture(ctx)["status"] == "error"
    assert get_schedule(ctx, date_range="today")["status"] == "error"
    assert "Lab 3" in briefing(ctx)          # the rest of the briefing still works
