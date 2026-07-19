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
        try:
            path = shutil.which(name)
        except Exception as exc:  # noqa: BLE001
            checks[name] = {"available": False, "detail": f"probe failed: {exc}"}
            continue
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
