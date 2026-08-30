-- Retiring something she used to hold.
--
-- Distinct from supersession: superseded means she changed her mind and there
-- is a newer version, retired means the thing stopped applying at all -- as
-- when a persona that had a body was replaced by one that does not, and
-- "doesn't eat coriander" stopped being about anyone.
--
-- Kept rather than deleted. That she used to be described this way is part of
-- the record, and deleting it would make the change invisible.

ALTER TABLE self_fact ADD COLUMN retired_at TEXT;
