from __future__ import annotations

from typing import Iterator, Sequence

import pytest

from hearth_friend.persona import Persona
from hearth_friend.providers.base import Message, ProviderError
from hearth_friend.store import Store


class StubProvider:
    """A provider that returns scripted output, so the deterministic layer can
    be tested without a network call.

    Each entry in `messages` becomes one of her messages: the runtime splits on
    newlines, so the stub joins with them.
    """

    def __init__(self, messages: Sequence[str] = ("hi",), fail: bool = False):
        self.model_id = "stub"
        self.messages = list(messages)
        self.fail = fail
        self.calls: list[list[Message]] = []

    def generate(self, messages, *, temperature=None) -> str:
        self.calls.append(list(messages))
        if self.fail:
            raise ProviderError("stub failure")
        return "\n".join(self.messages)

    def stream(self, messages, *, temperature=None) -> Iterator[str]:
        yield self.generate(messages, temperature=temperature)


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
