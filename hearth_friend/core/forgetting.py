"""Forgetting.

Decay, not deletion. A memory that drops out of reach stays in the table: what
she can no longer bring to mind is not the same as what never happened, and the
row is the only place the difference is recorded.

Strength is stored as its value at the moment it was last reinforced, and the
decay is computed from the elapsed time rather than written back. A stored,
repeatedly-decayed number drifts with how often the pass happens to run; this
way the answer depends only on the clock.

Important things last longer. That is the whole point of scoring importance at
all -- otherwise every memory fades at the same rate and being told something
that mattered is worth no more than being told the weather.
"""

from __future__ import annotations

import math

# How long the least and the most important things take to fade halfway.
# Interpolated geometrically between them, because the distance between
# small talk and something that mattered is orders of magnitude and not a
# factor of two: a linear scale had a 0.9 memory gone in three months.
# UNCALIBRATED -- the shape is the claim, the numbers are a guess.
MIN_HALF_LIFE_DAYS = 2.0
MAX_HALF_LIFE_DAYS = 730.0

# Below this it stops coming to mind on its own. Not gone -- a direct enough
# cue can still reach it.
FORGOTTEN_BELOW = 0.05


def half_life_hours(importance: float) -> float:
    """Something that mattered fades more slowly -- by a lot, not by a little."""
    weight = max(0.0, min(1.0, importance))
    days = MIN_HALF_LIFE_DAYS * math.pow(
        MAX_HALF_LIFE_DAYS / MIN_HALF_LIFE_DAYS, weight
    )
    return days * 24.0


def effective_strength(strength: float, importance: float, hours: float) -> float:
    """How strongly it comes to mind now, given how long it has been."""
    if hours <= 0:
        return strength
    return strength * math.pow(0.5, hours / half_life_hours(importance))


def is_forgotten(strength: float, importance: float, hours: float) -> bool:
    return effective_strength(strength, importance, hours) < FORGOTTEN_BELOW
