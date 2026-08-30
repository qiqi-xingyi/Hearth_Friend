from __future__ import annotations

import pytest

from hearth_friend.core import system_prompt
from hearth_friend.persona import Persona, PersonaError


def test_shipped_personas_load_and_differ():
    warm = Persona.load("persona/example.yaml")
    quiet = Persona.load("persona/quiet.yaml")

    assert warm.name != quiet.name
    assert system_prompt(warm) != system_prompt(quiet)
    for persona in (warm, quiet):
        assert persona.core
        assert persona.boundaries


def test_missing_file_says_what_to_do(tmp_path):
    with pytest.raises(PersonaError, match="not found"):
        Persona.load(tmp_path / "nope.yaml")


def test_required_fields_are_checked(tmp_path):
    path = tmp_path / "p.yaml"
    path.write_text("persona:\n  name: Xiaoman\n", encoding="utf-8")
    with pytest.raises(PersonaError, match="missing required field"):
        Persona.load(path)


def test_boundaries_reach_the_prompt(persona):
    with_boundaries = Persona(
        name=persona.name, core=persona.core, boundaries=("never invent experiences",)
    )
    assert "never invent experiences" in system_prompt(with_boundaries)


def test_chinese_persona_reaches_the_prompt(chinese_persona):
    """Persona files are written in Chinese, so verify that text survives
    prompt assembly rather than assuming it does."""
    prompt = system_prompt(chinese_persona)
    assert "二十六岁，住在杭州" in prompt
    assert "短句，标点随意。" in prompt
    assert "不编造经历" in prompt
