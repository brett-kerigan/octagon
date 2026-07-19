# GitHub UX Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the on-ramps an AI-developer audience expects — agent skill, unified `octagon` CLI, headless agent-CLI clients (claude/codex/gemini) + OpenAI-compatible client, Codespaces devcontainer, README polish + offline hero GIF — per `docs/superpowers/specs/2026-07-18-github-ux-pass-design.md`.

**Architecture:** All runtime code stays pure stdlib. New clients share one hardened subprocess runner with per-vendor secret scoping. A thin `cli.py` argparse dispatcher wraps existing entry points and exposes `doctor` (backend detection) and `prompt` (canonical prompt dump) for the agent skill, which lives at `.claude/skills/octagon/SKILL.md` and drives the harness through the CLI rather than duplicating any prompt text.

**Tech Stack:** Python ≥3.9 stdlib only (argparse, urllib, subprocess, json). pytest (dev-only). Pillow used once, outside the repo, to render the GIF asset.

## Global Constraints

- **Stdlib only** in all shipped `.py` files: `dependencies = []` in pyproject stays empty.
- **Python ≥ 3.9 compatibility**: no `match`, no `X | Y` type unions, no 3.10+ syntax (CI runs 3.9).
- **Every test runs offline**: mock `subprocess.run` / `urllib.request.urlopen`; never hit a network or a real CLI in tests.
- **Windows-safe output**: any new entry point that prints model text reconfigures stdout to UTF-8 with `errors="replace"` (existing pattern in `demo.py:89-92`).
- **Error style**: clients raise `RuntimeError` with actionable messages (existing pattern in `client.py`); `doctor` never raises.
- **Commits**: conventional-commit style messages ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`. Commit locally; NEVER push (no remote exists; pushing is Brett's call).
- Existing invocations must keep working: `python demo.py [--local|--hybrid|--live]`, `python forge.py --demo`, `python -m adapters.reslice`, `python -m pytest -q`.
- Run the full suite (`python -m pytest -q`) before every commit; it must be green.

---

### Task 1: Parameterized secret scoping + shared agent-CLI runner

Refactor `claude_cli_client` onto a shared runner so codex/gemini clients (Task 2) reuse the same hardening. Behavior of `claude_cli_client` must not change — the four existing tests in `tests/test_client_hardening.py` are the regression harness.

**Files:**
- Modify: `client.py`
- Test: `tests/test_client_hardening.py`

**Interfaces:**
- Consumes: existing `_scoped_env()`, `_SECRETISH`, `_ALLOW_PREFIXES` in `client.py`.
- Produces (Task 2 depends on these exact signatures):
  - `_scoped_env(allow_prefixes=_ALLOW_PREFIXES) -> dict`
  - `_run_agent_cli(binary_name: str, argv_rest: list, prompt: str, *, timeout_s: int, allow_prefixes: tuple, parse) -> str` where `parse(stdout: str) -> str`
  - `_parse_claude_envelope(stdout: str) -> str`
  - `claude_cli_client(prompt, *, model="opus", timeout_s=600) -> str` (signature unchanged)

- [ ] **Step 1: Write the failing test** — append to `tests/test_client_hardening.py`:

```python
def test_scoped_env_allow_prefixes_parameter(monkeypatch):
    """Each vendor's child keeps only its own credentials."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-cred")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-cred")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-cred")
    env = client_mod._scoped_env(allow_prefixes=("OPENAI", "CODEX"))
    assert env.get("OPENAI_API_KEY") == "openai-cred"
    assert "ANTHROPIC_API_KEY" not in env
    assert "GOOGLE_API_KEY" not in env
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_client_hardening.py::test_scoped_env_allow_prefixes_parameter -v`
Expected: FAIL with `TypeError: _scoped_env() got an unexpected keyword argument`

- [ ] **Step 3: Implement** — in `client.py`, replace `_scoped_env` and `claude_cli_client` with:

```python
def _scoped_env(allow_prefixes=_ALLOW_PREFIXES):
    """A copy of the environment with unrelated-provider secrets removed.

    PATH, HOME, SystemRoot and everything non-secret pass through unchanged, so the child
    still runs normally; only vars that look like another service's credential (and do not
    start with one of `allow_prefixes`, the vendor's own) are dropped.
    """
    env = {}
    for k, v in os.environ.items():
        if _SECRETISH.search(k) and not k.upper().startswith(allow_prefixes):
            continue
        env[k] = v
    return env


def _run_agent_cli(binary_name, argv_rest, prompt, *, timeout_s, allow_prefixes, parse):
    """Shared runner for headless agent CLIs (claude/codex/gemini).

    One place owns the hardening: PATH check, prompt over stdin (Windows CLI shims
    truncate multi-line argv), explicit timeout, per-vendor secret scoping, UTF-8
    decode with replacement, and clear errors. `parse(stdout) -> str` is the only
    per-CLI part.
    """
    binary = shutil.which(binary_name)
    if not binary:
        raise RuntimeError(
            f"`{binary_name}` CLI not on PATH; install it and authenticate, "
            f"or inject a different client."
        )
    proc = subprocess.run(
        [binary] + argv_rest,
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=_scoped_env(allow_prefixes),   # the child sees only its own vendor's secrets
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{binary_name} CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}"
        )
    return parse(proc.stdout)


def _parse_claude_envelope(stdout):
    try:
        envelope = json.loads(stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"claude CLI returned non-JSON output: {stdout.strip()[:200]!r}"
        ) from exc
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI error: {envelope.get('subtype')}")
    return envelope.get("result", "")


def claude_cli_client(prompt, *, model: str = "opus", timeout_s: int = 600) -> str:
    """A live client that shells out to the local `claude` CLI in print mode (`claude -p`).

    The prompt is fed via stdin (on Windows `claude` is a .cmd shim that truncates a
    multi-line argv). Output is parsed from the CLI's JSON envelope. A four-seat round is
    four of these calls. Not invoked until you choose to run the table live.
    """
    return _run_agent_cli(
        "claude",
        ["-p", "--output-format", "json", "--model", model],
        prompt,
        timeout_s=timeout_s,
        allow_prefixes=("ANTHROPIC", "CLAUDE"),
        parse=_parse_claude_envelope,
    )
```

Keep `_SECRETISH` and `_ALLOW_PREFIXES` module constants exactly as they are.

- [ ] **Step 4: Run the whole client test file** (regression: the 4 existing tests must still pass)

Run: `python -m pytest tests/test_client_hardening.py -v`
Expected: 5 passed

- [ ] **Step 5: Full suite green, then commit**

Run: `python -m pytest -q` — expected: 50 passed
```bash
git add client.py tests/test_client_hardening.py
git commit -m "refactor: shared hardened runner for agent CLIs; per-vendor secret scoping

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `codex_cli_client` and `gemini_cli_client`

Both vendors' headless modes run on subscription login (no API key): `codex exec`, `gemini` reading stdin. The codex CLI **is installed on this machine** — verify the real output shape before finalizing the parser. Gemini is not installed; its adapter is written version-tolerantly (plain-text stdout) and mock-tested.

**Files:**
- Modify: `client.py`
- Test: `tests/test_client_hardening.py`

**Interfaces:**
- Consumes: `_run_agent_cli`, from Task 1.
- Produces (Tasks 4–5 depend on these):
  - `codex_cli_client(prompt, *, model=None, timeout_s=600) -> str`
  - `gemini_cli_client(prompt, *, model=None, timeout_s=600) -> str`
  - `_parse_codex_jsonl(stdout: str) -> str`

- [ ] **Step 1: Verify the real codex output shape** (one live smoke call, NOT a test):

Run: `codex exec --json "Reply with exactly the word: pong" 2>&1 | head -40`

Inspect the JSONL: find which event carries the final agent text (expected: an event whose `item.type` or `type` is `agent_message` with a `text` field). If the real shape differs from the parser below, adapt `_parse_codex_jsonl` AND the mocked test payloads to the real shape — the parser below already tolerates both known variants. Also confirm whether `codex exec - --json` reads the prompt from stdin (`echo hi | codex exec --json -`); if `-` is unsupported in the installed version, pass the prompt as the final argv element instead and note it in the docstring.

- [ ] **Step 2: Write the failing tests** — append to `tests/test_client_hardening.py`:

```python
def _codex_jsonl(text):
    return "\n".join([
        json.dumps({"type": "session.created", "session_id": "s1"}),
        json.dumps({"type": "item.completed",
                    "item": {"type": "agent_message", "text": text}}),
    ])


def test_codex_cli_parses_agent_message(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/codex")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc(_codex_jsonl("pong")))
    assert client_mod.codex_cli_client("ping") == "pong"


def test_codex_cli_env_keeps_only_openai_creds(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/codex")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "leak-me")
    monkeypatch.setenv("OPENAI_API_KEY", "keep-me")
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return _fake_proc(_codex_jsonl("ok"))

    monkeypatch.setattr(client_mod.subprocess, "run", fake_run)
    client_mod.codex_cli_client("prompt")
    assert captured["env"].get("OPENAI_API_KEY") == "keep-me"
    assert "ANTHROPIC_API_KEY" not in captured["env"]


def test_codex_cli_no_agent_message_raises(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/codex")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("garbage\nnot json"))
    with pytest.raises(RuntimeError) as exc:
        client_mod.codex_cli_client("prompt")
    assert "agent_message" in str(exc.value)


def test_gemini_cli_returns_stdout(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/gemini")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("a reply\n"))
    assert client_mod.gemini_cli_client("ping") == "a reply"


def test_gemini_cli_empty_output_raises(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: "/fake/gemini")
    monkeypatch.setattr(client_mod.subprocess, "run",
                        lambda cmd, **kw: _fake_proc("   \n"))
    with pytest.raises(RuntimeError) as exc:
        client_mod.gemini_cli_client("prompt")
    assert "empty" in str(exc.value)


def test_missing_binary_raises_for_each_vendor(monkeypatch):
    monkeypatch.setattr(client_mod.shutil, "which", lambda name: None)
    for fn in (client_mod.codex_cli_client, client_mod.gemini_cli_client):
        with pytest.raises(RuntimeError) as exc:
            fn("prompt")
        assert "not on PATH" in str(exc.value)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_client_hardening.py -v`
Expected: the 6 new tests FAIL with `AttributeError: ... has no attribute 'codex_cli_client'`

- [ ] **Step 4: Implement** — append to `client.py` (after `claude_cli_client`):

```python
def _parse_codex_jsonl(stdout):
    """Pull the final agent message out of `codex exec --json` JSONL events.

    Tolerates the two shapes seen across codex versions: a wrapped
    {"type": "item.completed", "item": {"type": "agent_message", "text": ...}}
    and a flat {"type": "agent_message", "text": ...}. Last one wins.
    """
    text = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        item = evt.get("item") or {}
        if item.get("type") == "agent_message" and item.get("text"):
            text = item["text"]
        elif evt.get("type") == "agent_message" and evt.get("text"):
            text = evt["text"]
    if text is None:
        raise RuntimeError(
            f"codex CLI output contained no agent_message: {stdout.strip()[:200]!r}"
        )
    return text


def codex_cli_client(prompt, *, model=None, timeout_s: int = 600) -> str:
    """A live client for OpenAI's `codex` CLI in headless mode (`codex exec`).

    Runs on the user's Codex subscription login; no API key handled here. The prompt
    is fed via stdin (`-`) for the same Windows argv-truncation reason as claude's.
    """
    argv = ["exec", "--json"]
    if model:
        argv += ["-m", model]
    argv.append("-")
    return _run_agent_cli(
        "codex", argv, prompt,
        timeout_s=timeout_s,
        allow_prefixes=("OPENAI", "CODEX"),
        parse=_parse_codex_jsonl,
    )


def _parse_gemini_text(stdout):
    out = stdout.strip()
    if not out:
        raise RuntimeError("gemini CLI returned empty output")
    return out


def gemini_cli_client(prompt, *, model=None, timeout_s: int = 600) -> str:
    """A live client for Google's `gemini` CLI in non-interactive mode.

    Runs on the user's Google account login; no API key handled here. The prompt is
    piped via stdin (the CLI treats piped stdin as the prompt and prints the reply as
    plain text). Adapter note: gemini's flags drift between versions; this function is
    the isolation layer — adjust argv here if your installed version differs.
    """
    argv = []
    if model:
        argv += ["-m", model]
    return _run_agent_cli(
        "gemini", argv, prompt,
        timeout_s=timeout_s,
        allow_prefixes=("GOOGLE", "GEMINI"),
        parse=_parse_gemini_text,
    )
```

Adjust the codex argv/parser here if Step 1's live check showed a different shape (and keep the tests' fake payloads matching reality).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_client_hardening.py -v`
Expected: 11 passed

- [ ] **Step 6: Full suite green, then commit**

Run: `python -m pytest -q` — expected: 56 passed
```bash
git add client.py tests/test_client_hardening.py
git commit -m "feat: codex and gemini headless CLI clients on the shared hardened runner

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: `openai_compat_client` + `.env.example`

A stdlib factory client for any OpenAI-compatible endpoint (OpenRouter, LM Studio, vLLM, llama.cpp). Key comes from env only, never a function argument.

**Files:**
- Modify: `client.py`, `.env.example`
- Test: `tests/test_client_hardening.py`

**Interfaces:**
- Produces (Task 4 depends on this): `openai_compat_client(model=None, *, base_url=None, timeout_s=300) -> callable`, returning `_c(prompt: str) -> str`. Raises `RuntimeError` **at construction** if no base URL (arg or `OCTAGON_BASE_URL`) or no model (arg or `OCTAGON_MODEL`). `OCTAGON_API_KEY` optional (local servers need none); sent as `Authorization: Bearer` only when set.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_client_hardening.py`:

```python
import contextlib
import io
import urllib.request


def _fake_urlopen_returning(payload_dict):
    def fake_urlopen(req, timeout=None):
        body = json.dumps(payload_dict).encode("utf-8")
        fake = io.BytesIO(body)
        return contextlib.closing(fake)
    return fake_urlopen


def test_openai_compat_needs_base_url(monkeypatch):
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        client_mod.openai_compat_client("some-model")
    assert "OCTAGON_BASE_URL" in str(exc.value)


def test_openai_compat_needs_model(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.delenv("OCTAGON_MODEL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        client_mod.openai_compat_client()
    assert "OCTAGON_MODEL" in str(exc.value)


def test_openai_compat_parses_choices(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_returning(
        {"choices": [{"message": {"content": "a reply"}}]}))
    c = client_mod.openai_compat_client("local-model")
    assert c("ping") == "a reply"


def test_openai_compat_bad_shape_raises(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen_returning({"nope": 1}))
    c = client_mod.openai_compat_client("local-model")
    with pytest.raises(RuntimeError) as exc:
        c("ping")
    assert "unexpected shape" in str(exc.value)


def test_openai_compat_auth_header_only_when_key_set(monkeypatch):
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization")
        body = json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")
        return contextlib.closing(io.BytesIO(body))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.delenv("OCTAGON_API_KEY", raising=False)
    client_mod.openai_compat_client("m")("ping")
    assert captured["auth"] is None
    monkeypatch.setenv("OCTAGON_API_KEY", "sk-test")
    client_mod.openai_compat_client("m")("ping")
    assert captured["auth"] == "Bearer sk-test"
```

(Note: `urllib.request.Request` normalizes header keys — if `req.headers.get("Authorization")` returns None despite the header being set, use `req.get_header("Authorization")` in the fake.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_client_hardening.py -k openai_compat -v`
Expected: 5 FAIL with `AttributeError: ... 'openai_compat_client'`

- [ ] **Step 3: Implement** — append to `client.py`:

```python
def openai_compat_client(model=None, *, base_url=None, timeout_s=300):
    """Client factory for ANY OpenAI-compatible endpoint (OpenRouter, LM Studio, vLLM,
    llama.cpp server, ...). Returns a `client(prompt) -> str` callable.

    Configuration comes from arguments or environment:
      base URL : `base_url=` or OCTAGON_BASE_URL   (e.g. http://localhost:1234/v1)
      model    : `model=`    or OCTAGON_MODEL
      key      : OCTAGON_API_KEY, optional — omitted entirely for keyless local servers,
                 and never accepted as a function argument.
    Talks to {base}/chat/completions over stdlib urllib (no extra deps).
    """
    import urllib.request

    base = (base_url or os.environ.get("OCTAGON_BASE_URL", "")).rstrip("/")
    if not base:
        raise RuntimeError(
            "openai_compat_client needs a base URL: pass base_url= or set OCTAGON_BASE_URL "
            "(e.g. https://openrouter.ai/api/v1 or http://localhost:1234/v1)."
        )
    mdl = model or os.environ.get("OCTAGON_MODEL", "")
    if not mdl:
        raise RuntimeError(
            "openai_compat_client needs a model: pass model= or set OCTAGON_MODEL."
        )

    def _c(prompt: str) -> str:
        payload = json.dumps(
            {"model": mdl, "messages": [{"role": "user", "content": prompt}]}
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        key = os.environ.get("OCTAGON_API_KEY", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(f"{base}/chat/completions", data=payload, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"openai-compatible call failed (base_url={base}, model={mdl}): {exc}"
            ) from exc
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"openai-compatible endpoint returned unexpected shape: {str(data)[:200]}"
            ) from exc

    return _c
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_client_hardening.py -v`
Expected: 16 passed

- [ ] **Step 5: Update `.env.example`** — append:

```
# Optional: any OpenAI-compatible endpoint (OpenRouter, LM Studio, vLLM, llama.cpp).
# Used by client.openai_compat_client and `python demo.py --room=openai`.
# OCTAGON_BASE_URL=http://localhost:1234/v1
# OCTAGON_MODEL=your-model-name
# OCTAGON_API_KEY=            # optional; leave unset for keyless local servers

# The codex / gemini CLI clients shell out to those CLIs on your PATH and need no key
# here; authenticate each CLI separately (subscription login).
```

- [ ] **Step 6: Full suite green, then commit**

Run: `python -m pytest -q` — expected: 61 passed
```bash
git add client.py tests/test_client_hardening.py .env.example
git commit -m "feat: stdlib OpenAI-compatible client (base-URL + env config)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: demo seat wiring — `--room` / `--harvest` / `--dye` / `--rounds`

Rework `demo.py` argument handling into `parse_args` + `cli_main` so the CLI (Task 5) can forward to it. Legacy flags stay as aliases. `--dye seat=backend` runs one seat on a different model family.

**Files:**
- Modify: `demo.py`
- Test: `tests/test_demo_wiring.py` (create)

**Interfaces:**
- Consumes: `stub_client`, `ollama_client`, `claude_cli_client`, `codex_cli_client`, `gemini_cli_client`, `openai_compat_client` from `client.py`.
- Produces (Task 5 and the skill depend on these):
  - `parse_args(argv: list) -> (room_client, harvest_client, dye: dict, rounds: int)`
  - `cli_main(argv=None) -> dict` (runs the demo; returns `run_octagon`'s result dict)
  - `example_room(client, dye=None)` — `dye` maps seat name (`dreamer|fool|scientist|insider`) to a client callable.
  - `main(room_client, harvest_client, rounds=2, out_path="last_run.md", dye=None)`
  - Backend names: `stub | ollama | claude | codex | gemini | openai`.

- [ ] **Step 1: Check nothing else imports the old `pick_clients`**

Run: `grep -rn "pick_clients" --include="*.py" .`
Expected: only `demo.py`. (If a test references it, update that test to `parse_args` in Step 4.)

- [ ] **Step 2: Write the failing tests** — create `tests/test_demo_wiring.py`:

```python
"""Offline tests for demo.py seat wiring. Constructing clients never touches a network;
only *calling* them would, and these tests never call the live ones."""

import pytest

import client as client_mod
import demo


def test_default_is_stub_stub():
    room, harv, dye, rounds = demo.parse_args([])
    assert room("x") == harv("x")            # both stubs return the same canned line
    assert dye == {} and rounds == 2


def test_legacy_live_flag_maps_to_claude():
    room, harv, dye, _ = demo.parse_args(["--live"])
    assert room is client_mod.claude_cli_client
    assert harv is client_mod.claude_cli_client


def test_room_and_harvest_flags():
    room, harv, _, _ = demo.parse_args(["--room=codex", "--harvest=claude"])
    assert room is client_mod.codex_cli_client
    assert harv is client_mod.claude_cli_client


def test_harvest_defaults_to_room():
    room, harv, _, _ = demo.parse_args(["--room=gemini"])
    assert room is client_mod.gemini_cli_client
    assert harv is client_mod.gemini_cli_client


def test_dye_flag_builds_seat_override():
    _, _, dye, _ = demo.parse_args(["--dye=fool=claude"])
    assert dye == {"fool": client_mod.claude_cli_client}


def test_rounds_flag():
    _, _, _, rounds = demo.parse_args(["--rounds=3"])
    assert rounds == 3


def test_openai_backend_without_env_raises_clearly(monkeypatch):
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    with pytest.raises(RuntimeError) as exc:
        demo.parse_args(["--room=openai"])
    assert "OCTAGON_BASE_URL" in str(exc.value)


def test_unknown_backend_exits_with_message():
    with pytest.raises(SystemExit) as exc:
        demo.parse_args(["--room=chatgpt"])
    assert "chatgpt" in str(exc.value)


def test_example_room_dye_overrides_one_seat():
    a, b = client_mod.stub_client("A"), client_mod.stub_client("B")
    seats = demo.example_room(a, dye={"fool": b})
    by_name = {p.name: p for p in seats}
    assert by_name["fool"].speak([]) == "B"
    assert by_name["dreamer"].speak([]) == "A"


def test_cli_main_offline_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)              # run artifacts land in tmp, not the repo
    result = demo.cli_main([])
    assert result["status"] == "completed"
    assert (tmp_path / "last_run.md").exists()
    assert (tmp_path / "last_harvest.md").exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_demo_wiring.py -v`
Expected: FAIL with `AttributeError: module 'demo' has no attribute 'parse_args'`

- [ ] **Step 4: Implement** — in `demo.py`:

Replace the import line to pull in the new clients:

```python
from client import (claude_cli_client, codex_cli_client, gemini_cli_client,
                    ollama_client, openai_compat_client, stub_client)
```

Change `example_room`'s signature and body to honor `dye` (docstring unchanged):

```python
def example_room(client, dye=None):
    dye = dye or {}
    def c(name):
        return dye.get(name, client)
    return [
        dreamer(c("dreamer"), topic=TOPIC, domain=EXAMPLE_DOMAIN),
        fool(c("fool"), topic=TOPIC, domain=EXAMPLE_DOMAIN),
        behavioral_scientist(c("scientist"), topic=TOPIC, domain=EXAMPLE_DOMAIN),
        insider(c("insider"), topic=TOPIC, domain=EXAMPLE_DOMAIN,
                who="a thirty-year veteran trader who never opened a stats book but reads the "
                    "crowd, knows which questions draw dumb money, and remembers exactly why "
                    "old edges died"),
    ]
```

Replace `pick_clients` with `_backend` + `parse_args` (keep the taught principle in the docstring):

```python
def _backend(name, model=None):
    """Map a backend name to a client callable. Constructing a client never makes a
    network call; only speaking does."""
    if name == "stub":
        return stub_client("(stub: a provocation would go here)")
    if name == "ollama":
        return ollama_client(model or "qwen2.5:7b")
    if name == "claude":
        return claude_cli_client
    if name == "codex":
        return codex_cli_client
    if name == "gemini":
        return gemini_cli_client
    if name == "openai":
        return openai_compat_client(model)
    raise SystemExit(
        f"unknown backend {name!r}; choose from stub|ollama|claude|codex|gemini|openai"
    )


def parse_args(argv):
    """Seat wiring. The principle the local runs taught us: cheap models GENERATE well,
    strong models SYNTHESIZE, so the divergent room can run cheap while the one harvest
    call gets the muscle.

      --room=<backend>       who powers the four seats        (default: stub)
      --harvest=<backend>    who powers the one harvest call  (default: same as room)
      --dye=<seat>=<backend> run ONE seat on a different model family
                             (seats: dreamer|fool|scientist|insider) — the
                             shared-basin antidote; repeatable
      --rounds=N             rounds to run (default 2)
      --model=<name>         model for ollama/openai backends

    Legacy aliases: --live (claude/claude), --hybrid (ollama/claude),
    --local (ollama/ollama).
    """
    def val(prefix, default=None):
        return next((a.split("=", 1)[1] for a in argv if a.startswith(prefix)), default)

    model = val("--model=")
    rounds = int(val("--rounds=", "2"))
    room_name = val("--room=")
    harvest_name = val("--harvest=")
    if room_name is None and harvest_name is None:
        if "--live" in argv:
            room_name = harvest_name = "claude"
        elif "--hybrid" in argv:
            room_name, harvest_name = "ollama", "claude"
        elif "--local" in argv:
            room_name = harvest_name = "ollama"
    room_name = room_name or "stub"
    harvest_name = harvest_name or room_name

    dye = {}
    for a in argv:
        if a.startswith("--dye="):
            seat, sep, backend = a.split("=", 1)[1].partition("=")
            if not sep or seat not in ("dreamer", "fool", "scientist", "insider"):
                raise SystemExit(
                    f"--dye takes <seat>=<backend> with seat in "
                    f"dreamer|fool|scientist|insider; got {a.split('=', 1)[1]!r}"
                )
            dye[seat] = _backend(backend, model)

    return _backend(room_name, model), _backend(harvest_name, model), dye, rounds
```

Thread `dye` through `main` and add `cli_main`:

```python
def main(room_client, harvest_client, rounds=2, out_path="last_run.md", dye=None):
    ...
    table = example_room(room_client, dye=dye)      # only change inside main
    ...


def cli_main(argv=None):
    room_client, harvest_client, dye, rounds = parse_args(
        sys.argv[1:] if argv is None else argv)
    return main(room_client, harvest_client, rounds=rounds, dye=dye)


if __name__ == "__main__":
    cli_main()
```

Also update the module docstring's usage block to mention `--room/--harvest/--dye/--rounds` alongside the legacy flags.

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_demo_wiring.py -v`
Expected: 10 passed

- [ ] **Step 6: Manual smoke of the legacy path, full suite, commit**

Run: `python demo.py` — expected: stub transcript + harvest print, artifacts written.
Run: `python -m pytest -q` — expected: 71 passed
```bash
git add demo.py tests/test_demo_wiring.py
git commit -m "feat: demo seat wiring — --room/--harvest/--dye/--rounds with legacy aliases

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: `cli.py` (`octagon` command) + `personas.SYSTEMS` + pyproject script

The unified entry point and the two subcommands the skill depends on (`doctor --json`, `prompt`).

**Files:**
- Create: `cli.py`, `tests/test_cli.py`
- Modify: `personas/personas.py`, `personas/__init__.py`, `pyproject.toml`

**Interfaces:**
- Consumes: `demo.cli_main(argv)` (Task 4), `forge.demo()`, `harvest.HARVEST_PROMPT`.
- Produces:
  - `personas.SYSTEMS: dict[str, str]` — roster name → system-prompt text (`practitioner`/`insider` values contain a literal `{who}` slot).
  - `cli.main(argv=None) -> int`; subcommands `demo`, `gate`, `reslice`, `doctor [--json]`, `prompt <name>|--list`.
  - `cli.run_doctor() -> dict` — `{backend: {"available": bool, "detail": str}}` for backends `claude, codex, gemini, ollama, openai_compat`. Never raises.
  - Console script: `octagon = "cli:main"`.

- [ ] **Step 1: Add `SYSTEMS` to `personas/personas.py`** (below `ROSTER`):

```python
# Canonical system-prompt text by roster name, for tooling that needs the words
# themselves (e.g. `octagon prompt <name>`, which the agent skill shells out to so
# prompts are never duplicated outside this file). The two domain-cast roles keep
# their literal {who} slot; fill it when you cast them.
SYSTEMS = {
    "dreamer": DREAMER_SYSTEM,
    "fool": FOOL_SYSTEM,
    "scientist": SCIENTIST_SYSTEM,
    "gambler": GAMBLER_SYSTEM,
    "skeptic": SKEPTIC_SYSTEM,
    "practitioner": PRACTITIONER_SYSTEM,
    "insider": INSIDER_SYSTEM,
}
```

In `personas/__init__.py` add `SYSTEMS` to the import from `.personas` and to `__all__`.

- [ ] **Step 2: Write the failing tests** — create `tests/test_cli.py`:

```python
"""Offline tests for the `octagon` CLI. doctor is fully mocked; gate/demo dispatch run
the real offline code paths."""

import json
import urllib.request

import pytest

import cli
from harvest import HARVEST_PROMPT
from personas import ROSTER, SYSTEMS


def test_systems_covers_the_whole_roster():
    assert set(SYSTEMS) == set(ROSTER)


def test_doctor_never_raises_and_covers_all_backends(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    def boom(*a, **kw):
        raise OSError("connection refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.delenv("OCTAGON_BASE_URL", raising=False)
    checks = cli.run_doctor()
    assert set(checks) == {"claude", "codex", "gemini", "ollama", "openai_compat"}
    assert all(c["available"] is False for c in checks.values())


def test_doctor_reports_available_backends(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda name: f"/fake/{name}")
    monkeypatch.setenv("OCTAGON_BASE_URL", "http://localhost:1234/v1")
    import io, contextlib
    body = json.dumps({"models": [{"name": "m1"}]}).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, timeout=None: contextlib.closing(io.BytesIO(body)))
    checks = cli.run_doctor()
    assert all(c["available"] for c in checks.values())
    assert "1 model" in checks["ollama"]["detail"]


def test_doctor_json_flag_prints_parseable_json(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)
    def boom(*a, **kw):
        raise OSError("refused")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    assert cli.main(["doctor", "--json"]) == 0
    parsed = json.loads(capsys.readouterr().out)
    assert "claude" in parsed


def test_prompt_prints_canonical_text(capsys):
    assert cli.main(["prompt", "dreamer"]) == 0
    assert capsys.readouterr().out.strip() == SYSTEMS["dreamer"].strip()


def test_prompt_harvest(capsys):
    assert cli.main(["prompt", "harvest"]) == 0
    assert capsys.readouterr().out.strip() == HARVEST_PROMPT.strip()


def test_prompt_list_names_the_bench(capsys):
    assert cli.main(["prompt", "--list"]) == 0
    out = capsys.readouterr().out
    for name in list(ROSTER) + ["harvest"]:
        assert name in out


def test_prompt_unknown_name_errors(capsys):
    assert cli.main(["prompt", "nostradamus"]) == 2
    assert "nostradamus" in capsys.readouterr().err


def test_gate_demo_dispatch_runs_the_synthetic_proof(capsys):
    assert cli.main(["gate", "--demo"]) == 0
    out = capsys.readouterr().out
    assert "VERDICT" in out and "pure-noise nulls" in out


def test_demo_dispatch_offline(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["demo"]) == 0
    assert (tmp_path / "last_run.md").exists()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cli'`

- [ ] **Step 4: Implement** — create `cli.py`:

```python
"""The `octagon` command: one front door for every entry point.

    octagon demo [--room=... --harvest=... --dye=seat=... --rounds=N ...]
    octagon gate --demo          the synthetic gate proof (forge.py)
    octagon reslice              the pre-registered re-slice campaign demo
    octagon doctor [--json]      which model backends are available on this machine
    octagon prompt <name>|--list canonical persona/harvest prompt text

`doctor` and `prompt` exist for tooling as much as humans: the agent skill in
.claude/skills/octagon/ shells out to them so backend detection and prompt text have
exactly one source of truth. Pure stdlib, like everything else here.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys


def run_doctor():
    """Probe every backend. Reports, never raises: a doctor that dies at the bedside
    helps nobody."""
    import urllib.request

    checks = {}
    for name in ("claude", "codex", "gemini"):
        path = shutil.which(name)
        checks[name] = {
            "available": bool(path),
            "detail": path or "not on PATH",
        }
    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as resp:
            models = json.loads(resp.read().decode("utf-8")).get("models", [])
        n = len(models)
        checks["ollama"] = {
            "available": True,
            "detail": f"{host} ({n} model{'s' if n != 1 else ''} pulled)",
        }
    except Exception as exc:  # noqa: BLE001
        checks["ollama"] = {"available": False, "detail": f"{host}: {exc}"}
    base = os.environ.get("OCTAGON_BASE_URL", "")
    checks["openai_compat"] = {
        "available": bool(base),
        "detail": base or "OCTAGON_BASE_URL not set",
    }
    return checks


def _cmd_doctor(args):
    checks = run_doctor()
    if args.json:
        print(json.dumps(checks, indent=2))
        return 0
    for name, c in checks.items():
        mark = "ok " if c["available"] else "-- "
        print(f"{mark}{name:<14} {c['detail']}")
    return 0


def _cmd_prompt(args):
    from harvest import HARVEST_PROMPT
    from personas import SYSTEMS

    prompts = dict(SYSTEMS)
    prompts["harvest"] = HARVEST_PROMPT
    if args.list:
        for name in sorted(prompts):
            print(name)
        return 0
    if args.name not in prompts:
        print(f"unknown prompt {args.name!r}; try: {', '.join(sorted(prompts))}",
              file=sys.stderr)
        return 2
    print(prompts[args.name])
    return 0


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    argv = sys.argv[1:] if argv is None else list(argv)

    # `demo` forwards its flags verbatim to demo.parse_args — bypass argparse entirely
    # (argparse.REMAINDER chokes on leading --flags it does not recognize).
    if argv and argv[0] == "demo":
        import demo
        demo.cli_main(argv[1:])
        return 0

    parser = argparse.ArgumentParser(
        prog="octagon",
        description="Adversarial idea generation gated by an incorruptible reality test.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    # help-text stub only; real dispatch happens above before argparse runs
    sub.add_parser("demo", help="run the roundtable demo (offline by default; "
                                "--room=, --harvest=, --dye=seat=backend, --rounds=N, "
                                "--model=, --local/--hybrid/--live)")

    p_gate = sub.add_parser("gate", help="the incorruptible gate (forge)")
    p_gate.add_argument("--demo", action="store_true", required=True,
                        help="run the synthetic proof on planted signals")

    sub.add_parser("reslice", help="pre-registered re-slice campaign (dry run)")

    p_doc = sub.add_parser("doctor", help="which model backends are available here")
    p_doc.add_argument("--json", action="store_true")

    p_prompt = sub.add_parser("prompt", help="print canonical persona/harvest prompts")
    p_prompt.add_argument("name", nargs="?")
    p_prompt.add_argument("--list", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "gate":
        import forge
        forge.demo()
        return 0
    if args.cmd == "reslice":
        import runpy
        runpy.run_module("adapters.reslice", run_name="__main__")
        return 0
    if args.cmd == "doctor":
        return _cmd_doctor(args)
    if args.cmd == "prompt":
        if not args.list and not args.name:
            print("prompt needs a name or --list", file=sys.stderr)
            return 2
        return _cmd_prompt(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Wire the console script** — in `pyproject.toml`:

Add `"cli"` to the `py-modules` list, and add after `[project.urls]`:

```toml
[project.scripts]
octagon = "cli:main"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: 10 passed

- [ ] **Step 7: Manual smoke of the installed command**

Run: `pip install -e . && octagon doctor && octagon prompt --list && octagon gate --demo`
Expected: doctor prints a status line per backend (claude/codex ok on this machine), prompt lists 8 names, gate prints the verdict table.

- [ ] **Step 8: Full suite green, then commit**

Run: `python -m pytest -q` — expected: 81 passed
```bash
git add cli.py tests/test_cli.py personas/personas.py personas/__init__.py pyproject.toml
git commit -m "feat: unified octagon CLI (demo/gate/reslice/doctor/prompt) + console script

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: the agent skill

**Files:**
- Create: `.claude/skills/octagon/SKILL.md`

**Interfaces:**
- Consumes: `python cli.py doctor --json`, `python cli.py prompt <name>`, `python cli.py prompt harvest`, the transcript format from `demo.py` (`### [r{round} s{seat}] {name}` sections), `python forge.py --demo`.
- Produces: the `/octagon` skill available to anyone opening the repo in Claude Code.

- [ ] **Step 1: Create `.claude/skills/octagon/SKILL.md`** with exactly this content:

```markdown
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
```

- [ ] **Step 2: Verify the skill's command claims against reality**

Run: `python cli.py prompt insider | head -3` and `python cli.py doctor --json`
Expected: both work from the repo root (the skill's commands are honest).

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/octagon/SKILL.md
git commit -m "feat: /octagon agent skill — host-model roundtable driving the repo's CLI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Codespaces devcontainer

**Files:**
- Create: `.devcontainer/devcontainer.json`

- [ ] **Step 1: Create `.devcontainer/devcontainer.json`:**

```json
{
  "name": "octagon",
  "image": "mcr.microsoft.com/devcontainers/python:3.12",
  "postCreateCommand": "pip install -e '.[dev]' && python -m pytest -q",
  "customizations": {
    "vscode": {
      "extensions": ["ms-python.python"]
    }
  }
}
```

- [ ] **Step 2: Validate the JSON parses**

Run: `python -c "import json; json.load(open('.devcontainer/devcontainer.json')); print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .devcontainer/devcontainer.json
git commit -m "feat: devcontainer for one-click Codespaces trial

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: hero GIF + README polish

The GIF is produced OUTSIDE the repo (scratchpad venv with Pillow); only the finished asset is committed. Subject: the `octagon gate --demo` verdict table (real functionality, fully offline).

**Files:**
- Create: `docs/assets/gate-demo.gif`
- Modify: `README.md`

- [ ] **Step 1: Capture the demo output**

Run: `python forge.py --demo > "$SCRATCHPAD/gate_demo_output.txt" 2>&1` (use the session scratchpad path). Inspect: the table should be ~28 lines, 90 columns.

- [ ] **Step 2: Render the GIF** — in the scratchpad, create a venv, `pip install pillow`, then run this script (adjust font path if Consolas is missing):

```python
"""Render captured terminal text as an animated GIF: progressive line reveal, then hold."""
from PIL import Image, ImageDraw, ImageFont

TEXT = open("gate_demo_output.txt", encoding="utf-8").read().rstrip().splitlines()
FONT = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 15)
PAD, LH = 16, 20
W = PAD * 2 + int(max(FONT.getlength(l) for l in TEXT)) + 8
H = PAD * 2 + LH * len(TEXT)
BG, FG, ACCENT = (13, 17, 23), (201, 209, 217), (63, 185, 80)

def frame(n):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    for i, line in enumerate(TEXT[:n]):
        color = ACCENT if ("REAL" in line or "VERDICT" in line) else FG
        d.text((PAD, PAD + i * LH), line, font=FONT, fill=color)
    return im

frames = [frame(n) for n in range(2, len(TEXT) + 1, 2)] + [frame(len(TEXT))] * 12
frames[0].save("gate-demo.gif", save_all=True, append_images=frames[1:],
               duration=140, loop=0, optimize=True)
print("bytes:", __import__("os").path.getsize("gate-demo.gif"))
```

Copy the result to `docs/assets/gate-demo.gif`. Expected size: well under 1.5 MB (text on flat background compresses hard). View it once to confirm it renders legibly.

- [ ] **Step 3: Update `README.md`:**

1. Directly under the `# octagon` heading + intro paragraph, add:

```markdown
![The gate demo: planted signals judged, all 20 noise nulls rejected](docs/assets/gate-demo.gif)
```

2. Replace the "How to run" section body with:

````markdown
## How to run

Zero dependencies — clone and run:

```bash
python demo.py            # offline: a full octagon run with deterministic stub personas
python forge.py --demo    # the synthetic gate proof shown above (no data needed)
python -m adapters.reslice    # a pre-registered re-slice campaign against a synthetic gate
python -m pytest -q       # the full offline test suite
```

Or install the `octagon` command (`pip install -e .`), or run it with nothing installed:

```bash
uvx --from git+https://github.com/brett-kerigan/octagon octagon gate --demo
```

`octagon doctor` tells you which model backends this machine can run live.

### Use it as a skill (zero setup)

Open this repo in Claude Code (or any agent that reads `SKILL.md`) and type `/octagon`:
the model you are already running becomes the table — one isolated subagent per seat —
and the deterministic gate stays in Python. No API keys, no configuration. To make it
available everywhere, copy `.claude/skills/octagon/` into `~/.claude/skills/`.

### Going live from the command line

Any headless agent CLI you already subscribe to can power a seat — no API keys, the
CLIs use their own logins:

| backend                | powered by                     | flag                          |
|------------------------|--------------------------------|-------------------------------|
| your current agent     | the `/octagon` skill           | (none — zero setup)           |
| Claude                 | `claude` CLI                   | `--room=claude`               |
| Codex                  | `codex` CLI                    | `--room=codex`                |
| Gemini                 | `gemini` CLI                   | `--room=gemini`               |
| local models           | Ollama                         | `--room=ollama --model=...`   |
| anything OpenAI-compat | OpenRouter, LM Studio, vLLM, … | `--room=openai` + env vars    |

```bash
python demo.py --room=ollama --harvest=claude      # cheap divergence, strong synthesis
python demo.py --room=claude --dye=fool=codex      # dye one seat a different family
```

`--dye seat=backend` exists because of the shared-basin warning below: one seat from a
different model family is the cheap antidote.
````

3. In the intro (line ~8): change "and the full test suite runs offline" wording only if needed — it contains no count. Find the one hardcoded count (`# 44 offline tests`) — it is inside the old "How to run" block replaced above; confirm no other hardcoded test count remains: `grep -n "44" README.md` → expected: no matches.

4. Add the Codespaces badge under the title line:

```markdown
[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/brett-kerigan/octagon)
```

(The CI badge is still deferred until the first green Actions run — unchanged decision.)

- [ ] **Step 4: Verify all README commands actually work**

Run each bash line that can run offline: `python demo.py`, `python forge.py --demo`, `python -m adapters.reslice`, `python -m pytest -q`, `python demo.py --room=stub`. Expected: all succeed. (`uvx` and Codespaces are verifiable only post-push; they are documented, not asserted.)

- [ ] **Step 5: Commit**

```bash
git add docs/assets/gate-demo.gif README.md
git commit -m "docs: hero GIF, skill quickstart, provider matrix, uvx + Codespaces on-ramps

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: final verification sweep

- [ ] **Step 1: Full suite from a clean state**

Run: `python -m pytest -q`
Expected: 81 passed, ~0.5s, no network.

- [ ] **Step 2: Every entry point, old and new**

```bash
python demo.py
python forge.py --demo
python -m adapters.reslice
octagon demo
octagon gate --demo
octagon reslice
octagon doctor
octagon doctor --json
octagon prompt --list
octagon prompt dreamer
python cli.py doctor --json
```
Expected: every command exits 0. `octagon doctor` shows claude=ok, codex=ok on this machine.

- [ ] **Step 3: Check nothing stray is tracked**

Run: `git status --porcelain`
Expected: empty (run artifacts like `last_run.md` are gitignored; the pip `octagon.egg-info/` is gitignored via `*.egg-info/`).

- [ ] **Step 4: Spec success-criteria walk** — re-read `docs/superpowers/specs/2026-07-18-github-ux-pass-design.md` "Success criteria" and confirm each: (1) zero-install offline paths ✓ Step 2; (2) installed CLI paths ✓ Step 2 (uvx = post-push); (3) skill present and honest ✓ Task 6 Step 2; (4) README assets/claims ✓ Task 8 Step 4; (5) suite offline and green ✓ Step 1. Report any miss instead of papering over it.

- [ ] **Step 5: Update the plan checkboxes, commit any doc touch-ups, and STOP — no push.** The push sequence remains Brett's call (see PUBLISH_HANDOFF.local.md; the CI badge waits for the first green Actions run).
