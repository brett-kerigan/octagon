"""Tests for the AlphaLedger: the anti-p-hacking core.

Covers the budget int-guard (the adversarial-review finding), registration/recording
contracts, BH-FDR survivor selection, the selective-recording guard, and the one-shot vault.
"""

import pytest

from alpha_ledger import AlphaLedger


def test_budget_must_be_positive_int():
    # The hard-cap defeat the review found: NaN/inf/float silently bypass an int budget.
    with pytest.raises(ValueError):
        AlphaLedger(float("inf"))
    with pytest.raises(ValueError):
        AlphaLedger(2.5)
    with pytest.raises(ValueError):
        AlphaLedger(True)        # bool is an int subclass; must be rejected explicitly
    with pytest.raises(ValueError):
        AlphaLedger(0)
    AlphaLedger(3)               # a positive int is fine


def test_registration_budget_is_hard():
    L = AlphaLedger(2)
    L.register("a", "f", "s", "e")
    L.register("b", "f", "s", "e")
    assert L.remaining() == 0
    with pytest.raises(ValueError):
        L.register("c", "f", "s", "e")


def test_cannot_record_unregistered_or_twice():
    L = AlphaLedger(2)
    with pytest.raises(ValueError):
        L.record("ghost", 0.01, 0.1)
    L.register("a", "f", "s", "e")
    L.record("a", 0.01, 0.1)
    with pytest.raises(ValueError):
        L.record("a", 0.02, 0.2)


def test_pvalue_bounds_validated():
    L = AlphaLedger(1)
    L.register("a", "f", "s", "e")
    with pytest.raises(ValueError):
        L.record("a", 1.5, 0.1)


def test_bh_fdr_survivors():
    # One strong signal among nulls should survive BH at alpha=0.10.
    L = AlphaLedger(5, fdr_alpha=0.10)
    for tid, p in [("strong", 0.001), ("n1", 0.4), ("n2", 0.6), ("n3", 0.8), ("n4", 0.95)]:
        L.register(tid, "f", "s", "e")
        L.record(tid, p, 0.2)
    survivors = L.survivors()
    assert "strong" in survivors
    assert L.verdict("strong") == "SURVIVED"
    assert L.verdict("n4") == "REJECTED"


def test_all_nulls_yield_no_survivors():
    L = AlphaLedger(4, fdr_alpha=0.10)
    for i, p in enumerate([0.3, 0.5, 0.7, 0.9]):
        L.register(f"n{i}", "f", "s", "e")
        L.record(f"n{i}", p, 0.0)
    assert L.survivors() == []


def test_assert_all_resolved_blocks_selective_recording():
    L = AlphaLedger(3)
    for tid in ("a", "b", "c"):
        L.register(tid, "f", "s", "e")
    L.record("a", 0.01, 0.2)
    # Leaving b and c PENDING would shrink the BH family; the guard forbids it.
    with pytest.raises(ValueError):
        L.assert_all_resolved()
    L.record("b", 0.5, 0.0)
    L.record("c", 0.6, 0.0)
    L.assert_all_resolved()       # now legal


def test_vault_is_one_shot():
    L = AlphaLedger(1)
    L.open_vault()
    assert L.vault_open() is True
    with pytest.raises(ValueError):
        L.open_vault()


def test_pending_verdict_before_record():
    L = AlphaLedger(1)
    L.register("a", "f", "s", "e")
    assert L.verdict("a") == "PENDING"
    assert L.verdict("never") == "UNREGISTERED"
