"""RAG plug-in point. RAG is built separately; implement this protocol to connect it.

    class MyRetriever:
        def search(self, query: str, course: str | None = None, k: int = 4) -> list[Passage]: ...

Pass an instance as `retriever=` to build_tools()/Agent. If none is given, the
`search_course_documents` tool is simply not offered to the model.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class Passage:
    text: str
    source: str            # e.g. "Syllabus MOCK-GENAI, p. 3"
    course: str | None = None


class Retriever(Protocol):
    def search(self, query: str, course: str | None = None, k: int = 4) -> list[Passage]: ...
