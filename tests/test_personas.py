"""Tests for the persona + client (model/IO) layer, not just the pure scheduler.

These exercise the injected-client contract, prompt rendering, the str-coercion guarantee,
draft() validation, and the graceful-failure paths of the live clients (without making any
network call).
"""

import pytest

import client as client_mod
from octagon import run_octagon
from personas import LLMPersona, draft, dreamer


def test_persona_uses_injected_client_and_sees_context():
    seen = {}

    def spy(prompt):
        seen["prompt"] = prompt
        return "my contribution"

    p = LLMPersona("dreamer", "SYS", spy, topic="the topic", domain="the world")
    out = p.speak([])
    assert out == "my contribution"
    # The render must carry system prompt, domain, topic, and the seat's own turn marker.
    assert "SYS" in seen["prompt"]
    assert "the world" in seen["prompt"]
    assert "the topic" in seen["prompt"]
    assert "Your turn, dreamer" in seen["prompt"]


def test_speak_coerces_non_str_to_str():
    # The octagon stores whatever speak() returns verbatim; the persona must guarantee str.
    p = LLMPersona("x", "SYS", lambda prompt: 12345)
    assert p.speak([]) == "12345"
    assert isinstance(p.speak([]), str)


def test_persona_renders_prior_transcript():
    captured = {}
    p = LLMPersona("b", "SYS", lambda prompt: captured.setdefault("p", prompt) or "ok")
    transcript = [{"round": 1, "seat": 0, "name": "a", "text": "first idea", "error": False}]
    p.speak(transcript)
    assert "a: first idea" in captured["p"]


def test_bad_persona_construction_rejected():
    with pytest.raises(ValueError):
        LLMPersona("", "SYS", lambda p: "x")
    with pytest.raises(TypeError):
        LLMPersona("name", "SYS", "not callable")


def test_draft_validates_lineup():
    c = lambda prompt: "x"
    with pytest.raises(KeyError):
        draft(["dreamer", "nope"], c)
    with pytest.raises(ValueError):
        draft([], c)
    table = draft(["dreamer", "skeptic"], c, topic="t", domain="d")
    assert [p.name for p in table] == ["dreamer", "skeptic"]


def test_full_offline_run_with_stub_personas():
    # A real end-to-end octagon run using stub-backed personas, no network.
    stub = client_mod.stub_client("(stub provocation)")
    table = [dreamer(stub, topic="t", domain="d")]
    result = run_octagon(table, max_rounds=2)
    assert result["status"] == "completed"
    assert all(turn["text"] == "(stub provocation)" for turn in result["transcript"])


def test_echo_client_reports_length():
    assert client_mod.echo_client("abcd").startswith("(echo: prompt was 4")


def test_claude_cli_client_raises_clearly_when_cli_missing(monkeypatch):
    # IO layer: a missing CLI must raise a clear RuntimeError, not hang or crash obscurely.
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError) as exc:
        client_mod.claude_cli_client("hello")
    assert "claude" in str(exc.value).lower()
