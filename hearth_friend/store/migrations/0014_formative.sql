-- Things that do not fade.
--
-- Decay scaled by importance is still decay: at the top of the scale a memory
-- had a half-life of about a year, so given long enough it went too. That is
-- wrong about people. Who your parents are, where you studied, the year
-- something broke, the thing you finally managed -- these do not have a
-- half-life. They are not remembered harder than other things, they are held
-- differently.
--
-- Marked at the time rather than inferred later: importance is how much
-- something weighed when it happened, and this is whether it became part of
-- who he is.

ALTER TABLE memory ADD COLUMN formative INTEGER NOT NULL DEFAULT 0;
