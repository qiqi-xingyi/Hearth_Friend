"""Persona loading.

Persona is data, not code. Who she is lives in a YAML file that travels with the
database, not in constants scattered through the modules that use it.

Fields are added as the implementation needs them. This is what M0 uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hearth_friend.world.feeds import KNOWN_SOURCES


class PersonaError(ValueError):
    """The persona file is missing or malformed."""


@dataclass(frozen=True)
class Traits:
    """Personality as parameters, not adjectives.

    Every field here is read by code and changes a number. A trait that only
    gets described in the prompt is not a trait; it is a word in a file, and the
    model will render it as tone and then ignore it.
    """

    # Where her mood settles when nothing is happening.  -1 .. +1
    baseline_mood: float = 0.0
    # How far someone else's feeling carries into hers.  0 .. 1
    warmth: float = 0.5
    # How fast she moves at all. Low means steady, high means she takes it in.
    volatility: float = 0.3
    # How much a salient subject pulls her in, versus leaving her flat.
    curiosity: float = 0.5
    # How much of her own condition shows in what she says.
    expressiveness: float = 0.5

    @classmethod
    def from_dict(cls, data: dict | None) -> "Traits":
        data = data or {}
        known = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        try:
            traits = cls(**{k: float(v) for k, v in known.items()})
        except (TypeError, ValueError) as exc:
            raise PersonaError(f"traits must be numbers: {exc}") from exc
        for field, value in vars(traits).items():
            low = -1.0 if field == "baseline_mood" else 0.0
            if not low <= value <= 1.0:
                raise PersonaError(f"trait {field}={value} is outside [{low}, 1.0]")
        return traits


@dataclass(frozen=True)
class MessageStyle:
    """How she breaks what she says into messages.

    Rhythm is part of a person. Someone who fires off five short lines and
    someone who writes one considered paragraph are recognisably different
    people before you read a word of it, and a runtime that always emits
    exactly one message per turn has flattened that away.
    """

    # Roughly how many messages one reply becomes.
    messages_per_reply: float = 2.0
    # Roughly how long each one runs, in characters.
    chars_per_message: int = 30
    # Seconds between them, as if she were typing.
    pause_seconds: float = 1.2

    @classmethod
    def from_dict(cls, data: dict | None) -> "MessageStyle":
        data = data or {}
        try:
            style = cls(
                messages_per_reply=float(data.get("messages_per_reply", 2.0)),
                chars_per_message=int(data.get("chars_per_message", 30)),
                pause_seconds=float(data.get("pause_seconds", 1.2)),
            )
        except (TypeError, ValueError) as exc:
            raise PersonaError(f"message_style must be numbers: {exc}") from exc
        if not 1.0 <= style.messages_per_reply <= 8.0:
            raise PersonaError("messages_per_reply must be between 1 and 8")
        if not 4 <= style.chars_per_message <= 400:
            raise PersonaError("chars_per_message must be between 4 and 400")
        if not 0.0 <= style.pause_seconds <= 10.0:
            raise PersonaError("pause_seconds must be between 0 and 10")
        return style


@dataclass(frozen=True)
class Persona:
    name: str
    core: str
    language_register: str = ""
    self_disclosure: str = ""
    boundaries: tuple[str, ...] = field(default_factory=tuple)
    traits: Traits = field(default_factory=Traits)
    message_style: MessageStyle = field(default_factory=MessageStyle)
    self_facts: tuple[dict, ...] = field(default_factory=tuple)
    reads: tuple[dict, ...] = field(default_factory=tuple)
    source_path: Path | None = None

    @classmethod
    def load(cls, path: Path | str) -> "Persona":
        path = Path(path)
        if not path.is_file():
            raise PersonaError(
                f"persona file not found: {path}\n"
                f"Copy persona/example.yaml, or set HEARTH_PERSONA to another file."
            )
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise PersonaError(f"persona file is not valid YAML: {path}\n{exc}") from exc

        data = raw.get("persona", raw)
        if not isinstance(data, dict):
            raise PersonaError(f"persona file must contain a mapping: {path}")

        missing = [key for key in ("name", "core") if not str(data.get(key, "")).strip()]
        if missing:
            raise PersonaError(f"persona file is missing required field(s) {missing}: {path}")

        boundaries = data.get("boundaries") or []
        if isinstance(boundaries, str):
            boundaries = [boundaries]

        return cls(
            name=str(data["name"]).strip(),
            core=str(data["core"]).strip(),
            language_register=str(data.get("language_register") or "").strip(),
            self_disclosure=str(data.get("self_disclosure") or "").strip(),
            boundaries=tuple(str(b).strip() for b in boundaries if str(b).strip()),
            traits=Traits.from_dict(data.get("traits")),
            message_style=MessageStyle.from_dict(data.get("message_style")),
            self_facts=_read_self_facts(data.get("self"), path),
            reads=_read_sources(data.get("reads"), path),
            source_path=path,
        )


def _read_self_facts(raw: object, path: Path) -> tuple[dict, ...]:
    """Seed entries for what is true about her, from the persona file."""
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise PersonaError(f"persona 'self' must be a list: {path}")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise PersonaError(f"each 'self' entry must be a mapping: {path}")
        kind = str(entry.get("kind", "fact")).strip()
        if kind not in ("fact", "view", "dislike", "unsure"):
            raise PersonaError(f"unknown self kind {kind!r}: {path}")
        cues = str(entry.get("cues", "")).strip()
        statement = str(entry.get("say", "")).strip()
        if not cues or not statement:
            raise PersonaError(f"a 'self' entry needs both cues and say: {path}")
        out.append({
            "kind": kind,
            "cues": cues,
            "statement": statement,
            "always_on": bool(entry.get("always", False)),
        })
    return tuple(out)


def _read_sources(raw: object, path: Path) -> tuple[dict, ...]:
    """Where she reads. What someone reads is part of who they are, so it lives
    with the rest of the persona rather than in configuration."""
    if not raw:
        return ()
    if not isinstance(raw, list):
        raise PersonaError(f"persona 'reads' must be a list: {path}")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise PersonaError(f"each 'reads' entry must be a mapping: {path}")
        name = str(entry.get("name", "")).strip()
        url = str(entry.get("url", "")).strip()
        kind = str(entry.get("kind", "rss")).strip() or "rss"
        if not name:
            raise PersonaError(f"a 'reads' entry needs a name: {path}")
        if kind == "rss":
            if not url.startswith(("http://", "https://")):
                raise PersonaError(f"'reads' url must be http(s): {url!r} in {path}")
        elif kind not in KNOWN_SOURCES:
            raise PersonaError(f"unknown 'reads' kind {kind!r}: {path}")
        out.append({"name": name, "url": url, "kind": kind})
    return tuple(out)
