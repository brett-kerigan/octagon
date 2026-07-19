"""Offline tests for demo.py seat wiring. Constructing clients never touches a network;
only *calling* them would, and these tests never call the live ones."""

import pytest

import client as client_mod
import demo


def test_default_is_stub_stub():
    room, harv, dye, rounds = demo.parse_args([])
    assert room("x") == harv("x")            # both stubs return the same canned line
    assert dye == {} and rounds == 2


def test_legacy_live_flag_maps_to_claude():
    room, harv, dye, _ = demo.parse_args(["--live"])
    assert room is client_mod.claude_cli_client
    assert harv is client_mod.claude_cli_client


def test_room_and_harvest_flags():
    room, harv, _, _ = demo.parse_args(["--room=codex", "--harvest=claude"])
    assert room is client_mod.codex_cli_client
    assert harv is client_mod.claude_cli_client


def test_harvest_defaults_to_room():
    room, harv, _, _ = demo.parse_args(["--room=gemini"])
    assert room is client_mod.gemini_cli_client
    assert harv is client_mod.gemini_cli_client


def test_dye_flag_builds_seat_override():
    _, _, dye, _ = demo.parse_args(["--dye=fool=claude"])
    assert dye == {"fool": client_mod.claude_cli_client}


def test_rounds_flag():
    _, _, _, rounds = demo.parse_args(["--rounds=3"])
    assert rounds == 3


def test_openai_backend_without_env_raises_clearly(monkeypatch):
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        demo.parse_args(["--room=openai"])
    assert "OCTAGON_BASE_URL" in str(exc.value)


def test_unknown_backend_exits_with_message():
    with pytest.raises(SystemExit) as exc:
        demo.parse_args(["--room=chatgpt"])
    assert "chatgpt" in str(exc.value)


def test_example_room_dye_overrides_one_seat():
    a, b = client_mod.stub_client("A"), client_mod.stub_client("B")
    seats = demo.example_room(a, dye={"fool": b})
    by_name = {p.name: p for p in seats}
    assert by_name["fool"].speak([]) == "B"
    assert by_name["dreamer"].speak([]) == "A"


def test_cli_main_offline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)              # run artifacts land in tmp, not the repo
    result = demo.cli_main([])
    assert result["status"] == "completed"
    assert (tmp_path / "last_run.md").exists()
    assert (tmp_path / "last_harvest.md").exists()
