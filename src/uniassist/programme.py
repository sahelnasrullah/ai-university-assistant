"""Next-semester courses from a student-provided JSON file.

Format: {"semester": "Spring 2027", "courses": [{"code","name","credits","period"}]}
(plan.bth.se is JavaScript-rendered and unverified, so the student supplies this.)
"""
from __future__ import annotations

import json
from pathlib import Path


class Programme:
    def __init__(self, path: Path | None):
        self.path = path

    def configured(self) -> bool:
        return bool(self.path and Path(self.path).exists())

    def load(self) -> dict:
        return json.loads(Path(self.path).read_text())
