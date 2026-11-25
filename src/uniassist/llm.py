"""LLM wrapper. Swappable: anything with chat(messages, tools) -> message dict.

OllamaClient talks to a local Ollama server, so personal data stays on the machine.
"""
from __future__ import annotations

from typing import Any, Protocol

import httpx


class LLMError(Exception):
    pass


class LLMClient(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return an assistant message: {'role','content','tool_calls'?}."""


class OllamaClient:
    def __init__(self, host: str, model: str, temperature: float = 0.0,
                 transport: httpx.BaseTransport | None = None):
        self.model = model
        self.temperature = temperature
        self._http = httpx.Client(base_url=host, timeout=300.0, transport=transport)

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        try:
            r = self._http.post("/api/chat", json={
                "model": self.model, "messages": messages, "tools": tools,
                "stream": False, "options": {"temperature": self.temperature}})
        except httpx.ConnectError as e:
            raise LLMError("Cannot reach Ollama. Is it running? (`ollama serve`)") from e
        except httpx.HTTPError as e:
            raise LLMError(f"Ollama request failed: {e.__class__.__name__}") from e
        if r.status_code == 404:
            raise LLMError(f"Model '{self.model}' not found. Run: ollama pull {self.model}")
        if r.status_code >= 400:
            raise LLMError(f"Ollama error {r.status_code}: {r.text[:200]}")
        return r.json()["message"]


class ScriptedLLM:
    """Deterministic LLM for tests: replays a list of assistant messages."""

    def __init__(self, replies: list[dict]):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        self.calls.append([dict(m) for m in messages])
        return self.replies.pop(0)
