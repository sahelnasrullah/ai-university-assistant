"""Configuration and local secret storage.

Non-secret settings: TOML file. Secrets (Canvas token, iCal URL): env vars first,
then a 0600 JSON file. Secrets are never written to the config file or logged.
"""
from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("UNIASSIST_HOME", "~/.config/uniassist")).expanduser()
DEFAULT_CONFIG = CONFIG_DIR / "config.toml"
SECRETS_FILE = CONFIG_DIR / "secrets.json"

SECRET_ENV = {"canvas_token": "CANVAS_TOKEN", "ical_url": "ICAL_URL"}


@dataclass
class Config:
    timezone: str = "Europe/Stockholm"
    canvas_base_url: str = "https://bth.instructure.com"
    llm_host: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b-instruct"
    llm_temperature: float = 0.0
    cache_ttl: int = 300
    cache_dir: Path = field(default_factory=lambda: CONFIG_DIR / "cache")
    programme_path: Path | None = None


def load_config(path: Path | None = None) -> Config:
    path = Path(path).expanduser() if path else DEFAULT_CONFIG
    cfg = Config()
    if not path.exists():
        return cfg
    with path.open("rb") as f:
        raw = tomllib.load(f)
    cfg.timezone = raw.get("timezone", cfg.timezone)
    cfg.canvas_base_url = raw.get("canvas", {}).get("base_url", cfg.canvas_base_url)
    llm = raw.get("llm", {})
    cfg.llm_host = llm.get("host", cfg.llm_host)
    cfg.llm_model = llm.get("model", cfg.llm_model)
    cfg.llm_temperature = float(llm.get("temperature", cfg.llm_temperature))
    cfg.cache_ttl = int(raw.get("cache", {}).get("ttl_seconds", cfg.cache_ttl))
    prog = raw.get("programme", {}).get("path")
    if prog:
        cfg.programme_path = Path(prog).expanduser()
    return cfg


# ---- secrets -------------------------------------------------------------

def _read_secrets() -> dict[str, str]:
    if not SECRETS_FILE.exists():
        return {}
    return json.loads(SECRETS_FILE.read_text())


def _write_secrets(data: dict[str, str]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    fd = os.open(SECRETS_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f)
    os.chmod(SECRETS_FILE, 0o600)


def get_secret(name: str) -> str | None:
    env = os.environ.get(SECRET_ENV[name])
    if env:
        return env
    return _read_secrets().get(name)


def set_secret(name: str, value: str) -> None:
    if name not in SECRET_ENV:
        raise KeyError(name)
    data = _read_secrets()
    data[name] = value
    _write_secrets(data)


def clear_secrets() -> bool:
    """Delete all stored secrets. Returns True if a file was removed."""
    if SECRETS_FILE.exists():
        SECRETS_FILE.unlink()
        return True
    return False


def secret_status() -> dict[str, str]:
    """Where each secret comes from, never its value."""
    out = {}
    for name, env in SECRET_ENV.items():
        if os.environ.get(env):
            out[name] = f"set (env {env})"
        elif name in _read_secrets():
            out[name] = f"set ({SECRETS_FILE})"
        else:
            out[name] = "not set"
    return out
