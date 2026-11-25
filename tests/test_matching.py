from uniassist.matching import resolve, score


def test_prefix_tokens():
    assert score("gen ai", "Generative AI") >= 0.85


def test_numbers_must_match_exactly():
    assert score("assignment 2", "Assignment 12") == 0
    assert score("assignment 2", "Assignment 1") == 0
    assert score("assignment 2", "Assignment 2") == 1.0


def test_resolve_none_and_ambiguous():
    items = ["Software Testing", "Software Architecture"]
    assert resolve("physics", items, lambda x: x) == (None, [])
    m, cands = resolve("software", items, lambda x: x)
    assert m is None and len(cands) == 2
