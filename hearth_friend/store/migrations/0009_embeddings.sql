-- Vectors for the things she can attend over.
--
-- Stored beside the text rather than in a separate store: there are hundreds of
-- rows, not millions, and a dot product over a few hundred vectors is
-- microseconds. A vector database here would be infrastructure in place of a
-- matrix multiply.
--
-- The model is recorded per row because changing it invalidates every vector,
-- and without knowing which rows were made by which model there is no way to
-- recompute only what needs it.

ALTER TABLE reading ADD COLUMN embedding BLOB;
ALTER TABLE reading ADD COLUMN embedding_model TEXT;

ALTER TABLE curiosity ADD COLUMN embedding BLOB;
ALTER TABLE curiosity ADD COLUMN embedding_model TEXT;
