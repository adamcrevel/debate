"""Tests for persona system-prompt builders in `debate.agents`."""

import pytest

from debate.agents import (
    build_debater_system_prompt,
    build_host_system_prompt,
    build_judge_system_prompt,
)

TOPIC = "Remote work should be the default for knowledge workers"

SIDES = ["FOR", "AGAINST"]
ROLES = ["Lead", "Researcher", "Rebuttal"]

_ROLE_KEYWORDS = {
    "Lead": ["opening", "closing"],
    "Researcher": ["evidence brief"],
    "Rebuttal": ["rebuttal loop"],
}


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("role", ROLES)
def test_debater_prompt_names_side(side: str, role: str) -> None:
    """Each debater prompt must identify the agent's side."""
    prompt = build_debater_system_prompt(side, role, TOPIC)
    assert side in prompt


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("role", ROLES)
def test_debater_prompt_names_role_instruction(side: str, role: str) -> None:
    """Each debater prompt must mention its role-specific duty."""
    prompt = build_debater_system_prompt(side, role, TOPIC).lower()
    for keyword in _ROLE_KEYWORDS[role]:
        assert keyword in prompt


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("role", ROLES)
def test_debater_prompt_has_word_limit(side: str, role: str) -> None:
    """Each debater prompt must instruct a 120-word answer cap."""
    prompt = build_debater_system_prompt(side, role, TOPIC)
    assert "120 words" in prompt


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("role", ROLES)
def test_debater_prompt_prefers_web_search(side: str, role: str) -> None:
    """Each debater prompt must instruct preferring verified web search."""
    prompt = build_debater_system_prompt(side, role, TOPIC).lower()
    assert "web search" in prompt
    assert "unverified" in prompt


@pytest.mark.parametrize("side", SIDES)
@pytest.mark.parametrize("role", ROLES)
def test_debater_prompt_includes_topic(side: str, role: str) -> None:
    """Each debater prompt must interpolate the debate's topic."""
    prompt = build_debater_system_prompt(side, role, TOPIC)
    assert TOPIC in prompt


def test_debater_prompt_distinguishes_roles() -> None:
    """A Lead prompt must not claim the Researcher's or Rebuttal's duty."""
    lead_prompt = build_debater_system_prompt("FOR", "Lead", TOPIC).lower()
    assert "evidence brief" not in lead_prompt
    assert "rebuttal loop" not in lead_prompt


def test_judge_prompt_mentions_verdict_rationale_and_citations() -> None:
    """The Judge prompt must mention verdict, rationale, and citing turns."""
    prompt = build_judge_system_prompt(TOPIC).lower()
    assert "verdict" in prompt
    assert "rationale" in prompt
    assert "stage" in prompt
    assert "side" in prompt


def test_judge_prompt_states_not_on_either_team() -> None:
    """The Judge prompt must state the Judge is not on either team."""
    prompt = build_judge_system_prompt(TOPIC).lower()
    assert "not a member of either team" in prompt


def test_judge_prompt_allows_draw() -> None:
    """The Judge prompt must allow declaring a draw."""
    prompt = build_judge_system_prompt(TOPIC).lower()
    assert "draw" in prompt

def test_judge_prompt_has_word_limit() -> None:
    """The Judge prompt must instruct a 120-word answer cap."""
    prompt = build_judge_system_prompt(TOPIC)
    assert "120 words" in prompt


def test_judge_prompt_prefers_web_search() -> None:
    """The Judge prompt must instruct preferring verified web search."""
    prompt = build_judge_system_prompt(TOPIC).lower()
    assert "verified" in prompt
    assert "unverified" in prompt


def test_judge_prompt_names_all_five_fixed_verdict_strings() -> None:
    """The Judge prompt must name all five fixed first-line verdict strings
    `debate.render` parses deterministically."""
    prompt = build_judge_system_prompt(TOPIC)
    for fixed_string in (
        "FOR wins",
        "FOR wins narrowly",
        "AGAINST wins",
        "AGAINST wins narrowly",
        "Draw",
    ):
        assert f'"{fixed_string}"' in prompt


def test_judge_prompt_requires_first_line_format() -> None:
    """The Judge prompt must require the verdict string on the response's
    first line, not merely mention it somewhere."""
    prompt = build_judge_system_prompt(TOPIC).lower()
    assert "first line" in prompt


def test_host_prompt_includes_topic() -> None:
    """The Host prompt must interpolate the debate's topic."""
    prompt = build_host_system_prompt(TOPIC, [])
    assert TOPIC in prompt


def test_host_prompt_handles_empty_already_asked() -> None:
    """An empty already-asked list must be handled cleanly, not crash."""
    prompt = build_host_system_prompt(TOPIC, [])
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_host_prompt_interpolates_every_already_asked_question() -> None:
    """Every already-asked question must appear in the prompt verbatim."""
    asked = [
        "Does remote work hurt junior employee mentorship?",
        "Does remote work reduce office real-estate costs enough to matter?",
    ]
    prompt = build_host_system_prompt(TOPIC, asked)
    for question in asked:
        assert question in prompt


def test_host_prompt_instructs_checking_against_history() -> None:
    """The Host prompt must instruct checking against already-asked questions
    so it never repeats one."""
    prompt = build_host_system_prompt(TOPIC, ["Some prior question?"]).lower()
    assert "repeat" in prompt or "already" in prompt
    assert "check" in prompt


def test_host_prompt_has_word_limit() -> None:
    """The Host prompt must instruct a 120-word answer cap."""
    prompt = build_host_system_prompt(TOPIC, [])
    assert "120 words" in prompt


def test_host_prompt_prefers_web_search() -> None:
    """The Host prompt must instruct preferring verified web search."""
    prompt = build_host_system_prompt(TOPIC, []).lower()
    assert "verified" in prompt
    assert "unverified" in prompt
