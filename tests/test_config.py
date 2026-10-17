"""Tests for debate.config.DebateConfig."""

import pytest

from debate.config import DebateConfig


def test_valid_config_constructs_with_defaults():
    """A config with a real topic constructs, and defaults match the spec."""
    config = DebateConfig(topic="Should cities ban cars downtown?")

    assert config.topic == "Should cities ban cars downtown?"
    assert config.model is None
    assert config.max_rebuttal_rounds == 2
    assert config.max_minutes == 10
    assert config.judge_enabled is True


def test_valid_config_accepts_overrides():
    """Every field can be overridden from its default."""
    config = DebateConfig(
        topic="Is remote work net positive?",
        model="gpt-5",
        max_rebuttal_rounds=4,
        max_minutes=20,
        judge_enabled=False,
    )

    assert config.model == "gpt-5"
    assert config.max_rebuttal_rounds == 4
    assert config.max_minutes == 20
    assert config.judge_enabled is False


def test_empty_topic_raises():
    """An empty-string topic is rejected with a clear ValueError."""
    with pytest.raises(ValueError, match="topic"):
        DebateConfig(topic="")


def test_whitespace_only_topic_raises():
    """A whitespace-only topic is rejected with a clear ValueError."""
    with pytest.raises(ValueError, match="topic"):
        DebateConfig(topic="   \t\n  ")
