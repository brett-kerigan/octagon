"""Re-slice campaign orchestration, correct-by-construction.

Connects the ML roundtable (experts + fool) to the AlphaLedger and a reality gate,
enforcing the disciplines that make the ledger's protection real rather than theatre
(selective recording defeats FDR; an inert vault protects nothing). The ledger is the
scarce-budget allocator; reality (the gate) decides.

The campaign:
  table proposes -> SELECT (spend budget only on justified slices) -> register -> run the
  gate -> FORCE-record EVERY registered slice (abandoned -> p=1.0) -> assert_all_resolved
  -> read survivors() ONCE -> verdicts by school -> if anything survives, ONE-SHOT holdout
  confirmation on a SEPARATE ledger behind the vault.

Invariants enforced here by construction:
  1 int budget                          (AlphaLedger asserts; we pass len(slices) or an int)
  2 force-record every registered slice  (the record loop covers all, gate-error -> p=1.0;
                                          then assert_all_resolved() -> no selective recording)
  3 read the family exactly ONCE         (survivors() called once, at close)
  4 each record uses its slice's (p,e)   (per-slice register -> run -> record, no foreign numbers)
  5 holdout isolated on its own ledger   (separate AlphaLedger, never BH-pooled)
  6 holdout data sealed behind the vault (vault_guard() then open_vault() immediately before read)

The gate is injected as `gate_fn(feature_sql, where, label) -> {"p", "effect"}`, so this
loop is fully domain-agnostic. See adapters/example_gate.py for a synthetic gate you can
run with no database.
"""

from alpha_ledger import AlphaLedger

REQUIRED = ("test_id", "school", "feature_sql", "expected")  # `where` is optional (empty = whole population)


def run_campaign(finding, slices, gate_fn, *, budget=None, fdr_alpha=0.10,
                 holdout=None, vault_guard=None):
    """Re-litigate `finding` by running each SELECTED, pre-registered slice through the gate.

    slices:  list of dicts with keys (test_id, school, feature_sql, where, expected[, rationale]).
             Selection from the table's raw proposals happens upstream; only justified slices
             worth the scarce budget reach here.
    gate_fn(feature_sql, where, label) -> {"p": float in [0,1], "effect": float}: the reality
             gate. A raised gate_fn records the slice as a worst-case non-result (p=1.0), so an
             abandoned slice can only hurt the family, never shrink it.
    budget:  hard registration budget (int). Defaults to len(slices).
    holdout: optional one-shot out-of-sample confirmation dict (same keys); run only if the
             exploratory campaign yields a survivor.
    vault_guard: optional callable invoked right before open_vault(); use it to physically
             unseal the holdout data so 'forgetting to check' is impossible.

    Returns {finding, results:[{**slice, p, effect, verdict}], survivors:[id], holdout:{...}|None}.
    """
    for s in slices:
        missing = [k for k in REQUIRED if not s.get(k)]
        if missing:
            raise ValueError(f"slice {s.get('test_id', '?')} missing {missing}")

    L = AlphaLedger(len(slices) if budget is None else budget, fdr_alpha)   # inv 1
    for s in slices:                                                        # pre-register the family
        L.register(s["test_id"], s["school"], s["feature_sql"], s["expected"])

    recorded = {}
    for s in slices:                                                        # inv 2,4: run + record EACH
        p, eff = _gate(gate_fn, s)
        L.record(s["test_id"], p, eff)
        recorded[s["test_id"]] = (p, eff)

    L.assert_all_resolved()                                                 # inv 2: no PENDING shrinks m
    survivors = L.survivors()                                              # inv 3: read ONCE
    results = [{**s, "p": recorded[s["test_id"]][0], "effect": recorded[s["test_id"]][1],
                "verdict": L.verdict(s["test_id"])} for s in slices]
    out = {"finding": finding, "results": results, "survivors": survivors, "holdout": None}

    if holdout and survivors:                                              # inv 5,6: sealed one-shot
        H = AlphaLedger(1, fdr_alpha)                                       # separate ledger, never pooled
        H.register(holdout["test_id"], holdout["school"], holdout["feature_sql"], holdout["expected"])
        if vault_guard:
            vault_guard()                                                  # physically unseal holdout data
        H.open_vault()                                                     # one-shot, immediately before read
        p, eff = _gate(gate_fn, holdout)
        H.record(holdout["test_id"], p, eff)
        H.assert_all_resolved()
        out["holdout"] = {**holdout, "p": p, "effect": eff,
                          "verdict": H.verdict(holdout["test_id"]),
                          "confirmed": holdout["test_id"] in H.survivors()}
    return out


def _gate(gate_fn, s):
    """Run the gate for one slice; an error -> worst-case non-result (p=1.0) so it never lingers PENDING."""
    try:
        r = gate_fn(s["feature_sql"], s.get("where", ""), s["test_id"])
        return float(r["p"]), float(r.get("effect", 0.0))
    except Exception:  # noqa: BLE001
        return 1.0, 0.0


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # DRY RUN with a stub gate (no real gate, no DB): re-litigating a TOSSED finding.
    fake = {"bayes_shrink": (0.004, 0.6), "tree_interaction": (0.30, 0.2),
            "fool_obvious": (0.80, 0.1), "causal_confound": (0.02, -0.4),
            "ts_recent": (0.50, 0.05), "holdout": (0.03, 0.5)}

    def stub_gate(sql, where, label):
        p, e = fake.get(label, (1.0, 0.0))
        return {"p": p, "effect": e}

    def slc(tid, school, expected):
        return {"test_id": tid, "school": school, "feature_sql": f"<{tid} expr>",
                "where": "subgroup <= 3", "expected": expected}

    slices = [slc("bayes_shrink", "bayesian", "pooled effect > 0"),
              slc("tree_interaction", "tree", "effect concentrated in one segment"),
              slc("fool_obvious", "fool", "famous entities behave differently"),
              slc("causal_confound", "causal", "survives controlling for the obvious confound"),
              slc("ts_recent", "timeseries", "holds in the recent regime")]
    holdout = slc("holdout", "bayesian", "replicates out-of-sample")

    unsealed = {"v": False}
    out = run_campaign("a TOSSED finding, re-litigated", slices, stub_gate,
                       fdr_alpha=0.10, holdout=holdout,
                       vault_guard=lambda: unsealed.__setitem__("v", True))

    print(f"=== re-litigating: {out['finding']} ===")
    for r in out["results"]:
        print(f"  {r['school']:<11} {r['test_id']:<18} p={r['p']:<6} -> {r['verdict']}")
    print("exploratory survivors:", out["survivors"])
    h = out["holdout"]
    print(f"holdout (separate ledger, vault-sealed): unsealed-before-read={unsealed['v']} "
          f"-> {h['verdict']} confirmed={h['confirmed']}" if h else "holdout: not run (no survivors)")
