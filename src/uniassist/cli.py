"""Command line interface: chat, ask, summary, tool, auth, schedule, cache."""
from __future__ import annotations

import argparse
import shutil
import getpass
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import config as cfgmod
from .agent import Agent
from .cache import Cache
from .canvas import CanvasClient, CanvasError
from .config import Config, get_secret, load_config
from .llm import LLMError, OllamaClient
from .programme import Programme
from .schedule import Event, Schedule, add_manual, guess_type, import_ics
from .summary import briefing, daily_summary, week_overview
from .timeutil import fmt, get_tz
from .tools import Context, build_tools, call_tool


def build_context(cfg: Config, mock: bool, retriever=None) -> Context:
    tz = get_tz(cfg.timezone)
    if mock:
        from . import mock as m
        return Context(m.mock_canvas(tz), m.mock_schedule(tz), m.mock_programme(),
                       lambda: m.mock_now(tz), retriever, aliases=cfg.aliases,
                       schedule_all=cfg.schedule_all_events)
    cache = Cache(cfg.cache_dir, cfg.cache_ttl)
    token = get_secret("canvas_token")
    canvas = CanvasClient(cfg.canvas_base_url, token, tz, cache) if token else None
    schedule = Schedule(tz, ics_url=get_secret("ical_url"), cache=cache)
    return Context(canvas, schedule, Programme(cfg.programme_path),
                   lambda: datetime.now(tz), retriever,
                   include_past=cfg.include_past_courses, aliases=cfg.aliases,
                   schedule_all=cfg.schedule_all_events)


def _agent(args, cfg: Config) -> Agent:
    ctx = build_context(cfg, args.mock)
    llm = OllamaClient(cfg.llm_host, args.model or cfg.llm_model, cfg.llm_temperature)
    return Agent(llm, ctx, tz_name=cfg.timezone)


def _print_turn(turn, verbose: bool) -> None:
    print(turn.answer)
    if turn.sources:
        print(f"  [sources: {', '.join(turn.sources)}]")
    if verbose:
        for c in turn.tool_calls:
            print(f"  [tool: {c['name']}({json.dumps(c['args'])}) -> {c['status']}]")


def cmd_chat(args, cfg) -> int:
    agent = _agent(args, cfg)
    print("University assistant (read-only). /reset clears memory, /quit exits.")
    while True:
        try:
            q = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not q:
            continue
        if q in ("/quit", "/exit"):
            return 0
        if q == "/reset":
            agent.reset()
            print("Memory cleared.")
            continue
        try:
            _print_turn(agent.ask(q), args.verbose)
        except (LLMError, CanvasError) as e:
            print(f"Error: {e}")


def cmd_ask(args, cfg) -> int:
    try:
        _print_turn(_agent(args, cfg).ask(" ".join(args.question)), args.verbose)
    except (LLMError, CanvasError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    return 0


def cmd_summary(args, cfg) -> int:
    print(daily_summary(build_context(cfg, args.mock)))
    return 0


def cmd_briefing(args, cfg) -> int:
    from . import notify
    text = briefing(build_context(cfg, args.mock))
    print(text)
    if args.notify and not notify.send("Morning briefing", text):
        print("(notify-send not available; printed only)", file=sys.stderr)
    return 0


def cmd_week(args, cfg) -> int:
    print(week_overview(build_context(cfg, args.mock), cfg.study_hours_per_day))
    return 0


def cmd_plan(args, cfg) -> int:
    from .planner import make_plan
    plan = make_plan(build_context(cfg, args.mock), args.days, cfg.study_hours_per_day)
    for d in plan["days"]:
        print(d["date"], f"{d['total_hours']:g} h:",
              ", ".join(f"{x['assignment']} {x['hours']:g}h" for x in d["sessions"]))
    for m in plan["not_enough_time"]:
        print(f"NOT ENOUGH TIME: {m['assignment']} is {m['missing_hours']:g} h short before {m['due']}")
    print(plan["note"])
    return 0


def cmd_priorities(args, cfg) -> int:
    from .planner import prioritise
    for i, t in enumerate(prioritise(build_context(cfg, args.mock)), 1):
        print(f"{i}. {t['assignment']} ({t['course'].split()[0]}): {t['why']}")
    return 0


def cmd_clashes(args, cfg) -> int:
    from .planner import find_clashes
    found = find_clashes(build_context(cfg, args.mock))
    print("\n".join(c["message"] for c in found) or "No clashes in the next 14 days.")
    return 0


def cmd_notify(args, cfg) -> int:
    """Check for changes and deadlines; send each new alert once. Meant for a timer."""
    import tempfile
    from . import alerts, notify
    ctx = build_context(cfg, args.mock)
    if not ctx.canvas:
        print("Canvas is not linked (run: uniassist auth set).", file=sys.stderr)
        return 1
    state = Path(tempfile.mkdtemp()) if args.mock else cfgmod.CONFIG_DIR
    try:
        changes, first = alerts.check_changes(ctx, state / "snapshot.json")
    except CanvasError as e:
        print(f"Canvas check failed: {e}", file=sys.stderr)
        return 1
    if first:
        print("Baseline saved. Future runs report changes.")
    fresh = alerts.only_new(changes + alerts.deadline_warnings(ctx), state / "notified.json")
    for a in fresh:
        print(f"{a.title}: {a.text}")
        notify.send(a.title, a.text)
    if not fresh and not first:
        print("Nothing new.")
    return 0


def cmd_web(args, cfg) -> int:
    from .web import App, serve
    ctx = build_context(cfg, args.mock)
    llm = OllamaClient(cfg.llm_host, args.model or cfg.llm_model, cfg.llm_temperature)
    serve(App(ctx, llm, args.port, cfg.study_hours_per_day, cfg.cache_ttl // 60, cfg.timezone),
          open_browser=args.open)
    return 0


def cmd_timers(args, cfg) -> int:
    """Print systemd user units. Nothing is installed until you do it yourself."""
    from .notify import TIMER_UNITS
    local = Path(sys.executable).parent / "uniassist"
    found = str(local) if local.exists() else shutil.which("uniassist")
    exe = f'"{found}"' if found else f'"{sys.executable}" -m uniassist.cli'  # quoted: paths may hold spaces
    for name, body in TIMER_UNITS.items():
        print(f"# ~/.config/systemd/user/{name}\n{body.format(exe=exe)}")
    print("# Install:  save the files above, then\n"
          "#   systemctl --user daemon-reload\n"
          "#   systemctl --user enable --now uniassist-check.timer uniassist-briefing.timer")
    return 0


def cmd_tool(args, cfg) -> int:
    """Call a tool directly (no LLM). Useful to check your Canvas/schedule setup."""
    ctx = build_context(cfg, args.mock)
    tools = build_tools(ctx)
    if not args.name:
        print("\n".join(sorted(tools)))
        return 0
    print(json.dumps(call_tool(tools, ctx, args.name, json.loads(args.args)),
                     indent=2, ensure_ascii=False))
    return 0


def cmd_auth(args, cfg) -> int:
    if args.action == "set":
        tok = getpass.getpass("Canvas access token (hidden, Enter to skip): ").strip()
        if tok:
            cfgmod.set_secret("canvas_token", tok)
        url = getpass.getpass("iCal schedule URL (hidden, Enter to skip): ").strip()
        if url:
            cfgmod.set_secret("ical_url", url)
        print("Saved to", cfgmod.SECRETS_FILE, "(permissions 600).")
    elif args.action == "clear":
        print("Secrets removed." if cfgmod.clear_secrets() else "No stored secrets.")
        print("Also revoke the token in Canvas: Account > Settings > Approved Integrations.")
    else:
        for k, v in cfgmod.secret_status().items():
            print(f"{k}: {v}")
    return 0


def _when(s: str, tz) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M").replace(tzinfo=tz)


def cmd_schedule(args, cfg) -> int:
    tz = get_tz(cfg.timezone)
    if args.action == "import":
        print(f"Imported {import_ics(Path(args.file))} events.")
    elif args.action == "add":
        start = _when(args.start, tz)
        end = _when(args.end, tz) if args.end else start + timedelta(minutes=args.minutes)
        add_manual(Event(start, end, args.title, args.course,
                         args.type or guess_type(args.title), args.location))
        print("Added.")
    else:
        for e in Schedule(tz, ics_url=None).events():
            print(f"{fmt(e.start)}  {e.type or '-':9} {e.title}  {e.location or ''}")
    return 0


def cmd_cache(args, cfg) -> int:
    print(f"Removed {Cache(cfg.cache_dir, cfg.cache_ttl).clear()} cached responses.")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="uniassist", description="Read-only university assistant")
    p.add_argument("--config", type=Path)
    p.add_argument("--mock", action="store_true", help="use bundled mock data")
    p.add_argument("--model", help="override Ollama model")
    p.add_argument("-v", "--verbose", action="store_true", help="show tool calls")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("chat")
    a = sub.add_parser("ask"); a.add_argument("question", nargs="+")
    sub.add_parser("summary")
    b = sub.add_parser("briefing"); b.add_argument("--notify", action="store_true")
    sub.add_parser("week")
    pl = sub.add_parser("plan"); pl.add_argument("--days", type=int, default=14)
    sub.add_parser("priorities")
    sub.add_parser("clashes")
    sub.add_parser("notify")
    sub.add_parser("timers")
    w = sub.add_parser("web", help="local web interface"); w.add_argument("--port", type=int, default=8765)
    w.add_argument("--open", action="store_true")
    t = sub.add_parser("tool"); t.add_argument("name", nargs="?"); t.add_argument("--args", default="{}")
    au = sub.add_parser("auth"); au.add_argument("action", choices=["set", "clear", "status"])
    s = sub.add_parser("schedule")
    ss = s.add_subparsers(dest="action", required=True)
    i = ss.add_parser("import"); i.add_argument("file")
    ad = ss.add_parser("add")
    ad.add_argument("--title", required=True)
    ad.add_argument("--start", required=True, help="'YYYY-MM-DD HH:MM'")
    ad.add_argument("--end", help="'YYYY-MM-DD HH:MM'")
    ad.add_argument("--minutes", type=int, default=105)
    ad.add_argument("--course"); ad.add_argument("--type"); ad.add_argument("--location")
    ss.add_parser("list")
    sub.add_parser("cache-clear")
    args = p.parse_args(argv)
    cfg = load_config(args.config)
    handlers = {None: cmd_chat, "chat": cmd_chat, "ask": cmd_ask, "summary": cmd_summary, "briefing": cmd_briefing, "week": cmd_week,
                "plan": cmd_plan, "priorities": cmd_priorities, "clashes": cmd_clashes,
                "notify": cmd_notify, "timers": cmd_timers, "web": cmd_web,
                "tool": cmd_tool, "auth": cmd_auth, "schedule": cmd_schedule,
                "cache-clear": cmd_cache}
    return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
