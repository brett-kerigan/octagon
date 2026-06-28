"""Assembly example: draft a lineup, seat it, run the octagon, harvest the result.

Offline (safe, deterministic stub personas):
    python demo.py
Live (real model calls via the claude CLI, four seats x rounds):
    python demo.py --live

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
from client import claude_cli_client, stub_client, ollama_client
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


def example_room(client):
    """Pure-divergence room: GENERATORS ONLY, no filtering.

    The skeptic (the gate) and gambler (triage) are pulled DOWNSTREAM; the room's only job
    is to spark challenges off each other. Output = the harvest of every provocation raised,
    all of which earn a test against reality. No consensus, no funnel, nothing disqualified.

    This lineup holds on a small local model. For a stronger run, swap `insider` for the
    domain-cast practitioner to add real domain grounding."""
    return [
        dreamer(client, topic=TOPIC, domain=EXAMPLE_DOMAIN),
        fool(client, topic=TOPIC, domain=EXAMPLE_DOMAIN),
        behavioral_scientist(client, topic=TOPIC, domain=EXAMPLE_DOMAIN),
        insider(client, topic=TOPIC, domain=EXAMPLE_DOMAIN,
                who="a thirty-year veteran trader who never opened a stats book but reads the "
                    "crowd, knows which questions draw dumb money, and remembers exactly why "
                    "old edges died"),
    ]


def general_room(client):
    """A generic divergence room drafted by name; generators only, no domain casting."""
    return draft(["dreamer", "fool", "scientist", "practitioner"], client,
                 topic=TOPIC, domain=EXAMPLE_DOMAIN)


def pick_clients(argv):
    """Return (room_client, harvest_client). The principle the local runs taught us: cheap
    models GENERATE well, strong models SYNTHESIZE, so the divergent room can run free while
    the one harvest call gets the muscle.
      (default)  stub   / stub    offline, instant
      --local    ollama / ollama  fully local
      --hybrid   ollama / claude  local divergent room + one stronger harvest (recommended)
      --live     claude / claude  both on the claude CLI
    """
    model = next((a.split("=", 1)[1] for a in argv if a.startswith("--model=")),
                 "qwen2.5:7b")
    if "--live" in argv:
        return claude_cli_client, claude_cli_client
    if "--hybrid" in argv:
        return ollama_client(model), claude_cli_client
    if "--local" in argv:
        return ollama_client(model), ollama_client(model)
    stub = stub_client("(stub: a provocation would go here)")
    return stub, stub


def main(room_client, harvest_client, rounds=2, out_path="last_run.md"):
    # Windows consoles default to cp1252 and choke on the non-ASCII text models emit.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

    table = example_room(room_client)
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


if __name__ == "__main__":
    room_client, harvest_client = pick_clients(sys.argv)
    main(room_client, harvest_client, rounds=2)
