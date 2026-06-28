"""Adapters: optional, swappable pieces that wire the engine to a concrete world.

The engine (octagon, personas, harvest, scout, forge, alpha_ledger) is domain-neutral.
These adapters show how to plug it into something real without the engine depending on any
of them:

  - example_gate : a synthetic reality gate so a re-slice campaign runs with no database.
  - reslice      : the pre-registered re-slice campaign orchestration (gate is injected).
  - store        : a stdlib SQLite idea registry (dedup + count + provenance).
"""
