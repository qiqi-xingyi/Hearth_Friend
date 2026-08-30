"""Command line entry point.

M0 exposes two commands: `hearth chat` to talk to her, and `hearth status` to see
what is in the database. There is no `serve` yet — a background process only
becomes meaningful once something runs in the background, and nothing does.
"""

from __future__ import annotations

import argparse
import sys

from hearth_friend import __version__
from hearth_friend.config import Config
from hearth_friend.core import Runtime
from hearth_friend.persona import Persona, PersonaError
from hearth_friend.providers import ProviderError, build_provider
from hearth_friend.store import Store

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def _style(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if sys.stdout.isatty() else text


def cmd_status(config: Config) -> int:
    store = Store(config.db_path)
    stats = store.stats(config.user_id)
    try:
        persona_name = Persona.load(config.persona_path).name
    except PersonaError:
        persona_name = "unreadable"
    rows = [
        ("database", f"{config.db_path} (schema v{stats['schema_version']})"),
        ("persona", f"{config.persona_path} ({persona_name})"),
        ("provider", f"{config.provider} / {config.model}"),
        ("user", config.user_id),
        ("sessions", str(stats["sessions"])),
        ("turns", str(stats["turns"])),
        ("since", stats["first_turn_at"] or "-"),
    ]
    width = max(len(key) for key, _ in rows)
    for key, value in rows:
        print(f"{_style(key.ljust(width), DIM)}  {value}")
    store.close()
    return 0


def cmd_backup(config: Config, destination: str) -> int:
    store = Store(config.db_path)
    path = store.backup(destination)
    stats = store.stats()
    store.close()
    print(f"{path}  ({stats['turns']} turns, {path.stat().st_size} bytes)")
    print(_style(f"copy {config.persona_path} as well: it is the other half.", DIM))
    return 0


def cmd_chat(config: Config) -> int:
    try:
        persona = Persona.load(config.persona_path)
    except PersonaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        provider = build_provider(config)
    except ProviderError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:  # line editing and history, when the platform has it
        import readline  # noqa: F401
    except ImportError:
        pass

    store = Store(config.db_path)
    stats = store.stats(config.user_id)
    print(
        _style(
            f"{persona.name} · {config.model} · {stats['turns']} turns so far"
            "   (/exit to leave)",
            DIM,
        )
    )

    runtime = Runtime(
        store,
        provider,
        persona,
        user_id=config.user_id,
        channel=config.channel,
        context_turns=config.context_turns,
        temperature=config.temperature,
    )
    speaker = _style(f"{persona.name}", BOLD)

    with runtime:
        while True:
            try:
                line = input(_style("> ", DIM))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            line = line.strip()
            if not line:
                continue
            if line in ("/exit", "/quit"):
                break
            if line == "/status":
                print(_style(str(store.stats(config.user_id)), DIM))
                continue

            print(f"{speaker}  ", end="", flush=True)
            stream = runtime.respond(line)
            try:
                for piece in stream:
                    print(piece, end="", flush=True)
                print("\n")
            except KeyboardInterrupt:
                stream.close()  # persists whatever was already shown
                print(_style("\n[interrupted]\n", DIM))
            except ProviderError as exc:
                stream.close()
                print(_style(f"\n[provider error: {exc}]\n", DIM), file=sys.stderr)

    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hearth", description="A runtime for a companion that persists."
    )
    parser.add_argument("--version", action="version", version=f"hearth {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("chat", help="talk to her (default)")
    sub.add_parser("status", help="show what is in the database")
    backup = sub.add_parser("backup", help="write a complete copy to a file")
    backup.add_argument("destination", help="path to write the copy to")
    parser.set_defaults(command="chat")

    args = parser.parse_args(argv)
    config = Config.from_env()

    if args.command == "status":
        return cmd_status(config)
    if args.command == "backup":
        return cmd_backup(config, args.destination)
    return cmd_chat(config)


if __name__ == "__main__":
    raise SystemExit(main())
