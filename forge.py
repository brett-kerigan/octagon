"""The forge: the incorruptible gate.

The asymmetry the whole project rests on: the table can be infinitely loud, but the gate
must be incorruptible. This is the gate. It does NOT find edges; it refuses to be FOOLED
by them. It is domain-agnostic: you plug in a `score_fn(slice) -> (effect, p, n)` and the
forge wraps it in an anti-self-deception protocol:

  1. PER-ERA REPLICATION    the effect must hold across eras, with a HARD requirement on
                            the MOST RECENT era. Edges decay; a 30-year signal that is
                            dead today is worthless.
  2. FDR / MULTIPLE-TESTING across every hypothesis in a batch, Benjamini-Hochberg the
                            recent-era p-values. Testing 100 challenges and keeping the
                            "best" is how you confirm dice at industrial scale.
  3. SACRED VAULT           a final slice no discovery ever touches, until survivors get
                            ONE shot. Holds in the vault => REAL; fails => MIRAGE.

Verdicts: REAL / DECAYED / MIRAGE / INCONCLUSIVE.
Run `python forge.py --demo` to prove the protocol on synthetic planted signals
(no database, no domain needed).
"""

from __future__ import annotations

import math
import random
import sys

P_RECENT = 0.05      # significance bar for the recent-era hard requirement
FDR_ALPHA = 0.10     # false-discovery rate across the batch


# ---- stats (no scipy dependency) -------------------------------------------------
def _phi(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def corr_test(xs, ys):
    """Pearson r + two-sided p (normal approx; fine for n>~100, understates p for small
    samples). Returns (effect, p, n)."""
    if len(xs) != len(ys):
        raise ValueError(f"xs and ys must be the same length; got {len(xs)} and {len(ys)}")
    n = len(xs)
    if n < 3:
        return 0.0, 1.0, n
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0, 1.0, n
    r = max(min(sxy / math.sqrt(sxx * syy), 0.999999), -0.999999)
    t = r * math.sqrt((n - 2) / (1 - r * r))
    return r, 2 * (1 - _phi(abs(t))), n


def benjamini_hochberg(pvals, alpha):
    """Return a list of bools: which p-values survive BH-FDR at `alpha`."""
    m = len(pvals)
    order = sorted(range(m), key=lambda i: pvals[i])
    cutoff = 0
    for rank, i in enumerate(order, 1):
        if pvals[i] <= alpha * rank / m:
            cutoff = rank
    sig = [False] * m
    for rank, i in enumerate(order, 1):
        if rank <= cutoff:
            sig[i] = True
    return sig


def tail_concentration(xs, ys, k=10):
    """Is the effect TAIL-concentrated (flat middle, strong extremes) rather than linear?
    A linear-only score undersells tail-shaped edges. Bin by x into k quantiles, fit a line
    to the per-bin mean of y, and report the extreme spread plus how far the tail bins
    deviate from that line. A big extreme_spread with low linear r is the signature of a
    real tail edge."""
    n = len(xs)
    if n < k * 5:
        return {"k": k, "extreme_spread": 0.0, "tail_dev": 0.0, "bin_means": []}
    order = sorted(range(n), key=lambda i: xs[i])
    size = n // k
    bins = [order[i * size:(i + 1) * size] for i in range(k)]
    bins[-1] = order[(k - 1) * size:]                       # last bin takes the remainder
    means = [sum(ys[i] for i in b) / len(b) for b in bins]
    idx = list(range(k))
    mi, mm = sum(idx) / k, sum(means) / k
    sxx = sum((i - mi) ** 2 for i in idx)
    slope = (sum((i - mi) * (m - mm) for i, m in zip(idx, means)) / sxx) if sxx else 0.0
    fit = [mm + slope * (i - mi) for i in idx]
    devs = [m - f for m, f in zip(means, fit)]
    return {"k": k,
            "extreme_spread": round(means[-1] - means[0], 4),   # top-bin minus bottom-bin
            "tail_dev": round(max(abs(devs[0]), abs(devs[-1])), 4),
            "bin_means": [round(m, 4) for m in means]}


# ---- the protocol ----------------------------------------------------------------
def gate_one(score_fn, eras, recent_era, p_recent=P_RECENT):
    """Score a hypothesis across discovery eras (the vault is NOT passed here).
    Returns (per_era, consistent, recent_ok, older_strong, recent_p)."""
    if recent_era not in eras:
        raise ValueError(f"recent_era {recent_era!r} is not among the eras {sorted(eras)}")
    per = {}
    for era, slice_ in eras.items():
        eff, p, n = score_fn(slice_)
        per[era] = {"effect": eff, "p": p, "n": n}
    nz = [per[e]["effect"] > 0 for e in per if abs(per[e]["effect"]) > 1e-9]
    consistent = len(set(nz)) <= 1
    rec = per[recent_era]
    recent_ok = rec["p"] < p_recent
    older_strong = any(per[e]["p"] < p_recent for e in per if e != recent_era)
    return per, consistent, recent_ok, older_strong, rec["p"]


def classify(consistent, recent_ok, older_strong, fdr_ok, vault_ok):
    if not consistent:
        return "MIRAGE"                      # never coherent across eras
    if not recent_ok and older_strong:
        return "DECAYED"                     # was real, died in the recent era
    if not recent_ok:
        return "MIRAGE"                      # not alive now
    if not fdr_ok:
        return "MIRAGE"                      # didn't survive multiple-testing
    if vault_ok is False:
        return "MIRAGE"                      # overfit; failed the sacred vault
    return "REAL" if vault_ok else "INCONCLUSIVE"


def gate_batch(hypotheses, recent_era, alpha=FDR_ALPHA):
    """hypotheses: list of dicts {name, score_fn, eras, vault}.
    Runs per-era -> FDR across the batch -> one-shot vault on survivors -> verdicts."""
    rows = []
    for h in hypotheses:
        per, consistent, recent_ok, older_strong, rp = gate_one(h["score_fn"], h["eras"], recent_era)
        rows.append({"name": h["name"], "per": per, "consistent": consistent,
                     "recent_ok": recent_ok, "older_strong": older_strong,
                     "recent_p": rp, "score_fn": h["score_fn"], "vault": h["vault"]})

    fdr = benjamini_hochberg([r["recent_p"] for r in rows], alpha)
    for r, ok in zip(rows, fdr):
        r["fdr_ok"] = ok

    # one-shot vault: ONLY for hypotheses still alive after per-era + FDR
    for r in rows:
        alive = r["consistent"] and r["recent_ok"] and r["fdr_ok"]
        if alive:
            v_eff, v_p, _ = r["score_fn"](r["vault"])
            r["vault_ok"] = (v_p < P_RECENT) and ((v_eff > 0) == (r["per"][recent_era]["effect"] > 0))
            r["vault_effect"] = v_eff
        else:
            r["vault_ok"] = None
            r["vault_effect"] = None
        r["verdict"] = classify(r["consistent"], r["recent_ok"], r["older_strong"],
                                 r["fdr_ok"], r["vault_ok"])
    return rows


# ---- synthetic demo: prove the protocol catches what it must ---------------------
def _planted(rng, r_by_era, vault_r, n=400):
    """Build a hypothesis whose feature-outcome correlation is r per era (+ in vault)."""
    def make(r):
        xs = [rng.gauss(0, 1) for _ in range(n)]
        ys = [r * x + math.sqrt(max(1 - r * r, 0)) * rng.gauss(0, 1) for x in xs]
        return list(zip(xs, ys))
    eras = {era: make(r) for era, r in r_by_era.items()}
    vault = make(vault_r)
    return eras, vault


def _planted_tail(rng, edge, n=600):
    """Tail-shaped: flat middle, strong ONLY in the extreme deciles. Linear corr is weak;
    the real signal lives at d1/d10, the exact shape a linear gate undersells."""
    def make(e):
        out = []
        for _ in range(n):
            x = rng.gauss(0, 1)
            y = (-e * 3 if x < -1.0 else e * 3 if x > 1.0 else 0.0) + rng.gauss(0, 1)
            out.append((x, y))
        return out
    return {er: make(edge) for er in ("2010-14", "2015-19", "2020-24")}, make(edge)


def _score(slice_):
    xs = [a for a, _ in slice_]
    ys = [b for _, b in slice_]
    return corr_test(xs, ys)


def demo():
    rng = random.Random(7)
    recent = "2020-24"

    def H(name, r_old, r_recent, r_vault):
        e, v = _planted(rng, {"2010-14": r_old, "2015-19": r_old, "2020-24": r_recent}, r_vault)
        return {"name": name, "score_fn": _score, "eras": e, "vault": v}

    et, vt = _planted_tail(rng, 0.45)
    hyps = [
        H("REAL linear     (holds everywhere)", 0.25, 0.25, 0.25),
        H("DECAYED         (died post-2020)",   0.30, 0.02, 0.02),
        H("MIRAGE/overfit  (discovery only)",   0.18, 0.18, 0.00),
        {"name": "TAIL (tail-shaped)", "score_fn": _score, "eras": et, "vault": vt},
    ]
    for k in range(20):                     # 20 pure-noise nulls: multiple-testing torture
        hyps.append(H(f"null-{k:02d}", 0.0, 0.0, 0.0))

    recent_slices = {h["name"]: h["eras"][recent] for h in hyps}
    rows = gate_batch(hyps, recent)

    print(f"{'hypothesis':<34} {'recent_r':>8} {'recent_p':>8} {'fdr':>4} "
          f"{'vault_r':>8} {'tail_spread':>11} {'VERDICT':>10}")
    print("-" * 90)
    named = [r for r in rows if not r["name"].startswith("null")]
    nulls = [r for r in rows if r["name"].startswith("null")]
    for r in named:
        rr = r["per"][recent]
        sl = recent_slices[r["name"]]
        tc = tail_concentration([a for a, _ in sl], [b for _, b in sl])
        vault_str = (str(round(r['vault_effect'], 4)) if r['vault_effect'] is not None
                     else str(None))
        print(f"{r['name']:<34} {round(rr['effect'], 4):>8} {round(rr['p'], 4):>8} "
              f"{'Y' if r['fdr_ok'] else 'n':>4} {vault_str:>8} "
              f"{tc['extreme_spread']:>11} {r['verdict']:>10}")
    fp = sum(1 for r in nulls if r["verdict"] == "REAL")
    print("-" * 90)
    print(f"20 pure-noise nulls -> {fp} survived as REAL (FDR <= {FDR_ALPHA:.0%}).")
    print("TAIL row: monotonic but flat-middled. The linear/decile measure dilutes the "
          "magnitude across the dead middle, while tail_spread captures the true "
          "extreme-decile edge: the exact shape a linear gate undersells.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    if "--demo" not in sys.argv[1:]:
        print("usage: python forge.py --demo    (or: octagon gate --demo)", file=sys.stderr)
        sys.exit(2)
    demo()
