"""A synthetic reality gate, so the re-slice campaign runs end-to-end with no database.

In a real deployment, `gate_fn(feature_sql, where, label)` runs the feature against your
historical data and returns a real (p, effect). Here we fabricate a deterministic,
reproducible result per label by planting a known signal and measuring it with the same
stats the forge uses. Swap this for a database-backed gate to go live; the campaign
orchestration (adapters/reslice.py) does not change.
"""

from __future__ import annotations

import hashlib
import math

from forge import corr_test


def _seed_for(label: str) -> int:
    # Deterministic per-label seed (Math.random would not be reproducible across runs).
    return int(hashlib.sha256(label.encode("utf-8")).hexdigest(), 16) % (2 ** 32)


class _Rng:
    """Tiny deterministic Gaussian source (stdlib `random` seeded per label)."""

    def __init__(self, seed):
        import random
        self._r = random.Random(seed)

    def gauss(self):
        return self._r.gauss(0, 1)


def make_example_gate(planted_effects=None, n=500):
    """Return a gate_fn(feature_sql, where, label) -> {"p", "effect"}.

    planted_effects: optional {label: true_correlation} map. Labels not listed are planted
    as pure noise (true correlation 0), so an honest gate should mostly reject them.
    """
    planted_effects = planted_effects or {}

    def gate_fn(feature_sql, where, label):
        r_true = float(planted_effects.get(label, 0.0))
        rng = _Rng(_seed_for(label + "|" + (where or "")))
        xs, ys = [], []
        for _ in range(n):
            x = rng.gauss()
            y = r_true * x + math.sqrt(max(1 - r_true * r_true, 0)) * rng.gauss()
            xs.append(x)
            ys.append(y)
        effect, p, _ = corr_test(xs, ys)
        return {"p": p, "effect": effect}

    return gate_fn


if __name__ == "__main__":
    # Show the synthetic gate scoring one real signal and one noise label.
    gate = make_example_gate({"real_signal": 0.25})
    print("real_signal:", gate("<expr>", "", "real_signal"))
    print("noise_label:", gate("<expr>", "", "noise_label"))
