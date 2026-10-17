"""Tests for `debate.engine`.

`run_omp_turn` is always patched on `debate.engine` so no real `omp`
subprocess call ever happens. Async code under test is driven with
`asyncio.run` from plain (sync) test functions, matching
`tests/test_omp_client.py`'s pattern (no pytest-asyncio dependency needed).
"""

import asyncio
import time

import pytest

import debate.engine as engine_module
from debate.config import DebateConfig
from debate.engine import generate_next_question, run_question
from debate.omp_client import OmpResult
from debate.store import Store


@pytest.fixture
def store():
    """An isolated in-memory Store, closed automatically after the test."""
    s = Store(":memory:")
    yield s
    s.close()


def _recording_mock(truncated_for_index=None):
    """Build a fake `run_omp_turn` that records every call's kwargs.

    Args:
        truncated_for_index: Optional callable `(call_index) -> bool`
            controlling the `truncated` flag returned for each call, in
            call order. Defaults to always `False`.

    Returns:
        A `(fake_run_omp_turn, calls)` pair; `calls` accumulates one dict
        per invocation, in invocation order.
    """
    calls: list[dict] = []

    async def fake_run_omp_turn(
        system_prompt, user_prompt, *, model=None, tools=None, no_tools=False, timeout=120.0
    ):
        idx = len(calls)
        calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "model": model,
                "tools": tools,
                "no_tools": no_tools,
                "timeout": timeout,
            }
        )
        truncated = truncated_for_index(idx) if truncated_for_index else False
        return OmpResult(
            text=f"response-{idx}",
            truncated=truncated,
            model_used=model,
            returncode=0,
            duration_seconds=0.001,
        )

    return fake_run_omp_turn, calls


def test_full_pipeline_runs_stages_in_order(monkeypatch, store):
    """One run_question call persists every stage in the exact required order."""
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Cats are better than dogs")
    config = DebateConfig(topic="Cats are better than dogs")

    question_id = asyncio.run(
        run_question(store, debate_id, "Are cats smarter?", config)
    )

    turns = store.list_turns(question_id)
    stage_side_role = [(t.stage, t.side, t.role) for t in turns]

    assert stage_side_role == [
        ("huddle", "FOR", "Researcher"),
        ("huddle", "AGAINST", "Researcher"),
        ("opening", "FOR", "Lead"),
        ("opening", "AGAINST", "Lead"),
        ("rebuttal", "AGAINST", "Rebuttal"),
        ("rebuttal", "FOR", "Rebuttal"),
        ("rebuttal", "AGAINST", "Rebuttal"),
        ("rebuttal", "FOR", "Rebuttal"),
        ("closing", "AGAINST", "Lead"),
        ("closing", "FOR", "Lead"),
        ("verdict", None, "judge"),
    ]


def test_rebuttal_loop_stops_at_round_limit(monkeypatch, store):
    """With an instant mock, the round limit (not the clock) binds: exactly 4 turns."""
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="UBI")
    config = DebateConfig(topic="UBI", max_rebuttal_rounds=2, max_minutes=10)

    question_id = asyncio.run(run_question(store, debate_id, "Should UBI exist?", config))

    rebuttal_turns = [t for t in store.list_turns(question_id) if t.stage == "rebuttal"]
    assert len(rebuttal_turns) == 4
    assert [t.side for t in rebuttal_turns] == ["AGAINST", "FOR", "AGAINST", "FOR"]


@pytest.mark.parametrize("rounds,expected_turns", [(1, 2), (3, 6)])
def test_rebuttal_loop_round_limit_scales_with_config(monkeypatch, store, rounds, expected_turns):
    """The round limit is read from config: 1 round -> 2 turns, 3 rounds -> 6 turns."""
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="UBI scaling")
    config = DebateConfig(topic="UBI scaling", max_rebuttal_rounds=rounds, max_minutes=10)

    question_id = asyncio.run(run_question(store, debate_id, "Should UBI exist?", config))

    rebuttal_turns = [t for t in store.list_turns(question_id) if t.stage == "rebuttal"]
    assert len(rebuttal_turns) == expected_turns


def test_question_index_increments_across_questions_on_same_debate(monkeypatch, store):
    """Running two questions against the same debate yields question_index 0 then 1."""
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Indexing")
    config = DebateConfig(topic="Indexing")

    first_question_id = asyncio.run(run_question(store, debate_id, "First?", config))
    second_question_id = asyncio.run(run_question(store, debate_id, "Second?", config))

    questions = {q.id: q for q in store.list_questions(debate_id)}
    assert questions[first_question_id].question_index == 0
    assert questions[second_question_id].question_index == 1


def test_rebuttal_loop_stops_on_wallclock_budget(monkeypatch, store):
    """When the wall-clock budget expires, no new rebuttal turn starts.

    The in-flight turn (the one running when the budget check last passed)
    is always allowed to complete and gets persisted -- the test proves
    that by asserting exactly one rebuttal turn was persisted rather than
    zero, even though the mock is instant and the clock is fully synthetic.
    """
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    clock = {"t": 0.0}

    def fake_monotonic():
        return clock["t"]

    real_fake_run_omp_turn = fake

    async def clock_advancing_run_omp_turn(*args, **kwargs):
        result = await real_fake_run_omp_turn(*args, **kwargs)
        clock["t"] += 1000.0
        return result

    monkeypatch.setattr(engine_module, "run_omp_turn", clock_advancing_run_omp_turn)
    monkeypatch.setattr(engine_module.time, "monotonic", fake_monotonic)

    debate_id = store.create_debate(topic="Budget")
    config = DebateConfig(topic="Budget", max_rebuttal_rounds=2, max_minutes=1)

    question_id = asyncio.run(run_question(store, debate_id, "Does the budget bind?", config))

    rebuttal_turns = [t for t in store.list_turns(question_id) if t.stage == "rebuttal"]
    assert len(rebuttal_turns) == 1
    assert rebuttal_turns[0].side == "AGAINST"


def test_judge_disabled_skips_verdict(monkeypatch, store):
    """judge_enabled=False skips the verdict stage entirely."""
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="No judge")
    config = DebateConfig(topic="No judge", judge_enabled=False)

    question_id = asyncio.run(run_question(store, debate_id, "Any verdict?", config))

    stages = [t.stage for t in store.list_turns(question_id)]
    assert "verdict" not in stages


def test_judge_enabled_persists_one_verdict_turn(monkeypatch, store):
    """judge_enabled=True (default) persists exactly one verdict turn with web_search."""
    fake, calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Judged")
    config = DebateConfig(topic="Judged")

    question_id = asyncio.run(run_question(store, debate_id, "Who wins?", config))

    turns = store.list_turns(question_id)
    verdict_turns = [t for t in turns if t.stage == "verdict"]
    assert len(verdict_turns) == 1
    assert verdict_turns[0].side is None
    assert verdict_turns[0].role == "judge"
    assert calls[-1]["tools"] == "web_search"


def test_truncated_flag_roundtrips(monkeypatch, store):
    """Each turn's persisted `truncated` matches the mocked OmpResult's flag."""
    fake, _calls = _recording_mock(truncated_for_index=lambda idx: idx % 2 == 0)
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Truncation")
    config = DebateConfig(topic="Truncation")

    question_id = asyncio.run(run_question(store, debate_id, "Does it truncate?", config))

    turns = store.list_turns(question_id)
    for idx, turn in enumerate(turns):
        assert turn.truncated == (idx % 2 == 0)


@pytest.mark.parametrize("model", [None, "anthropic/claude-haiku-4-5"])
def test_model_passed_through_every_call(monkeypatch, store, model):
    """config.model (including None) is forwarded unchanged to every run_omp_turn call."""
    fake, calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Model passthrough")
    config = DebateConfig(topic="Model passthrough", model=model)

    asyncio.run(run_question(store, debate_id, "Does model pass through?", config))

    assert len(calls) == 11
    assert all(call["model"] == model for call in calls)


def test_generate_next_question_uses_host_prompt_and_history(monkeypatch, store):
    """generate_next_question builds the Host prompt from already-asked questions.

    It returns the (whitespace-stripped) generated text and does not
    persist any turn row.
    """
    debate_id = store.create_debate(topic="History test")
    store.create_question(debate_id, "Q1?", 0)
    store.create_question(debate_id, "Q2?", 1)

    recorded_already_asked = []

    def fake_build_host_system_prompt(topic, already_asked):
        recorded_already_asked.append(list(already_asked))
        assert topic == "History test"
        return "HOST-SYSTEM-PROMPT"

    monkeypatch.setattr(engine_module, "build_host_system_prompt", fake_build_host_system_prompt)

    fake, calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    config = DebateConfig(topic="History test", model="some-model")
    question = asyncio.run(generate_next_question(store, debate_id, config))

    assert question == "response-0"
    assert recorded_already_asked == [["Q1?", "Q2?"]]
    assert calls[0]["system_prompt"] == "HOST-SYSTEM-PROMPT"
    assert calls[0]["model"] == "some-model"
    # No turn row is persisted, and no new question row is created either.
    assert len(store.list_questions(debate_id)) == 2


def test_generate_next_question_strips_whitespace(monkeypatch, store):
    """The returned question text has surrounding whitespace stripped."""

    async def fake_run_omp_turn(system_prompt, user_prompt, **kwargs):
        return OmpResult(
            text="  What about the future?  \n",
            truncated=False,
            model_used=kwargs.get("model"),
            returncode=0,
            duration_seconds=0.001,
        )

    monkeypatch.setattr(engine_module, "run_omp_turn", fake_run_omp_turn)

    debate_id = store.create_debate(topic="Strip test")
    config = DebateConfig(topic="Strip test")

    question = asyncio.run(generate_next_question(store, debate_id, config))

    assert question == "What about the future?"


def _brief_tracking_mock():
    """Build a fake `run_omp_turn` returning a per-side sentinel for huddle turns.

    Each Researcher (huddle) call returns a sentinel naming its own side, and
    every other call returns a sentinel naming its call index, so a later
    prompt can be checked for exactly which team's brief and which earlier
    turns it carries.

    Returns:
        A `(fake_run_omp_turn, calls)` pair; `calls` accumulates one dict per
        invocation, in invocation order.
    """
    calls: list[dict] = []

    async def fake_run_omp_turn(
        system_prompt, user_prompt, *, model=None, tools=None, no_tools=False, timeout=120.0
    ):
        idx = len(calls)
        calls.append(
            {"system_prompt": system_prompt, "user_prompt": user_prompt, "tools": tools}
        )
        if "private huddle stage" in user_prompt:
            side = "FOR" if "on the FOR team" in system_prompt else "AGAINST"
            text = f"<<BRIEF-{side}>>"
        else:
            text = f"<<TURN-{idx}>>"
        return OmpResult(
            text=text,
            truncated=False,
            model_used=model,
            returncode=0,
            duration_seconds=0.001,
        )

    return fake_run_omp_turn, calls


def test_each_teams_huddle_brief_reaches_only_its_own_lead_and_rebuttal(monkeypatch, store):
    """Every Lead/Rebuttal prompt carries its own team's brief and not the other's.

    Requirement 6: the huddle brief "is included as context in every later
    prompt to that team's Lead and Rebuttal agents for this question", and the
    huddle is private per team, so the opposing side's brief must never appear.
    """
    fake, calls = _brief_tracking_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Brief propagation")
    config = DebateConfig(topic="Brief propagation")

    asyncio.run(run_question(store, debate_id, "Does the brief travel?", config))

    later_team_calls = [
        call
        for call in calls
        if "You are a debater" in call["system_prompt"]
        and "private huddle stage" not in call["user_prompt"]
    ]
    # 2 openings + 4 rebuttals + 2 closings.
    assert len(later_team_calls) == 8
    for call in later_team_calls:
        on_for_team = "on the FOR team" in call["system_prompt"]
        own, other = ("FOR", "AGAINST") if on_for_team else ("AGAINST", "FOR")
        assert f"<<BRIEF-{own}>>" in call["user_prompt"]
        assert f"<<BRIEF-{other}>>" not in call["user_prompt"]


def test_verdict_prompt_contains_every_debated_turn(monkeypatch, store):
    """The Judge's prompt carries the full question transcript (Requirement 7)."""
    fake, calls = _brief_tracking_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Verdict context")
    config = DebateConfig(topic="Verdict context")

    asyncio.run(run_question(store, debate_id, "Who argued better?", config))

    judge_calls = [call for call in calls if "You are a debater" not in call["system_prompt"]]
    assert len(judge_calls) == 1
    verdict_prompt = judge_calls[0]["user_prompt"]
    # Calls 2-9 are the openings, rebuttals and closings, in order.
    for idx in range(2, 10):
        assert f"<<TURN-{idx}>>" in verdict_prompt


def test_intermediate_stage_prompts_carry_prior_turns(monkeypatch, store):
    """Rebuttal, closing, and the AGAINST opening prompts each include every
    prior debated turn's text (not an empty transcript), proving
    `_render_transcript` output actually reaches these call sites and isn't
    dropped in favor of a literal `""`.
    """
    fake, calls = _brief_tracking_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Transcript propagation")
    config = DebateConfig(topic="Transcript propagation")

    asyncio.run(run_question(store, debate_id, "Does the transcript travel?", config))

    # Call indices: 0-1 huddles, 2 FOR opening, 3 AGAINST opening,
    # 4-7 rebuttals, 8-9 closings, 10 verdict.
    against_opening_prompt = calls[3]["user_prompt"]
    assert "<<TURN-2>>" in against_opening_prompt  # FOR opening

    first_rebuttal_prompt = calls[4]["user_prompt"]
    assert "<<TURN-2>>" in first_rebuttal_prompt
    assert "<<TURN-3>>" in first_rebuttal_prompt

    last_rebuttal_prompt = calls[7]["user_prompt"]
    for idx in range(2, 7):
        assert f"<<TURN-{idx}>>" in last_rebuttal_prompt

    first_closing_prompt = calls[8]["user_prompt"]
    for idx in range(2, 8):
        assert f"<<TURN-{idx}>>" in first_closing_prompt

    second_closing_prompt = calls[9]["user_prompt"]
    for idx in range(2, 9):
        assert f"<<TURN-{idx}>>" in second_closing_prompt


def test_no_judge_run_keeps_full_stage_order_through_closings(monkeypatch, store):
    """With judge_enabled=False the pipeline still runs every other stage, in order."""
    fake, _calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="No judge order")
    config = DebateConfig(topic="No judge order", judge_enabled=False)

    question_id = asyncio.run(run_question(store, debate_id, "Order without judge?", config))

    turns = store.list_turns(question_id)
    assert [(t.stage, t.side, t.role) for t in turns] == [
        ("huddle", "FOR", "Researcher"),
        ("huddle", "AGAINST", "Researcher"),
        ("opening", "FOR", "Lead"),
        ("opening", "AGAINST", "Lead"),
        ("rebuttal", "AGAINST", "Rebuttal"),
        ("rebuttal", "FOR", "Rebuttal"),
        ("rebuttal", "AGAINST", "Rebuttal"),
        ("rebuttal", "FOR", "Rebuttal"),
        ("closing", "AGAINST", "Lead"),
        ("closing", "FOR", "Lead"),
    ]


def test_rebuttal_budget_is_minutes_and_starts_at_the_loop(monkeypatch, store):
    """`max_minutes` is a minutes budget covering the rebuttal loop alone.

    Synthetic clock: every turn advances it by exactly 30 seconds. With
    max_minutes=1 (a 60-second budget) the loop may start a turn at 0s and at
    30s elapsed, but not at 60s elapsed, so exactly two rebuttal turns run.
    The round limit is set to 5 rounds (10 turns) so only the clock can bind,
    and the four turns before the loop burn 120 synthetic seconds that must
    not count against the loop's own budget.
    """
    clock = {"t": 0.0}
    base_fake, _calls = _recording_mock()

    async def clock_advancing_run_omp_turn(*args, **kwargs):
        result = await base_fake(*args, **kwargs)
        clock["t"] += 30.0
        return result

    monkeypatch.setattr(engine_module, "run_omp_turn", clock_advancing_run_omp_turn)
    monkeypatch.setattr(engine_module.time, "monotonic", lambda: clock["t"])

    debate_id = store.create_debate(topic="Minute budget")
    config = DebateConfig(topic="Minute budget", max_rebuttal_rounds=5, max_minutes=1)

    question_id = asyncio.run(run_question(store, debate_id, "How long?", config))

    rebuttal_turns = [t for t in store.list_turns(question_id) if t.stage == "rebuttal"]
    assert len(rebuttal_turns) == 2


def test_rebuttal_turn_in_flight_when_budget_expires_still_finishes(monkeypatch, store):
    """A rebuttal turn already running when the clock expires completes and is kept.

    Real wall-clock timing (no patched monotonic): every turn takes ~0.3s and
    the loop budget is 0.45s. The loop starts turn 1 at 0s elapsed and turn 2
    at ~0.3s elapsed -- both inside the budget -- so turn 2 is still in flight
    when the budget expires at 0.45s and must still finish and be persisted.
    No third turn starts. The round limit is 5 rounds (10 turns) so only the
    clock can bind.
    """
    timings: list[tuple[float, float]] = []

    async def slow_run_omp_turn(
        system_prompt, user_prompt, *, model=None, tools=None, no_tools=False, timeout=120.0
    ):
        started = time.monotonic()
        await asyncio.sleep(0.3)
        timings.append((started, time.monotonic()))
        return OmpResult(
            text="slow-turn",
            truncated=False,
            model_used=model,
            returncode=0,
            duration_seconds=0.3,
        )

    monkeypatch.setattr(engine_module, "run_omp_turn", slow_run_omp_turn)

    debate_id = store.create_debate(topic="In flight")
    # 0.0075 minutes = 0.45 seconds.
    config = DebateConfig(
        topic="In flight", max_rebuttal_rounds=5, max_minutes=0.0075, judge_enabled=False
    )

    question_id = asyncio.run(run_question(store, debate_id, "Does it finish?", config))

    rebuttal_turns = [t for t in store.list_turns(question_id) if t.stage == "rebuttal"]
    assert len(rebuttal_turns) == 2
    assert [t.text for t in rebuttal_turns] == ["slow-turn", "slow-turn"]

    # Calls 0-3 are the two huddles and two openings; the loop (and its
    # budget) starts when the last opening returns.
    loop_start = timings[3][1]
    second_rebuttal_started, second_rebuttal_ended = timings[5]
    assert second_rebuttal_started < loop_start + 0.45, "turn 2 must start inside the budget"
    assert second_rebuttal_ended > loop_start + 0.45, "turn 2 must still be running at expiry"


def test_researchers_and_judge_run_with_web_search(monkeypatch, store):
    """Both huddle Researchers and the Judge get `tools="web_search"`.

    Requirement 6 names `--tools=web_search` for the huddle Researchers and
    Requirement 7 names it for the Judge; no other turn needs it.
    """
    fake, calls = _recording_mock()
    monkeypatch.setattr(engine_module, "run_omp_turn", fake)

    debate_id = store.create_debate(topic="Search tools")
    config = DebateConfig(topic="Search tools")

    asyncio.run(run_question(store, debate_id, "Who searches?", config))

    huddle_calls = [call for call in calls if "private huddle stage" in call["user_prompt"]]
    assert len(huddle_calls) == 2
    assert [call["tools"] for call in huddle_calls] == ["web_search", "web_search"]

    judge_calls = [call for call in calls if "You are a debater" not in call["system_prompt"]]
    assert len(judge_calls) == 1
    assert judge_calls[0]["tools"] == "web_search"
