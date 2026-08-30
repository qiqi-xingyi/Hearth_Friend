"""Configuration, read from the environment with the HEARTH_ prefix.

A .env file in the working directory is loaded if present. Values already set in
the real environment always win, so `HEARTH_MODEL=... hearth chat` overrides the
file without editing it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ENV_PREFIX = "HEARTH_"
DEFAULT_ENV_FILE = Path(".env")


def load_env_file(path: Path = DEFAULT_ENV_FILE) -> None:
    """Read KEY=VALUE lines into os.environ without overriding existing values."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _get(name: str, default: str) -> str:
    return os.environ.get(ENV_PREFIX + name, default)


@dataclass(frozen=True)
class Config:
    db_path: Path
    persona_path: Path
    user_id: str
    channel: str
    provider: str
    api_key: str
    base_url: str
    model: str
    temperature: float
    context_turns: int
    request_timeout: float

    @classmethod
    def from_env(cls, *, load_dotenv: bool = True) -> "Config":
        if load_dotenv:
            load_env_file()
        data_dir = Path(_get("DATA_DIR", "data"))
        return cls(
            db_path=Path(_get("DB_PATH", str(data_dir / "hearth.db"))),
            persona_path=Path(_get("PERSONA", "persona/example.yaml")),
            user_id=_get("USER_ID", "local"),
            channel=_get("CHANNEL", "cli"),
            provider=_get("PROVIDER", "deepseek"),
            api_key=_get("API_KEY", ""),
            base_url=_get("BASE_URL", "https://api.deepseek.com"),
            model=_get("MODEL", "deepseek-v4-flash"),
            temperature=float(_get("TEMPERATURE", "1.0")),
            # How many past turns are replayed as context. M0 has no summarisation,
            # so this is a hard window rather than a budget.
            context_turns=int(_get("CONTEXT_TURNS", "40")),
            request_timeout=float(_get("REQUEST_TIMEOUT", "60")),
        )
