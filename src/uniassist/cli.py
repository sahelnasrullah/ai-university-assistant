"""Command line interface: chat, ask, summary, tool, auth, schedule, cache."""
from __future__ import annotations

import argparse
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
from .summary import daily_summary
from .timeutil import fmt, get_tz
from .tools import Context, build_tools, call_tool


def build_context(cfg: Config, mock: bool, retriever=None) -> Context:
    tz = get_tz(cfg.timezone)
    if mock:
        from . import mock as m
        return Context(m.mock_canvas(tz), m.mock_schedule(tz), m.mock_programme(),
                       lambda: m.mock_now(tz), retriever)
    cache = Cache(cfg.cache_dir, cfg.cache_ttl)
    token = get_secret("canvas_token")
    canvas = CanvasClient(cfg.canvas_base_url, token, tz, cache) if token else None
    schedule = Schedule(tz, ics_url=get_secret("ical_url"), cache=cache)
    return Context(canvas, schedule, Programme(cfg.programme_path),
                   lambda: datetime.now(tz), retriever)


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
    handlers = {None: cmd_chat, "chat": cmd_chat, "ask": cmd_ask, "summary": cmd_summary,
                "tool": cmd_tool, "auth": cmd_auth, "schedule": cmd_schedule,
                "cache-clear": cmd_cache}
    return handlers[args.cmd](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
