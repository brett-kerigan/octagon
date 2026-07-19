---
name: octagon
description: Run an adversarial persona roundtable on a hard "is there an overlooked edge?" question, using the model you are already running as the seats, then harvest every provocation for testing. Use when the user wants divergent hypothesis generation on an open-ended search problem, or asks for "the roundtable" / "the octagon".
---

# The octagon, driven by the host agent

You (the host agent) become the table: each seat is played by a fresh subagent so the
seats do not share working memory. The deterministic parts — prompts, backend
detection, the statistical gate — stay in this repo's Python and are FETCHED, never
improvised. Run every command below from the repo root.

## 0. Ground rules

- NEVER invent or paraphrase a persona prompt. Always fetch the canonical text with
  `python cli.py prompt <name>`.
- The gate is not you. You may generate and harvest; only `forge.py` /
  `alpha_ledger.py` may judge a hypothesis against data.
- Keep each seat's turn to 2-5 sentences (the prompts enforce this; do not "improve"
  on it).

## 1. Aim the table

Ask the user for two things (offer to draft them if the user prefers):
- **domain** — the world being hunted in: what the "crowd" is, what an "edge" means
  there, why the easy answers are gone.
- **topic** — the specific question on the table.

Also ask how many rounds (default 2).

## 2. Detect backends, offer to dye one seat

Run: `python cli.py doctor --json`

If a backend from a DIFFERENT model family than yours is available (codex, gemini, or
ollama), tell the user and offer to run ONE seat on it — the fool is the best choice
(orthogonality matters more than rigor there). Rationale, briefly: when all seats run
on one model family they tend to explore the same idea-space (shared-basin collapse);
one differently-cloned seat is the cheap antidote. If the user accepts, that seat's
turns are produced by shelling out, e.g.:

    python -c "import client,sys; print(client.codex_cli_client(sys.stdin.read()))" < turn_prompt.txt

(or `gemini_cli_client` / `ollama_client(...)` accordingly). If nothing else is
available, run all seats yourself — that is fine; just note it in the final summary.

## 3. Seat the table

Default lineup (matches the repo demo): dreamer, fool, scientist, insider.
Fetch each seat's system prompt:

    python cli.py prompt dreamer
    python cli.py prompt fool
    python cli.py prompt scientist
    python cli.py prompt insider

`insider` and `practitioner` contain a literal `{who}` slot — fill it with a concrete
identity fitted to the domain (one sentence, specific, lived-in).

## 4. Run the rounds

For each round (1..N), for each seat in order: spawn a FRESH subagent whose entire
prompt is, in this order (this mirrors `personas/base.py::LLMPersona._render`):

1. the seat's fetched system prompt (with `{who}` filled if applicable)
2. a blank line, then `--- The world you are hunting in ---` and the domain
3. a blank line, then `--- On the table ---` and the topic
4. a blank line, then `--- Discussion so far ---` and every prior turn as
   `name: text` lines (or `(nothing yet; you are opening the discussion.)`)
5. a blank line, then `--- Your turn, <name> ---` and
   `Give your next contribution, fully in character.`

The subagent's reply is that seat's turn, verbatim. If a seat errors or times out,
record the error text as its turn and continue — one bad seat never aborts a round
(same fault isolation the scheduler guarantees).

Append every turn to `last_run.md` as it happens, in the repo's transcript format:

    ### [r{round} s{seat}] {name}

    {text}

## 5. Harvest

Fetch the harvest prompt: `python cli.py prompt harvest`
Fill its `{transcript}` slot with the full transcript rendered as `name: text` blocks.
Run it in ONE fresh subagent (the harvester must not be a seat). Save the output to
`last_harvest.md` and show it to the user.

## 6. Hand off to reality

Close with this, honestly: every harvested challenge is an UNTESTED provocation. The
repo's gate machinery is how one earns belief — `python forge.py --demo` shows the
protocol; wiring a real `gate_fn` and pre-registering via `alpha_ledger.py` is how a
real campaign runs. Do not present any harvested idea as a finding.
