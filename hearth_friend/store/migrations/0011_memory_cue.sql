-- The first stage of recall.
--
-- Attention over every vector in the table is bounded by how much has ever
-- happened, which is the wrong thing to be bounded by. This index makes the
-- first stage cost depend on the size of the cue vocabulary instead -- which
-- grows far more slowly than the number of memories, because people keep
-- talking about the same handful of things.

CREATE TABLE memory_cue (
    cue       TEXT NOT NULL,
    memory_id INTEGER NOT NULL REFERENCES memory (id)
);

CREATE INDEX idx_memory_cue_lookup ON memory_cue (cue, memory_id);
