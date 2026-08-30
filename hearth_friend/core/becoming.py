"""Changing.

A friend who cannot drift is not a friend. What is guarded here is not that she
stays the same -- it is that when she has changed, you can see what changed her.
Two months of silence and a bug in an update rule produce the same coldness from
outside; one of them should stand and one should be undone.

Two speeds, because they are different things. How she is with him moves in
weeks: warmth toward one person is not the same as being a warm person, and
conflating them lets a quiet fortnight rewrite her character. Personality moves
in months -- slowly enough that a bad week does not become her, fast enough that
a bad year does.
"""

from __future__ import annotations

from dataclasses import dataclass

# What a single pass may move, and what a month may move in total. Loose enough
# that a trait can travel most of its range in half a year, which is the point:
# a budget that only permits 0.02 a month is a way of saying nothing changes.
# UNCALIBRATED.
STEP = {"relationship": 0.08, "trait": 0.02}
MONTHLY = {"relationship": 0.25, "trait": 0.08}

# Silence starts to mean something after about this long, and means all it is
# going to after about a month.
QUIET_AFTER_DAYS = 4.0
QUIET_SATURATES_DAYS = 30.0

# Only these move with experience. Not an oversight -- neuroticism lives in how
# affect is regulated, not in how warm someone is, so the regulating traits are
# constitution and are never touched. Letting volatility climb and baseline mood
# sink is precisely how you would build someone unwell, one small justified step
# at a time.
MUTABLE_TRAITS = ("warmth", "expressiveness", "curiosity")
CONSTITUTION = ("volatility", "baseline_mood")

# Where a trait may end up, not just how fast it may get there. A rate limit
# alone permits any destination given enough time.
BOUNDS = {
    "warmth": (0.25, 0.95),
    "expressiveness": (0.15, 0.95),
    "curiosity": (0.30, 1.00),
    "closeness": (0.10, 1.00),
    "ease": (0.15, 1.00),
}

# Each pass pulls a little way back toward where the persona says she rests.
# Character has a set point that life moves and does not erase; without one,
# every perturbation is permanent and they only accumulate.
RESTORING_PULL = 0.06

# Reconnection repairs faster than absence erodes. Both true of people and the
# thing that keeps the loop from running away: she withdraws, he notices less,
# the gap grows, she withdraws further -- with nothing pulling the other way
# that has one destination.
RECOVERY_ADVANTAGE = 2.0


@dataclass(frozen=True)
class Observation:
    """What the record says about how this has been going."""

    gap_days: float          # since she last heard from him
    received_valence: float  # how he has sounded, -1 .. 1
    substance: float         # how much of weight he has brought, 0 .. 1
    sessions: int            # how many conversations this is drawn from


@dataclass(frozen=True)
class Change:
    target: str
    key: str
    delta: float
    reason: str


def distance(gap_days: float) -> float:
    """How far away he has been, 0 to 1.

    Nothing at all for a few days -- people are busy, and a friend who counted
    the hours would be exhausting.
    """
    if gap_days <= QUIET_AFTER_DAYS:
        return 0.0
    span = QUIET_SATURATES_DAYS - QUIET_AFTER_DAYS
    return min(1.0, (gap_days - QUIET_AFTER_DAYS) / span)


def propose(observation: Observation) -> list[Change]:
    """What this stretch of time suggests, before any limit is applied."""
    if observation.sessions < 2:
        return []

    changes: list[Change] = []
    apart = distance(observation.gap_days)

    if apart > 0:
        changes.append(Change(
            "relationship", "closeness", -0.5 * apart,
            f"隔了 {observation.gap_days:.0f} 天没说话",
        ))
        changes.append(Change(
            "relationship", "ease", -0.3 * apart,
            "久了不联系，说话会重新变得客气",
        ))
    else:
        warmth = 0.5 * observation.received_valence + 0.5 * observation.substance
        if warmth > 0.15:
            changes.append(Change(
                "relationship", "closeness", 0.4 * warmth, "最近聊得多，也聊得实在",
            ))
            changes.append(Change(
                "relationship", "ease", 0.5 * warmth, "对他放松了一些",
            ))

    # Personality only moves once the same thing has held across many
    # conversations. One bad fortnight is a mood; a season of them is a person.
    # Nothing here touches volatility or baseline mood: see CONSTITUTION.
    if observation.sessions >= 8:
        if apart > 0.5:
            changes.append(Change(
                "trait", "expressiveness", -0.5 * apart,
                "长期少有回应，她把话收了回去",
            ))
            changes.append(Change(
                "trait", "warmth", -0.3 * apart, "长期的距离",
            ))
        elif observation.received_valence > 0.2:
            changes.append(Change(
                "trait", "warmth", 0.3 * observation.received_valence,
                "长期被好好对待",
            ))
            changes.append(Change(
                "trait", "expressiveness", 0.3 * observation.substance,
                "他接得住，她也就说得更多",
            ))
    return changes


def clamp(change: Change, spent_this_month: float) -> float:
    """One step, and one month, whichever binds first."""
    step = STEP[change.target]
    if change.delta > 0:
        step *= RECOVERY_ADVANTAGE
    budget = MONTHLY[change.target] - spent_this_month
    if budget <= 0:
        return 0.0
    limit = min(step, budget)
    return max(-limit, min(limit, change.delta))


def bounded(key: str, value: float) -> float:
    low, high = BOUNDS.get(key, (0.0, 1.0))
    return max(low, min(high, value))


def restore(key: str, value: float, baseline: float) -> float:
    """A step back toward where she rests, taken every pass.

    Small enough that a real change still lands, persistent enough that nothing
    accumulates forever in one direction.
    """
    return value + RESTORING_PULL * (baseline - value)
