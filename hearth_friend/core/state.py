"""Her internal state, and the rules by which it moves.

The point of this module is that something happens to her and stays happened.
Everything here is deterministic: perception supplies the observation, these
rules decide what it does to her, and the personality traits decide how much.

Nothing here calls a model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from hearth_friend.persona import Persona

# How long it takes an unattended feeling to fall halfway back to baseline.
# UNCALIBRATED: chosen so that a mood survives an evening and not a week.
MOOD_HALF_LIFE_HOURS = 6.0
ENGAGEMENT_HALF_LIFE_HOURS = 1.5
ENERGY_HALF_LIFE_HOURS = 12.0


@dataclass(frozen=True)
class State:
    mood_valence: float = 0.0
    mood_arousal: float = 0.3
    energy: float = 0.7
    engagement: float = 0.3
    focus: str = ""
    updated_at: str = ""

    @classmethod
    def initial(cls, persona: Persona) -> "State":
        return cls(
            mood_valence=persona.traits.baseline_mood,
            mood_arousal=0.3,
            energy=0.7,
            engagement=0.3,
            focus="",
        )


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _decay_toward(current: float, baseline: float, hours: float, half_life: float) -> float:
    """Feelings fade. Without this, one bad evening becomes a permanent trait."""
    if hours <= 0:
        return current
    kept = math.pow(0.5, hours / half_life)
    return baseline + (current - baseline) * kept


def hours_since(timestamp: str | None, *, now: datetime | None = None) -> float:
    if not timestamp:
        return 0.0
    now = now or datetime.now(timezone.utc)
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return 0.0
    return max(0.0, (now - then).total_seconds() / 3600.0)


def decayed(state: State, persona: Persona, *, hours: float) -> State:
    """Where she has drifted to on her own, with nothing happening."""
    return replace(
        state,
        mood_valence=_decay_toward(
            state.mood_valence, persona.traits.baseline_mood, hours, MOOD_HALF_LIFE_HOURS
        ),
        mood_arousal=_decay_toward(state.mood_arousal, 0.3, hours, MOOD_HALF_LIFE_HOURS),
        engagement=_decay_toward(
            state.engagement, 0.2, hours, ENGAGEMENT_HALF_LIFE_HOURS
        ),
        energy=_decay_toward(state.energy, 0.7, hours, ENERGY_HALF_LIFE_HOURS),
    )


def after_perceiving(state: State, perception, persona: Persona) -> State:
    """Apply one perceived message to her.

    Every trait used here changes a number. A trait that changes nothing is not
    a trait, it is a word in a file.
    """
    traits = persona.traits

    # Warmth decides how far someone else's feeling carries into hers.
    # Volatility decides how fast she moves at all.
    pull = perception.valence * perception.emotion_intensity * traits.warmth
    valence = state.mood_valence + traits.volatility * (pull - state.mood_valence)

    arousal = state.mood_arousal + traits.volatility * (
        perception.emotion_intensity - state.mood_arousal
    )

    # Curiosity decides how much a salient message pulls her in. This is what
    # makes attention variable rather than constant, which is what makes
    # attention legible at all.
    # Concave, not linear. Perception is asked to keep most chatter down at
    # 0.1-0.3, so a linear map would leave the top half of her attention
    # permanently unreachable: being told an interview went badly would score
    # 0.4 and barely register. UNCALIBRATED, and the shape matters more than the
    # exact curve.
    target = math.sqrt(perception.salience) * (0.5 + 0.5 * traits.curiosity)
    if not perception.about_her:
        target *= 0.6

    # Asymmetric on purpose. Symmetric adaptation meant that one throwaway line
    # cancelled out having just been told something that mattered, and she was
    # left distracted four messages after someone confided in him. Attention
    # rises quickly and lets go slowly, which is also how it works in people.
    gain = 0.6 if target > state.engagement else 0.12
    engagement = state.engagement + gain * (target - state.engagement)

    # Talking costs something. Without this she is equally fresh forever.
    energy = state.energy - 0.02 * (0.5 + perception.emotion_intensity)

    return replace(
        state,
        mood_valence=_clamp(valence, -1.0, 1.0),
        mood_arousal=_clamp(arousal, 0.0, 1.0),
        engagement=_clamp(engagement, 0.0, 1.0),
        energy=_clamp(energy, 0.0, 1.0),
    )


def describe(state: State) -> str:
    """How she would put her own condition, for the prompt.

    Deliberately coarse. A number in a prompt reads as a number; a person says
    "有点烦" and means it.
    """
    if state.mood_valence > 0.35:
        mood = "心情不错"
    elif state.mood_valence < -0.35:
        mood = "心情不太好"
    elif state.mood_arousal > 0.6:
        mood = "有点绷着"
    else:
        mood = "平平的"

    if state.energy < 0.3:
        energy = "很累，懒得多说"
    elif state.energy < 0.55:
        energy = "有点疲"
    else:
        energy = "精神还行"

    if state.engagement > 0.65:
        attention = "现在挺想聊这个"
    elif state.engagement < 0.25:
        attention = "现在没太进入状态，心不在焉"
    else:
        attention = "在听，但没特别投入"

    parts = [mood, energy, attention]
    if state.focus:
        parts.append(f"最近一直在想：{state.focus}")
    return "，".join(parts) + "。"
