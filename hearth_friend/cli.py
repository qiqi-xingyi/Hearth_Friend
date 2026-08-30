"""Command line entry point.

M0 exposes two commands: `hearth chat` to talk to her, and `hearth status` to see
what is in the database. There is no `serve` yet — a background process only
becomes meaningful once something runs in the background, and nothing does.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time

from hearth_friend import __version__
from hearth_friend.config import Config
from hearth_friend.core import Runtime
from hearth_friend.persona import Persona, PersonaError
from hearth_friend.providers import ProviderError, build_provider
from hearth_friend.store import Store
from hearth_friend.world.feeds import Unreachable

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
    """Talk to her.

    Not a question-and-answer loop. What you type is recorded immediately and
    she answers when you seem to have stopped, so you can send three lines in a
    row the way you would to anyone else. She replies on another thread, which
    means her messages can land while you are still typing.
    """
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

    from prompt_toolkit import PromptSession, print_formatted_text
    from prompt_toolkit.formatted_text import FormattedText
    from prompt_toolkit.patch_stdout import patch_stdout

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

    last_input = time.monotonic()
    last_spoke = 0.0
    stop = threading.Event()

    def say(message: str) -> None:
        # Raw ANSI does not survive patch_stdout; prompt_toolkit has to do the
        # styling or the escape codes end up on screen as text.
        print_formatted_text(
            FormattedText([("bold", persona.name), ("", f"  {message}")])
        )

    def speaking() -> None:
        nonlocal last_spoke
        # Reading past sessions happens here rather than at startup, so a
        # backlog does not stand between you and saying hello.
        try:
            seen = runtime.refresh_reading()
            if seen:
                print(_style(f"[read {seen} new things]", DIM))
        except Unreachable:
            print(_style("[could not reach anything to read]", DIM))
        except Exception:
            pass
        try:
            learned = runtime.catch_up_extraction()
            if learned:
                print(_style(f"[settled {learned} more things about herself]", DIM))
        except Exception:
            pass
        while not stop.wait(0.2):
            if not runtime.unanswered():
                continue
            # Wait out both: you may still be typing, and if she has only just
            # finished talking she does not launch straight into another block.
            # Without the second, anything you send while she is composing
            # arrives to find the window already elapsed, and lands as a second
            # burst stacked on the first.
            quiet_since = max(last_input, last_spoke)
            if time.monotonic() - quiet_since < config.settle_seconds:
                continue
            try:
                for index, message in enumerate(runtime.reply()):
                    if index:
                        time.sleep(persona.message_style.pause_seconds)
                    say(message)
            except ProviderError as exc:
                print(_style(f"[provider error: {exc}]", DIM), file=sys.stderr)
            except Exception as exc:  # keep the conversation alive
                print(_style(f"[error: {exc}]", DIM), file=sys.stderr)
            finally:
                last_spoke = time.monotonic()

    session = PromptSession()
    with runtime:
        thread = threading.Thread(target=speaking, name="speaking", daemon=True)
        thread.start()
        try:
            with patch_stdout():
                while True:
                    try:
                        line = session.prompt("> ")
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
                    runtime.ingest(line)
                    last_input = time.monotonic()
        finally:
            stop.set()
            thread.join(timeout=config.request_timeout + 5)

    # The session is closed by the context manager above; read it now.
    try:
        if runtime.catch_up_extraction(limit=1):
            pass
    except ProviderError:
        pass

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
