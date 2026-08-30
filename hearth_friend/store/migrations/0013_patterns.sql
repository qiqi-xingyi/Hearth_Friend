-- Understandings drawn from more than one occasion.
--
-- This is the edge of attribution, and attribution is where being wrong stops
-- being annoying and starts being a relationship problem: three tired evenings
-- can become "he does not want to talk to me", and everything after that is
-- built on it.
--
-- So a pattern carries the memories it was drawn from, and is shown with them.
-- A conclusion you cannot see the evidence for is one you cannot correct.

ALTER TABLE about_you ADD COLUMN source_json TEXT;

-- SQLite cannot alter a CHECK, so the table is rebuilt to admit 'pattern'.
CREATE TABLE about_you_new (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL
                    CHECK (kind IN ('fact', 'preference', 'situation', 'pattern')),
    cues            TEXT NOT NULL,
    statement       TEXT NOT NULL,
    source_turn_id  INTEGER REFERENCES turn (id),
    superseded_by   INTEGER REFERENCES about_you (id),
    retired_at      TEXT,
    created_at      TEXT NOT NULL,
    source_json     TEXT
);

INSERT INTO about_you_new
SELECT id, kind, cues, statement, source_turn_id, superseded_by, retired_at,
       created_at, source_json
  FROM about_you;

DROP TABLE about_you;
ALTER TABLE about_you_new RENAME TO about_you;
CREATE INDEX idx_about_you_live ON about_you (superseded_by, retired_at, id);
