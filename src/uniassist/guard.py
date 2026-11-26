"""Code-level guardrails for learning mode. These do not depend on the model behaving.

Honest limits: they stop the obvious routes (asking for the solution, long code, echoing
a draft back). A determined student can still ask differently or use another tool.
The aim is to make the helpful path the easy one, not to be cheat-proof.
"""
from __future__ import annotations

import re

REDIRECT = ("I won't write your submission or give the full answer, but I can help you do it "
            "yourself: explain what the task asks, plan your time, give a hint (step by step), "
            "quiz you on the concepts, or review a draft you wrote.")

_SOLUTION_REQUEST = re.compile(
    r"(just|simply)\s+(give|show|tell|send|write)\s+(me\s+)?(the\s+)?(code|answer|solution|essay|report)|"
    r"(give|show|send|write|produce|generate)\s+(me\s+)?(the\s+|a\s+)?(full|complete|whole|entire|final|finished)\s+"
    r"(code|answer|solution|essay|report|assignment|program|implementation|submission)|"
    r"(write|do|solve|finish|complete|make|create)\s+(it|this|that|the\s+(assignment|task|lab|project|report|essay|homework|exercise)|my\s+(assignment|homework|lab|report|essay|project))"
    r"\s+(for\s+me|instead\s+of\s+me)|"
    r"(do|solve|write|complete)\s+my\s+(assignment|homework|lab|report|essay|project|exam)|"
    r"(ignore|disregard|forget|override)\s+(all\s+)?((your|the|my|previous|prior|above|earlier|these|those)\s+)+"
    r"(rules|instructions|guidelines|restrictions|prompt|system prompt)|"
    r"(pretend|act)\s+(you\s+are|as)\s+(not|no longer)|"
    r"(skriv|gör|lös)\s+(den|det|uppgiften|inlämningen|rapporten)\s+(åt|för)\s+mig|ge\s+mig\s+(hela\s+)?(lösningen|svaret|koden)",
    re.I)


def is_solution_request(text: str) -> bool:
    return bool(_SOLUTION_REQUEST.search(text or ""))


MAX_CODE_LINES = 6        # longer fenced code blocks are removed
MAX_REPLY_CHARS = 2500    # tutoring replies are short; a finished essay would not fit


def _strip_code(text: str) -> tuple[str, bool]:
    removed = False

    def repl(m: re.Match) -> str:
        nonlocal removed
        if m.group(0).count("\n") - 1 > MAX_CODE_LINES:
            removed = True
            return "[code removed: I only show short snippets. Try writing this part yourself, then ask me to review it.]"
        return m.group(0)

    return re.sub(r"```.*?```", repl, text, flags=re.S), removed


def _norm(line: str) -> str:
    return re.sub(r"\W+", " ", line.lower()).strip()


def echoes_draft(reply: str, draft: str, threshold: float = 0.5) -> bool:
    """True if the reply reproduces most of the student's draft (i.e. a rewrite)."""
    lines = {_norm(x) for x in draft.splitlines() if len(_norm(x)) > 25}
    if len(lines) < 3:
        return False
    rep = {_norm(x) for x in reply.splitlines()}
    return len(lines & rep) / len(lines) >= threshold


def guard_output(text: str, draft: str | None = None) -> tuple[str, list[str]]:
    """Make a model reply safe to show. Returns (text, list of what was changed)."""
    notes = []
    if draft and echoes_draft(text, draft):
        return ("I won't rewrite your work for you. Pick one issue from my feedback, fix it "
                "yourself, and ask me to look again."), ["echoed_draft"]
    text, removed = _strip_code(text)
    if removed:
        notes.append("code_removed")
    if len(text) > MAX_REPLY_CHARS:
        text = text[:MAX_REPLY_CHARS].rsplit(" ", 1)[0] + " …\n[shortened]"
        notes.append("shortened")
    return text, notes
