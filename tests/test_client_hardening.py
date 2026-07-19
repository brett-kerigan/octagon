"""Regression tests for the Pass-3 hardening fixes (see HARDENING.md).

These assert the model/IO client layer degrades safely and does not leak secrets, without
making any network call.
"""

import json
import types

import pytest

import client as client_mod


def test_scoped_env_strips_unrelated_provider_secrets(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak-me")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leak")
    monkeypatch.setenv("SOME_TOKEN", "leak")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep-me")     # the CLI's own creds survive
    monkeypatch.setenv("PATH", "/usr/bin")                  # ordinary vars survive
    env = client_mod._scoped_env()
    assert "OPENAI_API_KEY" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert "SOME_TOKEN" not in env
    assert env.get("ANTHROPIC_API_KEY") == "keep-me"
    assert env.get("PATH") == "/usr/bin"


def _fake_proc(stdout, returncode=0, stderr=""):
    return types.SimpleNamespace(stdout=stdout, returncode=returncode, stderr=stderr)


def test_claude_cli_passes_scoped_env(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/claude")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-leak")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return _fake_proc(json.dumps({"result": "hi"}))

    monkeypatch.setattr(client_mod.subprocess, "run", fake_run)
    out = client_mod.claude_cli_client("prompt")
    assert out == "hi"
    assert captured["env"] is not None                      # an explicit env was passed
    assert "OPENAI_API_KEY" not in captured["env"]          # and it was scrubbed


def test_claude_cli_non_json_raises_clear_error(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/claude")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("not json at all"))
    with pytest.raises(RuntimeError) as exc:
        client_mod.claude_cli_client("prompt")
    assert "non-JSON" in str(exc.value)


def test_claude_cli_error_envelope_raises(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/claude")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc(json.dumps({"is_error": True, "subtype": "rate_limit"})))
    with pytest.raises(RuntimeError) as exc:
        client_mod.claude_cli_client("prompt")
    assert "rate_limit" in str(exc.value)


def test_scoped_env_allow_prefixes_parameter(monkeypatch):
    """Each vendor's child keeps only its own credentials."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-cred")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-cred")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-cred")
    env = client_mod._scoped_env(allow_prefixes=("OPENAI", "CODEX"))
    assert env.get("OPENAI_API_KEY") == "openai-cred"
    assert "ANTHROPIC_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env
