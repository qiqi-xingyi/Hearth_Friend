"""The decision layer.

Every brain has roughly the same language in it. A warm person and a cold one
can both produce a warm sentence; what differs is which one they choose to say,
how much of it, whether they ask anything back, whether they let something
through. That choosing is not a language capability, and it does not need to
live in the weights of a language model.

So it lives here, as its own small set of weights. The model downstream is asked
to render a decision that has already been made -- the way a mouth renders what
a person has decided to say, and is not where their character is kept.

Everything below used to be scattered through the code as constants I picked:
a threshold at 0.25, a gain of 0.6, a temperature between 0.35 and 1.8. Those
numbers were the personality all along, which is the problem with them being
scattered and mine. Collected here, personality is a parameter vector: loaded
from the persona, moved by what happens, written to the audit log, and
eventually learned from the record of what actually worked.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

# What a decision is made from. Everything here is already measured elsewhere;
# nothing new has to be observed for this to run.
FEATURES = (
    "bias",
    "engagement",     # how much she is leaning in
    "energy",
    "mood_valence",
    "closeness",      # how near she feels to him
    "ease",           # how unguarded
    "salience",       # how much this message weighed
    "his_valence",    # how he sounded
    "intensity",
    "about_her",      # was it addressed to her
    "quiet_days",     # how long since he last said anything, scaled
    "his_length",     # how much he wrote, scaled
)

# Heads: what gets decided. Not descriptions of a mood -- things that change
# what is sent.
HEADS = ("speak", "length", "ask", "disclose", "push_back")

# A starting personality, in the only form personality has here. These
# reproduce roughly what the hand-written rules did, so that collecting them
# changes the shape of the code without changing who she is on the day.
# UNCALIBRATED, and openly so: they are a prior to be moved, not a finding.
DEFAULT_WEIGHTS: dict[str, dict[str, float]] = {
    # Almost always speak. Silence is a real option, but not a common one, and
    # a friend who often does not answer is not a friend.
    "speak": {"bias": 3.0, "engagement": 1.0, "energy": 0.5, "about_her": 1.0},
    # How much she says. Driven by her state and by his -- someone who writes
    # one line and gets a paragraph back is talking to a machine.
    "length": {
        "bias": -0.2, "engagement": 1.4, "energy": 0.6, "salience": 0.8,
        "his_length": 0.9, "ease": 0.4,
    },
    # Asking back is not free. She was ending most turns with a question, which
    # is an interview and not a conversation.
    "ask": {
        "bias": -2.0, "engagement": 2.2, "salience": 1.0, "about_her": 0.5,
        "quiet_days": -0.6,
    },
    # Offering something of her own, which takes some ease to do.
    "disclose": {"bias": -2.6, "ease": 2.8, "closeness": 1.4, "engagement": 0.9},
    # Saying so when she does not agree. Needs to be possible, or warmth means
    # nothing; needs ease, because disagreeing with someone you are guarded
    # around is not what people do.
    "push_back": {"bias": -3.0, "ease": 2.6, "closeness": 1.2, "his_valence": -0.5},
}

# Attention is part of the same decision: how sharply she is looking at what she
# knows. Kept as its own small mapping rather than a head, since it is a scalar
# the retrieval layer consumes directly.
TEMPERATURE = {"focused": 0.35, "scattered": 1.8}


@dataclass(frozen=True)
class Parameters:
    """The personality, as numbers that do something."""

    weights: dict[str, dict[str, float]] = field(
        default_factory=lambda: {h: dict(w) for h, w in DEFAULT_WEIGHTS.items()}
    )
    temperature: dict[str, float] = field(default_factory=lambda: dict(TEMPERATURE))

    def score(self, head: str, features: dict[str, float]) -> float:
        row = self.weights.get(head, {})
        return sum(row.get(name, 0.0) * features.get(name, 0.0) for name in FEATURES)

    def merged(self, overrides: dict) -> "Parameters":
        weights = {h: dict(w) for h, w in self.weights.items()}
        for head, row in (overrides or {}).items():
            if head in weights and isinstance(row, dict):
                for name, value in row.items():
                    if name in FEATURES:
                        weights[head][name] = float(value)
        return Parameters(weights, dict(self.temperature))


@dataclass(frozen=True)
class Decision:
    speak: bool
    length: float            # 0 .. 1
    ask: bool
    disclose: bool
    push_back: bool
    temperature: float
    scores: dict[str, float]


def logistic(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, x))))


def features_from(state, perception, relationship, quiet_days: float, his_length: int
                  ) -> dict[str, float]:
    """Everything the decision is allowed to see, on a comparable scale."""
    return {
        "bias": 1.0,
        "engagement": state.engagement,
        "energy": state.energy,
        "mood_valence": state.mood_valence,
        "closeness": relationship.get("closeness", 0.3),
        "ease": relationship.get("ease", 0.4),
        "salience": getattr(perception, "salience", 0.2),
        "his_valence": getattr(perception, "valence", 0.0),
        "intensity": getattr(perception, "emotion_intensity", 0.2),
        "about_her": 1.0 if getattr(perception, "about_her", True) else 0.0,
        "quiet_days": min(1.0, quiet_days / 14.0),
        "his_length": min(1.0, his_length / 120.0),
    }


def decide(
    parameters: Parameters,
    features: dict[str, float],
    *,
    rng: random.Random | None = None,
) -> Decision:
    """Sampled, not thresholded.

    A decision taken at a threshold is the same decision every time the inputs
    are the same, which is a lookup table wearing a personality. Sampling from
    the probability gives what a person has: usually asks when interested,
    sometimes does not.
    """
    rng = rng or random.Random()
    scores = {head: parameters.score(head, features) for head in HEADS}

    attention = max(0.0, min(1.0, 0.75 * features["engagement"] + 0.25 * features["energy"]))
    low, high = parameters.temperature["focused"], parameters.temperature["scattered"]

    return Decision(
        speak=rng.random() < logistic(scores["speak"]),
        length=logistic(scores["length"]),
        ask=rng.random() < logistic(scores["ask"]),
        disclose=rng.random() < logistic(scores["disclose"]),
        push_back=rng.random() < logistic(scores["push_back"]),
        temperature=high + (low - high) * attention,
        scores=scores,
    )
