"""Tests for the harvest and scout stages: both delegate to an injected client, so we
assert they build the right prompt and pass content through, using a capturing stub.
"""

from harvest import harvest
from scout import scout


def test_harvest_empty_transcript_short_circuits():
    assert harvest([], lambda p: "should not be called").startswith("(empty")


def test_harvest_passes_transcript_to_client():
    captured = {}

    def spy(prompt):
        captured["p"] = prompt
        return "1. an idea | from: dreamer | first test: look"

    transcript = [{"round": 1, "seat": 0, "name": "dreamer", "text": "a wild idea", "error": False}]
    out = harvest(transcript, spy)
    assert "dreamer: a wild idea" in captured["p"]
    assert out.startswith("1.")


def test_scout_empty_short_circuits():
    assert scout("", lambda p: "x", sources="anything").startswith("(no challenges")


def test_scout_injects_sources_and_challenges():
    captured = {}

    def spy(prompt):
        captured["p"] = prompt
        return "routed"

    scout(["1. test something"], spy, sources="OUR DATA: a, b, c")
    assert "OUR DATA: a, b, c" in captured["p"]
    assert "1. test something" in captured["p"]
