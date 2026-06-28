"""Tests for the adapters: the SQLite idea store, the synthetic gate, and the re-slice
campaign orchestration. All run offline with no external services.
"""

from adapters.store import IdeaStore, parse_challenges, jaccard
from adapters.example_gate import make_example_gate
from adapters.reslice import run_campaign


# ---- store -----------------------------------------------------------------------
def test_store_dedups_paraphrases_and_counts():
    with IdeaStore(":memory:", threshold=0.5) as s:
        s.ingest_one("d", "1. fade horses on a hot streak | from: scientist")
        r = s.ingest_one("d", "2. fade horses that are on a hot streak | from: dreamer")
        assert r["new"] is False          # near-paraphrase collapses onto the first
        rows = s.report("d")
        assert len(rows) == 1
        assert rows[0][0] == 2            # seen_count == 2


def test_store_keeps_distinct_ideas_apart():
    with IdeaStore(":memory:", threshold=0.5) as s:
        s.ingest_one("d", "1. weather affects outcomes | from: fool")
        r = s.ingest_one("d", "2. late money signals informed bettors | from: insider")
        assert r["new"] is True
        assert len(s.report("d")) == 2


def test_store_records_first_persona_provenance():
    with IdeaStore(":memory:", threshold=0.5) as s:
        out = s.ingest_one("d", "1. some novel idea here | from: fool")
        assert out["persona"] == "fool"


def test_parse_challenges_splits_numbered_list():
    text = "1. first idea | from: a\n2. second idea | from: b\nnot a challenge"
    items = parse_challenges(text)
    assert len(items) == 2


def test_jaccard_bounds():
    assert jaccard("a b c", "a b c") == 1.0
    assert jaccard("a b c", "x y z") == 0.0


# ---- example gate ----------------------------------------------------------------
def test_example_gate_is_deterministic():
    g = make_example_gate({"real": 0.3})
    a = g("<expr>", "", "real")
    b = g("<expr>", "", "real")
    assert a == b                         # same label -> same planted result
    assert a["effect"] > 0.1


def test_example_gate_noise_label_is_weak():
    g = make_example_gate({"real": 0.3})
    noise = g("<expr>", "", "unlisted_noise_label")
    assert abs(noise["effect"]) < 0.2     # unplanted labels are ~noise


# ---- re-slice campaign -----------------------------------------------------------
def test_campaign_force_records_and_confirms_holdout():
    planted = {"good": 0.3, "holdout": 0.3}     # one real slice + a real holdout
    gate = make_example_gate(planted, n=2000)

    def slc(tid, school):
        return {"test_id": tid, "school": school, "feature_sql": f"<{tid}>",
                "where": "", "expected": "effect > 0"}

    slices = [slc("good", "tree"), slc("dud1", "bayesian"), slc("dud2", "causal")]
    holdout = slc("holdout", "tree")
    out = run_campaign("a finding", slices, gate, holdout=holdout)

    assert "good" in out["survivors"]
    assert "dud1" not in out["survivors"]
    assert out["holdout"] is not None
    assert out["holdout"]["confirmed"] is True


def test_campaign_with_no_survivors_skips_holdout():
    gate = make_example_gate({}, n=500)         # everything is noise
    slc = lambda tid: {"test_id": tid, "school": "x", "feature_sql": "<e>",
                       "where": "", "expected": "e>0"}
    out = run_campaign("f", [slc("a"), slc("b")], gate, holdout=slc("h"))
    assert out["survivors"] == []
    assert out["holdout"] is None


def test_campaign_missing_required_field_raises():
    import pytest
    bad = [{"test_id": "a", "school": "x", "expected": "e"}]   # no feature_sql
    with pytest.raises(ValueError):
        run_campaign("f", bad, make_example_gate({}))
