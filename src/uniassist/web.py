"""Local web interface (stdlib only). Dashboard, assignment actions, ask box.

Security (it is a server on your machine, so it is locked down):
- binds to 127.0.0.1 only
- Host header must be localhost/127.0.0.1 (blocks DNS-rebinding from other websites)
- every POST needs a per-run secret token (blocks cross-site requests)
- strict Content-Security-Policy; all data is rendered with textContent, never as HTML
- read-only toward Canvas; tutor actions go through the same guards as the CLI
"""
from __future__ import annotations

import json
import secrets
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .agent import Agent
from .canvas import CanvasError
from .llm import LLMClient
from .schedule import ScheduleError
from .planner import find_clashes, make_plan, prioritise
from .summary import week_overview
from .timeutil import fmt, day_bounds
from .tools import Context, active_courses, clean_text, find_ai_policy, get_upcoming_assignments
from .tutor import ACTIONS, Tutor

MAX_BODY = 64_000


class App:
    def __init__(self, ctx: Context, llm: LLMClient | None, port: int, hours_per_day: float = 3.0,
                 cache_minutes: int = 5, tz_name: str = "Europe/Stockholm"):
        self.ctx, self.port, self.hours = ctx, port, hours_per_day
        self.cache_minutes = cache_minutes
        self.token = secrets.token_urlsafe(24)
        self.tutor = Tutor(llm, ctx) if llm else None
        self.agent = Agent(llm, ctx, tz_name=tz_name) if llm else None
        self.lock = threading.Lock()   # one LLM request at a time

    # -- routing ----------------------------------------------------------------------
    def handle(self, method: str, target: str, headers: dict, body: bytes = b"") -> tuple[int, dict, bytes]:
        h = {k.lower(): v for k, v in headers.items()}
        if h.get("host", "") not in (f"127.0.0.1:{self.port}", f"localhost:{self.port}"):
            return self._json(403, {"error": "bad host"})
        u = urlparse(target)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if method == "GET":
                if u.path == "/":
                    return self._page()
                routes = {"/api/dashboard": self.dashboard, "/api/courses": self.courses,
                          "/api/assignments": self.assignments, "/api/assignment": self.assignment}
                fn = routes.get(u.path)
                return self._json(200, fn(q)) if fn else self._json(404, {"error": "not found"})
            if method == "POST":
                if not secrets.compare_digest(h.get("x-token", ""), self.token):
                    return self._json(403, {"error": "bad token"})
                if "application/json" not in h.get("content-type", ""):
                    return self._json(415, {"error": "json only"})
                if len(body) > MAX_BODY:
                    return self._json(413, {"error": "too large"})
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    return self._json(400, {"error": "object expected"})
                if u.path == "/api/tutor":
                    return self._json(200, self.tutor_act(data))
                if u.path == "/api/ask":
                    return self._json(200, self.ask(data))
                return self._json(404, {"error": "not found"})
        except CanvasError as e:
            return self._json(502, {"error": f"Canvas: {e}"})
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad request"})
        except Exception as e:  # never leak a traceback to the browser
            return self._json(500, {"error": f"{e.__class__.__name__}"})
        return self._json(405, {"error": "method not allowed"})

    @staticmethod
    def _json(status: int, obj) -> tuple[int, dict, bytes]:
        return status, {"Content-Type": "application/json", "Cache-Control": "no-store",
                        "X-Content-Type-Options": "nosniff"}, json.dumps(obj, ensure_ascii=False).encode()

    def _page(self):
        nonce = secrets.token_urlsafe(12)
        html = PAGE.replace("__TOKEN__", self.token).replace("__NONCE__", nonce)
        return 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store",
                     "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                     "Content-Security-Policy": f"default-src 'none'; style-src 'nonce-{nonce}'; "
                                                f"script-src 'nonce-{nonce}'; connect-src 'self'; "
                                                "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
                     }, html.encode()

    # -- data ------------------------------------------------------------------------------
    def dashboard(self, q) -> dict:
        ctx = self.ctx
        now = ctx.now()
        out = {"now": fmt(now), "note": f"Canvas data can be up to {self.cache_minutes} min old.",
               "today": [], "deadlines": [], "start_with": [], "watch_out": [], "week": ""}
        if ctx.schedule and ctx.schedule.configured():
            try:
                s, e = day_bounds(now.date(), now.tzinfo)
                out["today"] = [{"start": f"{x.start:%H:%M}", "end": f"{x.end:%H:%M}", "title": x.title,
                                 "location": x.location} for x in ctx.events_between(s, e)]
            except ScheduleError as err:
                out["schedule_error"] = str(err)
        if ctx.canvas:
            r = get_upcoming_assignments(ctx, days=7)
            out["deadlines"] = r.get("upcoming", []) + [{**o, "overdue": True} for o in r.get("overdue_unsubmitted", [])]
            out["start_with"] = prioritise(ctx, 14)[:3]
            out["watch_out"] = [c["message"] for c in find_clashes(ctx, 7)][:4]
            out["week"] = week_overview(ctx, self.hours)
        else:
            out["note"] = "Canvas is not linked. Run: uniassist auth set"
        return out

    def courses(self, q) -> dict:
        if not self.ctx.canvas:
            return {"courses": []}
        return {"courses": [{"id": c.id, "name": c.name} for c in active_courses(self.ctx)]}

    def _course(self, q):
        cid = int(q.get("course", "0"))
        return next((c for c in active_courses(self.ctx) if c.id == cid), None)

    def assignments(self, q) -> dict:
        c = self._course(q)
        if not c:
            return {"assignments": []}
        items = sorted(self.ctx.canvas.assignments(c.id), key=lambda a: (a.due_at is None, a.due_at or 0))
        return {"assignments": [{"id": a.id, "name": a.name, "due": fmt(a.due_at), "submitted": a.submitted}
                                for a in items]}

    def assignment(self, q) -> dict:
        c = self._course(q)
        if not c:
            return {"error": "unknown course"}
        a = next((x for x in self.ctx.canvas.assignments(c.id) if x.id == int(q.get("id", "0"))), None)
        if not a:
            return {"error": "unknown assignment"}
        return {"course": c.name, "name": a.name, "due": fmt(a.due_at), "points": a.points_possible,
                "submitted": a.submitted, "types": a.submission_types, "rubric": a.rubric,
                "instructions": clean_text(a.description, 3000), "url": a.url,
                "policy": find_ai_policy(self.ctx, c.name), "actions": list(ACTIONS)}

    # -- actions ------------------------------------------------------------------------------
    def tutor_act(self, d: dict) -> dict:
        if not self.tutor:
            return {"status": "error", "text": "No language model configured."}
        with self.lock:
            c = self._course({"course": str(d.get("course", 0))})
            if not c:
                return {"status": "error", "text": "Unknown course."}
            r = self.tutor.act(str(d.get("action", "")), c.name, str(d.get("assignment", "")),
                               str(d.get("message", "")), bool(d.get("confirm_policy", False)))
        return {"status": r.status, "text": r.text, "hint_level": r.hint_level,
                "policy": r.policy, "notes": r.guard_notes}

    def ask(self, d: dict) -> dict:
        if not self.agent:
            return {"answer": "No language model configured.", "sources": []}
        q = str(d.get("question", ""))[:1000]
        with self.lock:
            try:
                t = self.agent.ask(q)
            except Exception as e:
                return {"answer": f"The language model is not available: {e}", "sources": []}
        return {"answer": t.answer, "sources": t.sources, "tools": [c["name"] for c in t.tool_calls]}


def serve(app: App, open_browser: bool = False) -> None:
    class H(BaseHTTPRequestHandler):
        def _run(self, method):
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(n, MAX_BODY + 1)) if n else b""
            status, headers, payload = app.handle(method, self.path, dict(self.headers), body)
            self.send_response(status)
            for k, v in headers.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self): self._run("GET")
        def do_POST(self): self._run("POST")
        def log_message(self, *a): pass   # no request logging (URLs may hold course names)

    srv = ThreadingHTTPServer(("127.0.0.1", app.port), H)
    url = f"http://localhost:{app.port}/"
    print(f"Serving on {url} (local only). Ctrl+C to stop.")
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>University assistant</title>
<style nonce="__NONCE__">
:root{--bg:#f6f7f9;--card:#fff;--ink:#1c2430;--mute:#5b6675;--acc:#2456d6;--warn:#b45309;--bad:#b42318;--ok:#18794e;--line:#d9dde3}
*{box-sizing:border-box}body{margin:0;font:16px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--ink)}
header{background:var(--card);border-bottom:1px solid var(--line);padding:.6rem 1rem;display:flex;gap:1rem;align-items:center;flex-wrap:wrap}
h1{font-size:1.1rem;margin:0}nav{display:flex;gap:.4rem}
button{font:inherit;padding:.45rem .8rem;border:1px solid var(--line);background:#fff;border-radius:6px;cursor:pointer}
button:hover{border-color:var(--acc)}button:focus-visible,select:focus-visible,textarea:focus-visible,input:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
button[aria-pressed=true],button.primary{background:var(--acc);color:#fff;border-color:var(--acc)}
main{max-width:980px;margin:1rem auto;padding:0 1rem}.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:1rem;margin-bottom:1rem}
h2{font-size:1rem;margin:.1rem 0 .5rem}ul{margin:0;padding-left:1.1rem}.mute{color:var(--mute)}.warn{color:var(--warn)}.bad{color:var(--bad)}.ok{color:var(--ok)}
pre{white-space:pre-wrap;margin:0;font:inherit}select,textarea,input[type=text]{font:inherit;padding:.45rem;border:1px solid var(--line);border-radius:6px;width:100%}
textarea{min-height:7rem}.row{display:flex;gap:.5rem;flex-wrap:wrap;margin:.5rem 0}.grid{display:grid;grid-template-columns:1fr 2fr;gap:1rem}
@media(max-width:760px){.grid{grid-template-columns:1fr}}.item{display:block;width:100%;text-align:left;margin:.2rem 0}
.box{border-left:4px solid var(--warn);padding:.4rem .7rem;background:#fff8ec;margin:.5rem 0}.hidden{display:none}
</style></head><body>
<header><h1>University assistant</h1>
<nav aria-label="Sections"><button data-tab="dash" aria-pressed="true">Dashboard</button>
<button data-tab="work" aria-pressed="false">Assignments</button>
<button data-tab="ask" aria-pressed="false">Ask</button></nav>
<span class="mute" id="now" aria-live="polite"></span></header><main>
<section id="dash"><div class="card"><h2>Today</h2><div id="today">Loading…</div></div>
<div class="card"><h2>Deadlines (next 7 days)</h2><div id="deadlines"></div></div>
<div class="card"><h2>Start with</h2><div id="start"></div></div>
<div class="card" id="watchcard"><h2>Watch out</h2><div id="watch"></div></div>
<div class="card"><h2>This week</h2><pre id="week"></pre></div><p class="mute" id="note"></p></section>
<section id="work" class="hidden"><div class="grid"><div class="card"><h2>Course</h2>
<label for="course" class="mute">Choose a course</label><select id="course"></select>
<div id="alist" role="list"></div></div>
<div class="card" id="detail"><p class="mute">Pick an assignment.</p></div></div></section>
<section id="ask" class="hidden"><div class="card"><h2>Ask</h2><label for="q" class="mute">For example: When is my next lecture?</label>
<input type="text" id="q" maxlength="1000"><div class="row"><button class="primary" id="askbtn">Ask</button></div>
<pre id="answer" aria-live="polite"></pre><p class="mute" id="src"></p></div></section></main>
<script nonce="__NONCE__">
const TOKEN="__TOKEN__";
const $=id=>document.getElementById(id);
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function clear(n){while(n.firstChild)n.removeChild(n.firstChild)}
async function api(path,body){
  const opt=body?{method:"POST",headers:{"Content-Type":"application/json","X-Token":TOKEN},body:JSON.stringify(body)}:{};
  const r=await fetch(path,opt);const j=await r.json().catch(()=>({error:"bad response"}));
  if(!r.ok)throw new Error(j.error||("HTTP "+r.status));return j}
function list(box,items,fmt,empty){clear(box);if(!items.length){box.appendChild(el("p",empty,"mute"));return}
  const ul=el("ul");items.forEach(i=>{const li=el("li");fmt(li,i);ul.appendChild(li)});box.appendChild(ul)}
document.querySelectorAll("nav button").forEach(b=>b.addEventListener("click",()=>{
  document.querySelectorAll("nav button").forEach(x=>x.setAttribute("aria-pressed",x===b));
  ["dash","work","ask"].forEach(t=>$(t).classList.toggle("hidden",t!==b.dataset.tab));
  if(b.dataset.tab==="work"&&!$("course").options.length)loadCourses()}));
async function dash(){
  try{const d=await api("/api/dashboard");$("now").textContent=d.now;$("note").textContent=d.note;
  if(d.schedule_error){$("today").textContent="";$("today").appendChild(el("p","Schedule problem: "+d.schedule_error,"warn"))}else
  list($("today"),d.today,(li,e)=>li.textContent=e.start+"–"+e.end+"  "+e.title+(e.location?" ("+e.location+")":""),"Nothing scheduled today (or no schedule added yet).");
  list($("deadlines"),d.deadlines,(li,x)=>{li.textContent=x.due+"  "+x.assignment+" · "+x.course.split(" ")[0]+(x.overdue?"  OVERDUE":"");if(x.overdue)li.className="bad"},"No unsubmitted deadlines this week.");
  list($("start"),d.start_with,(li,t)=>li.textContent=t.assignment+" ("+t.course.split(" ")[0]+"): "+t.why,"Nothing to start.");
  $("watchcard").classList.toggle("hidden",!d.watch_out.length);
  list($("watch"),d.watch_out,(li,m)=>{li.textContent=m;li.className="warn"},"");
  $("week").textContent=d.week}catch(e){$("today").textContent="Could not load: "+e.message}}
async function loadCourses(){const s=$("course");const d=await api("/api/courses");clear(s);
  d.courses.forEach(c=>{const o=el("option",c.name);o.value=c.id;s.appendChild(o)});if(d.courses.length)loadAssignments()}
$("course").addEventListener("change",loadAssignments);
async function loadAssignments(){const d=await api("/api/assignments?course="+encodeURIComponent($("course").value));
  const box=$("alist");clear(box);d.assignments.forEach(a=>{const b=el("button",a.name+(a.due?" · "+a.due:"")+(a.submitted?" ✓":""),"item");
  b.addEventListener("click",()=>openAssignment(a.id));box.appendChild(b)})}
let current=null;
async function openAssignment(id){const cid=$("course").value;const a=await api("/api/assignment?course="+cid+"&id="+id);
  current={course:cid,assignment:a.name};const box=$("detail");clear(box);
  if(a.error){box.appendChild(el("p",a.error,"bad"));return}
  box.appendChild(el("h2",a.name));box.appendChild(el("p",(a.due||"No due date")+" · "+(a.points??"?")+" points"+(a.submitted?" · submitted":""),"mute"));
  const pol=policyBox(a.policy);box.appendChild(pol);
  box.appendChild(el("h2","Instructions"));box.appendChild(el("pre",a.instructions||"(none written in Canvas)"));
  if(a.rubric.length){box.appendChild(el("h2","Rubric"));const ul=el("ul");a.rubric.forEach(r=>ul.appendChild(el("li",r.criterion+" ("+r.points+")")));box.appendChild(ul)}
  box.appendChild(el("h2","Get help learning it (not a finished answer)"));
  const row=el("div",undefined,"row");[["understand","Understand it"],["plan","Plan it"],["hint","Hint"],["quiz","Quiz me"],["review","Review my draft"]].forEach(([k,l])=>{
    const b=el("button",l);b.addEventListener("click",()=>act(k));row.appendChild(b)});box.appendChild(row);
  const lab=el("label","Your message, what you tried, or your draft (for review):","mute");lab.setAttribute("for","msg");box.appendChild(lab);
  const ta=el("textarea");ta.id="msg";ta.maxLength=6000;box.appendChild(ta);
  const cl=el("label",undefined,"hidden");cl.id="confirmlab";const cb=document.createElement("input");cb.type="checkbox";cb.id="confirm";
  cl.appendChild(cb);cl.appendChild(document.createTextNode(" I read the course's AI statements above and this help is allowed for this assignment."));box.appendChild(cl);
  const out=el("pre");out.id="out";out.setAttribute("aria-live","polite");box.appendChild(out)}
function policyBox(p){const b=el("div",undefined,"box");b.appendChild(el("strong","Course AI policy (read this first)"));
  if(p.status==="ok"){const ul=el("ul");p.statements.forEach(s=>ul.appendChild(el("li",s.untrusted_text)));b.appendChild(ul);b.appendChild(el("p",p.note,"mute"))}
  else b.appendChild(el("p",p.message||"No information found. Do not assume AI help is allowed; ask your teacher."));return b}
async function act(action){const out=$("out");out.textContent="Thinking…";
  try{const r=await api("/api/tutor",{action,course:Number(current.course),assignment:current.assignment,message:$("msg").value,confirm_policy:$("confirm").checked});
  $("confirmlab").classList.toggle("hidden",r.status!=="needs_confirmation"&&!$("confirm").checked);
  out.textContent=(r.hint_level?"Hint "+r.hint_level+" of 3\n\n":"")+r.text}catch(e){out.textContent="Error: "+e.message}}
$("askbtn").addEventListener("click",async()=>{$("answer").textContent="Thinking…";$("src").textContent="";
  try{const r=await api("/api/ask",{question:$("q").value});$("answer").textContent=r.answer;if(r.sources.length)$("src").textContent="Sources: "+r.sources.join(", ")}
  catch(e){$("answer").textContent="Error: "+e.message}});
$("q").addEventListener("keydown",e=>{if(e.key==="Enter")$("askbtn").click()});
dash();
</script></body></html>
"""
