# Pre-ship hardening review

A pre-release adversarial pass over the codebase, run as separate read-only lenses, then the
real findings fixed with tests. This documents what was looked for, what was found, and what
was changed, so the "found and fixed before shipping" trail is visible.

## Lenses applied

1. Core logic and edge cases
2. Concurrency, races, and hangs
3. Error handling and graceful degradation (does it crash or hang on a dependency failure?)
4. Input validation, edge cases, and encoding
5. Security, cost/token honesty, and test coverage

## Findings and fixes

| # | Severity | Lens | Location | Trigger | Fix |
|---|----------|------|----------|---------|-----|
| 1 | **High** | Security | `client.py` `claude_cli_client` | `subprocess.run` inherited the full parent environment, so shelling out to the `claude` CLI handed the child every unrelated provider secret in the environment (`OPENAI_API_KEY`, `AWS_SECRET_ACCESS_KEY`, etc.). | Added `_scoped_env()`: the child receives a copy of the environment with secret-looking variables removed, except Anthropic/Claude's own. `env=` is now passed explicitly. |
| 2 | Low | Error handling | `client.py` `claude_cli_client` | If the CLI emitted non-JSON (a crash banner, an auth prompt), `json.loads` raised a raw `JSONDecodeError`. | Wrapped the parse in a clear `RuntimeError` that includes the offending output. |
| 3 | Low | Core logic | `forge.py` `gate_one` | A `recent_era` not present in the supplied `eras` dict raised an opaque `KeyError` deep in the function. | Validate up front and raise a clear `ValueError` naming the available eras. |

## Reviewed and confirmed OK (no change needed)

- **Hangs on a provider/dependency failure.** Both network-facing clients carry an explicit
  timeout (`claude_cli_client` via `subprocess.run(timeout=...)`, `ollama_client` via
  `urllib` `timeout=`). A persona that hangs and then times out is caught by the octagon's
  per-seat fault isolation and recorded as an error turn, so one bad seat cannot hang or abort
  a round. Robustness to errors and robustness to hangs are both covered.
- **Encoding (the Windows cp1252 trap).** Every entry point that prints model-generated text
  (`demo.py`, `forge.py`, `adapters/reslice.py`, `adapters/store.py`) reconfigures stdout to
  UTF-8 with `errors="replace"`, and run artifacts are written with `encoding="utf-8"`. The
  demo writes its transcript to disk *before* printing, so a console-encoding hiccup can never
  lose a completed run. The live clients decode subprocess output as UTF-8 with replacement.
- **Concurrency / races.** The harness is sequential by design; there is no shared mutable
  state across threads and no concurrency primitive to race.
- **Cost / token honesty.** No cost or token comparison is asserted anywhere. Earlier internal
  framing that implied "free" runs was removed; the clients are described by what they do, not
  by a price.
- **SQL safety** (`adapters/store.py`). All values are bound parameters; the only string-built
  SQL is a static `WHERE` clause with no interpolated user data.
- **Multiple-testing math** (`alpha_ledger.py`, `forge.py`). Empty families return no
  survivors rather than dividing by zero; the budget int-guard (a NaN/inf/float defeating a
  hard cap) is covered by tests.

## Test coverage of the IO/model layer

Pure logic was already tested. This pass added tests that exercise the client/IO layer itself
without any network call: a missing CLI raises clearly, the child env is scrubbed of unrelated
secrets, non-JSON output and error envelopes raise clear errors, and the persona layer coerces
non-string model output to `str`. Suite: **49 tests, all offline.**
