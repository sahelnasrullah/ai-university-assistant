"""Fuzzy matching for course and assignment names ('assignment 2 in gen ai')."""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Callable, TypeVar

T = TypeVar("T")
_STOP = {"the", "in", "for", "of", "my", "a", "an", "course", "on"}


def tokens(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9åäö]+", s.lower()) if t not in _STOP]


def score(query: str, name: str) -> float:
    """0..1. Numbers must match exactly ('assignment 2' never matches 'Assignment 12')."""
    q, n = tokens(query), tokens(name)
    if not q or not n:
        return 0.0
    qnum = {t for t in q if t.isdigit()}
    if qnum and not qnum <= {t for t in n if t.isdigit()}:
        return 0.0
    if " ".join(q) == " ".join(n):
        return 1.0
    # every query token is a prefix of some name token ('gen ai' -> 'generative ai')
    if all(any(nt.startswith(qt) for nt in n) for qt in q):
        return 0.85 + 0.1 * (len(q) / len(n))
    return SequenceMatcher(None, " ".join(q), " ".join(n)).ratio() * 0.8


def best_matches(query: str, items: list[T], key: Callable[[T], list[str]] | Callable,
                 threshold: float = 0.6) -> list[tuple[float, T]]:
    """Return items scoring >= threshold, best first. key returns names (str or list)."""
    scored = []
    for it in items:
        names = key(it)
        names = [names] if isinstance(names, str) else names
        s = max((score(query, n) for n in names), default=0.0)
        if s >= threshold:
            scored.append((s, it))
    return sorted(scored, key=lambda x: -x[0])


def resolve(query: str, items: list[T], key, threshold: float = 0.6):
    """Return (match, candidates). match is None when nothing or ambiguous."""
    m = best_matches(query, items, key, threshold)
    if not m:
        return None, []
    if len(m) > 1 and m[0][0] - m[1][0] < 0.05:
        return None, [it for _, it in m[:5]]
    return m[0][1], [m[0][1]]
