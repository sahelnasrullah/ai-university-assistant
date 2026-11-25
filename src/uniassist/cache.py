"""Tiny JSON file cache with TTL, so repeated questions don't hit the APIs."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable


class Cache:
    def __init__(self, directory: Path | None, ttl: int = 300):
        self.dir = directory
        self.ttl = ttl
        if self.dir and ttl > 0:
            self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.dir / (hashlib.sha256(key.encode()).hexdigest()[:32] + ".json")

    def get_or_fetch(self, key: str, fetch: Callable[[], Any]) -> Any:
        if not self.dir or self.ttl <= 0:
            return fetch()
        p = self._path(key)
        if p.exists() and time.time() - p.stat().st_mtime < self.ttl:
            try:
                return json.loads(p.read_text())
            except json.JSONDecodeError:
                pass
        value = fetch()
        p.write_text(json.dumps(value))
        p.chmod(0o600)
        return value

    def clear(self) -> int:
        if not self.dir or not self.dir.exists():
            return 0
        n = 0
        for f in self.dir.glob("*.json"):
            f.unlink()
            n += 1
        return n
