"""The scout: data-feasibility triage between HARVEST and GATE.

A challenge is worthless if you cannot get the data to test it. Given a harvest of
challenges and a map of the domain's known data sources, the scout sorts each challenge by
data-feasibility and points at where the data lives, WITHOUT killing any idea (no idea is
disqualified; un-gettable ones are parked, not deleted).

It is a feasibility ROUTER, not a filter:
  HAVE IT        already in your data; go straight to the gate.
  SCRAPEABLE     a public source exists; it needs a fetcher built.
  NEEDS-PROXY    not directly observable; what measurable stands in for it?
  NOT-OBTAINABLE parked (e.g. needs an experiment you cannot run on historical data).

The hard constraints below are the load-bearing part. An early version of this routed an
idea as HAVE IT against data that did not exist, and another as obtainable when it actually
required a prospective experiment. The fix: route ONLY against a real, supplied source map,
forbid asserting access you cannot prove, and forbid interventions on observational data.
Hand this a strong model; it is a synthesis job.
"""

from __future__ import annotations

SCOUT_PROMPT = """\
You are THE SCOUT. Below is a list of CHALLENGES (hypotheses to test) and the REAL data
situation for this domain. For EACH challenge, decide how you would actually get the data to
test it. You do NOT judge whether the idea is good and you do NOT discard any; even absurd
ones get routed.

HARD CONSTRAINTS, apply these BEFORE bucketing:
- Assume OBSERVATIONAL HISTORICAL data ONLY unless the source map says otherwise. If a
  challenge requires manipulating, varying, or controlling conditions, or any
  prospective/lab procedure, it is NOT-OBTAINABLE no matter how cheap the data sounds.
- Bucket HAVE IT *only* if the data is backed by a real source in the DATA SITUATION below.
  If testing it would need a source you do NOT have (a paid subscription, an un-built
  fetcher, an external API), it is NOT "HAVE IT". When unsure, never claim it.

For each challenge output exactly:

N. <title>
   bucket: HAVE IT | SCRAPEABLE | NEEDS-PROXY | NOT-OBTAINABLE
   source: <which known source, or "none, explain">
   next: <if SCRAPEABLE, a one-line seed for a fetcher brief (which page, which fields);
          if NEEDS-PROXY, the observable that could stand in; if HAVE IT, the table/field;
          if NOT-OBTAINABLE, why>

Rules: route every challenge; never delete one. Prefer data you already have, but only if a
real source backs it. Be concrete. NEVER invent a source or assert access you do not have.

DATA SITUATION:
---
{sources}
---

CHALLENGES:
---
{challenges}
---
Now output ONLY the routed list."""


def scout(challenges, client, sources):
    """Route a harvest of challenges by data-feasibility.

    challenges: the harvest text (or a list of challenge lines).
    client: a callable client(prompt) -> str (give it a STRONG model; this is synthesis).
    sources: a string describing the domain's known data sources and access reality.
    """
    if isinstance(challenges, (list, tuple)):
        challenges = "\n".join(str(c) for c in challenges)
    if not challenges.strip():
        return "(no challenges to scout)"
    return client(SCOUT_PROMPT.format(sources=sources, challenges=challenges))
