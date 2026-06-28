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


def _scoped_env():
    """A copy of the environment with unrelated-provider secrets removed.

    PATH, HOME, SystemRoot and everything non-secret pass through unchanged, so the child
    still runs normally; only vars that look like another service's credential (and are not
    Anthropic/Claude's own) are dropped.
    """
    env = {}
    for k, v in os.environ.items():
        if _SECRETISH.search(k) and not k.upper().startswith(_ALLOW_PREFIXES):
            continue
        env[k] = v
    return env


def stub_client(reply="(stub reply)"):
    """A deterministic offline client for dry runs and tests. Returns a callable."""

    def _c(prompt: str) -> str:
        return reply

    return _c


def echo_client(prompt: str) -> str:
    """Trivial client that reports how much context it saw, for wiring smoke checks."""
    return f"(echo: prompt was {len(prompt)} chars)"


def claude_cli_client(prompt: str, *, model: str = "opus", timeout_s: int = 600) -> str:
    """A live client that shells out to the local `claude` CLI in print mode (`claude -p`).

    The prompt is fed via stdin (on Windows `claude` is a .cmd shim that truncates a
    multi-line argv). Output is parsed from the CLI's JSON envelope. A four-seat round is
    four of these calls. Not invoked until you choose to run the table live.
    """
    claude = shutil.which("claude")
    if not claude:
        raise RuntimeError(
            "`claude` CLI not on PATH; install it and authenticate, or inject a different client."
        )
    proc = subprocess.run(
        [claude, "-p", "--output-format", "json", "--model", model],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_s,
        env=_scoped_env(),                 # don't hand the child unrelated provider secrets
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:300]}"
        )
    try:
        envelope = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(
            f"claude CLI returned non-JSON output: {proc.stdout.strip()[:200]!r}"
        ) from exc
    if envelope.get("is_error"):
        raise RuntimeError(f"claude CLI error: {envelope.get('subtype')}")
    return envelope.get("result", "")


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
