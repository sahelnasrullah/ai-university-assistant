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
