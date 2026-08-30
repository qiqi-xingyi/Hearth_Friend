-- Facts that have to be in front of her whether or not anything reminded her.
--
-- Asked how she was doing she said she felt tired, which she had recorded that
-- she cannot be. The cues on that entry were 身体 累 困 饿; the question was
-- 你状态怎么样, which matches none of them, so the entry was never recalled.
-- The trigger word was in her answer, not in his question.
--
-- Cue-triggered recall can only fire on what is in front of it. A boundary has
-- to hold when nothing raised the subject.

ALTER TABLE self_fact ADD COLUMN always_on INTEGER NOT NULL DEFAULT 0;
