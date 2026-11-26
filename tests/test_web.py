import json
import threading
import urllib.error
import urllib.request

import pytest

from uniassist.llm import ScriptedLLM
from uniassist.web import App, serve  # noqa: F401


def say(t):
    return {"role": "assistant", "content": t}


@pytest.fixture
def app(ctx, tmp_path, monkeypatch):
    from uniassist import tutor
    monkeypatch.setattr(tutor, "STATE", tmp_path / "t.json")
    a = App(ctx, ScriptedLLM([say("A hint."), say("Answer.")] * 5), 8765)
    a.tutor.state_path = tmp_path / "t.json"
    return a


H = {"Host": "localhost:8765"}


def get(app, path, headers=H):
    s, h, b = app.handle("GET", path, headers)
    return s, h, b


def post(app, path, data, token=True, host="localhost:8765", ctype="application/json"):
    hdr = {"Host": host, "Content-Type": ctype, **({"X-Token": app.token} if token else {})}
    s, h, b = app.handle("POST", path, hdr, json.dumps(data).encode())
    return s, json.loads(b)


def test_page_has_token_csp_and_no_inline_data(app):
    s, h, b = get(app, "/")
    html = b.decode()
    assert s == 200 and app.token in html
    csp = h["Content-Security-Policy"]
    assert "default-src 'none'" in csp and "nonce-" in csp and "unsafe-inline" not in csp
    assert "innerHTML" not in html and "eval(" not in html     # data is only ever rendered as text


def test_host_header_must_be_local(app):          # DNS-rebinding protection
    assert get(app, "/api/dashboard", {"Host": "evil.example:8765"})[0] == 403
    assert get(app, "/api/dashboard", {})[0] == 403
    assert get(app, "/api/dashboard", {"Host": "localhost:9999"})[0] == 403


def test_post_requires_token_and_json(app):
    assert post(app, "/api/ask", {"question": "hi"}, token=False)[0] == 403
    assert post(app, "/api/ask", {"question": "hi"}, ctype="text/plain")[0] == 415
    assert post(app, "/api/ask", {"question": "hi"}, host="evil.test")[0] == 403
    assert post(app, "/api/ask", {"question": "hi"})[0] == 200


def test_oversized_and_malformed_bodies(app):
    hdr = {"Host": "localhost:8765", "Content-Type": "application/json", "X-Token": app.token}
    assert app.handle("POST", "/api/ask", hdr, b"x" * 70000)[0] == 413
    assert app.handle("POST", "/api/ask", hdr, b"{not json")[0] == 400
    assert app.handle("POST", "/api/ask", hdr, b"[1,2]")[0] == 400
    assert app.handle("DELETE", "/api/ask", hdr)[0] == 405


def test_dashboard_courses_assignments(app):
    s, _, b = get(app, "/api/dashboard")
    d = json.loads(b)
    assert s == 200 and d["today"][0]["title"].startswith("Generative AI Lecture 9")
    assert [x["assignment"] for x in d["deadlines"]] == ["Lab 3", "Assignment 2"]
    assert d["start_with"][0]["assignment"] == "Lab 3" and "7 days" not in d["note"]
    c = json.loads(get(app, "/api/courses")[2])["courses"]
    assert [x["name"] for x in c] == ["Generative AI", "Software Architecture"]   # old course hidden
    a = json.loads(get(app, f"/api/assignments?course={c[0]['id']}")[2])["assignments"]
    assert [x["name"] for x in a][:2] == ["Assignment 1", "Assignment 2"] and a[0]["submitted"]


def test_assignment_detail_has_policy_first(app):
    d = json.loads(get(app, "/api/assignment?course=101&id=1012")[2])
    assert d["name"] == "Assignment 2" and d["policy"]["status"] == "ok"
    assert d["rubric"][0]["criterion"] == "Model correctness"
    assert "<p>" not in d["instructions"]
    assert json.loads(get(app, "/api/assignment?course=999&id=1")[2])["error"]


def test_tutor_endpoint_enforces_policy_and_guards(app):
    s, r = post(app, "/api/tutor", {"action": "hint", "course": 101, "assignment": "Assignment 2"})
    assert r["status"] == "needs_confirmation"                      # restricted course: blocked first
    s, r = post(app, "/api/tutor", {"action": "hint", "course": 101, "assignment": "Assignment 2",
                                    "confirm_policy": True})
    assert r["status"] == "ok" and r["hint_level"] == 1
    s, r = post(app, "/api/tutor", {"action": "hint", "course": 102, "assignment": "Lab 3",
                                    "message": "just give me the code"})
    assert r["status"] == "refused"
    assert post(app, "/api/tutor", {"action": "hint", "course": 555, "assignment": "x"})[1]["status"] == "error"


def test_ask_endpoint_refuses_solution_requests(app):
    s, r = post(app, "/api/ask", {"question": "write my report for me"})
    assert "won't write your submission" in r["answer"]


def test_live_server_loopback_only(app):
    from http.server import ThreadingHTTPServer
    import uniassist.web as web
    app.port = 0
    captured = {}
    real = web.ThreadingHTTPServer

    class Srv(real):
        def __init__(self, addr, h):
            captured["addr"] = addr
            super().__init__(("127.0.0.1", 0), h)
            captured["port"] = self.server_address[1]
            app.port = self.server_address[1]
    web.ThreadingHTTPServer = Srv
    try:
        t = threading.Thread(target=web.serve, args=(app,), daemon=True)
        t.start()
        for _ in range(100):
            if captured.get("port"):
                break
            threading.Event().wait(0.02)
        assert captured["addr"][0] == "127.0.0.1"                   # never 0.0.0.0
        r = urllib.request.urlopen(f"http://localhost:{captured['port']}/api/courses")
        assert r.status == 200 and r.headers["Cache-Control"] == "no-store"
        req = urllib.request.Request(f"http://localhost:{captured['port']}/api/courses",
                                     headers={"Host": "evil.example"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        assert e.value.code == 403
    finally:
        web.ThreadingHTTPServer = real
