import os
import stat

from uniassist import config, cli


def test_secrets_file_permissions_and_clear(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "secrets.json")
    monkeypatch.delenv("CANVAS_TOKEN", raising=False)
    config.set_secret("canvas_token", "abc")
    assert stat.S_IMODE(os.stat(config.SECRETS_FILE).st_mode) == 0o600
    assert config.get_secret("canvas_token") == "abc"
    assert "abc" not in str(config.secret_status())
    assert config.clear_secrets() and config.get_secret("canvas_token") is None


def test_env_overrides_file(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "s.json")
    monkeypatch.setenv("CANVAS_TOKEN", "fromenv")
    assert config.get_secret("canvas_token") == "fromenv"


def test_cli_summary_and_tool(capsys):
    assert cli.main(["--mock", "summary"]) == 0
    assert "Assignment 2" in capsys.readouterr().out
    assert cli.main(["--mock", "tool", "get_next_lecture"]) == 0
    assert "Diffusion" in capsys.readouterr().out


def test_cli_schedule_add(tmp_path, monkeypatch, capsys):
    from uniassist import schedule
    monkeypatch.setattr(schedule, "MANUAL_FILE", tmp_path / "m.json")
    assert cli.main(["schedule", "add", "--title", "Lecture 1", "--start", "2026-12-01 10:15"]) == 0
    assert (tmp_path / "m.json").exists()
