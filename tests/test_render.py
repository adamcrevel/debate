"""Tests for `debate.render`."""

from debate.render import render_gist_markdown
from debate.store import Debate, Question, Turn


def _debate(**overrides) -> Debate:
    defaults = dict(
        id=1,
        topic="Should cities ban private cars downtown?",
        model=None,
        max_rebuttal_rounds=2,
        max_minutes=10.0,
        judge_enabled=True,
        created_at="2026-01-01T00:00:00Z",
    )
    defaults.update(overrides)
    return Debate(**defaults)


def _question(question_id: int, index: int, text: str) -> Question:
    return Question(
        id=question_id,
        debate_id=1,
        text=text,
        question_index=index,
        created_at="2026-01-01T00:00:00Z",
    )


def _turn(
    question_id: int,
    side: str | None,
    role: str,
    stage: str,
    text: str,
    *,
    truncated: bool = False,
    turn_id: int = 1,
) -> Turn:
    return Turn(
        id=turn_id,
        question_id=question_id,
        side=side,
        role=role,
        stage=stage,
        model_used=None,
        text=text,
        citations=[],
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:00:05Z",
        truncated=truncated,
    )


def test_title_and_subtitle_use_raw_topic_and_question_count():
    """The H1 and subtitle both use the debate's raw topic string, and the subtitle
    names the real question count rather than the hand-built example's
    auto-generated-specific phrasing."""
    debate = _debate(topic="sports teams")
    question = _question(10, 0, "Should salary caps exist?")
    turns = {10: [_turn(10, "FOR", "Lead", "opening", "Yes because X.")]}

    md = render_gist_markdown(debate, [question], turns)

    assert "# 🏟️ Debate: sports teams" in md
    assert "Topic: **sports teams** · 1 question ·" in md
    assert "auto-generated" not in md


def test_results_table_links_to_anchor_and_shows_trophy_for_compliant_verdict():
    """A verdict turn whose first line is one of the five canonical strings
    produces a trophy-emoji table cell linked to that question's anchor."""
    debate = _debate()
    question = _question(10, 0, "Should salary caps exist?")
    turns = {
        10: [
            _turn(10, "FOR", "Lead", "opening", "Opening text."),
            _turn(10, None, "judge", "verdict", "FOR wins narrowly\n\nRationale here."),
        ]
    }

    md = render_gist_markdown(debate, [question], turns)

    assert "| [Q1](#q1) | Should salary caps exist? | 🏆 FOR wins narrowly |" in md
    assert '<a id="q1"></a>' in md


def test_draw_gets_handshake_cell():
    """A `Draw` verdict renders with the handshake-emoji cell, not a trophy."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {10: [_turn(10, None, "judge", "verdict", "Draw\n\nBoth sides argued well.")]}

    md = render_gist_markdown(debate, [question], turns)

    assert "🤝 Draw" in md
    assert "🏆" not in md


def test_noncompliant_verdict_falls_back_without_guessing_a_winner():
    """A verdict turn whose first line doesn't match the five fixed strings
    exactly falls back to a neutral table cell, never a fabricated winner --
    but the per-question section still renders its actual first line verbatim."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {
        10: [_turn(10, None, "judge", "verdict", "I think FOR argued slightly better.\n\nDetails.")]
    }

    md = render_gist_markdown(debate, [question], turns)

    assert "Verdict delivered — see below" in md
    assert "🏆" not in md
    assert "🤝" not in md
    assert "**I think FOR argued slightly better.**" in md


def test_judge_disabled_question_has_no_verdict_turn_and_neutral_cell():
    """A question with no verdict turn (judge disabled) gets the
    judge-disabled table cell and prints no Judge Verdict section."""
    debate = _debate(judge_enabled=False)
    question = _question(10, 0, "Q?")
    turns = {10: [_turn(10, "FOR", "Lead", "opening", "Opening text.")]}

    md = render_gist_markdown(debate, [question], turns)

    assert "— No verdict (judge disabled)" in md
    assert "⚖️ Judge Verdict" not in md


def test_truncated_turn_shows_marker_in_its_header():
    """A turn whose truncated flag is set renders the [truncated] marker
    in its stage header, same as `debate show` already does."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {10: [_turn(10, "AGAINST", "Rebuttal", "rebuttal", "Cut off mid", truncated=True)]}

    md = render_gist_markdown(debate, [question], turns)

    assert "⚔️ Rebuttal — AGAINST Rebuttal [truncated]" in md


def test_turns_render_in_the_exact_order_given_not_a_fixed_side_order():
    """Turns render in exactly the order they appear in turns_by_question --
    the same order Store.list_turns already returns -- never a renderer-
    imposed FOR-then-AGAINST ordering, since huddle turns run concurrently
    and their real completion order varies."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {
        10: [
            _turn(10, "AGAINST", "Researcher", "huddle", "AGAINST brief first.", turn_id=1),
            _turn(10, "FOR", "Researcher", "huddle", "FOR brief second.", turn_id=2),
        ]
    }

    md = render_gist_markdown(debate, [question], turns)

    assert md.index("AGAINST Researcher") < md.index("FOR Researcher")
    assert md.index("AGAINST brief first.") < md.index("FOR brief second.")


def test_stage_headers_use_fixed_emoji_and_role_for_each_stage():
    """Each non-verdict stage renders its own fixed emoji + label."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {
        10: [
            _turn(10, "FOR", "Researcher", "huddle", "Brief.", turn_id=1),
            _turn(10, "FOR", "Lead", "opening", "Open.", turn_id=2),
            _turn(10, "AGAINST", "Rebuttal", "rebuttal", "Rebut.", turn_id=3),
            _turn(10, "FOR", "Lead", "closing", "Close.", turn_id=4),
        ]
    }

    md = render_gist_markdown(debate, [question], turns)

    assert "#### 🔍 Huddle (evidence brief) — FOR Researcher" in md
    assert "#### 🎤 Opening — FOR Lead" in md
    assert "#### ⚔️ Rebuttal — AGAINST Rebuttal" in md
    assert "#### 🏁 Closing — FOR Lead" in md


def test_multiple_questions_get_distinct_sequential_anchors():
    """Each question gets its own `#qN` anchor, numbered by question_index + 1."""
    debate = _debate()
    q1 = _question(10, 0, "First question?")
    q2 = _question(11, 1, "Second question?")
    turns = {
        10: [_turn(10, "FOR", "Lead", "opening", "A.", turn_id=1)],
        11: [_turn(11, "FOR", "Lead", "opening", "B.", turn_id=2)],
    }

    md = render_gist_markdown(debate, [q1, q2], turns)

    assert '<a id="q1"></a>' in md
    assert "## Q1: First question?" in md
    assert '<a id="q2"></a>' in md
    assert "## Q2: Second question?" in md


def test_single_separator_only_after_the_results_table():
    """Exactly one standalone '---' line appears, right after the results
    table -- never a second one between questions or at the end."""
    debate = _debate()
    q1 = _question(10, 0, "First?")
    q2 = _question(11, 1, "Second?")
    turns = {
        10: [
            _turn(10, "FOR", "Lead", "opening", "A.", turn_id=1),
            _turn(10, None, "judge", "verdict", "FOR wins\n\nR.", turn_id=2),
        ],
        11: [_turn(11, "FOR", "Lead", "opening", "B.", turn_id=3)],
    }

    md = render_gist_markdown(debate, [q1, q2], turns)

    separator_lines = [line for line in md.split("\n") if line.strip() == "---"]
    assert len(separator_lines) == 1


def test_footer_links_to_the_real_repo_not_a_placeholder():
    """The attribution footer links `debate` to its real repo, not the
    hand-built example's generic github.com placeholder."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {10: [_turn(10, "FOR", "Lead", "opening", "A.")]}

    md = render_gist_markdown(debate, [question], turns)

    assert "[`debate`](https://github.com/adamcrevel/debate)" in md
    assert "](https://github.com)" not in md


def test_no_citations_line_rendered_separately():
    """Citations stay embedded in a turn's own prose -- no separate
    citations line is ever added, matching the approved reference format."""
    debate = _debate()
    question = _question(10, 0, "Q?")
    turns = {
        10: [
            Turn(
                id=1,
                question_id=10,
                side="FOR",
                role="Researcher",
                stage="huddle",
                model_used=None,
                text="See https://example.com/evidence for proof.",
                citations=["https://example.com/evidence"],
                started_at="2026-01-01T00:00:00Z",
                ended_at="2026-01-01T00:00:05Z",
                truncated=False,
            )
        ]
    }

    md = render_gist_markdown(debate, [question], turns)

    assert "Sources:" not in md
    assert md.count("https://example.com/evidence") == 1
