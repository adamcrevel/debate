"""Command-line interface for the `debate` console script.

Six subcommands cover the requirements this CLI implements:

* ``debate start``  -- create a new debate (Requirement 1).
* ``debate ask``     -- run one human-supplied question through the pipeline
  (Requirement 3).
* ``debate auto``    -- run N consecutive Host-generated questions
  (Requirement 4).
* ``debate show``    -- print a debate's full persisted transcript
  (Requirement 11).
* ``debate list``    -- list every persisted debate (Requirement 12).
* ``debate export``  -- render a debate as gist-ready Markdown, optionally
  publishing it as a GitHub gist (gist-export feature, Requirements 1-9).

Layering boundary: this module never spawns an OS process directly for a
model call -- every `omp` call happens inside
`engine.run_question`/`engine.generate_next_question`, which route through
`omp_client.py`. This module only ever calls `asyncio.run` on those two
coroutines for model calls; it never imports `subprocess` or
`asyncio.create_subprocess_exec` itself. `cmd_export`'s `--publish` path
calls `gist_publish.publish_gist`, which is the only other module allowed
to shell out (to `gh`, not `omp`) -- this module still never calls
`subprocess` directly even for that.

**Active-debate resolution.** Since each CLI invocation is a separate process
with no shared in-memory state, there is no "current debate" kept between
calls. `debate start` prints the new debate's id so a caller can remember it.
`debate ask` and `debate auto` accept an optional `--debate-id`; when it is
omitted, they operate on the *most recently created* debate (the last entry
of `Store.list_debates()`, which is ordered oldest first). An LLM-driven
caller (see the `debate` omp skill) should prefer passing `--debate-id`
explicitly once it knows one, and only rely on the "most recent" fallback
immediately after `debate start`.

**Config-override semantics for `ask`/`auto`.** A debate's `model`,
`max_rebuttal_rounds`, `max_minutes`, and `judge_enabled` are fixed at
`debate start` time and persisted on the debate row. `debate ask`/`debate
auto` accept the same `--model`/`--max-rebuttal-rounds`/`--max-minutes`/
`--no-judge` flags, but only as *per-invocation overrides for that one call*
-- the debate row itself is never modified. Any flag left unset falls back to
the debate's stored value. `--no-judge` can only force the verdict stage off
for this call; it can never force a debate that was created with
`judge_enabled=False` back on.
"""

import argparse
import asyncio
import sys
import textwrap

from . import engine, render
from .config import DebateConfig
from .gist_publish import GistPublishError, publish_gist
from .store import DEFAULT_DB_PATH, Debate, Store


def _resolve_debate_id(store: Store, debate_id: int | None) -> int:
    """Resolve which debate a command targets.

    Args:
        store: The open `Store` to query.
        debate_id: The `--debate-id` the user supplied, or `None`.

    Returns:
        `debate_id` unchanged if given. Otherwise the id of the most
        recently created debate -- `store.list_debates()` is ordered oldest
        first, so that is the last element of that list.

    Raises:
        SystemExit: If `debate_id` is `None` and no debate has been created
            yet.
    """
    if debate_id is not None:
        return debate_id
    debates = store.list_debates()
    if not debates:
        print(
            "Error: no debates found. Run `debate start --topic ...` first.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return debates[-1].id


def _require_debate(store: Store, debate_id: int) -> Debate:
    """Fetch a debate by id or exit cleanly if it does not exist.

    Args:
        store: The open `Store` to query.
        debate_id: The debate's row id.

    Returns:
        The matching `Debate`.

    Raises:
        SystemExit: If no debate with `debate_id` exists.
    """
    debate = store.get_debate(debate_id)
    if debate is None:
        print(f"Error: no debate with id {debate_id}.", file=sys.stderr)
        raise SystemExit(1)
    return debate


def _build_config(debate: Debate, args: argparse.Namespace) -> DebateConfig:
    """Build a `DebateConfig` for `ask`/`auto` from a debate's stored settings.

    Any of `args.model`/`args.max_rebuttal_rounds`/`args.max_minutes` that
    was explicitly set on this invocation overrides the debate's stored
    value for this call only; unset ones (left `None` by the subparsers'
    defaults) fall back to the stored value. `args.no_judge` can only force
    the verdict stage off, never force it back on.

    Args:
        debate: The target debate's persisted row.
        args: Parsed CLI args for an `ask` or `auto` invocation.

    Returns:
        A `DebateConfig` reflecting the debate's stored settings with this
        invocation's overrides applied.
    """
    return DebateConfig(
        topic=debate.topic,
        model=args.model if args.model is not None else debate.model,
        max_rebuttal_rounds=(
            args.max_rebuttal_rounds
            if args.max_rebuttal_rounds is not None
            else debate.max_rebuttal_rounds
        ),
        max_minutes=args.max_minutes if args.max_minutes is not None else debate.max_minutes,
        judge_enabled=False if args.no_judge else debate.judge_enabled,
    )


def cmd_start(args: argparse.Namespace) -> None:
    """Handle `debate start`: validate the topic, create a debate, print its id.

    A blank/whitespace-only `--topic` is rejected with a clean error message
    on stderr and exit code 1 -- `DebateConfig`'s `ValueError` is caught here
    rather than propagating as a raw traceback -- and no debate row is
    created in that case.
    """
    try:
        config = DebateConfig(
            topic=args.topic,
            model=args.model,
            max_rebuttal_rounds=args.max_rebuttal_rounds,
            max_minutes=args.max_minutes,
            judge_enabled=not args.no_judge,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None

    with Store(args.db_path) as store:
        debate_id = store.create_debate(
            topic=config.topic,
            model=config.model,
            max_rebuttal_rounds=config.max_rebuttal_rounds,
            max_minutes=config.max_minutes,
            judge_enabled=config.judge_enabled,
        )
    print(f"Created debate {debate_id}: {config.topic}")


def cmd_ask(args: argparse.Namespace) -> None:
    """Handle `debate ask`: run one question through the pipeline on the target debate.

    See the module docstring for active-debate resolution and
    config-override semantics.
    """
    with Store(args.db_path) as store:
        debate_id = _resolve_debate_id(store, args.debate_id)
        debate = _require_debate(store, debate_id)
        config = _build_config(debate, args)
        question_id = asyncio.run(engine.run_question(store, debate_id, args.question, config))
    print(f"Question {question_id} complete on debate {debate_id}: {args.question}")


async def _run_auto(store: Store, debate_id: int, count: int, config: DebateConfig) -> None:
    """Generate and run `count` consecutive Host-generated questions, sequentially.

    Each iteration generates one question via `engine.generate_next_question`
    (which sees every question already asked in this debate, including ones
    generated by earlier iterations of this same loop) and then runs it via
    `engine.run_question`, printing progress as each step completes rather
    than collecting output to print after the whole loop finishes.

    Args:
        store: The `Store` the target debate and its history live in.
        debate_id: The target debate's row id.
        count: How many questions to generate and run.
        config: The resolved `DebateConfig` for every question this call runs.
    """
    for i in range(count):
        question_text = await engine.generate_next_question(store, debate_id, config)
        print(f"[{i + 1}/{count}] Generated question: {question_text}")
        question_id = await engine.run_question(store, debate_id, question_text, config)
        print(f"[{i + 1}/{count}] Question {question_id} complete on debate {debate_id}.")


def cmd_auto(args: argparse.Namespace) -> None:
    """Handle `debate auto`: run `--count` consecutive Host-generated questions.

    See the module docstring for active-debate resolution and
    config-override semantics; identical to `debate ask` except the question
    text comes from `engine.generate_next_question` instead of the command
    line, and runs `--count` times in one `asyncio.run` call.
    """
    with Store(args.db_path) as store:
        debate_id = _resolve_debate_id(store, args.debate_id)
        debate = _require_debate(store, debate_id)
        config = _build_config(debate, args)
        asyncio.run(_run_auto(store, debate_id, args.count, config))


def cmd_show(args: argparse.Namespace) -> None:
    """Handle `debate show`: print one debate's full persisted transcript.

    Prints a header with the debate's id/topic/creation time, then for each
    question (in `question_index` order) its text followed by every turn, in
    the order they were actually persisted (which is the order the pipeline
    actually ran them in), labeled by stage/side/role, with a
    `[truncated]` marker on any turn whose truncation backstop fired.
    """
    with Store(args.db_path) as store:
        debate = _require_debate(store, args.debate_id)
        questions = store.list_questions(debate.id)
        print(f"Debate {debate.id}: {debate.topic}")
        print(f"Created: {debate.created_at}")
        if not questions:
            print("\n(no questions yet)")
            return
        for question in questions:
            print(f"\nQ{question.question_index + 1}: {question.text}")
            for turn in store.list_turns(question.id):
                label = f"{turn.side} {turn.role}" if turn.side else turn.role
                marker = " [truncated]" if turn.truncated else ""
                print(f"\n  [{turn.stage}] {label}{marker}:")
                print(textwrap.indent(turn.text, "    "))


def cmd_list(args: argparse.Namespace) -> None:
    """Handle `debate list`: print every persisted debate, oldest first.

    Each row shows the debate's id, topic, question count, and creation
    time.
    """
    with Store(args.db_path) as store:
        debates = store.list_debates()
    if not debates:
        print("No debates found.")
        return
    for summary in debates:
        print(
            f"{summary.id}\t{summary.topic}\t"
            f"{summary.question_count} question(s)\t{summary.created_at}"
        )


def cmd_export(args: argparse.Namespace) -> None:
    """Handle `debate export`: render a debate as gist-ready Markdown.

    Fetches the debate, its questions, and every question's turns, renders
    them with `render.render_gist_markdown`, and either prints the result
    to stdout or -- with `--publish` -- creates a GitHub gist containing it
    via `gist_publish.publish_gist` and prints the resulting URL instead.
    `--public` only makes sense together with `--publish`; passing it alone
    is a clean usage error, not a silently-ignored flag.
    """
    if args.public and not args.publish:
        print("Error: --public only makes sense together with --publish.", file=sys.stderr)
        raise SystemExit(1)

    with Store(args.db_path) as store:
        debate = _require_debate(store, args.debate_id)
        questions = store.list_questions(debate.id)
        turns_by_question = {q.id: store.list_turns(q.id) for q in questions}

    markdown = render.render_gist_markdown(debate, questions, turns_by_question)

    if not args.publish:
        print(markdown)
        return

    try:
        url = publish_gist(
            markdown, filename=f"debate-{debate.id}-transcript.md", public=args.public
        )
    except GistPublishError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
    print(url)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level `argparse.ArgumentParser` with all six subcommands.

    Returns:
        A fully configured parser; `main()` calls `parse_args()` on it and
        dispatches via each subcommand's `set_defaults(func=...)`.
    """
    parser = argparse.ArgumentParser(
        prog="debate",
        description=(
            "Run structured, evidence-grounded debates via the omp CLI. "
            "Two 3-agent teams (FOR and AGAINST) argue a question through a "
            "huddle -> openings -> rebuttal -> closings -> verdict pipeline."
        ),
    )
    parser.add_argument(
        "--db-path",
        default=str(DEFAULT_DB_PATH),
        help=f"Path to the SQLite database file (default: {DEFAULT_DB_PATH}).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Create a new debate.")
    start.add_argument("--topic", required=True, help="The debate's topic (required, non-blank).")
    start.add_argument(
        "--model",
        default=None,
        help="Model name passed to omp's --model flag (default: omp's own configured default).",
    )
    start.add_argument(
        "--max-rebuttal-rounds",
        type=int,
        default=2,
        help="Max rebuttal rounds, one round = one turn per side (default: 2).",
    )
    start.add_argument(
        "--max-minutes",
        type=float,
        default=10,
        help="Wall-clock budget in minutes for the rebuttal loop (default: 10).",
    )
    start.add_argument(
        "--no-judge",
        action="store_true",
        help="Disable the verdict stage for this debate (default: judge enabled).",
    )
    start.set_defaults(func=cmd_start)

    ask = subparsers.add_parser(
        "ask", help="Run one question through the pipeline on a debate."
    )
    ask.add_argument("question", help="The question text to debate.")
    ask.add_argument(
        "--debate-id",
        type=int,
        default=None,
        help="Which debate to target (default: the most recently created debate).",
    )
    ask.add_argument(
        "--model", default=None, help="Override this debate's model for this question only."
    )
    ask.add_argument(
        "--max-rebuttal-rounds",
        type=int,
        default=None,
        help="Override this debate's rebuttal-round limit for this question only.",
    )
    ask.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        help="Override this debate's wall-clock budget for this question only.",
    )
    ask.add_argument(
        "--no-judge",
        action="store_true",
        help=(
            "Force-disable the verdict stage for this question only "
            "(cannot re-enable a debate-level disabled judge)."
        ),
    )
    ask.set_defaults(func=cmd_ask)

    auto = subparsers.add_parser(
        "auto", help="Run N consecutive Host-generated questions, no human input."
    )
    auto.add_argument(
        "--count", type=int, required=True, help="How many questions to generate and run."
    )
    auto.add_argument(
        "--debate-id",
        type=int,
        default=None,
        help="Which debate to target (default: the most recently created debate).",
    )
    auto.add_argument(
        "--model", default=None, help="Override this debate's model for these questions."
    )
    auto.add_argument(
        "--max-rebuttal-rounds",
        type=int,
        default=None,
        help="Override this debate's rebuttal-round limit for these questions.",
    )
    auto.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        help="Override this debate's wall-clock budget for these questions.",
    )
    auto.add_argument(
        "--no-judge",
        action="store_true",
        help=(
            "Force-disable the verdict stage for these questions "
            "(cannot re-enable a debate-level disabled judge)."
        ),
    )
    auto.set_defaults(func=cmd_auto)

    show = subparsers.add_parser("show", help="Print a debate's full persisted transcript.")
    show.add_argument("debate_id", type=int, help="The debate's id.")
    show.set_defaults(func=cmd_show)

    list_cmd = subparsers.add_parser("list", help="List every persisted debate.")
    list_cmd.set_defaults(func=cmd_list)

    export = subparsers.add_parser(
        "export", help="Render a debate as gist-ready Markdown, optionally publishing it."
    )
    export.add_argument("debate_id", type=int, help="The debate's id.")
    export.add_argument(
        "--publish",
        action="store_true",
        help="Create a GitHub gist (via gh) containing the rendered Markdown and print its URL.",
    )
    export.add_argument(
        "--public",
        action="store_true",
        help="With --publish, create a public gist instead of the default secret one.",
    )
    export.set_defaults(func=cmd_export)

    return parser


def main() -> None:
    """Entry point for the `debate` console script.

    Parses `sys.argv`, then dispatches to the matched subcommand's handler
    (one of `cmd_start`/`cmd_ask`/`cmd_auto`/`cmd_show`/`cmd_list`).
    """
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
