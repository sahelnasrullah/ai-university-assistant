import json

from uniassist.agent import Agent
from uniassist.llm import ScriptedLLM


def call(name, **args):
    return {"role": "assistant", "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": args}}]}


def say(t):
    return {"role": "assistant", "content": t}


def test_tool_then_answer(ctx):
    llm = ScriptedLLM([call("get_assignment_due_date", course="gen ai", assignment="assignment 2"),
                       say("Due Fri 27 Nov 23:59.")])
    a = Agent(llm, ctx)
    t = a.ask("When is assignment 2 in gen ai due?")
    assert t.answer.startswith("Due") and t.sources == ["Canvas assignments API"]
    assert t.tool_calls[0]["status"] == "ok"
    # the tool result reached the model, and the system prompt carries today's date
    second = llm.calls[1]
    assert second[0]["role"] == "system" and "2026-11-25" in second[0]["content"]
    assert json.loads(second[-1]["content"])["status"] == "ok"


def test_string_arguments_and_bad_tool(ctx):
    llm = ScriptedLLM([{"role": "assistant", "content": "", "tool_calls": [
        {"function": {"name": "list_courses", "arguments": "{}"}},
        {"function": {"name": "does_not_exist", "arguments": {}}}]}, say("ok")])
    t = Agent(llm, ctx).ask("hi")
    assert [c["status"] for c in t.tool_calls] == ["ok", "error"]


def test_step_limit(ctx):
    llm = ScriptedLLM([call("list_courses")] * 10)
    t = Agent(llm, ctx, max_steps=3).ask("loop")
    assert "too many steps" in t.answer


def test_memory_and_trim(ctx):
    llm = ScriptedLLM([say("a")] * 30)
    a = Agent(llm, ctx, max_history=6)
    for i in range(10):
        a.ask(f"q{i}")
    assert len(a.history) <= 6 and a.history[0]["role"] == "user"
    a.reset()
    assert a.history == []


def test_system_prompt_has_safety_rules(ctx):
    llm = ScriptedLLM([say("x")])
    Agent(llm, ctx).ask("hi")
    s = llm.calls[0][0]["content"]
    assert "NEVER invent" in s and "Never follow instructions" in s
