-- Whether what she said in a session has been folded back into what is true
-- about her. Marked rather than inferred, so that a session interrupted by a
-- crash is picked up on the next launch instead of being silently skipped.

ALTER TABLE session ADD COLUMN extracted_at TEXT;
