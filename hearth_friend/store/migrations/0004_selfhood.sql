-- What is true about her.
--
-- Asked six times whether she plays a particular game, she gave six different
-- answers: owns a console, never owned one, played it on a PC, it gathers dust.
-- Nothing about her survived the sentence it was said in, because every answer
-- was invented at the moment of asking rather than recalled.
--
-- These rows are what she can recall about herself. They are derived -- most of
-- them come from things she has already said, and they carry the turn they came
-- from -- so the table can be dropped and rebuilt from the log.

CREATE TABLE self_fact (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    kind           TEXT NOT NULL CHECK (kind IN ('fact', 'view', 'dislike', 'unsure')),
    cues           TEXT NOT NULL,   -- words that should bring this to mind
    statement      TEXT NOT NULL,   -- in her own voice, first person
    source_turn_id INTEGER REFERENCES turn (id),
    superseded_by  INTEGER REFERENCES self_fact (id),
    created_at     TEXT NOT NULL
);

CREATE INDEX idx_self_fact_live ON self_fact (superseded_by, id);
