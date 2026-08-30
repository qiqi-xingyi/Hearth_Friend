"""SQLite store.

The `turn` table is the source of truth. Everything else in this project is
derived from it and may be dropped and rebuilt, which is what makes the rest of
the design safe to change while it is being built.

Migrations run automatically on open. They exist from the first commit precisely
because the schema is expected to move a lot: by the time it does there is real
conversation in the database, and a design change must not cost data.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utcnow() -> str:
    """Timestamps are ISO-8601 UTC text: portable, sortable, exports cleanly."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Turn:
    id: int
    session_id: int
    role: str
    content: str
    created_at: str


class AppendOnlyViolation(RuntimeError):
    """Raised when something tries to rewrite the turn log."""


class Store:
    def __init__(self, path: Path | str):
        self.path = Path(path)
        if self.path.parent != Path(""):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # One connection per thread rather than one shared behind a lock.
        # Reading you in and answering you happen on different threads, because
        # you have to be able to keep talking while she is still composing.
        # SQLite in WAL mode handles that between connections; sharing a single
        # connection across threads is what it will not do.
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self.applied_migrations = self.migrate()

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            # isolation_level=None puts the driver in autocommit mode so that
            # transactions are managed explicitly here rather than implicitly.
            conn = sqlite3.connect(str(self.path), isolation_level=None)
            conn.row_factory = sqlite3.Row
            self._configure(conn)
            self._local.conn = conn
            self._connections.append(conn)
        return conn

    @staticmethod
    def _configure(conn: sqlite3.Connection) -> None:
        # WAL from the start: a scheduler will share this file soon enough, and
        # switching later means a moment where the database is not readable.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Long enough that a writer waiting on another writer waits instead of
        # failing; short enough that a genuine deadlock still surfaces.
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")

    # ---------------------------------------------------------------- schema

    def migrate(self) -> list[int]:
        """Apply pending migrations in filename order. Returns versions applied."""
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "  version INTEGER PRIMARY KEY,"
            "  applied_at TEXT NOT NULL)"
        )
        applied = {
            row["version"] for row in self.conn.execute("SELECT version FROM schema_version")
        }
        newly: list[int] = []
        for sql_path in sorted(MIGRATIONS_DIR.glob("[0-9]*.sql")):
            version = int(sql_path.name.split("_", 1)[0])
            if version in applied:
                continue
            body = sql_path.read_text(encoding="utf-8")
            # The migration and its version record commit together. executescript
            # commits any pending transaction first, so the BEGIN belongs inside
            # the script rather than around the call.
            script = (
                "BEGIN;\n"
                f"{body}\n"
                "INSERT INTO schema_version (version, applied_at) "
                f"VALUES ({version}, '{utcnow()}');\n"
                "COMMIT;\n"
            )
            try:
                self.conn.executescript(script)
            except Exception:
                try:
                    self.conn.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise
            newly.append(version)
        return newly

    @property
    def schema_version(self) -> int:
        row = self.conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
        return row["v"] or 0

    # -------------------------------------------------------------- sessions

    def open_session(self, user_id: str, channel: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO session (user_id, channel, started_at) VALUES (?, ?, ?)",
            (user_id, channel, utcnow()),
        )
        return int(cur.lastrowid)

    def close_session(self, session_id: int) -> None:
        self.conn.execute(
            "UPDATE session SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
            (utcnow(), session_id),
        )

    # ----------------------------------------------------------------- turns

    def append_turn(
        self,
        session_id: int,
        role: str,
        content: str,
        *,
        channel_msg_id: str | None = None,
        meta: dict[str, Any] | None = None,
        answers_through: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO turn (session_id, role, content, created_at, channel_msg_id,"
            "                  meta_json, answers_through)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                utcnow(),
                channel_msg_id,
                json.dumps(meta, ensure_ascii=False) if meta else None,
                answers_through,
            ),
        )
        return int(cur.lastrowid)

    def answered_through(self, user_id: str) -> int:
        """The last message of yours she has actually read and answered.

        Recorded on her messages, but the column was added late and the turn log
        cannot be rewritten, so rows from before it exists carry NULL. The
        fallback reads the structure instead: anything you said before her last
        message was, by construction, something she had already seen. Without
        it, the first launch after the migration treats the entire history as
        unanswered and she opens by replying to a week-old conversation.
        """
        recorded = self.conn.execute(
            "SELECT MAX(t.answers_through) AS n FROM turn t"
            "  JOIN session s ON s.id = t.session_id"
            " WHERE s.user_id = ? AND t.role = 'assistant'",
            (user_id,),
        ).fetchone()["n"]
        # Confined to rows from before the column existed. Applying it more
        # widely would be wrong in exactly the case the column was added for:
        # something you send while she is composing lands before her reply, and
        # is not something she saw.
        implied = self.conn.execute(
            "SELECT MAX(u.id) AS n FROM turn u JOIN session su ON su.id = u.session_id"
            " WHERE su.user_id = ? AND u.role = 'user' AND u.id < ("
            "   SELECT MAX(a.id) FROM turn a JOIN session sa ON sa.id = a.session_id"
            "    WHERE sa.user_id = ? AND a.role = 'assistant'"
            "      AND a.answers_through IS NULL)",
            (user_id, user_id),
        ).fetchone()["n"]
        return max(int(recorded or 0), int(implied or 0))

    def unanswered_turns(self, user_id: str, limit: int) -> list[Turn]:
        """Your messages she has not got to yet, oldest first."""
        rows = self.conn.execute(
            "SELECT t.id, t.session_id, t.role, t.content, t.created_at"
            "  FROM turn t JOIN session s ON s.id = t.session_id"
            " WHERE s.user_id = ? AND t.role = 'user' AND t.id > ?"
            " ORDER BY t.id LIMIT ?",
            (user_id, self.answered_through(user_id), limit),
        ).fetchall()
        return [Turn(**dict(row)) for row in rows]

    def recent_turns(self, user_id: str, limit: int) -> list[Turn]:
        """The most recent turns for a user, oldest first.

        Context deliberately spans sessions: a session is one attach to the CLI,
        not one conversation. M0 takes a fixed window; summarising a longer
        history is a later problem.
        """
        rows = self.conn.execute(
            "SELECT t.id, t.session_id, t.role, t.content, t.created_at"
            "  FROM turn t JOIN session s ON s.id = t.session_id"
            " WHERE s.user_id = ? AND t.role IN ('user', 'assistant')"
            " ORDER BY t.id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [Turn(**dict(row)) for row in reversed(rows)]

    # ----------------------------------------------------------- her interior

    def load_state(self, user_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT mood_valence, mood_arousal, energy, engagement, focus, updated_at"
            "  FROM state WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None

    def save_state(self, user_id: str, state: dict) -> None:
        self.conn.execute(
            "INSERT INTO state (user_id, mood_valence, mood_arousal, energy,"
            "                   engagement, focus, updated_at)"
            " VALUES (:user_id, :mood_valence, :mood_arousal, :energy,"
            "         :engagement, :focus, :updated_at)"
            " ON CONFLICT(user_id) DO UPDATE SET"
            "   mood_valence = excluded.mood_valence,"
            "   mood_arousal = excluded.mood_arousal,"
            "   energy       = excluded.energy,"
            "   engagement   = excluded.engagement,"
            "   focus        = excluded.focus,"
            "   updated_at   = excluded.updated_at",
            {"user_id": user_id, **state, "updated_at": utcnow()},
        )

    def save_perception(self, turn_id: int, perception) -> int:
        """Kept as the evidence behind a state change, not as authority.

        Derived from `turn`, so it can be recomputed; recorded anyway, because
        without it a state change has no explanation.
        """
        cur = self.conn.execute(
            "INSERT INTO perception (turn_id, user_emotion, emotion_intensity,"
            "                        wants, salience, about_her, raw_json, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn_id,
                perception.emotion,
                perception.emotion_intensity,
                perception.wants,
                perception.salience,
                int(perception.about_her),
                perception.raw or None,
                utcnow(),
            ),
        )
        return int(cur.lastrowid)

    def assistant_turns(self, session_id: int) -> list[Turn]:
        rows = self.conn.execute(
            "SELECT id, session_id, role, content, created_at FROM turn"
            " WHERE session_id = ? AND role = 'assistant' ORDER BY id",
            (session_id,),
        ).fetchall()
        return [Turn(**dict(row)) for row in rows]

    def unextracted_sessions(self, user_id: str) -> list[int]:
        """Finished sessions whose contents have not been folded back in yet."""
        rows = self.conn.execute(
            "SELECT id FROM session"
            " WHERE user_id = ? AND ended_at IS NOT NULL AND extracted_at IS NULL"
            " ORDER BY id",
            (user_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def mark_extracted(self, session_id: int) -> None:
        self.conn.execute(
            "UPDATE session SET extracted_at = ? WHERE id = ?", (utcnow(), session_id)
        )

    # ------------------------------------------------------------- selfhood

    def self_facts(self) -> list[dict[str, Any]]:
        """Everything currently true about her."""
        rows = self.conn.execute(
            "SELECT id, kind, cues, statement FROM self_fact"
            " WHERE superseded_by IS NULL ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_self_fact(
        self,
        kind: str,
        cues: str,
        statement: str,
        *,
        source_turn_id: int | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO self_fact (kind, cues, statement, source_turn_id, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (kind, cues, statement, source_turn_id, utcnow()),
        )
        return int(cur.lastrowid)

    def supersede_self_fact(self, old_id: int, new_id: int) -> None:
        """Kept rather than deleted: that she used to think otherwise is part of
        the record, and is the only way a change in her is ever visible."""
        self.conn.execute(
            "UPDATE self_fact SET superseded_by = ? WHERE id = ?", (new_id, old_id)
        )

    def has_self_statement(self, statement: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM self_fact WHERE statement = ? LIMIT 1", (statement,)
        ).fetchone()
        return row is not None

    # ----------------------------------------------------------------- misc

    def stats(self, user_id: str | None = None) -> dict[str, Any]:
        if user_id is None:
            sessions = self.conn.execute("SELECT COUNT(*) AS n FROM session").fetchone()["n"]
            turns = self.conn.execute("SELECT COUNT(*) AS n FROM turn").fetchone()["n"]
            first = self.conn.execute("SELECT MIN(created_at) AS t FROM turn").fetchone()["t"]
        else:
            sessions = self.conn.execute(
                "SELECT COUNT(*) AS n FROM session WHERE user_id = ?", (user_id,)
            ).fetchone()["n"]
            turns = self.conn.execute(
                "SELECT COUNT(*) AS n FROM turn t JOIN session s ON s.id = t.session_id"
                " WHERE s.user_id = ?",
                (user_id,),
            ).fetchone()["n"]
            first = self.conn.execute(
                "SELECT MIN(t.created_at) AS t FROM turn t JOIN session s ON s.id = t.session_id"
                " WHERE s.user_id = ?",
                (user_id,),
            ).fetchone()["t"]
        return {
            "schema_version": self.schema_version,
            "sessions": sessions,
            "turns": turns,
            "first_turn_at": first,
        }

    def backup(self, destination: Path | str) -> Path:
        """Write a single self-contained copy, safe to run while in use.

        This exists because copying the database file is not a backup. In WAL
        mode recent writes live in a side file until a checkpoint, so `cp
        hearth.db` can quietly produce an empty database — no error, nothing
        missing until the day it is needed. SQLite's own backup API reads
        through the WAL and produces one complete file.
        """
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        try:
            self.conn.backup(target)
        finally:
            target.close()
        return dest

    def close(self) -> None:
        # Fold the WAL back into the main file so that after a clean exit the
        # one file really is the whole thing.
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        for conn in self._connections:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        self._connections.clear()
        self._local = threading.local()

    def __enter__(self) -> "Store":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
