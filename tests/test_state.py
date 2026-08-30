"""The rules by which she moves.

All deterministic, so all directly testable. This is the layer that decides
whether something that happens to her leaves a trace.
"""

from __future__ import annotations

import pytest

from hearth_friend.core.perception import Perception
from hearth_friend.core.state import State, after_perceiving, decayed, describe
from hearth_friend.persona import Persona, Traits


def persona_with(**traits) -> Persona:
    return Persona(name="T", core="c", traits=Traits(**traits))


def test_a_mood_fades_instead_of_becoming_a_trait(persona):
    low = State(mood_valence=-0.8)
    after_an_hour = decayed(low, persona, hours=1)
    after_a_day = decayed(low, persona, hours=24)

    assert low.mood_valence < after_an_hour.mood_valence < after_a_day.mood_valence
    assert after_a_day.mood_valence == pytest.approx(persona.traits.baseline_mood, abs=0.05)


def test_warmth_decides_how_far_your_feeling_carries(persona):
    upset = Perception(valence=-0.9, emotion_intensity=0.9, salience=0.8)
    start = State()

    warm = after_perceiving(start, upset, persona_with(warmth=0.9, volatility=0.5))
    cool = after_perceiving(start, upset, persona_with(warmth=0.1, volatility=0.5))

    assert warm.mood_valence < cool.mood_valence


def test_volatility_decides_how_fast_she_moves_at_all(persona):
    good_news = Perception(valence=0.9, emotion_intensity=0.9, salience=0.8)
    start = State()

    quick = after_perceiving(start, good_news, persona_with(volatility=0.9))
    slow = after_perceiving(start, good_news, persona_with(volatility=0.05))

    assert quick.mood_valence > slow.mood_valence


def test_attention_follows_what_matters_rather_than_being_constant(persona):
    """Uniform attention is what reads as going through the motions. If a big
    thing and a small thing land the same, nothing she does carries a signal."""
    start = State(engagement=0.3)
    big = after_perceiving(start, Perception(salience=0.95), persona)
    small = after_perceiving(start, Perception(salience=0.05), persona)

    assert big.engagement > start.engagement > small.engagement


def test_something_not_addressed_to_her_pulls_her_in_less(persona):
    start = State(engagement=0.3)
    to_her = after_perceiving(start, Perception(salience=0.8, about_her=True), persona)
    past_her = after_perceiving(start, Perception(salience=0.8, about_her=False), persona)

    assert to_her.engagement > past_her.engagement


def test_talking_costs_energy(persona):
    start = State(energy=0.8)
    assert after_perceiving(start, Perception(), persona).energy < start.energy


def test_state_stays_in_range_under_repeated_extremes(persona):
    state = State()
    hammer = Perception(valence=-1.0, emotion_intensity=1.0, salience=1.0)
    for _ in range(200):
        state = after_perceiving(state, hammer, persona_with(warmth=1.0, volatility=1.0))

    assert -1.0 <= state.mood_valence <= 1.0
    assert 0.0 <= state.mood_arousal <= 1.0
    assert 0.0 <= state.engagement <= 1.0
    assert 0.0 <= state.energy <= 1.0


def test_she_describes_her_condition_in_words_not_numbers(persona):
    text = describe(State(mood_valence=-0.8, energy=0.2, engagement=0.1))
    assert "心情不太好" in text and "累" in text
    assert not any(ch.isdigit() for ch in text)


def test_attention_rises_fast_and_lets_go_slowly(persona):
    """Found by running it: with symmetric adaptation, one throwaway message
    undid a confidence, and she was distracted moments after being told
    something that mattered."""
    state = State(engagement=0.2)
    confided_in = after_perceiving(state, Perception(salience=0.9), persona)
    then_small_talk = after_perceiving(confided_in, Perception(salience=0.05), persona)

    assert confided_in.engagement > 0.45, "a heavy message must land"
    assert then_small_talk.engagement > confided_in.engagement * 0.8, (
        "one light message must not undo it"
    )
