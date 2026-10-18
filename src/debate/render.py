"""Deterministic Markdown rendering of a debate transcript, gist-ready.

Pure functions only -- no I/O, no subprocess. A caller fetches a `Debate`,
its `Question`s, and each question's `Turn`s from a `Store` and passes them
in; `render_gist_markdown` turns that into one self-contained Markdown
document matching the format a user hand-built and approved, formalized here
so reproducing it never again depends on an LLM re-deriving it from scratch.

Verdict parsing: `agents.build_judge_system_prompt` requires the Judge's
response to start with one of five fixed strings (see `_VERDICT_CELLS`
below). `_verdict_cell` reads only that first line, verbatim -- a Judge
reply that doesn't comply with the format falls back to a neutral label
rather than guessing a winner from free prose.
"""

from .store import Debate, Question, Turn

_STAGE_LABELS: dict[str, str] = {
    "huddle": "🔍 Huddle (evidence brief)",
    "opening": "🎤 Opening",
    "rebuttal": "⚔️ Rebuttal",
    "closing": "🏁 Closing",
}

_VERDICT_CELLS: dict[str, str] = {
    "FOR wins": "🏆 FOR wins",
    "FOR wins narrowly": "🏆 FOR wins narrowly",
    "AGAINST wins": "🏆 AGAINST wins",
    "AGAINST wins narrowly": "🏆 AGAINST wins narrowly",
    "Draw": "🤝 Draw",
}

_FOOTER = (
    "*Produced via the [`debate`](https://github.com/adamcrevel/debate) CLI "
    "— the `omp` structured debate engine. Each turn persisted to SQLite; "
    "transcript reproducible via `debate show <id>`.*"
)


def _blockquote(text: str) -> str:
    """Prefix every line of `text` with `"> "` (a bare `">"` for blank lines).

    Args:
        text: The text to quote, possibly multi-line.

    Returns:
        `text` rendered as one Markdown blockquote.
    """
    return "\n".join(f"> {line}" if line else ">" for line in text.split("\n"))


def _verdict_cell(verdict_turn: Turn | None) -> str:
    """Build the results-table cell for one question's verdict.

    Args:
        verdict_turn: That question's `stage == "verdict"` turn, or `None`
            if the judge was disabled for this question.

    Returns:
        A trophy-emoji cell for one of the five canonical verdict strings
        (an exact match on the turn's first line), a handshake-emoji cell
        for a draw, a neutral "no verdict" label when `verdict_turn` is
        `None`, or a neutral "verdict delivered" label when the turn's
        first line doesn't match any of the five canonical strings exactly
        -- this never guesses a winner from free-form text.
    """
    if verdict_turn is None:
        return "— No verdict (judge disabled)"
    first_line = verdict_turn.text.partition("\n")[0].strip()
    return _VERDICT_CELLS.get(first_line, "Verdict delivered — see below")


def _render_turn(turn: Turn) -> list[str]:
    """Render one non-verdict turn as its header line, a blank line, and its text.

    Args:
        turn: A turn whose `stage` is `"huddle"`, `"opening"`, `"rebuttal"`,
            or `"closing"` (never `"verdict"` -- see `_render_verdict`).

    Returns:
        The lines for this turn's section, not yet joined.
    """
    marker = " [truncated]" if turn.truncated else ""
    header = f"#### {_STAGE_LABELS[turn.stage]} — {turn.side} {turn.role.title()}{marker}"
    return [header, "", turn.text, ""]


def _render_verdict(turn: Turn) -> list[str]:
    """Render the Judge-verdict turn as a heading and a Markdown blockquote.

    The turn's first line (its required verdict headline, per
    `agents.build_judge_system_prompt`) is rendered bolded on its own quoted
    line, verbatim -- whatever it actually is, compliant or not -- followed
    by a blank quoted line and the rest of the turn's text.

    Args:
        turn: The question's `stage == "verdict"` turn.

    Returns:
        The lines for the Judge Verdict section, not yet joined.
    """
    headline, _, rest = turn.text.partition("\n")
    body = f"**{headline.strip()}**"
    rest = rest.strip()
    if rest:
        body += "\n\n" + rest
    return ["### ⚖️ Judge Verdict", "", _blockquote(body), ""]


def render_gist_markdown(
    debate: Debate,
    questions: list[Question],
    turns_by_question: dict[int, list[Turn]],
) -> str:
    """Render a full debate transcript as one gist-ready Markdown document.

    Args:
        debate: The debate's persisted row.
        questions: Every question in the debate, in `question_index` order
            (as `Store.list_questions` already returns).
        turns_by_question: Maps each question's id to its turns, each list
            already in the order `Store.list_turns` returns them -- actual
            persisted/run order, never an order this function imposes
            itself (the huddle's two Researcher turns run concurrently, so
            their relative order is not fixed FOR-then-AGAINST).

    Returns:
        The complete Markdown document as one string.
    """
    lines: list[str] = [f"# 🏟️ Debate: {debate.topic}", ""]
    noun = "question" if len(questions) == 1 else "questions"
    lines.append(
        f"Topic: **{debate.topic}** · {len(questions)} {noun} · structured 3-vs-3 agent "
        "debate (huddle → openings → rebuttals → closings → judge verdict), "
        "web-search-backed evidence."
    )
    lines.append("")
    lines.append("## Results at a glance")
    lines.append("")
    lines.append("| # | Question | Verdict |")
    lines.append("|---|---|---|")
    for question in questions:
        qn = question.question_index + 1
        turns = turns_by_question.get(question.id, [])
        verdict_turn = next((t for t in turns if t.stage == "verdict"), None)
        lines.append(f"| [Q{qn}](#q{qn}) | {question.text} | {_verdict_cell(verdict_turn)} |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for question in questions:
        qn = question.question_index + 1
        lines.append(f'<a id="q{qn}"></a>')
        lines.append(f"## Q{qn}: {question.text}")
        lines.append("")
        for turn in turns_by_question.get(question.id, []):
            if turn.stage == "verdict":
                lines.extend(_render_verdict(turn))
            else:
                lines.extend(_render_turn(turn))

    lines.append(_FOOTER)
    return "\n".join(lines)
