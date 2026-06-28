"""LLMPersona: the standard occupant of an octagon seat.

Transport-agnostic by the same principle as the octagon: a persona NEVER imports a
model or a client. You inject `client`, a callable `client(prompt: str) -> str`.
Inject a stub for offline work and tests; inject a live client to run for real.
Swapping the brain never touches the scheduler or the persona's character.

Three layers of context, kept separate on purpose:
  - system_prompt : WHO you are (the functional role, domain-neutral).
  - domain        : the WORLD you are hunting in (what the crowd/edge means here).
  - topic         : the specific question on the table right now.
The same role (e.g. the Skeptic) is reused across domains by swapping `domain`.

Honors the three contracts the scheduler imposes on a seat:
  1. .speak() always returns a str (we coerce; the octagon stores it verbatim).
  2. the transcript is read-only here; we only read it to build the prompt.
  3. nothing here is depended on by a stop_when predicate.
"""

from __future__ import annotations


class LLMPersona:
    """A persona: a role, a domain, a topic, and an injected client."""

    def __init__(self, name, system_prompt, client, topic=None, domain=None):
        if not isinstance(name, str) or not name:
            raise ValueError("persona name must be a non-empty str")
        if not callable(client):
            raise TypeError("client must be callable: client(prompt: str) -> str")
        self.name = name
        self.system_prompt = system_prompt
        self.topic = topic
        self.domain = domain
        self._client = client

    def speak(self, transcript):
        text = self._client(self._render(transcript))
        # Contract #1: the octagon stores whatever we return verbatim; guarantee str.
        return text if isinstance(text, str) else str(text)

    def _render(self, transcript):
        # Contract #2: read-only use of the live transcript list.
        parts = [self.system_prompt]
        if self.domain:
            parts += ["", "--- The world you are hunting in ---", self.domain]
        if self.topic:
            parts += ["", "--- On the table ---", self.topic]
        parts += ["", "--- Discussion so far ---"]
        if not transcript:
            parts.append("(nothing yet; you are opening the discussion.)")
        else:
            for turn in transcript:
                tag = turn["name"] + (" [error]" if turn.get("error") else "")
                parts.append(f"{tag}: {turn['text']}")
        parts += ["", f"--- Your turn, {self.name} ---",
                  "Give your next contribution, fully in character."]
        return "\n".join(parts)
