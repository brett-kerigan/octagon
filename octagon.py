"""The octagon: a pure, persona-agnostic turn scheduler.

`run_octagon(personas, max_rounds, stop_when=None) -> dict` seats 1 to 4 personas,
runs them in order for N rounds, threads the running transcript through every turn,
isolates faults so one raising persona cannot abort the round, and stops on
`max_rounds` or an optional `stop_when(transcript)` predicate.

The octagon knows nothing about who rides in it. A persona is anything with a `.name`
(str) and a `.speak(transcript) -> str`. That agnosticism is the point: swap models,
swap personas, swap transports without touching this file. Pure stdlib.
"""


def run_octagon(personas, max_rounds, stop_when=None):
    if len(personas) < 1 or len(personas) > 4:
        raise ValueError(f"personas must contain 1 to 4 agents; got {len(personas)}")
    if max_rounds < 1:
        raise ValueError(f"max_rounds must be >= 1; got {max_rounds}")

    for p in personas:
        if not hasattr(p, "name") or not isinstance(p.name, str):
            raise TypeError(f"persona {p!r} must have a str .name attribute")
        if not hasattr(p, "speak") or not callable(p.speak):
            raise TypeError(f"persona {p.name!r} must have a callable .speak method")

    for p in personas:
        if p.name == "":
            raise ValueError("persona .name must be non-empty")
    names = [p.name for p in personas]
    if len(names) != len(set(names)):
        raise ValueError(f"persona names must be unique; got {names}")

    transcript = []
    status = "completed"
    rounds_run = max_rounds

    for round_num in range(1, max_rounds + 1):
        for seat, persona in enumerate(personas):
            try:
                text = persona.speak(transcript)
                turn = {"round": round_num, "seat": seat, "name": persona.name, "text": text, "error": False}
            except Exception as exc:
                turn = {"round": round_num, "seat": seat, "name": persona.name, "text": str(exc), "error": True}
            transcript.append(turn)

        if stop_when is not None and stop_when(transcript):
            status = "stopped"
            rounds_run = round_num
            break

    return {
        "transcript": transcript,
        "rounds_run": rounds_run,
        "seats": len(personas),
        "status": status,
    }
