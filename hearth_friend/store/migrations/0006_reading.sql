-- What she has actually read.
--
-- Without a body she has no invented life to draw on, which is the point of
-- being honest about what she is -- but it leaves her with nothing at all
-- unless she can reach the world she can actually reach. Asked what she does,
-- she said she had been reading about memory and time. She had not read
-- anything. A claim about her inner life should be checkable against a row.

CREATE TABLE reading (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    source     TEXT NOT NULL,
    url        TEXT NOT NULL UNIQUE,
    title      TEXT NOT NULL,
    summary    TEXT,
    published  TEXT,
    read_at    TEXT NOT NULL
);

CREATE INDEX idx_reading_read_at ON reading (read_at DESC);
