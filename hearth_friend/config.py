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
    context_chars: int
    request_timeout: float
    settle_seconds: float
    embedding_model: str
    qq_ws_url: str
    qq_user_id: int
    qq_token: str
    vision_model: str

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
            # A count is not a budget: forty turns of one word and forty turns
            # of a pasted document are the same number and very different
            # prompts. Whichever limit is reached first wins.
            context_chars=int(_get("CONTEXT_CHARS", "6000")),
            request_timeout=float(_get("REQUEST_TIMEOUT", "60")),
            # How long she waits after you stop typing before answering, so that
            # sending three lines in a row gets one reply rather than three.
            settle_seconds=float(_get("SETTLE_SECONDS", "2.0")),
            # Local, because an embedding call carries the text itself. "off"
            # falls back to keyword matching, which is a working system.
            embedding_model=_get("EMBEDDING_MODEL", "BAAI/bge-m3"),
            # QQ has no usable API of its own; a protocol implementation
            # (NapCat, Lagrange) signs in and speaks OneBot on its behalf.
            qq_ws_url=_get("QQ_WS_URL", "ws://127.0.0.1:3001"),
            qq_user_id=int(_get("QQ_USER_ID", "0") or 0),
            qq_token=_get("QQ_TOKEN", ""),
            # Only used for the turn a picture arrives in. "off" means she says
            # she cannot see it, which is what she did before this existed.
            vision_model=_get("VISION_MODEL", "deepseek-v4-flash-vision-exp"),
        )
