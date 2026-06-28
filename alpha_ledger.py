"""AlphaLedger: the anti-p-hacking core for a re-slice campaign.

When several lenses re-slice the same finding, you are multiple-testing your way toward
confirming noise unless something enforces discipline. The ledger is that something. It
enforces:

  - a hard PRE-REGISTRATION budget: you declare how many tests the family may contain,
    up front, and registration fails once the budget is exhausted;
  - result-only-after-registration: you cannot record a p-value for a test you never
    registered;
  - Benjamini-Hochberg FDR across the whole recorded family, read once at close;
  - a one-shot SACRED VAULT: a final holdout that survivors get exactly one shot at;
  - `assert_all_resolved()`, which forbids the selective-recording p-hack (shrinking the
    BH family by leaving inconvenient tests unrecorded).

Two guards worth calling out, both the product of adversarial review: the budget is
validated as a positive int (a NaN/inf/float silently defeats a hard cap otherwise), and
`assert_all_resolved()` lets the orchestration require every registered test to be
recorded before survivors are read. Pure stdlib.
"""


class AlphaLedger:
    def __init__(self, budget, fdr_alpha=0.10):
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise ValueError(f"budget must be an int, got {budget!r}")  # NaN/inf/float defeat the cap
        if budget < 1:
            raise ValueError(f"budget must be >= 1, got {budget}")
        fdr_alpha = float(fdr_alpha)
        if not (0 < fdr_alpha < 1):
            raise ValueError(f"fdr_alpha must be in (0, 1), got {fdr_alpha}")
        self._budget = budget
        self._fdr_alpha = fdr_alpha
        self._tests = {}   # test_id -> {"feature", "slice_spec", "expected", "result": None | {"p", "effect"}}
        self._vault_open = False

    def register(self, test_id, feature, slice_spec, expected) -> None:
        for name, val in [("test_id", test_id), ("feature", feature), ("slice_spec", slice_spec), ("expected", expected)]:
            if not isinstance(val, str) or not val.strip():
                raise ValueError(f"{name} must be a non-empty, non-whitespace string")
        if test_id in self._tests:
            raise ValueError(f"test_id '{test_id}' is already registered")
        if len(self._tests) >= self._budget:
            raise ValueError(f"Registration budget of {self._budget} already exhausted")
        self._tests[test_id] = {"feature": feature, "slice_spec": slice_spec, "expected": expected, "result": None}

    def record(self, test_id, p_value, effect) -> None:
        if test_id not in self._tests:
            raise ValueError(f"test_id '{test_id}' is not registered")
        if self._tests[test_id]["result"] is not None:
            raise ValueError(f"test_id '{test_id}' already has a recorded result")
        p_value = float(p_value)
        if not (0.0 <= p_value <= 1.0):
            raise ValueError(f"p_value must be in [0, 1], got {p_value}")
        self._tests[test_id]["result"] = {"p": p_value, "effect": float(effect)}

    def remaining(self) -> int:
        return self._budget - len(self._tests)

    def assert_all_resolved(self) -> None:
        """Raise if any registered test is still PENDING. The orchestration calls this before
        reading survivors() so the BH family cannot be shrunk by selectively leaving slices
        unrecorded (the selective-recording p-hack). Additive guard; does not change
        survivors()/verdict() behavior."""
        pending = sorted(tid for tid, info in self._tests.items() if info["result"] is None)
        if pending:
            raise ValueError(f"{len(pending)} registered test(s) still PENDING "
                             f"({pending[:5]}{'...' if len(pending) > 5 else ''}); "
                             f"record all before reading survivors()")

    def survivors(self) -> list:
        recorded = [(tid, info["result"]["p"]) for tid, info in self._tests.items() if info["result"] is not None]
        if not recorded:
            return []
        m = len(recorded)
        sorted_recorded = sorted(recorded, key=lambda x: x[1])
        threshold_p = None
        for k, (_, p) in enumerate(sorted_recorded, start=1):
            if p <= (k / m) * self._fdr_alpha:
                threshold_p = p
        if threshold_p is None:
            return []
        return sorted(tid for tid, p in recorded if p <= threshold_p)

    def verdict(self, test_id) -> str:
        if test_id not in self._tests:
            return "UNREGISTERED"
        if self._tests[test_id]["result"] is None:
            return "PENDING"
        return "SURVIVED" if test_id in self.survivors() else "REJECTED"

    def open_vault(self) -> None:
        if self._vault_open:
            raise ValueError("Vault has already been opened")
        self._vault_open = True

    def vault_open(self) -> bool:
        return self._vault_open
