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
class Persona:
    name: str
    core: str
    language_register: str = ""
    self_disclosure: str = ""
    boundaries: tuple[str, ...] = field(default_factory=tuple)
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
            source_path=path,
        )
