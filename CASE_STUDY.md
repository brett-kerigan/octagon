# Case study: a real edge-research campaign

This is a **case study, not a proof.** It describes one real application that exercised the
harness end to end, what it produced, and the unflattering parts. It deliberately withholds
the specific signals, math, data, and modeling details of a private research project; what is
shareable is *how the system behaved*, not the recipe it was pointed at.

## The setting

The harness was run against a real, hard, efficient-market problem: handicapping research in
a parimutuel betting market (horse racing), where the "crowd" sets prices and an "edge" is an
outcome whose true probability differs from its market price by more than the cost of
trading. This is a good stress test precisely because the easy edges are already gone and the
honest default answer is "there is nothing left here."

Two cooperating agents ran the loop: one generated divergent hypotheses through the
roundtable; a separate one owned the reality gate and tested each hypothesis against a large
historical dataset (millions of past results). The separation matters. The generator was
never allowed to grade its own work.

## What it produced

**1. A provocation became a method upgrade, not just a hypothesis.** One idea out of the
roundtable was not a bet at all; it was a critique of the *gate itself*: the suggestion that
a real effect might be concentrated in the extremes rather than spread evenly, so a test that
only looks for an even effect would undersell it. Taken to reality, that critique held, and
it changed how the downstream model valued signals it already had. The idea-room improved the
instrument that judges the idea-room. (Functionality observed; the magnitude is private.)

**2. The discipline layer caught three real failure modes, not hypothetical ones.**
   - *A data-access hallucination.* An early triage step confidently routed a hypothesis as
     "we already have this data" when the data did not exist. The fix now lives in this repo's
     scout: route only against a real, supplied source map, and never assert access you cannot
     prove.
   - *A HARK (hypothesizing after results are known).* Pre-registration forced the hypothesis
     and its expected direction to be declared before the result was seen. A family that would
     have made a tidy story after the fact instead closed honestly with nothing.
   - *A p-hacking vector.* An adversarial review of the pre-registration ledger found a real
     bug (a non-integer budget could silently defeat the hard cap) and a real hole (selectively
     leaving tests unrecorded could shrink the multiple-testing family). Both were fixed
     *before* the ledger gated anything real. Both guards are in `alpha_ledger.py` today.

**3. The gate rejected its own statistically significant finding.** A re-slice campaign
produced a result that cleared the significance bar and replicated across eras. It was still
rejected, because the effect was too small to clear the economic floor. A system that will
throw away its own significant results on cost-benefit grounds is the opposite of a system
that p-hacks toward a win.

**4. A transferable structural lesson.** Across many hypotheses, a pattern held that
generalizes well beyond this one domain: **markets price out over-reactions to discrete events
quickly, while the durable residual edge tends to sit in stable structural and identity
factors rather than in reactions to recent events.** Most "the crowd over-reacted to event X"
hypotheses died at the gate; the survivors were structural. That is a reusable prior for where
to look first in any adversarial market, and the roundtable surfaced it.

## The honest scoreboard

- Roughly twenty hypotheses across several families were generated and taken to the gate.
- **New, deployable edges found in this window: about zero.** For an efficient market, that is
  the expected and healthy outcome, not a failure. An honest null is the credibility asset
  here.
- Model-improving method upgrades: one, with a real (private) effect on how the downstream
  model scored existing signals.
- Real defects and methodological holes caught by the discipline layer: three.

## What this does and does not show

It **shows** that the harness runs a real campaign end to end, that its discipline layer
catches concrete failure modes, and that its gate is willing to reject attractive but weak
findings. That is functionality, and the offline tests in this repo demonstrate the same
machinery on synthetic data anyone can run.

It does **not** show that the roundtable will find an edge in your domain, or that
multi-persona generation beats a single strong model at this. Those are efficacy claims, and
proving them would need a controlled evaluation this case study does not attempt. See the
"Help wanted" section of the [README](README.md) for the open question.
