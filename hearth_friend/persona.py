"""Persona loading.

Persona is data, not code. Who she is lives in a YAML file that travels with the
database, not in constants scattered through the modules that use it.

Fields are added as the implementation needs them. This is what M0 uses.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


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
class Persona:
    name: str
    core: str
    language_register: str = ""
    self_disclosure: str = ""
    boundaries: tuple[str, ...] = field(default_factory=tuple)
    traits: Traits = field(default_factory=Traits)
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
            source_path=path,
        )
