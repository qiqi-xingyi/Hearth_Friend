from __future__ import annotations

from typing import Iterator, Sequence

import pytest

from hearth_friend.persona import Persona
from hearth_friend.providers.base import Message, ProviderError
from hearth_friend.store import Store


class StubProvider:
    """A provider that returns scripted output, so the deterministic layer can be
    tested without a network call."""

    def __init__(self, pieces: Sequence[str] = ("hi",), fail_after: int | None = None):
        self.model_id = "stub"
        self.pieces = list(pieces)
        self.fail_after = fail_after
        self.calls: list[list[Message]] = []

    def generate(self, messages, *, temperature=None) -> str:
        self.calls.append(list(messages))
        return "".join(self.pieces)

    def stream(self, messages, *, temperature=None) -> Iterator[str]:
        self.calls.append(list(messages))
        for index, piece in enumerate(self.pieces):
            if self.fail_after is not None and index >= self.fail_after:
                raise ProviderError("stub failure")
            yield piece


@pytest.fixture
def store(tmp_path) -> Store:
    s = Store(tmp_path / "hearth.db")
    yield s
    s.close()


@pytest.fixture
def persona() -> Persona:
    return Persona(name="Xiaoman", core="A persona used by the tests.",
                   language_register="Short sentences.")


@pytest.fixture
def chinese_persona() -> Persona:
    """The product talks in Chinese, so the tests carry Chinese too.

    Behaviour is asserted in English for readability; this fixture exists so
    that encoding, prompt assembly and storage are exercised against the text
    that will actually be used.
    """
    return Persona(
        name="Xiaoman",
        core="二十六岁，住在杭州，做自由插画。",
        language_register="短句，标点随意。",
        boundaries=("不编造经历",),
    )
