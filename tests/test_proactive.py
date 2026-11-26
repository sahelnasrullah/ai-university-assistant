import json
from datetime import datetime, timedelta

from uniassist import alerts, notify, planner
from uniassist.schedule import Event, Schedule, add_manual
from uniassist.summary import briefing, week_overview


def test_estimates():
    assert planner.estimate_hours("Peer Evaluation Survey", 0) == 0.5
    assert planner.estimate_hours("Project Report", 50) == 8
    assert planner.estimate_hours("Assignment 2", 20) == 4
    assert planner.estimate_hours("Mystery", None) == 3


def test_priorities_sorted_by_slack_with_reasons(ctx):
    r = planner.prioritise(ctx)
    assert [x["assignment"] for x in r] == ["Lab 3", "Assignment 2", "Project Report"]
    assert "due in 38 h" in r[0]["why"] and "estimate" in r[0]["why"]


def test_plan_respects_daily_capacity_and_reports_shortfall(ctx):
    p = planner.make_plan(ctx, days=5, hours_per_day=3)
    for d in p["days"]:
        assert d["total_hours"] <= 3
        names = [s["assignment"] for s in d["sessions"]]
        assert len(names) == len(set(names))            # one entry per assignment per day
    planned = {}
    for d in p["days"]:
        for s in d["sessions"]:
            planned[s["assignment"]] = planned.get(s["assignment"], 0) + s["hours"]
    short = {m["assignment"]: m["missing_hours"] for m in p["not_enough_time"]}
    assert planned["Lab 3"] + short.get("Lab 3", 0) == 3        # nothing silently dropped
    assert planned["Assignment 2"] + short.get("Assignment 2", 0) == 4


def test_nothing_planned_after_deadline(ctx):
    p = planner.make_plan(ctx, days=14)
    for d in p["days"]:
        for s in d["sessions"]:
            due = next(t for t in planner.collect_tasks(ctx) if t.name == s["assignment"]).due
            assert datetime.fromisoformat(d["date"]).date() <= due.date()


def test_clash_detection(ctx, tz, tmp_path, monkeypatch):
    f = tmp_path / "m.json"
    t0 = datetime(2026, 11, 26, 9, 0, tzinfo=tz)
    add_manual(Event(t0, t0 + timedelta(hours=2), "Seminar A"), f)
    add_manual(Event(t0 + timedelta(hours=1), t0 + timedelta(hours=3), "Seminar B"), f)
    ctx.schedule = Schedule(tz, ics_file=None, manual_file=f)
    kinds = {c["kind"] for c in planner.find_clashes(ctx)}
    assert "schedule_overlap" in kinds
    assert "deadline_on_busy_day" in kinds                  # Thu: Lab 3 due + 4 h of classes

    same_day = [planner.Task("A", "x", t0, 1, 1), planner.Task("B", "y", t0, 1, 1)]
    monkeypatch.setattr(planner, "collect_tasks", lambda *a, **k: same_day)
    assert any(c["kind"] == "deadline_cluster" for c in planner.find_clashes(ctx))


def test_briefing_and_week(ctx):
    b = briefing(ctx)
    assert "Start with:" in b and "Lab 3" in b
    w = week_overview(ctx)
    assert "DUE" in w and "class" in w and "study" in w


# ---- alerts ---------------------------------------------------------------------

def test_first_run_is_baseline_then_quiet(ctx, tmp_path):
    snap = tmp_path / "s.json"
    a, first = alerts.check_changes(ctx, snap)
    assert first and a == []
    a, first = alerts.check_changes(ctx, snap)
    assert not first and a == []
    assert oct(snap.stat().st_mode & 0o777) == "0o600"


def test_diff_detects_changes(ctx):
    old = alerts.take_snapshot(ctx)
    new = json.loads(json.dumps(old))
    k = next(k for k, v in new["assignments"].items() if v["name"] == "Assignment 2")
    new["assignments"][k]["due"] = "2026-12-01T23:59:00+01:00"
    new["assignments"]["101:9999"] = {"course": "Generative AI", "name": "Assignment 3", "due": None}
    new["announcements"]["101:1"] = {"course": "Generative AI", "title": "Lecture moved", "important": True}
    new["grades"]["101:1012"] = {"course": "Generative AI", "name": "Assignment 2", "grade": "A", "score": 20}
    kinds = {a.kind: a for a in alerts.diff(old, new)}
    assert set(kinds) == {"due_changed", "new_assignment", "announcement", "new_grade"}
    assert "mentions a change" in kinds["announcement"].text


def test_announcement_importance_ignores_body_instructions(ctx):
    snap = alerts.take_snapshot(ctx)
    ann = snap["announcements"]
    assert all(set(v) == {"course", "title", "important"} for v in ann.values())  # no body stored


def test_deadline_warnings_and_dedup(ctx, tmp_path):
    w = alerts.deadline_warnings(ctx, within_hours=48)
    assert [a.title for a in w] == ["Due in 38 h: Lab 3"]
    n = tmp_path / "n.json"
    assert len(alerts.only_new(w, n)) == 1
    assert alerts.only_new(w, n) == []                      # not repeated on the next timer run


def test_notify_never_uses_a_shell(monkeypatch):
    calls = []
    monkeypatch.setattr(notify.shutil, "which", lambda x: "/usr/bin/notify-send")
    monkeypatch.setattr(notify.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    assert notify.send("$(rm -rf ~)", "; reboot")
    argv = calls[0][0][0]
    assert isinstance(argv, list) and argv[-2:] == ["$(rm -rf ~)", "; reboot"] and "--" in argv
    assert not calls[0][1].get("shell")


def test_notify_missing_binary(monkeypatch):
    monkeypatch.setattr(notify.shutil, "which", lambda x: None)
    assert notify.send("a", "b") is False
