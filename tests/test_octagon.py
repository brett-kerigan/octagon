"""Acceptance tests for the octagon scheduler.

Each test exercises one acceptance scenario (H01-H03) against the public entry point
`run_octagon`, asserting the EXACT observable behavior specified by the scenario.

Interface under test:
    from octagon import run_octagon
    run_octagon(personas, max_rounds, stop_when=None) -> dict
"""

import pytest

from octagon import run_octagon


class Persona:
    """Minimal injected agent: a name plus a speak(transcript) callable.

    `fn` receives the transcript-so-far and returns the str to record.
    A `fn` that raises models a misbehaving persona.
    """

    def __init__(self, name, fn):
        self.name = name
        self._fn = fn

    def speak(self, transcript):
        return self._fn(transcript)


# --------------------------------------------------------------------------
# H01 - core turn scheduler: stable seat order, 1-based rounds, 0-based
# seats, exact max_rounds termination.
# --------------------------------------------------------------------------
def test_h01_core_scheduler_two_personas_two_rounds():
    a = Persona("A", lambda t: "A")
    b = Persona("B", lambda t: "B")

    result = run_octagon([a, b], max_rounds=2, stop_when=None)

    assert result["seats"] == 2
    assert result["rounds_run"] == 2
    assert result["status"] == "completed"
    assert result["transcript"] == [
        {"round": 1, "seat": 0, "name": "A", "text": "A", "error": False},
        {"round": 1, "seat": 1, "name": "B", "text": "B", "error": False},
        {"round": 2, "seat": 0, "name": "A", "text": "A", "error": False},
        {"round": 2, "seat": 1, "name": "B", "text": "B", "error": False},
    ]


# --------------------------------------------------------------------------
# H02 - context threading WITHIN the same round: B and C must observe the
# turns spoken earlier in the very same round.
# --------------------------------------------------------------------------
def test_h02_intra_round_context_threading():
    a = Persona("A", lambda t: "A sees " + str(len(t)))
    b = Persona("B", lambda t: "B sees " + str(len(t)) + " last=" + t[-1]["text"])
    c = Persona("C", lambda t: "C sees " + str(len(t)) + " last=" + t[-1]["text"])

    result = run_octagon([a, b, c], max_rounds=1, stop_when=None)

    assert result["seats"] == 3
    assert result["rounds_run"] == 1
    assert result["status"] == "completed"

    texts = [turn["text"] for turn in result["transcript"]]
    assert texts == [
        "A sees 0",
        "B sees 1 last=A sees 0",
        "C sees 2 last=B sees 1 last=A sees 0",
    ]


# --------------------------------------------------------------------------
# H03 - fault isolation: a raising persona is recorded (text=str(exc),
# error=True) and does NOT abort the round; the next persona still sees
# the recorded error turn.
# --------------------------------------------------------------------------
def _raise_boom(transcript):
    raise ValueError("boom")


def test_h03_exception_isolation_and_visible_error_turn():
    a = Persona("A", lambda t: "ok")
    b = Persona("B", _raise_boom)
    c = Persona("C", lambda t: "saw error=" + str(t[-1]["error"]) + " text=" + t[-1]["text"])

    result = run_octagon([a, b, c], max_rounds=1, stop_when=None)

    assert result["seats"] == 3
    assert result["rounds_run"] == 1
    assert result["status"] == "completed"
    assert result["transcript"] == [
        {"round": 1, "seat": 0, "name": "A", "text": "ok", "error": False},
        {"round": 1, "seat": 1, "name": "B", "text": "boom", "error": True},
        {"round": 1, "seat": 2, "name": "C", "text": "saw error=True text=boom", "error": False},
    ]


# --------------------------------------------------------------------------
# Validation + stop_when behavior.
# --------------------------------------------------------------------------
def test_seat_count_bounds():
    p = Persona("A", lambda t: "A")
    with pytest.raises(ValueError):
        run_octagon([], max_rounds=1)
    with pytest.raises(ValueError):
        run_octagon([Persona(str(i), lambda t: "x") for i in range(5)], max_rounds=1)
    with pytest.raises(ValueError):
        run_octagon([p], max_rounds=0)


def test_duplicate_names_rejected():
    a = Persona("dup", lambda t: "1")
    b = Persona("dup", lambda t: "2")
    with pytest.raises(ValueError):
        run_octagon([a, b], max_rounds=1)


def test_stop_when_halts_early_and_reports_stopped():
    a = Persona("A", lambda t: "A")
    # Stop after the first round completes.
    result = run_octagon([a], max_rounds=5, stop_when=lambda tr: len(tr) >= 1)
    assert result["status"] == "stopped"
    assert result["rounds_run"] == 1
