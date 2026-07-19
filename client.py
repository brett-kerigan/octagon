"""Clients you inject into personas. The persona contract is just:

    client(prompt: str) -> str

Keeping this separate is the whole point of the agnostic octagon/seat design: swap the
client without touching a persona or the scheduler. The stubs here are safe to run
anywhere; `claude_cli_client` and `ollama_client` are the only ones that talk to the
outside world, and nothing calls them until you deliberately choose to run live.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

# Vars whose names look like a credential for some OTHER service. We strip these from the
# child process env so shelling out to one CLI never hands it unrelated provider secrets.
_SECRETISH = re.compile(r"(API[_-]?KEY|SECRET|TOKEN|PASSWORD|PASSWD|ACCESS[_-]?KEY)", re.I)
# ...except the ones the claude CLI itself may legitimately need.
_ALLOW_PREFIXES = ("ANTHROPIC", "CLAUDE")


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
    return envelope.get("result") or ""


def stub_client(reply="(stub reply)"):
    """A deterministic offline client for dry runs and tests. Returns a callable."""

    def _c(prompt: str) -> str:
        return reply

    return _c


def echo_client(prompt: str) -> str:
    """Trivial client that reports how much context it saw, for wiring smoke checks."""
    return f"(echo: prompt was {len(prompt)} chars)"


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

    Verified live against codex-cli 0.142.3: `codex exec --json -` reads the prompt
    from stdin, `-m/--model` selects the model, and the real JSONL stream matches the
    wrapped {"type": "item.completed", "item": {"type": "agent_message", ...}} shape
    this parser expects (preceded by thread.started/turn.started and followed by
    turn.completed events, which this parser correctly ignores).
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
    the isolation layer — adjust argv here if your installed version differs. Not
    verified live (gemini CLI is not installed on the machine this was built on); this
    is mock-tested only.
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


def ollama_client(model="qwen2.5:7b", *, host="http://localhost:11434", timeout_s=300):
    """LOCAL client via Ollama. Returns a `client(prompt) -> str` callable bound to one
    local model. Good for throw-away dev (iterate the harness for free) and for a
    genuinely different-family seat (e.g. the fool, where orthogonality matters more than
    rigor).

    Requires the Ollama service running and the model pulled:
        ollama pull qwen2.5:7b
    Talks to the native /api/generate endpoint over stdlib urllib (no extra deps).
    """
    import urllib.request

    def _c(prompt: str) -> str:
        payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode("utf-8")
        req = urllib.request.Request(
            f"{host}/api/generate", data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"ollama call failed (host={host}, model={model}): {exc}. "
                f"Is the Ollama service running, and have you run `ollama pull {model}`?"
            ) from exc
        return data.get("response", "")

    return _c


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
