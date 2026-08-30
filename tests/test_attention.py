"""What comes to mind.

Not the attention inside the model -- that already happens over whatever we put
in the context. This is the layer deciding what goes in: the same shape as
attention, done as arithmetic rather than as a layer, and deliberately noisy.
"""

from __future__ import annotations

import random

from hearth_friend.core.attention import attend, cosine, temperature_for
from hearth_friend.providers.embedding import pack, unpack

QUERY = [1.0, 0.0, 0.0]
KEYS = [
    [1.0, 0.0, 0.0],   # 0 exactly on topic
    [0.8, 0.6, 0.0],   # 1 close
    [0.0, 1.0, 0.0],   # 2 unrelated
    [0.0, 0.0, 1.0],   # 3 unrelated
]


def counts(temperature: float, trials: int = 400) -> list[int]:
    tally = [0] * len(KEYS)
    for seed in range(trials):
        for index in attend(
            QUERY, KEYS, k=2, temperature=temperature, rng=random.Random(seed)
        ):
            tally[index] += 1
    return tally


def test_attention_is_focused_when_she_is():
    focused = counts(temperature_for(engagement=0.9, energy=0.9))
    assert focused[0] > 380 and focused[1] > 380
    assert focused[2] + focused[3] < 40


def test_attention_wanders_when_she_is_not():
    """Uniform attention reads as indifference. Something has to make being
    distracted look different from being interested."""
    scattered = counts(temperature_for(engagement=0.05, energy=0.2))
    assert scattered[2] + scattered[3] > 150, "should wander"
    assert scattered[0] > scattered[2], "but still lean the right way"


def test_being_distracted_is_a_higher_temperature_than_being_engaged():
    assert temperature_for(0.9, 0.9) < temperature_for(0.1, 0.3)


def test_what_is_chosen_is_sampled_but_what_is_shown_is_ordered():
    """The draw order carries no meaning, and leading with the least relevant
    of what she thought of buries the point."""
    picked = attend(QUERY, KEYS, k=3, temperature=1.5, rng=random.Random(7))
    scores = [cosine(QUERY, KEYS[i]) for i in picked]
    assert scores == sorted(scores, reverse=True)


def test_the_same_moment_does_not_always_surface_the_same_thing():
    seen = {
        tuple(attend(QUERY, KEYS, k=2, temperature=1.2, rng=random.Random(s)))
        for s in range(60)
    }
    assert len(seen) > 1


def test_asking_for_more_than_exists_returns_what_exists():
    assert len(attend(QUERY, KEYS, k=99, temperature=0.5)) == len(KEYS)


def test_nothing_to_attend_to_is_not_an_error():
    assert attend(QUERY, [], k=3, temperature=0.5) == []


def test_a_vector_survives_the_round_trip_through_the_database():
    vector = [0.125, -0.5, 0.75]
    assert unpack(pack(vector)) == vector
