"""The per-question debate pipeline (Requirements 2, 4, 6-10).

This module orchestrates one question through the full debate pipeline --
huddle, openings, rebuttal loop, closings, and verdict -- by making one
`run_omp_turn` call per agent turn (T2) and persisting each turn via `Store`
(T1), using the prompt templates from `agents` (T3).

Layering boundary: this module never spawns an OS process or talks to the
`omp` CLI directly -- every model call goes through `omp_client.run_omp_turn`,
the only place that is allowed to do so.
"""

import asyncio
import itertools
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from .agents import (
    Side,
    build_debater_system_prompt,
    build_host_system_prompt,
    build_judge_system_prompt,
)
from .config import DebateConfig
from .omp_client import run_omp_turn
from .store import Store


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string.

    Matches the format `Store`'s own internal `_now()` helper uses, so
    `started_at`/`ended_at` timestamps persisted by this module are
    consistent with every other timestamp in the database.
    """
    return datetime.now(UTC).isoformat()


@dataclass
class _TurnRecord:
    """An in-memory record of one already-persisted turn.

    Used to render transcript-so-far context into later prompts without
    round-tripping through the database -- `side` is `None` for non-team
    speakers (the Judge).
    """

    side: Side | None
    role: str
    stage: str
    text: str


def _format_turn(turn: _TurnRecord) -> str:
    """Render one `_TurnRecord` as a labeled block for a transcript."""
    label = f"{turn.side} {turn.role}" if turn.side else turn.role
    return f"[{label} - {turn.stage}]\n{turn.text}"


def _render_transcript(turns: list[_TurnRecord]) -> str:
    """Render a list of `_TurnRecord`s into readable, labeled transcript text."""
    return "\n\n".join(_format_turn(turn) for turn in turns)


async def _execute_turn(
    store: Store,
    question_id: int,
    *,
    side: Side | None,
    role: str,
    stage: str,
    system_prompt: str,
    user_prompt: str,
    model: str | None,
    tools: str | None = None,
) -> _TurnRecord:
    """Run exactly one agent turn via `run_omp_turn` and persist it.

    Times the call with `started_at`/`ended_at` ISO-8601 timestamps taken
    immediately around the `await`, passes `model` through unchanged
    (Requirement 8 -- never hardcoded here), and forwards the returned
    `truncated` flag straight into `Store.create_turn` (Requirement 9).

    Args:
        store: The `Store` to persist this turn to.
        question_id: The owning question's row id.
        side: `"FOR"`, `"AGAINST"`, or `None` for a non-team speaker.
        role: The speaking agent's role (e.g. `"Lead"`, `"Researcher"`,
            `"Rebuttal"`, `"judge"`).
        stage: The pipeline stage (e.g. `"huddle"`, `"opening"`,
            `"rebuttal"`, `"closing"`, `"verdict"`).
        system_prompt: The agent's system/instruction text.
        user_prompt: The turn's task text.
        model: Passed straight through to `run_omp_turn`.
        tools: Passed straight through to `run_omp_turn` (e.g.
            `"web_search"` for Researchers and the Judge).

    Returns:
        A `_TurnRecord` capturing this turn's side/role/stage/text, for use
        as context in later prompts.
    """
    started_at = _now()
    result = await run_omp_turn(system_prompt, user_prompt, model=model, tools=tools)
    ended_at = _now()
    store.create_turn(
        question_id=question_id,
        role=role,
        stage=stage,
        text=result.text,
        started_at=started_at,
        ended_at=ended_at,
        truncated=result.truncated,
        side=side,
        model_used=result.model_used,
    )
    return _TurnRecord(side=side, role=role, stage=stage, text=result.text)


def _huddle_user_prompt(topic: str, question_text: str) -> str:
    """Build the Researcher's huddle-stage user prompt."""
    return (
        f'This is the private huddle stage, before the debate on the question '
        f'below begins. The debate\'s topic is: "{topic}".\n\n'
        f"The question under debate is: {question_text}\n\n"
        "Produce an evidence brief for your team: a grounded summary of the "
        "facts, data, and sources that support your side's position on this "
        "specific question. This brief will be given to your team's Lead and "
        "Rebuttal agents to use for the rest of this question."
    )


def _opening_user_prompt(
    topic: str, question_text: str, brief: str, transcript_so_far: str
) -> str:
    """Build a Lead's opening-stage user prompt.

    When `transcript_so_far` is non-empty (the AGAINST Lead, speaking after
    FOR's opening), the prompt explicitly notes this is still the opening
    stage, not a rebuttal, so the agent does not try to counter-argue yet.
    """
    parts = [
        f'This is the opening-statement stage of the debate on: "{topic}".',
        f"The question under debate is: {question_text}",
        f"Your team's evidence brief from this round's huddle:\n{brief}",
    ]
    if transcript_so_far:
        parts.append(
            "This is still the opening stage, not a rebuttal -- the other "
            "side has just delivered its opening statement below. Deliver "
            "your own team's opening statement; you do not need to rebut it "
            f"yet:\n{transcript_so_far}"
        )
    else:
        parts.append(
            "You are speaking first. Deliver your team's opening statement "
            "for this question now."
        )
    return "\n\n".join(parts)


def _rebuttal_user_prompt(
    topic: str, question_text: str, brief: str, transcript_so_far: str
) -> str:
    """Build a Rebuttal agent's rebuttal-stage user prompt."""
    return (
        f'This is the rebuttal stage of the debate on: "{topic}".\n\n'
        f"The question under debate is: {question_text}\n\n"
        f"Your team's evidence brief from this round's huddle:\n{brief}\n\n"
        "Transcript of the debate so far, labeled by side and stage:\n"
        f"{transcript_so_far}\n\n"
        "Directly respond to and counter the opposing team's most recent "
        "points. Deliver your team's next rebuttal turn now."
    )


def _closing_user_prompt(
    topic: str, question_text: str, brief: str, transcript_so_far: str
) -> str:
    """Build a Lead's closing-stage user prompt."""
    return (
        f'This is the closing-statement stage of the debate on: "{topic}".\n\n'
        f"The question under debate is: {question_text}\n\n"
        f"Your team's evidence brief from this round's huddle:\n{brief}\n\n"
        "Transcript of the debate so far, labeled by side and stage:\n"
        f"{transcript_so_far}\n\n"
        "Deliver your team's closing statement, tying together your team's "
        "case across the whole debate on this question."
    )


def _verdict_user_prompt(topic: str, question_text: str, transcript_so_far: str) -> str:
    """Build the Judge's verdict-stage user prompt."""
    return (
        f'This is the verdict stage of the debate on: "{topic}".\n\n'
        f"The question under debate is: {question_text}\n\n"
        "Full transcript of this question, labeled by side, role, and "
        f"stage:\n{transcript_so_far}\n\n"
        "Review the transcript and deliver your verdict now."
    )


async def run_question(
    store: Store, debate_id: int, question_text: str, config: DebateConfig
) -> int:
    """Run one question through the full debate pipeline and persist every turn.

    Runs, in order (Requirement 6):

    1. **Huddle** (private per team): the FOR and AGAINST Researchers each
       produce an evidence brief (concurrently, since they're independent),
       kept in memory and fed into that side's later Lead/Rebuttal prompts.
    2. **Openings**: FOR Lead, then AGAINST Lead.
    3. **Rebuttal loop**: AGAINST Rebuttal first, alternating with FOR, until
       `config.max_rebuttal_rounds * 2` turns have run or the
       `config.max_minutes` wall-clock budget (measured from when the loop
       starts) has elapsed -- checked only before starting a new turn, so a
       turn already in flight is always allowed to finish.
    4. **Closings**: AGAINST Lead, then FOR Lead.
    5. **Verdict**: one Judge turn, if `config.judge_enabled`; skipped
       entirely otherwise.

    Every turn is exactly one `run_omp_turn` call, uses `config.model`
    (never a hardcoded model), and is persisted via `Store.create_turn` with
    its `truncated` flag intact.

    Args:
        store: The `Store` to persist the question and its turns to.
        debate_id: The owning debate's row id.
        question_text: The question's text.
        config: This debate's `DebateConfig` (topic, model, rebuttal-round
            and wall-clock limits, judge toggle).

    Returns:
        The new question's row id.
    """
    topic = config.topic
    question_index = len(store.list_questions(debate_id))
    question_id = store.create_question(debate_id, question_text, question_index)

    # --- Huddle (private per team, run concurrently) ---
    for_huddle, against_huddle = await asyncio.gather(
        _execute_turn(
            store,
            question_id,
            side="FOR",
            role="Researcher",
            stage="huddle",
            system_prompt=build_debater_system_prompt("FOR", "Researcher", topic),
            user_prompt=_huddle_user_prompt(topic, question_text),
            model=config.model,
            tools="web_search",
        ),
        _execute_turn(
            store,
            question_id,
            side="AGAINST",
            role="Researcher",
            stage="huddle",
            system_prompt=build_debater_system_prompt("AGAINST", "Researcher", topic),
            user_prompt=_huddle_user_prompt(topic, question_text),
            model=config.model,
            tools="web_search",
        ),
    )
    briefs: dict[Side, str] = {"FOR": for_huddle.text, "AGAINST": against_huddle.text}

    # --- Openings: FOR Lead, then AGAINST Lead ---
    transcript: list[_TurnRecord] = []
    for side in ("FOR", "AGAINST"):
        turn = await _execute_turn(
            store,
            question_id,
            side=side,
            role="Lead",
            stage="opening",
            system_prompt=build_debater_system_prompt(side, "Lead", topic),
            user_prompt=_opening_user_prompt(
                topic, question_text, briefs[side], _render_transcript(transcript)
            ),
            model=config.model,
        )
        transcript.append(turn)

    # --- Rebuttal loop: AGAINST first, alternating, bounded by rounds and wall-clock ---
    max_rebuttal_turns = config.max_rebuttal_rounds * 2
    deadline = time.monotonic() + config.max_minutes * 60
    rebuttal_sides = itertools.cycle(("AGAINST", "FOR"))
    rebuttal_turns_run = 0
    while rebuttal_turns_run < max_rebuttal_turns:
        if time.monotonic() >= deadline:
            break
        side = next(rebuttal_sides)
        turn = await _execute_turn(
            store,
            question_id,
            side=side,
            role="Rebuttal",
            stage="rebuttal",
            system_prompt=build_debater_system_prompt(side, "Rebuttal", topic),
            user_prompt=_rebuttal_user_prompt(
                topic, question_text, briefs[side], _render_transcript(transcript)
            ),
            model=config.model,
        )
        transcript.append(turn)
        rebuttal_turns_run += 1

    # --- Closings: AGAINST Lead, then FOR Lead ---
    for side in ("AGAINST", "FOR"):
        turn = await _execute_turn(
            store,
            question_id,
            side=side,
            role="Lead",
            stage="closing",
            system_prompt=build_debater_system_prompt(side, "Lead", topic),
            user_prompt=_closing_user_prompt(
                topic, question_text, briefs[side], _render_transcript(transcript)
            ),
            model=config.model,
        )
        transcript.append(turn)

    # --- Verdict: one Judge turn, if enabled ---
    if config.judge_enabled:
        await _execute_turn(
            store,
            question_id,
            side=None,
            role="judge",
            stage="verdict",
            system_prompt=build_judge_system_prompt(topic),
            user_prompt=_verdict_user_prompt(topic, question_text, _render_transcript(transcript)),
            model=config.model,
            tools="web_search",
        )

    return question_id


async def generate_next_question(store: Store, debate_id: int, config: DebateConfig) -> str:
    """Generate the next debate question via the Host agent (Requirement 4).

    Fetches every question already asked in this debate, builds the Host
    system prompt against that history (so the Host never repeats a
    question), and makes one `run_omp_turn` call to generate the next one.
    This does not persist a turn row -- generating a question is a meta
    step before `run_question` runs the actual debate pipeline on it.

    Args:
        store: The `Store` to read already-asked questions from.
        debate_id: The owning debate's row id.
        config: This debate's `DebateConfig` (topic and model).

    Returns:
        The generated question's text, with surrounding whitespace stripped.
    """
    already_asked = [question.text for question in store.list_questions(debate_id)]
    system_prompt = build_host_system_prompt(config.topic, already_asked)
    result = await run_omp_turn(
        system_prompt,
        "Propose the next debate question now.",
        model=config.model,
    )
    return result.text.strip()
