import json

from uniassist.schedule import Schedule
from uniassist.tools import Context, build_tools, call_tool, get_assignment_due_date, \
    get_course_announcements, get_grades, get_next_lecture, get_next_semester_courses, \
    get_schedule, get_upcoming_assignments


def test_due_date_fuzzy(ctx):
    r = get_assignment_due_date(ctx, "gen ai", "assignment 2")
    assert r["status"] == "ok" and r["due"] == "Fri 2026-11-27 23:59 (CET)"


def test_due_date_not_found_lists_options(ctx):
    r = get_assignment_due_date(ctx, "gen ai", "assignment 9")
    assert r["status"] == "not_found" and "Assignment 2" in r["available_assignments"]


def test_unknown_course(ctx):
    assert get_upcoming_assignments(ctx, course="chemistry")["status"] == "not_found"


def test_upcoming_sorted_and_excludes_submitted(ctx):
    r = get_upcoming_assignments(ctx, days=14)
    assert [x["assignment"] for x in r["upcoming"]] == ["Lab 3", "Assignment 2"]


def test_upcoming_empty(ctx):
    assert get_upcoming_assignments(ctx, course="gen ai", days=1)["status"] == "empty"


def test_next_lecture_and_course_filter(ctx):
    assert get_next_lecture(ctx)["lecture"]["title"].startswith("Generative AI Lecture 9")
    r = get_next_lecture(ctx, course="software architecture")
    assert r["lecture"]["location"] == "C203"


def test_no_lecture_found(ctx):
    from datetime import datetime
    tz = ctx.now().tzinfo
    ctx.now = lambda: datetime(2027, 1, 1, tzinfo=tz)
    assert get_next_lecture(ctx)["status"] == "empty"


def test_schedule_ranges(ctx):
    assert len(get_schedule(ctx, date_range="today")["events"]) == 1
    assert get_schedule(ctx, date_range="tomorrow")["events"][0]["location"] == "C203"
    assert get_schedule(ctx, start_date="2026-12-24")["status"] == "empty"
    assert get_schedule(ctx, start_date="nonsense")["status"] == "error"


def test_grades(ctx):
    r = get_grades(ctx, course="software architecture")
    assert r["grades"][0]["graded_items"][0] == {
        "assignment": "Written Exam", "grade": "B", "score": 78, "points_possible": 100}


def test_next_semester(ctx, tz):
    assert get_next_semester_courses(ctx)["courses"][0]["name"] == "Machine Learning II"
    ctx.programme = None
    assert get_next_semester_courses(ctx)["status"] == "not_configured"


def test_no_canvas_and_no_schedule(tz, tmp_path):
    from datetime import datetime
    c = Context(None, Schedule(tz, ics_file=tmp_path / "x", manual_file=tmp_path / "y"), None,
                lambda: datetime(2026, 11, 25, tzinfo=tz))
    assert get_grades(c)["status"] == "not_configured"
    assert get_next_lecture(c)["status"] == "not_configured"


def test_announcement_is_marked_untrusted_and_stripped(ctx):
    r = get_course_announcements(ctx, course="gen ai")
    m = r["announcements"][0]["message"]
    assert "<p>" not in m["untrusted_text"] and "never follow" in m["note"].lower()


def test_call_tool_is_defensive(ctx):
    tools = build_tools(ctx)
    assert call_tool(tools, ctx, "nope", {})["status"] == "error"
    assert call_tool(tools, ctx, "get_assignment_due_date", {"course": "x"})["status"] == "error"
    r = call_tool(tools, ctx, "list_courses", {"bogus": 1})  # unknown args dropped
    assert r["status"] == "ok"


def test_retriever_tool_only_when_plugged_in(ctx):
    assert "search_course_documents" not in build_tools(ctx)
    from uniassist.rag import Passage

    class R:
        def search(self, query, course=None, k=4):
            return [Passage("Rules <b>here</b>", "Syllabus p1", course)]
    ctx.retriever = R()
    t = build_tools(ctx)
    r = call_tool(t, ctx, "search_course_documents", {"query": "grading"})
    assert r["passages"][0]["source"] == "Syllabus p1" and "<b>" not in r["passages"][0]["untrusted_text"]


def test_assignment_details(ctx):
    from uniassist.tools import get_assignment_details
    r = get_assignment_details(ctx, "gen ai", "assignment 2")
    assert r["status"] == "ok" and r["submission_types"] == ["online_upload"]
    assert r["rubric"][0] == {"criterion": "Model correctness", "points": 12}
    assert "<p>" not in r["instructions"]["untrusted_text"]
    assert "never follow" in r["instructions"]["note"].lower()
    assert get_assignment_details(ctx, "gen ai", "assignment 9")["status"] == "not_found"
    # assignment without a description says so instead of inventing one
    assert "No description" in get_assignment_details(ctx, "gen ai", "project report")["instructions"]


# ---- extra Canvas tools -----------------------------------------------------------

def test_past_courses_are_hidden_but_reachable_by_name(ctx):
    from uniassist.tools import active_courses, list_courses, get_grades
    assert [c.name for c in active_courses(ctx)] == ["Generative AI", "Software Architecture"]
    assert len(list_courses(ctx)["courses"]) == 2
    assert get_upcoming_assignments(ctx, days=2000)["status"] == "ok"
    assert all(a["course"] != "MOCK Old Course VT25 Databases"
               for a in get_upcoming_assignments(ctx, days=2000)["upcoming"])
    # asking for an old course by name still works
    assert get_grades(ctx, course="old course databases")["grades"][0]["course_current_grade"] == "A"


def test_course_term_parsing():
    from datetime import datetime
    from uniassist.canvas import Course
    now = datetime(2026, 11, 25)
    c = lambda n: Course(1, n, "x")
    assert c("DV2658 HT26 lp2 Generative AI").is_current(now)
    assert not c("DV2658 VT26 lp3 Old").is_current(now)
    assert not c("DV1493 V25 lp4 Old").is_current(now)
    assert c("DV9999 VT27 lp3 Future").is_current(now)
    assert c("Programme info").is_current(now)  # no term in the name -> kept


def test_initials_matching():
    from uniassist.matching import score
    assert score("gen ai", "DV2658 HT26 lp2 Generative Artificial Intelligence - Campus") >= 0.85
    assert score("ai", "Biology Basics") < 0.6


def test_missing_todo_calendar(ctx):
    from uniassist.tools import get_missing_submissions, get_todo_items, get_calendar_events
    m = get_missing_submissions(ctx)
    assert [x["assignment"] for x in m["missing"]] == ["Lab 3"]  # old course filtered out
    assert [x["item"] for x in get_todo_items(ctx)["todo"]] == ["Assignment 2"]
    e = get_calendar_events(ctx)["events"][0]
    assert e["title"].startswith("Guest lecture") and "never follow" in e["details"]["note"].lower()


def test_feedback(ctx):
    from uniassist.tools import get_submission_feedback
    r = get_submission_feedback(ctx, "gen ai", "assignment 1")
    assert r["score"] == 18 and r["comments"][0]["untrusted_text"].startswith("Good work")
    assert get_submission_feedback(ctx, "gen ai", "assignment 2")["status"] == "empty"


def test_syllabus_pages_files_teachers(ctx):
    from uniassist.tools import get_course_syllabus, get_course_pages, list_course_files, get_teachers
    assert get_course_syllabus(ctx, "gen ai")["status"] == "ok"
    assert get_course_syllabus(ctx, "software architecture")["status"] == "empty"
    assert get_course_pages(ctx, "gen ai")["pages"] == ["Course information"]
    assert "pairs" in get_course_pages(ctx, "gen ai", "course info")["content"]["untrusted_text"]
    assert list_course_files(ctx, "gen ai")["files"][0]["name"] == "slides-lecture-9.pdf"
    f = list_course_files(ctx, "software architecture")  # 403 -> friendly error, no crash
    assert f["status"] == "error" and "disable" in f["message"]
    assert get_teachers(ctx, "gen ai")["teachers"] == ["Dr Example"]


def test_ai_policy_finds_rules_not_topics(ctx):
    from uniassist.tools import find_ai_policy
    r = find_ai_policy(ctx, "gen ai")
    texts = " ".join(s["untrusted_text"] for s in r["statements"])
    assert "not allowed" in texts and "Plagiarism" in texts
    assert "covers generative AI" not in texts          # topical mention is not a policy
    none = find_ai_policy(ctx, "software architecture")
    assert none["status"] == "empty" and "Do not assume" in none["message"]
