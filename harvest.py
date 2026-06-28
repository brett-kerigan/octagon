"""The harvester: a DOWNSTREAM step that turns a divergent transcript into the HARVEST,
a clean, deduplicated list of every distinct challenge the table raised.

It is NOT a seat. The table's job is to spawn challenges with zero filtering; the
harvester's job is to catch them all, even the absurd ones, so each can be taken to the
gate (reality) on its own. It does not judge, rank, or discard; that is downstream of
here. It uses the injectable client, so it runs free on a local model too.
"""

from __future__ import annotations


def _render_transcript(transcript):
    lines = []
    for t in transcript:
        tag = t["name"] + (" [error]" if t.get("error") else "")
        lines.append(f"{tag}: {t['text']}")
    return "\n\n".join(lines)


HARVEST_PROMPT = """\
You are THE HARVESTER. Below is a transcript from a deliberately adversarial, divergent
roundtable. Its whole job was to throw out as many distinct CHALLENGES as possible
("I challenge us to test X") by bouncing ideas off each other, with NO filtering.

Your job is to catch every challenge, not to judge them. Specifically:
- Extract EVERY distinct challenge or hypothesis raised, INCLUDING the absurd, naive, or
  "stupid" ones. If the fool said it, it goes in. No idea is too dumb to harvest.
- Deduplicate only TRUE near-identical repeats; keep genuinely different angles apart.
- Do NOT rank, agree, dismiss, or pick favorites. Do NOT invent challenges that were not
  raised.
- ATTRIBUTE each challenge to the seat(s) that raised it, using the speaker names from the
  transcript (e.g. dreamer, fool, scientist, insider). If it was merged from several
  seats, list them comma-separated.

Output a numbered list. For each challenge, one line in this exact shape:

N. <short title> - <one-sentence testable statement> | from: <seat name(s)> | first test: <smallest concrete first step>

Transcript:
---
{transcript}
---
Now output ONLY the numbered harvest."""


def harvest(transcript, client):
    """Turn an octagon transcript into a deduped list of distinct challenges.

    transcript: the list[dict] returned in run_octagon(...)["transcript"].
    client: a callable client(prompt: str) -> str (local or live, your choice).
    """
    if not transcript:
        return "(empty transcript; nothing to harvest)"
    return client(HARVEST_PROMPT.format(transcript=_render_transcript(transcript)))
