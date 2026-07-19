"""Offline tests for the `octagon` CLI. doctor is fully mocked; gate/demo dispatch run
the real offline code paths."""

import json
import urllib.request

import pytest

import cli
from harvest import HARVEST_PROMPT
from personas import ROSTER, SYSTEMS


def test_systems_covers_the_whole_roster():
    assert set(SYSTEMS) == set(ROSTER)


def test_doctor_never_raises_and_covers_all_backends(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    def boom(*a, **kw):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    checks = cli.run_doctor()
    assert set(checks) == {"claude", "codex", "gemini", "ollama", "openai_compat"}
    assert all(c["available"] is False for c in checks.values())


def test_doctor_survives_a_raising_which(monkeypatch):
    def bad_which(name):
        raise OSError("unreadable PATH entry")
    monkeypatch.setattr(cli.shutil, "which", bad_which)
    def boom(*a, **kw):
        raise OSError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    checks = cli.run_doctor()
    assert checks["claude"]["available"] is False
    assert "probe failed" in checks["claude"]["detail"]


def test_doctor_reports_available_backends(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    import io, contextlib
    body = json.dumps({"models": [{"name": "m1"}]}).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: contextlib.closing(io.BytesIO(body)))
    checks = cli.run_doctor()
    assert all(c["available"] for c in checks.values())
    assert "1 model" in checks["ollama"]["detail"]


def test_doctor_json_flag_prints_parseable_json(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    def boom(*a, **kw):
        raise OSError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert cli.main(["doctor", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "claude" in parsed


def test_prompt_prints_canonical_text(capsys):
    assert cli.main(["prompt", "dreamer"]) == 0
    assert capsys.readouterr().out.strip() == SYSTEMS["dreamer"].strip()


def test_prompt_harvest(capsys):
    assert cli.main(["prompt", "harvest"]) == 0
    assert capsys.readouterr().out.strip() == HARVEST_PROMPT.strip()


def test_prompt_list_names_the_bench(capsys):
    assert cli.main(["prompt", "--list"]) == 0
    out = capsys.readouterr().out
    for name in list(ROSTER) + ["harvest"]:
        assert name in out


def test_prompt_unknown_name_errors(capsys):
    assert cli.main(["prompt", "nostradamus"]) == 2
    assert "nostradamus" in capsys.readouterr().err


def test_gate_demo_dispatch_runs_the_synthetic_proof(capsys):
    assert cli.main(["gate", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "VERDICT" in out and "pure-noise nulls" in out


def test_demo_dispatch_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["demo"]) == 0
    assert (tmp_path / "last_run.md").exists()


def test_demo_help_does_not_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as exc:
        cli.main(["demo", "--help"])
    assert exc.value.code == 0
    assert "--room" in capsys.readouterr().out
    assert not (tmp_path / "last_run.md").exists()
