"""What comes to mind.

Not the attention inside the model -- that is already happening, over whatever
we put in the context. This is the layer that decides what goes in, which is the
same shape (a query, a set of keys, a selection) implemented as arithmetic
rather than as a layer.

Two departures from the textbook version, both deliberate:

Selection is hard, not soft. The consumer is a language model reading text, and
there is no meaning in 0.3 of one memory plus 0.7 of another.

Selection is sampled, not top-k. Attention that is deterministic surfaces the
same thing every time a subject comes near, which reads as a lookup table.
Sampling gives what a person has: this occurs to her now, something else occurs
to her later. The temperature is her state -- focused when she is engaged,
scattered when she is not -- which is what makes "she is a bit distracted today"
a mechanism instead of a description.
"""

from __future__ import annotations

import math
import random
from typing import Sequence

# Focused at one end, wandering at the other. UNCALIBRATED.
TEMPERATURE_FOCUSED = 0.35
TEMPERATURE_SCATTERED = 1.8


def temperature_for(engagement: float, energy: float = 1.0) -> float:
    """How sharply she is attending. Low is pointed, high is diffuse."""
    attention = max(0.0, min(1.0, 0.75 * engagement + 0.25 * energy))
    return TEMPERATURE_SCATTERED + (TEMPERATURE_FOCUSED - TEMPERATURE_SCATTERED) * attention


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _standardise(scores: list[float]) -> list[float]:
    """Within the candidate set, so temperature means the same thing whether the
    scores happen to sit in a wide band or a narrow one."""
    if len(scores) < 2:
        return [0.0] * len(scores)
    mean = sum(scores) / len(scores)
    variance = sum((s - mean) ** 2 for s in scores) / len(scores)
    spread = math.sqrt(variance) or 1.0
    return [(s - mean) / spread for s in scores]


def attend(
    query: Sequence[float],
    keys: Sequence[Sequence[float]],
    *,
    k: int,
    temperature: float,
    rng: random.Random | None = None,
) -> list[int]:
    """Indices of what comes to mind, most strongly first."""
    if not keys or k <= 0:
        return []
    rng = rng or random.Random()

    scores = _standardise([cosine(query, key) for key in keys])
    weights = [math.exp(s / max(temperature, 1e-6)) for s in scores]

    chosen: list[int] = []
    remaining = list(range(len(keys)))
    for _ in range(min(k, len(remaining))):
        total = sum(weights[i] for i in remaining)
        if total <= 0:
            chosen.extend(remaining[: k - len(chosen)])
            break
        draw = rng.random() * total
        running = 0.0
        for index in remaining:
            running += weights[index]
            if running >= draw:
                chosen.append(index)
                remaining.remove(index)
                break

    # Which ones is sampled; the order they are presented in is not. The draw
    # order carries no meaning, and putting the least relevant of them first
    # buries the thing she actually thought of.
    chosen.sort(key=lambda i: -scores[i])
    return chosen
