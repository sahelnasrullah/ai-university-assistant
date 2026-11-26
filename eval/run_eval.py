"""Evaluation on the mock dataset (fixed 'now' = 2026-11-25 10:00 Europe/Stockholm).

  python eval/run_eval.py                  # data layer: tool output vs ground truth (no LLM)
  python eval/run_eval.py --llm            # full agent with Ollama: tool selection + exact match
  python eval/run_eval.py --llm --no-tools # baseline: same model WITHOUT tools

Metrics: tool-selection rate, exact-match rate (all expected strings present),
hallucination-guard rate (forbidden strings absent). The plain-RAG vs RAG+tools
comparison needs your RAG system: run it on the same testset.json questions.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from uniassist import mock
from uniassist.agent import Agent
from uniassist.config import load_config
from uniassist.llm import OllamaClient
from uniassist.timeutil import get_tz
from uniassist.tools import Context, build_tools, call_tool

HERE = Path(__file__).parent


def make_ctx() -> Context:
    tz = get_tz()
    return Context(mock.mock_canvas(tz), mock.mock_schedule(tz), mock.mock_programme(),
                   lambda: mock.mock_now(tz))


def eval_tools(cases) -> list[dict]:
    ctx = make_ctx()
    tools = build_tools(ctx)
    rows = []
    for c in cases:
        out = json.dumps(call_tool(tools, ctx, c["tool"], c["args"]), ensure_ascii=False)
        rows.append({"id": c["id"], "tool_ok": True,
                     "exact": all(e in out for e in c["expect"])})
    return rows


def eval_llm(cases, model: str | None, no_tools: bool) -> list[dict]:
    cfg = load_config()
    rows = []
    for c in cases:
        agent = Agent(OllamaClient(cfg.llm_host, model or cfg.llm_model, 0.0), make_ctx())
        if no_tools:
            agent.tools = {}
        turn = agent.ask(c["question"])
        ans = turn.answer
        rows.append({
            "id": c["id"],
            "tool_ok": any(t["name"] == c["tool"] for t in turn.tool_calls),
            # "not_found" is a tool status, not answer text, so it is skipped here
            "exact": all(e.lower() in ans.lower() for e in c["expect"] if e != "not_found"),
            "guard": not any(f.lower() in ans.lower() for f in c.get("forbid_in_answer", [])),
        })
    return rows


def eval_guard() -> int:
    """Request filter quality on eval/bypass.json (no LLM needed).
    'known_gap' cases are phrasings the code-level filter does NOT catch: they show the
    honest limit. For those, the output guard (code/length/echo limits) is the only backstop."""
    from uniassist.guard import is_solution_request
    cases = json.loads((HERE / "bypass.json").read_text())
    ok = gaps = bad = 0
    for c in cases:
        blocked = is_solution_request(c["text"])
        right = blocked == (c["expect"] == "blocked")
        if c.get("known_gap"):
            gaps += 1
            print(f"{'caught (bonus)' if right else 'MISSED (known gap)':20} {c['text'][:70]}")
        elif right:
            ok += 1
        else:
            bad += 1
            print(f"{'WRONG':20} expected {c['expect']}: {c['text'][:70]}")
    n = len(cases) - gaps
    print(f"\nrequest filter: {ok}/{n} correct on regular cases; known gaps listed above: {gaps}")
    return 0 if bad == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true")
    ap.add_argument("--no-tools", action="store_true")
    ap.add_argument("--model")
    ap.add_argument("--guard", action="store_true", help="evaluate the solution-request filter")
    a = ap.parse_args()
    if a.guard:
        return eval_guard()
    cases = json.loads((HERE / "testset.json").read_text())
    rows = eval_llm(cases, a.model, a.no_tools) if a.llm else eval_tools(cases)
    for r in rows:
        print(f"{r['id']:22} tool={'Y' if r['tool_ok'] else 'N'} exact={'Y' if r['exact'] else 'N'}"
              + (f" guard={'Y' if r['guard'] else 'N'}" if "guard" in r else ""))
    n = len(rows)
    print(f"\ntool selection: {sum(r['tool_ok'] for r in rows)}/{n}   "
          f"exact match: {sum(r['exact'] for r in rows)}/{n}")
    if a.llm:
        print(f"guard (no invented/injected answers): {sum(r['guard'] for r in rows)}/{n}")
    return 0 if all(r["exact"] for r in rows) or a.llm else 1


if __name__ == "__main__":
    sys.exit(main())
