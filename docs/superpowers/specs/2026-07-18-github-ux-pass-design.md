# Design: GitHub UX pass for octagon

Date: 2026-07-18. Status: approved by Brett (this doc is the written record).

## Goal

Octagon is release-ready but optimized for readers, not first-time runners. This pass adds
the on-ramps an **AI-developer audience** expects, so the first five minutes with the repo
are effortless: zero-setup as an agent skill, one command as a CLI, one click in a
browser. Explicitly *not* in scope: installer-style packaging for non-technical end users
(octagon's users are developers).

## Scope (approved)

1. **Agent Skill** — headline zero-setup on-ramp for Claude Code / SKILL.md-compatible agents.
2. **Thin CLI** (`cli.py`) — unified `octagon` command; no package restructure (Approach A).
3. **Client additions** — generalized headless agent-CLI clients (claude/codex/gemini) +
   an OpenAI-compatible HTTP client. Stdlib only.
4. **Codespaces devcontainer** — click-a-button in-browser trial.
5. **README polish + offline hero GIF** — fix stale claims, add the new on-ramps, record
   the gate demo.
6. **Offline tests for all new surface** — the "entire suite runs offline" claim stays true.

Out of scope: PyPI publishing, Docker/Compose, web UI, package restructure, per-seat GUI,
and installer-style packaging (for a different project).

## 1. Agent Skill

Location: `.claude/skills/octagon/SKILL.md` (Agent Skills format: frontmatter
`name`/`description` + instructions). Cloning the repo and opening it in Claude Code makes
`/octagon` available immediately; README documents copying the folder to `~/.claude/skills/`
for global use and notes the format is portable (Codex CLI reads SKILL.md too).

Skill flow:

1. **Collect topic + domain** from the user (the two strings that aim the table).
2. **Detect backends**: run `octagon doctor --json`. If a different model family is
   available (codex, gemini, ollama), *offer* to dye one seat with it, citing the
   shared-basin rationale from the README. Detection only — the skill never asks users to
   paste API keys.
3. **Run rounds**: one subagent per seat per turn (context isolation between seats is the
   point). Each subagent gets the canonical persona prompt plus the running transcript.
   Prompts are fetched at runtime via `octagon prompt <persona>` — SKILL.md never
   duplicates prompt text; `personas/` stays the single source of truth.
4. **Transcript**: written in the same format `demo.py` uses (`last_run.md` layout).
5. **Harvest**: the host agent performs the harvest using the canonical harvest prompt
   (also exposed via the CLI).
6. **Hand off to the gate**: the skill closes by routing testable hypotheses toward
   `forge.py` / `alpha_ledger.py`, which stay deterministic Python the model cannot
   sweet-talk. For a no-data demo it points at `octagon gate --demo`.

## 2. Thin CLI

New file `cli.py`, stdlib argparse, wired as `[project.scripts] octagon = "cli:main"` in
`pyproject.toml`. Existing `python demo.py` / `python forge.py --demo` invocations keep
working untouched.

Subcommands:

- `octagon demo` — wraps `demo.py` (all modes/flags below).
- `octagon gate --demo` — wraps `forge.py --demo`.
- `octagon reslice` — wraps `python -m adapters.reslice`.
- `octagon doctor [--json]` — probes: `claude` on PATH, `codex` on PATH, `gemini` on PATH,
  Ollama reachable (`GET /api/tags`), `OCTAGON_BASE_URL` set. Never raises; prints a status
  table (or JSON for the skill).
- `octagon prompt <persona> | --list` — prints the canonical persona prompt text for the
  skill to consume; `octagon prompt harvest` prints the harvest prompt the same way.

No-install one-liner (documented in README):
`uvx --from git+https://github.com/kerokerodayo/octagon octagon demo` — works without PyPI.

## 3. Clients

### Generalized headless agent-CLI clients

All three vendor CLIs have headless modes running on the user's existing subscription login
(no API key): `claude -p`, `codex exec`, `gemini -p`. Design: one shared runner
`_run_agent_cli(...)` (PATH check via `shutil.which`, timeout, scoped env, clear
RuntimeErrors — the hardening already proven in `claude_cli_client`) plus a small per-CLI
adapter table: argv builder, output parser, allowed-secret prefixes.

- `claude_cli_client` — behavior unchanged (JSON envelope parse); refactored onto the
  shared runner. Allow prefixes: `ANTHROPIC`, `CLAUDE`.
- `codex_cli_client` — new, via `codex exec`. Allow prefixes: `OPENAI`, `CODEX`.
- `gemini_cli_client` — new, via `gemini -p`. Allow prefixes: `GOOGLE`, `GEMINI`.

Exact argv/output parsing for codex and gemini is **verified against the real installed
CLIs during implementation** (their JSON output flags differ by version; the adapter is the
isolation layer for that). Adding a fourth CLI is a documented ~10-line adapter — an
explicit extension point.

The scoped-env mechanism (`_scoped_env`) takes the allow-prefix tuple as a parameter so
each child keeps only its own vendor's credentials.

### OpenAI-compatible HTTP client

`openai_compat_client(model, base_url, ...)` — stdlib urllib POST to
`{base_url}/chat/completions`; key read from `OCTAGON_API_KEY` (never a function
argument); helpful error messages. Covers OpenRouter, LM Studio, vLLM, llama.cpp, etc.
`.env.example` documents `OCTAGON_BASE_URL`, `OCTAGON_API_KEY`, `OCTAGON_MODEL`.

### Demo wiring

`demo.py` `pick_clients` grows explicit seat wiring while keeping legacy flags:

- `--room=<backend>` / `--harvest=<backend>` where backend ∈
  `stub | ollama | claude | codex | gemini | openai`.
- `--dye <seat>=<backend>` — run one named seat on a different model family (the
  shared-basin antidote, demoable from the command line).
- Legacy `--local` / `--hybrid` / `--live` / `--model=` keep working as aliases.

## 4. Codespaces devcontainer

`.devcontainer/devcontainer.json`: a current Python image, post-create
`pip install -e .[dev]`, nothing else. README gets an "Open in GitHub Codespaces" badge.
The offline demo and gate demo run instantly in the browser.

## 5. README + hero visual

- Fix the stale test count ("44") — and since this pass adds tests, stop hardcoding a
  number at all: the README says "the full offline suite" and lets CI vouch for the count.
- Hero GIF: **offline recording** (approved: no live model spend). Subject:
  `octagon gate --demo` — the verdict table (REAL / DECAYED / MIRAGE, 20 nulls rejected)
  is real functionality and the strongest offline visual. Committed under `docs/assets/`.
- New content near the top: "Use it as a skill" quickstart, the uvx one-liner, Codespaces
  badge, and a provider matrix (host agent via skill / claude / codex / gemini / ollama /
  any OpenAI-compat endpoint).
- CI badge added only after the first green Actions run (existing decision, unchanged).

## 6. Testing & error handling

All new surface tested offline, in the existing suite's style:

- `doctor`: mocked `shutil.which` + mocked urllib; asserts it never raises and reports
  each backend's status; `--json` shape test (the skill depends on it).
- `prompt`: dump matches the canonical prompt from `personas/`.
- Agent-CLI clients: mocked `subprocess.run` — missing binary, non-zero exit, garbage
  output, scoped-env correctness per vendor (each child sees only its own creds).
- `openai_compat_client`: mocked `urlopen` — success parse, HTTP error, missing key.
- CLI dispatch: each subcommand smoke-tested via `main([...])` with stubs.

Error-handling posture unchanged from HARDENING.md: clients raise clear `RuntimeError`s
with actionable messages; `doctor` reports instead of raising; the octagon's per-seat fault
isolation already contains client failures during a run.

## Success criteria

1. Fresh clone, zero installs: `python demo.py`, `python forge.py --demo`, `pytest -q`
   all still pass offline.
2. `pip install -e .` then `octagon doctor` / `demo` / `gate --demo` / `reslice` /
   `prompt` all work; `uvx --from git+…` path works.
3. Opening the repo in Claude Code exposes `/octagon`, which runs a roundtable end-to-end
   with zero configuration on the host model, and offers seat-dyeing when another backend
   is detected.
4. README shows the gate-demo GIF, the skill quickstart, the uvx one-liner, and the
   Codespaces badge; no stale claims.
5. Full suite still runs offline and green; new code is stdlib-only.

## Risks / notes

- Codex/gemini CLI output formats drift between versions — contained in per-CLI adapters;
  verified against installed CLIs at implementation time.
- Skill quality depends on the host agent following instructions — mitigated by keeping
  every deterministic piece (prompts, doctor, transcript format, gate) in Python and
  making the skill fetch rather than improvise.
- GIF tooling on Windows is finicky — the artifact is a committed asset, so any one-time
  production path is acceptable; nothing at runtime depends on it.
