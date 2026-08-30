-- Which of your messages a reply of hers actually covered.
--
-- "Everything since she last spoke" is the wrong definition of unanswered once
-- messages interleave: something you send while she is composing lands before
-- her reply does, and would be counted as answered by a reply that never saw
-- it. What matters is not the order the rows landed in but how far she had
-- read, so that is recorded rather than inferred.

ALTER TABLE turn ADD COLUMN answers_through INTEGER;
