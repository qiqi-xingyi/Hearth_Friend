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


def hours_between(timestamp: str | None, *, now: datetime | None = None) -> float:
    """Elapsed hours, treating a missing timestamp as no time at all."""
    if not timestamp:
        return 0.0
    now = now or datetime.now(timezone.utc)
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return 0.0
    return max(0.0, (now - then).total_seconds() / 3600.0)


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

    def session_turns(self, session_id: int) -> list[Turn]:
        rows = self.conn.execute(
            "SELECT id, session_id, role, content, created_at FROM turn"
            " WHERE session_id = ? ORDER BY id",
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

    # -------------------------------------------------------------- memory

    def add_about_you(
        self,
        kind: str,
        cues: str,
        statement: str,
        *,
        source_turn_id: int | None = None,
        source_memory_ids: list[int] | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO about_you (kind, cues, statement, source_turn_id, created_at,"
            "                       source_json)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                kind,
                cues,
                statement,
                source_turn_id,
                utcnow(),
                json.dumps(source_memory_ids, ensure_ascii=False)
                if source_memory_ids
                else None,
            ),
        )
        return int(cur.lastrowid)

    def log_refusal(self, kind: str, text: str, reason: str) -> None:
        """Something the floor would not let become a belief. Recorded, because
        a guard whose effect cannot be seen cannot be corrected."""
        self.conn.execute(
            "INSERT INTO state_change_log (target, key, old_value, new_value,"
            "                              reason, evidence_json, job, created_at)"
            " VALUES ('refused', ?, 0, 0, ?, ?, 'floor', ?)",
            (kind, reason, json.dumps({"text": text}, ensure_ascii=False), utcnow()),
        )

    def refusals(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT key, reason, evidence_json, created_at FROM state_change_log"
            " WHERE target = 'refused' ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def patterns(self) -> list[dict[str, Any]]:
        """What she has concluded, with what she concluded it from."""
        rows = self.conn.execute(
            "SELECT id, statement, source_json, created_at FROM about_you"
            " WHERE kind = 'pattern' AND superseded_by IS NULL AND retired_at IS NULL"
            " ORDER BY id DESC"
        ).fetchall()
        return [dict(row) for row in rows]

    def memories_by_id(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self.conn.execute(
            f"SELECT id, content FROM memory WHERE id IN ({marks})", tuple(ids)
        ).fetchall()
        return [dict(row) for row in rows]

    def recurring_cues(self, minimum: int = 3) -> list[tuple[str, list[int]]]:
        """Cues that keep coming up, with the memories under them.

        Repetition is the only evidence available for a pattern. One occasion is
        an event; three is the beginning of a claim about someone.
        """
        rows = self.conn.execute(
            "SELECT c.cue, GROUP_CONCAT(c.memory_id) AS ids, COUNT(*) AS n"
            "  FROM memory_cue c JOIN memory m ON m.id = c.memory_id"
            " WHERE m.status = 'active'"
            " GROUP BY c.cue HAVING n >= ? ORDER BY n DESC",
            (minimum,),
        ).fetchall()
        return [
            (row["cue"], [int(i) for i in row["ids"].split(",")]) for row in rows
        ]

    def about_you(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, kind, cues, statement FROM about_you"
            " WHERE superseded_by IS NULL AND retired_at IS NULL ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def has_about_you(self, statement: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM about_you WHERE statement = ? LIMIT 1", (statement,)
        ).fetchone()
        return row is not None

    def add_memory(
        self,
        content: str,
        cues: str,
        *,
        importance: float,
        event_time: str | None = None,
        source_turn_ids: list[int] | None = None,
        formative: bool = False,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO memory (content, cues, event_time, importance, strength,"
            "                    source_json, created_at, formative)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                content,
                cues,
                event_time,
                importance,
                importance,  # starts at its own weight and decays from there
                json.dumps(source_turn_ids or [], ensure_ascii=False),
                utcnow(),
                int(formative),
            ),
        )
        memory_id = int(cur.lastrowid)
        for cue in {c for c in cues.split() if c}:
            self.conn.execute(
                "INSERT INTO memory_cue (cue, memory_id) VALUES (?, ?)", (cue, memory_id)
            )
        return memory_id

    def has_memory(self, content: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM memory WHERE content = ? LIMIT 1", (content,)
        ).fetchone()
        return row is not None

    def cue_vocabulary(self) -> list[str]:
        """Every cue anyone has ever been reminded by.

        Grows with the variety of what you talk about, not with how much you
        have talked, which is why the first stage stays cheap.
        """
        return [
            row["cue"] for row in self.conn.execute("SELECT DISTINCT cue FROM memory_cue")
        ]

    def memory_candidates(
        self, cues: list[str], *, per_source: int = 80, limit: int = 200
    ) -> list[dict[str, Any]]:
        """First stage: bounded, indexed, no vectors touched.

        Three ways in -- reminded of it, it happened recently, or it mattered --
        because each alone misses obvious things.
        """
        found: dict[int, dict[str, Any]] = {}
        columns = (
            "id, content, cues, event_time, importance, strength, recall_count,"
            " embedding, embedding_model"
        )

        if cues:
            marks = ",".join("?" * len(cues))
            rows = self.conn.execute(
                f"SELECT {columns} FROM memory WHERE status = 'active' AND id IN ("
                f"  SELECT memory_id FROM memory_cue WHERE cue IN ({marks}))"
                " ORDER BY importance DESC LIMIT ?",
                (*cues, per_source),
            ).fetchall()
            found.update({row["id"]: dict(row) for row in rows})

        for order in ("id DESC", "importance DESC"):
            rows = self.conn.execute(
                f"SELECT {columns} FROM memory WHERE status = 'active'"
                f" ORDER BY {order} LIMIT ?",
                (per_source // 2,),
            ).fetchall()
            for row in rows:
                found.setdefault(row["id"], dict(row))

        return list(found.values())[:limit]

    def forget_pass(self) -> tuple[int, int]:
        """Let time act on what she holds, and on what she has let go.

        Returns (newly forgotten, revived). Forgetting is a status change, never
        a delete: the row stays, because what she can no longer bring to mind is
        not the same as what never happened.
        """
        from hearth_friend.core.forgetting import effective_strength, FORGOTTEN_BELOW

        rows = self.conn.execute(
            "SELECT id, importance, strength, status,"
            "       COALESCE(last_recalled_at, created_at) AS since"
            "  FROM memory WHERE status IN ('active', 'forgotten')"
            "   AND formative = 0"
        ).fetchall()

        forgotten, revived = [], []
        for row in rows:
            hours = hours_between(row["since"])
            live = effective_strength(row["strength"], row["importance"], hours)
            if row["status"] == "active" and live < FORGOTTEN_BELOW:
                forgotten.append(row["id"])
            elif row["status"] == "forgotten" and live >= FORGOTTEN_BELOW:
                revived.append(row["id"])

        for ids, status in ((forgotten, "forgotten"), (revived, "active")):
            if ids:
                marks = ",".join("?" * len(ids))
                self.conn.execute(
                    f"UPDATE memory SET status = ? WHERE id IN ({marks})", (status, *ids)
                )
        return len(forgotten), len(revived)

    def revive_memories(self, memory_ids: list[int]) -> int:
        """Bring something back because the cue was direct enough.

        People do this. Something you had not thought about in years surfaces
        whole when the right thing is said, and there is no reason she should be
        the one who cannot.
        """
        if not memory_ids:
            return 0
        marks = ",".join("?" * len(memory_ids))
        cur = self.conn.execute(
            f"UPDATE memory SET status = 'active', strength = MAX(strength, 0.4),"
            f"  last_recalled_at = ? WHERE id IN ({marks}) AND status = 'forgotten'",
            (utcnow(), *memory_ids),
        )
        return cur.rowcount

    def forgotten_matching(self, cues: list[str], limit: int = 3) -> list[int]:
        """Forgotten rows a direct cue reaches."""
        if not cues:
            return []
        marks = ",".join("?" * len(cues))
        rows = self.conn.execute(
            f"SELECT DISTINCT m.id FROM memory m"
            f"  JOIN memory_cue c ON c.memory_id = m.id"
            f" WHERE m.status = 'forgotten' AND c.cue IN ({marks})"
            f" ORDER BY m.importance DESC LIMIT ?",
            (*cues, limit),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def formative_memories(self) -> list[dict[str, Any]]:
        """What does not fade, and is always in reach."""
        rows = self.conn.execute(
            "SELECT id, content, event_time FROM memory"
            " WHERE formative = 1 AND status != 'superseded' ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def touch_memories(self, memory_ids: list[int]) -> None:
        """Recalling something makes it stick a little harder.

        Diminishing, so that a thing which keeps coming up cannot ratchet itself
        into permanence.
        """
        if not memory_ids:
            return
        marks = ",".join("?" * len(memory_ids))
        self.conn.execute(
            f"UPDATE memory SET recall_count = recall_count + 1,"
            f"  last_recalled_at = ?,"
            f"  strength = MIN(1.0, strength + 0.1 * (1.0 - strength))"
            f" WHERE id IN ({marks})",
            (utcnow(), *memory_ids),
        )

    # ------------------------------------------------------------- vectors

    def set_embedding(self, table: str, row_id: int, blob: bytes, model: str) -> None:
        if table not in ("reading", "curiosity", "memory"):
            raise ValueError(f"no embeddings on {table!r}")
        self.conn.execute(
            f"UPDATE {table} SET embedding = ?, embedding_model = ? WHERE id = ?",
            (blob, model, row_id),
        )

    def rows_needing_embedding(
        self, table: str, model: str, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Rows with no vector, or one made by a different model.

        The second case is why the model is recorded per row: changing it
        invalidates every vector, and there is otherwise no way to recompute
        only what needs it.
        """
        if table not in ("reading", "curiosity", "memory"):
            raise ValueError(f"no embeddings on {table!r}")
        text = {
            "reading": "title || ' ' || COALESCE(summary, '')",
            "curiosity": "question",
            "memory": "content || ' ' || cues",
        }[table]
        rows = self.conn.execute(
            f"SELECT id, {text} AS text FROM {table}"
            " WHERE embedding IS NULL OR embedding_model IS NOT ?"
            " ORDER BY id DESC LIMIT ?",
            (model, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def embedded_reading(self, model: str, limit: int = 60) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT source, url, title, summary, read_at, embedding FROM reading"
            " WHERE embedding IS NOT NULL AND embedding_model = ?"
            " ORDER BY id DESC LIMIT ?",
            (model, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------ curiosity

    def session_salience(self, session_id: int) -> float:
        """How much happened, by her reckoning.

        Curiosity fires on accumulated weight rather than on a timer, so a
        session where nothing much was said produces none.
        """
        row = self.conn.execute(
            "SELECT COALESCE(SUM(p.salience), 0) AS total FROM perception p"
            "  JOIN turn t ON t.id = p.turn_id"
            " WHERE t.session_id = ?",
            (session_id,),
        ).fetchone()
        return float(row["total"] or 0.0)

    def add_curiosity(
        self,
        question: str,
        cues: str,
        *,
        source_turn_id: int | None = None,
        rejected_reason: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO curiosity (question, cues, source_turn_id, created_at,"
            "                       rejected_reason)"
            " VALUES (?, ?, ?, ?, ?)",
            (question, cues, source_turn_id, utcnow(), rejected_reason),
        )
        return int(cur.lastrowid)

    def open_curiosity(self, limit: int = 4) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, question, cues, created_at FROM curiosity"
            " WHERE resolved_at IS NULL AND rejected_reason IS NULL"
            " ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def rejected_curiosity(self, limit: int = 20) -> list[dict[str, Any]]:
        """Kept and readable. A guard whose effect you cannot see is one you
        cannot tell is too tight."""
        rows = self.conn.execute(
            "SELECT id, question, rejected_reason, created_at FROM curiosity"
            " WHERE rejected_reason IS NOT NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def has_curiosity(self, question: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM curiosity WHERE question = ? LIMIT 1", (question,)
        ).fetchone()
        return row is not None

    # -------------------------------------------------------------- reading

    def add_reading(
        self, source: str, url: str, title: str, summary: str, published: str
    ) -> bool:
        """Record something she read. Returns False if she had already seen it."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO reading (source, url, title, summary, published,"
            "                               read_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (source, url, title, summary, published, utcnow()),
        )
        return cur.rowcount > 0

    def recent_reading(
        self, limit: int = 12, per_source: int = 3
    ) -> list[dict[str, Any]]:
        """A few from each source, not the newest overall.

        Sources are fetched one after another, so ordering by recency alone
        hands every slot to whichever was fetched last: five sources went in and
        only the fifth was ever in front of her.
        """
        rows = self.conn.execute(
            "SELECT source, url, title, summary, read_at FROM ("
            "  SELECT *, ROW_NUMBER() OVER ("
            "    PARTITION BY source ORDER BY id DESC) AS rn FROM reading)"
            " WHERE rn <= ? ORDER BY rn, id DESC LIMIT ?",
            (per_source, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def last_read_at(self) -> str | None:
        row = self.conn.execute("SELECT MAX(read_at) AS t FROM reading").fetchone()
        return row["t"]

    # ------------------------------------------------------------- selfhood

    def self_facts(self) -> list[dict[str, Any]]:
        """Everything currently true about her."""
        rows = self.conn.execute(
            "SELECT id, kind, cues, statement, always_on FROM self_fact"
            " WHERE superseded_by IS NULL AND retired_at IS NULL ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]

    def add_self_fact(
        self,
        kind: str,
        cues: str,
        statement: str,
        *,
        source_turn_id: int | None = None,
        always_on: bool = False,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO self_fact (kind, cues, statement, source_turn_id, created_at,"
            "                       always_on)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (kind, cues, statement, source_turn_id, utcnow(), int(always_on)),
        )
        return int(cur.lastrowid)

    def supersede_self_fact(self, old_id: int, new_id: int) -> None:
        """Kept rather than deleted: that she used to think otherwise is part of
        the record, and is the only way a change in her is ever visible."""
        self.conn.execute(
            "UPDATE self_fact SET superseded_by = ? WHERE id = ?", (new_id, old_id)
        )

    def retire_self_fact(self, fact_id: int) -> None:
        """Stop recalling something without pretending it was never true."""
        self.conn.execute(
            "UPDATE self_fact SET retired_at = ? WHERE id = ?", (utcnow(), fact_id)
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
