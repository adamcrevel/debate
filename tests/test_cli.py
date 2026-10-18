"""Tests for `debate.cli`.

`engine.run_question`/`engine.generate_next_question` are always patched on
`debate.engine` so no real `omp` call ever happens (that pipeline itself is
already covered by T4's own tests in `tests/test_engine.py`) -- these tests
only prove the CLI wires arguments to the right calls. Every test points
`--db-path` at an isolated file under `tmp_path`, so none of them touch the
real `~/.debate/debate.db`.
"""

import sys

import pytest

import debate.engine as engine_module
from debate.cli import main
from debate.store import Store


@pytest.fixture
def db_path(tmp_path):
    """An isolated SQLite file path for one test, as a string for --db-path."""
    return str(tmp_path / "debate.db")


def _run_cli(monkeypatch, argv):
    """Patch sys.argv to `["debate", *argv]` and invoke `main()`."""
    monkeypatch.setattr(sys, "argv", ["debate", *argv])
    main()


def test_start_blank_topic_exits_nonzero_and_creates_no_debate(monkeypatch, capsys, db_path):
    """A blank/whitespace topic exits non-zero with a clear message, not a traceback."""
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["--db-path", db_path, "start", "--topic", "   "])
    assert exc_info.value.code != 0

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "topic" in captured.err.lower()

    with Store(db_path) as store:
        assert store.list_debates() == []


def test_start_valid_topic_creates_debate_with_config(monkeypatch, capsys, db_path):
    """A valid `start` creates exactly one debate row with the given config fields."""
    _run_cli(
        monkeypatch,
        [
            "--db-path",
            db_path,
            "start",
            "--topic",
            "Cats vs dogs",
            "--model",
            "anthropic/claude-haiku-4-5",
            "--max-rebuttal-rounds",
            "3",
            "--max-minutes",
            "5",
            "--no-judge",
        ],
    )
    captured = capsys.readouterr()
    assert "Created debate" in captured.out

    with Store(db_path) as store:
        debates = store.list_debates()
        assert len(debates) == 1
        debate = store.get_debate(debates[0].id)
        assert debate.topic == "Cats vs dogs"
        assert debate.model == "anthropic/claude-haiku-4-5"
        assert debate.max_rebuttal_rounds == 3
        assert debate.max_minutes == 5
        assert debate.judge_enabled is False


def test_ask_resolves_most_recent_debate_without_debate_id(monkeypatch, db_path):
    """`ask` with no --debate-id targets the most recently created debate."""
    with Store(db_path) as store:
        store.create_debate(topic="First")
        second_id = store.create_debate(topic="Second")

    calls = []

    async def fake_run_question(store, debate_id, question_text, config):
        calls.append((debate_id, question_text, config))
        return 42

    monkeypatch.setattr(engine_module, "run_question", fake_run_question)

    _run_cli(monkeypatch, ["--db-path", db_path, "ask", "What now?"])

    assert len(calls) == 1
    assert calls[0][0] == second_id
    assert calls[0][1] == "What now?"


def test_ask_targets_specific_debate_id(monkeypatch, db_path):
    """`ask --debate-id N` targets exactly that debate, not the most recent one."""
    with Store(db_path) as store:
        first_id = store.create_debate(topic="First")
        store.create_debate(topic="Second")

    calls = []

    async def fake_run_question(store, debate_id, question_text, config):
        calls.append(debate_id)
        return 1

    monkeypatch.setattr(engine_module, "run_question", fake_run_question)

    _run_cli(monkeypatch, ["--db-path", db_path, "ask", "Q?", "--debate-id", str(first_id)])

    assert calls == [first_id]


def test_ask_calls_run_question_with_right_debate_id_text_and_config(monkeypatch, db_path):
    """`ask` forwards debate_id/question_text, with this call's flags overriding stored defaults."""
    with Store(db_path) as store:
        debate_id = store.create_debate(
            topic="Topic",
            model="stored-model",
            max_rebuttal_rounds=3,
            max_minutes=7,
            judge_enabled=True,
        )

    calls = []

    async def fake_run_question(store, debate_id, question_text, config):
        calls.append((debate_id, question_text, config))
        return 7

    monkeypatch.setattr(engine_module, "run_question", fake_run_question)

    _run_cli(
        monkeypatch,
        [
            "--db-path",
            db_path,
            "ask",
            "Is it true?",
            "--debate-id",
            str(debate_id),
            "--model",
            "override-model",
            "--max-rebuttal-rounds",
            "5",
            "--max-minutes",
            "0.5",
            "--no-judge",
        ],
    )

    assert len(calls) == 1
    got_debate_id, question_text, config = calls[0]
    assert got_debate_id == debate_id
    assert question_text == "Is it true?"
    assert config.topic == "Topic"
    assert config.model == "override-model"
    # Overrides differ from the stored value (3/7), the DebateConfig default
    # (2/10), and the `start` parser default (2/10) all at once.
    assert config.max_rebuttal_rounds == 5
    assert config.max_minutes == 0.5
    assert config.judge_enabled is False


def test_ask_falls_back_to_stored_config_when_no_overrides_given(monkeypatch, db_path):
    """`ask` with no override flags uses the debate's stored settings, not any default."""
    with Store(db_path) as store:
        debate_id = store.create_debate(
            topic="Topic",
            model="stored-model",
            max_rebuttal_rounds=5,
            max_minutes=7.5,
            judge_enabled=True,
        )

    calls = []

    async def fake_run_question(store, debate_id, question_text, config):
        calls.append((debate_id, question_text, config))
        return 7

    monkeypatch.setattr(engine_module, "run_question", fake_run_question)

    _run_cli(
        monkeypatch,
        ["--db-path", db_path, "ask", "Is it true?", "--debate-id", str(debate_id)],
    )

    assert len(calls) == 1
    _, _, config = calls[0]
    assert config.model == "stored-model"
    # None of these match the DebateConfig/`start` default of 2 rounds / 10 minutes.
    assert config.max_rebuttal_rounds == 5
    assert config.max_minutes == 7.5
    assert config.judge_enabled is True


def test_auto_calls_generate_then_run_question_paired_in_order(monkeypatch, db_path):
    """`auto --count N` calls generate_next_question then run_question, N times, paired in order."""
    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")

    call_order = []

    async def fake_generate(store, debate_id, config):
        call_order.append("generate")
        return f"Question {len(call_order)}"

    async def fake_run_question(store, debate_id, question_text, config):
        call_order.append("run")
        return len(call_order)

    monkeypatch.setattr(engine_module, "generate_next_question", fake_generate)
    monkeypatch.setattr(engine_module, "run_question", fake_run_question)

    _run_cli(
        monkeypatch,
        ["--db-path", db_path, "auto", "--count", "3", "--debate-id", str(debate_id)],
    )

    assert call_order == ["generate", "run", "generate", "run", "generate", "run"]


def test_show_prints_topic_question_and_stages_in_order(monkeypatch, capsys, db_path):
    """`show` prints topic, every question's text (in order), and each turn's stage
    label in actual run order (not alphabetical, since 'closing' < 'huddle' alphabetically
    but closing runs after huddle)."""
    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Cats vs dogs")
        question_id = store.create_question(debate_id, "Are cats smarter?", 0)
        store.create_question(debate_id, "Are dogs friendlier?", 1)
        for side, role, stage, text in [
            ("FOR", "Researcher", "huddle", "Cats are independent."),
            ("AGAINST", "Researcher", "huddle", "Dogs are loyal."),
            ("FOR", "Lead", "opening", "Cats win because they are smart."),
            ("AGAINST", "Rebuttal", "rebuttal", "Dogs follow commands."),
            ("AGAINST", "Lead", "closing", "Dogs are the clear winner."),
            (None, "judge", "verdict", "It's a tie."),
        ]:
            store.create_turn(
                question_id=question_id,
                role=role,
                stage=stage,
                text=text,
                started_at="t0",
                ended_at="t1",
                truncated=False,
                side=side,
            )

    _run_cli(monkeypatch, ["--db-path", db_path, "show", str(debate_id)])

    out = capsys.readouterr().out
    assert "Cats vs dogs" in out
    assert "Are cats smarter?" in out
    assert "Are dogs friendlier?" in out
    assert out.index("Are cats smarter?") < out.index("Are dogs friendlier?")
    assert "Cats are independent." in out
    assert "It's a tie." in out
    assert (
        out.index("huddle")
        < out.index("opening")
        < out.index("rebuttal")
        < out.index("closing")
        < out.index("verdict")
    )


def test_list_prints_every_debate_with_topic_and_question_count(monkeypatch, capsys, db_path):
    """`list` prints every debate's topic and question count (creation time: test below)."""
    with Store(db_path) as store:
        debate_a = store.create_debate(topic="Topic A")
        store.create_question(debate_a, "Q1", 0)
        store.create_question(debate_a, "Q2", 1)
        store.create_debate(topic="Topic B")

    _run_cli(monkeypatch, ["--db-path", db_path, "list"])

    out = capsys.readouterr().out
    assert "Topic A" in out
    assert "Topic B" in out
    assert "2 question" in out
    assert "0 question" in out


def test_start_without_flags_persists_spec_defaults(monkeypatch, capsys, db_path):
    """`start` with only --topic persists the spec defaults: 2 rounds, 10 minutes, judge on."""
    _run_cli(monkeypatch, ["--db-path", db_path, "start", "--topic", "Defaults"])
    capsys.readouterr()

    with Store(db_path) as store:
        debate = store.get_debate(store.list_debates()[0].id)

    assert debate.max_rebuttal_rounds == 2
    assert debate.max_minutes == 10
    assert debate.judge_enabled is True
    assert debate.model is None


def test_list_prints_each_debate_creation_time(monkeypatch, capsys, db_path):
    """`list` prints each debate's stored creation time, one debate per line."""
    with Store(db_path) as store:
        store.create_debate(topic="Topic A")
        store.create_debate(topic="Topic B")
        created_ats = [summary.created_at for summary in store.list_debates()]

    _run_cli(monkeypatch, ["--db-path", db_path, "list"])

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2
    for created_at, line in zip(created_ats, lines, strict=True):
        assert created_at in line


def test_auto_runs_each_generated_question_text_in_order(monkeypatch, db_path):
    """`auto` feeds each Host-generated question text straight into run_question."""
    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")

    generated = ["First generated?", "Second generated?"]
    ran = []

    async def fake_generate(store, debate_id, config):
        return generated[len(ran)]

    async def fake_run_question(store, debate_id, question_text, config):
        ran.append(question_text)
        return len(ran)

    monkeypatch.setattr(engine_module, "generate_next_question", fake_generate)
    monkeypatch.setattr(engine_module, "run_question", fake_run_question)

    _run_cli(
        monkeypatch,
        ["--db-path", db_path, "auto", "--count", "2", "--debate-id", str(debate_id)],
    )

    assert ran == ["First generated?", "Second generated?"]


def test_show_marks_only_the_truncated_turn(monkeypatch, capsys, db_path):
    """`show` flags the turn whose truncation backstop fired, and leaves the other unmarked."""
    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")
        question_id = store.create_question(debate_id, "Q?", 0)
        store.create_turn(
            question_id=question_id,
            role="Lead",
            stage="opening",
            text="Short and within the limit.",
            started_at="t0",
            ended_at="t1",
            truncated=False,
            side="FOR",
        )
        store.create_turn(
            question_id=question_id,
            role="Lead",
            stage="opening",
            text="Ran long and was cut off.",
            started_at="t0",
            ended_at="t1",
            truncated=True,
            side="AGAINST",
        )

    _run_cli(monkeypatch, ["--db-path", db_path, "show", str(debate_id)])

    marked = [line for line in capsys.readouterr().out.splitlines() if "[truncated]" in line]
    assert len(marked) == 1
    assert "AGAINST" in marked[0]


def test_export_prints_rendered_markdown_without_publish(monkeypatch, capsys, db_path):
    """`export` with no --publish prints the rendered Markdown to stdout and
    never calls publish_gist."""
    import debate.cli as cli_module

    def fail_if_called(*args, **kwargs):
        raise AssertionError("publish_gist must not be called without --publish")

    monkeypatch.setattr(cli_module, "publish_gist", fail_if_called)

    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Cats vs dogs")
        question_id = store.create_question(debate_id, "Who wins?", 0)
        store.create_turn(
            question_id=question_id,
            role="Lead",
            stage="opening",
            text="Cats are better.",
            started_at="t0",
            ended_at="t1",
            truncated=False,
            side="FOR",
        )
        store.create_turn(
            question_id=question_id,
            role="judge",
            stage="verdict",
            text="FOR wins\n\nStrong case.",
            started_at="t0",
            ended_at="t1",
            truncated=False,
        )

    _run_cli(monkeypatch, ["--db-path", db_path, "export", str(debate_id)])

    out = capsys.readouterr().out
    assert "# 🏟️ Debate: Cats vs dogs" in out
    assert "🏆 FOR wins" in out
    assert "#### 🎤 Opening — FOR Lead" in out


def test_export_publish_passes_markdown_filename_and_public_flag(monkeypatch, capsys, db_path):
    """`export --publish --public` calls publish_gist with the rendered
    Markdown, a filename naming the debate id, and public=True, then prints
    only the returned URL -- not the Markdown itself."""
    import debate.cli as cli_module

    calls = []

    def fake_publish_gist(markdown, *, filename, public):
        calls.append((markdown, filename, public))
        return "https://gist.github.com/adamcrevel/fake123"

    monkeypatch.setattr(cli_module, "publish_gist", fake_publish_gist)

    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")
        question_id = store.create_question(debate_id, "Q?", 0)
        store.create_turn(
            question_id=question_id,
            role="Lead",
            stage="opening",
            text="Text.",
            started_at="t0",
            ended_at="t1",
            truncated=False,
            side="FOR",
        )

    _run_cli(
        monkeypatch, ["--db-path", db_path, "export", str(debate_id), "--publish", "--public"]
    )

    out = capsys.readouterr().out.strip()
    assert out == "https://gist.github.com/adamcrevel/fake123"
    assert len(calls) == 1
    markdown, filename, public = calls[0]
    assert f"debate-{debate_id}-transcript.md" == filename
    assert public is True
    assert "# 🏟️ Debate: Topic" in markdown


def test_export_publish_without_public_defaults_to_secret(monkeypatch, capsys, db_path):
    """`export --publish` alone (no --public) calls publish_gist with public=False."""
    import debate.cli as cli_module

    calls = []
    monkeypatch.setattr(
        cli_module,
        "publish_gist",
        lambda markdown, *, filename, public: calls.append(public) or "https://gist/x",
    )

    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")

    _run_cli(monkeypatch, ["--db-path", db_path, "export", str(debate_id), "--publish"])

    assert calls == [False]


def test_export_public_without_publish_is_a_usage_error(monkeypatch, capsys, db_path):
    """`export --public` without `--publish` exits non-zero with a clear message."""
    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["--db-path", db_path, "export", str(debate_id), "--public"])
    assert exc_info.value.code != 0

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "--publish" in captured.err


def test_export_publish_error_surfaces_clean_message(monkeypatch, capsys, db_path):
    """A GistPublishError from publish_gist surfaces as a clean error, not a traceback."""
    import debate.cli as cli_module
    from debate.gist_publish import GistPublishError

    def fake_publish_gist(markdown, *, filename, public):
        raise GistPublishError("gh is not authenticated")

    monkeypatch.setattr(cli_module, "publish_gist", fake_publish_gist)

    with Store(db_path) as store:
        debate_id = store.create_debate(topic="Topic")

    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["--db-path", db_path, "export", str(debate_id), "--publish"])
    assert exc_info.value.code != 0

    captured = capsys.readouterr()
    assert "Traceback" not in captured.err
    assert "gh is not authenticated" in captured.err


def test_export_unknown_debate_id_exits_cleanly(monkeypatch, capsys, db_path):
    """`export` for a nonexistent debate id exits cleanly, same as `show` does."""
    with pytest.raises(SystemExit) as exc_info:
        _run_cli(monkeypatch, ["--db-path", db_path, "export", "999"])
    assert exc_info.value.code != 0
    assert "no debate with id 999" in capsys.readouterr().err
