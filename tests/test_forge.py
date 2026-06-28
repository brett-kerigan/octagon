"""Tests for the forge (the gate): the stats primitives and the end-to-end protocol.

The headline property: a batch of pure-noise nulls must (almost always) yield zero REAL
verdicts under FDR. That is the whole reason the gate exists.
"""

import random

from forge import (benjamini_hochberg, corr_test, tail_concentration,
                   gate_batch, _planted, _planted_tail, _score)


def test_corr_test_detects_strong_correlation():
    xs = list(range(100))
    ys = [2 * x + 1 for x in xs]          # perfectly linear
    r, p, n = corr_test(xs, ys)
    assert r > 0.99
    assert p < 0.001
    assert n == 100


def test_corr_test_degenerate_inputs():
    assert corr_test([1, 2], [1, 2]) == (0.0, 1.0, 2)        # n < 3
    assert corr_test([1, 1, 1], [1, 2, 3]) == (0.0, 1.0, 3)  # zero variance in x


def test_benjamini_hochberg_basic():
    # One tiny p among large ones survives; all-large survive none.
    sig = benjamini_hochberg([0.001, 0.4, 0.6, 0.8], 0.10)
    assert sig[0] is True
    assert sig.count(True) >= 1
    assert benjamini_hochberg([0.3, 0.5, 0.7, 0.9], 0.10) == [False, False, False, False]


def test_tail_concentration_flags_tail_shape():
    rng = random.Random(1)
    xs, ys = [], []
    for _ in range(600):
        x = rng.gauss(0, 1)
        y = (-3 if x < -1 else 3 if x > 1 else 0) + rng.gauss(0, 1)
        xs.append(x)
        ys.append(y)
    tc = tail_concentration(xs, ys)
    assert tc["extreme_spread"] > 1.0     # strong extremes
    assert tc["tail_dev"] > 0.0           # deviates from a straight line


def test_gate_batch_rejects_pure_noise_family():
    rng = random.Random(7)
    recent = "2020-24"
    hyps = []
    for k in range(20):
        e, v = _planted(rng, {"2010-14": 0.0, "2015-19": 0.0, "2020-24": 0.0}, 0.0)
        hyps.append({"name": f"null-{k}", "score_fn": _score, "eras": e, "vault": v})
    rows = gate_batch(hyps, recent)
    reals = [r for r in rows if r["verdict"] == "REAL"]
    assert reals == []                    # no noise should pass the full protocol


def test_gate_batch_confirms_a_real_signal():
    rng = random.Random(3)
    recent = "2020-24"
    e, v = _planted(rng, {"2010-14": 0.3, "2015-19": 0.3, "2020-24": 0.3}, 0.3)
    real = {"name": "real", "score_fn": _score, "eras": e, "vault": v}
    nulls = []
    for k in range(10):
        ne, nv = _planted(rng, {"2010-14": 0.0, "2015-19": 0.0, "2020-24": 0.0}, 0.0)
        nulls.append({"name": f"null-{k}", "score_fn": _score, "eras": ne, "vault": nv})
    rows = gate_batch([real] + nulls, recent)
    verdict = next(r["verdict"] for r in rows if r["name"] == "real")
    assert verdict == "REAL"


def test_gate_batch_marks_decayed_signal():
    rng = random.Random(11)
    recent = "2020-24"
    # strong in old eras, dead in the recent era => DECAYED, never REAL.
    e, v = _planted(rng, {"2010-14": 0.35, "2015-19": 0.35, "2020-24": 0.0}, 0.0)
    rows = gate_batch([{"name": "old", "score_fn": _score, "eras": e, "vault": v}], recent)
    assert rows[0]["verdict"] in ("DECAYED", "MIRAGE")
    assert rows[0]["verdict"] != "REAL"
