# agent-roundtable

> Draft placeholder. The final README (problem → approach → example → how to run →
> limitations) is pending review and will replace this file in the framing pass.

A persona-agnostic multi-agent deliberation harness: a pure turn-scheduler (the **octagon**)
seats 1 to 4 **personas** that generate divergent, testable hypotheses, which are then put
through an incorruptible reality gate (per-era replication, Benjamini-Hochberg FDR, and a
one-shot holdout vault).

```bash
python demo.py            # offline, deterministic stub personas
python forge.py --demo    # prove the gate on synthetic planted signals
python -m pytest -q       # run the offline test suite
```
