"""Assembly example: draft a lineup, seat it, run the octagon, harvest the result.

Offline (safe, deterministic stub personas):
    python demo.py
Live (real model calls via the claude CLI, four seats x rounds):
    python demo.py --live
Seat wiring (Task 4): pick a backend per role, dye one seat off-family, set rounds:
    python demo.py --room=ollama --harvest=claude --dye=fool=codex --rounds=3

Shows the two ways to field a table:
  - draft(...) for a general lineup of functional roles, and
  - a domain-cast lineup that names a specific expert for one seat.
The live path is gated behind --live so nothing hits a model by accident.

The DOMAIN here is a neutral, illustrative example: hunting for mispriced outcomes in an
efficient forecasting/prediction market. Swap the DOMAIN and TOPIC strings to point the
same personas at any hard, search-for-an-overlooked-edge problem.
"""

import sys
from pathlib import Path

from octagon import run_octagon
from harvest import harvest
from client import (claude_cli_client, codex_cli_client, gemini_cli_client,
                    ollama_client, openai_compat_client, stub_client)
from personas import draft, dreamer, fool, behavioral_scientist, insider

# The world the table is hunting in (domain), and the specific question (topic).
EXAMPLE_DOMAIN = (
    "An efficient forecasting/prediction market. The 'crowd' is the pool of participants "
    "setting prices; an 'edge' is an outcome whose true probability differs from its market "
    "price by more than the trading cost. There is a long history of resolved markets and a "
    "price-anchored baseline model. The obvious edges are already arbitraged away; the market "
    "is efficient to within costs on the popular, heavily-traded questions."
)
TOPIC = (
    "Where is there still an unpriced edge nobody bothers to compute, and exactly how would "
    "we test it against the historical data without fooling ourselves with variance?"
)


def example_room(client, dye=None):
    """Pure-divergence room: GENERATORS ONLY, no filtering.

    The skeptic (the gate) and gambler (triage) are pulled DOWNSTREAM; the room's only job
    is to spark challenges off each other. Output = the harvest of every provocation raised,
    all of which earn a test against reality. No consensus, no funnel, nothing disqualified.

    This lineup holds on a small local model. For a stronger run, swap `insider` for the
    domain-cast practitioner to add real domain grounding."""
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


def general_room(client):
    """A generic divergence room drafted by name; generators only, no domain casting."""
    return draft(["dreamer", "fool", "scientist", "practitioner"], client,
                 topic=TOPIC, domain=EXAMPLE_DOMAIN)


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


def main(room_client, harvest_client, rounds=2, out_path="last_run.md", dye=None):
    # Windows consoles default to cp1252 and choke on the non-ASCII text models emit.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    table = example_room(room_client, dye=dye)
    result = run_octagon(table, max_rounds=rounds)

    lines = []
    for turn in result["transcript"]:
        tag = turn["name"] + (" [error]" if turn["error"] else "")
        lines.append(f"### [r{turn['round']} s{turn['seat']}] {tag}\n\n{turn['text']}\n")
    lines.append(f"\n---\nstatus={result['status']} "
                 f"rounds_run={result['rounds_run']} seats={result['seats']}")
    report = "\n".join(lines)

    # Persist (utf-8) BEFORE printing, so a console-encoding hiccup can never lose a run.
    Path(out_path).write_text(report, encoding="utf-8")
    print(report)
    print(f"\n[saved transcript -> {out_path}]")

    # The deliverable: catch every challenge out of the divergent prose.
    harvested = harvest(result["transcript"], harvest_client)
    Path("last_harvest.md").write_text(harvested, encoding="utf-8")
    print("\n\n========== HARVEST ==========\n")
    print(harvested)
    print("\n[saved harvest -> last_harvest.md]")
    return result


def cli_main(argv=None):
    room_client, harvest_client, dye, rounds = parse_args(
        sys.argv[1:] if argv is None else argv)
    return main(room_client, harvest_client, rounds=rounds, dye=dye)


if __name__ == "__main__":
    cli_main()
