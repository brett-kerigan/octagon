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


def _codex_jsonl(text):
    return "\n".join([
        json.dumps({"type": "session.created", "session_id": "s1"}),
        json.dumps({"type": "item.completed",
                    "item": {"type": "agent_message", "text": text}}),
    ])


def test_codex_cli_parses_agent_message(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/codex")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc(_codex_jsonl("pong")))
    assert client_mod.codex_cli_client("ping") == "pong"


def test_codex_cli_env_keeps_only_openai_creds(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leak-me")
    monkeypatch.setenv("OPENAI_API_KEY", "keep-me")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return _fake_proc(_codex_jsonl("ok"))

    monkeypatch.setattr(client_mod.subprocess, "run", fake_run)
    client_mod.codex_cli_client("prompt")
    assert captured["env"].get("OPENAI_API_KEY") == "keep-me"
    assert "ANTHROPIC_API_KEY" not in captured["env"]


def test_codex_cli_no_agent_message_raises(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/codex")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("garbage\nnot json"))
    with pytest.raises(RuntimeError) as exc:
        client_mod.codex_cli_client("prompt")
    assert "agent_message" in str(exc.value)


def test_gemini_cli_returns_stdout(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/gemini")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("a reply\n"))
    assert client_mod.gemini_cli_client("ping") == "a reply"


def test_gemini_cli_empty_output_raises(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/gemini")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("   \n"))
    with pytest.raises(RuntimeError) as exc:
        client_mod.gemini_cli_client("prompt")
    assert "empty" in str(exc.value)


def test_missing_binary_raises_for_each_vendor(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: None)
    for fn in (client_mod.codex_cli_client, client_mod.gemini_cli_client):
        with pytest.raises(RuntimeError) as exc:
            fn("prompt")
        assert "not on PATH" in str(exc.value)


import contextlib
import io
import urllib.request


def _fake_urlopen_returning(payload_dict):
    def fake_urlopen(req, timeout=None):
        body = json.dumps(payload_dict).encode("utf-8")
        fake = io.BytesIO(body)
        return contextlib.closing(fake)
    return fake_urlopen


def test_openai_compat_needs_base_url(monkeypatch):
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        client_mod.openai_compat_client("some-model")
    assert "OCTAGON_BASE_URL" in str(exc.value)


def test_openai_compat_needs_model(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.delenv("OCTAGON_MODEL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        client_mod.openai_compat_client()
    assert "OCTAGON_MODEL" in str(exc.value)


def test_openai_compat_parses_choices(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_returning(
        {"choices": [{"message": {"content": "a reply"}}]}))
    c = client_mod.openai_compat_client("local-model")
    assert c("ping") == "a reply"


def test_openai_compat_bad_shape_raises(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_returning({"nope": 1}))
    c = client_mod.openai_compat_client("local-model")
    with pytest.raises(RuntimeError) as exc:
        c("ping")
    assert "unexpected shape" in str(exc.value)


def test_openai_compat_auth_header_only_when_key_set(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        return contextlib.closing(io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.delenv("OCTAGON_API_KEY", raising=False)
    client_mod.openai_compat_client("m")("ping")
    assert captured["auth"] is None
    monkeypatch.setenv("OCTAGON_API_KEY", "sk-test")
    client_mod.openai_compat_client("m")("ping")
    assert captured["auth"] == "Bearer sk-test"
