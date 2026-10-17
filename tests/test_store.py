"""Tests for debate.store.Store."""

import pytest

from debate.store import Store, extract_citations


@pytest.fixture
def store():
    """An isolated in-memory Store, closed automatically after the test."""
    s = Store(":memory:")
    yield s
    s.close()


def test_schema_creates_cleanly(store):
    """Opening a Store creates all three tables without error."""
    tables = {
        row[0]
        for row in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"debates", "questions", "turns"} <= tables


def test_schema_creation_is_idempotent(tmp_path):
    """Reopening a Store against the same file does not error or drop data."""
    db_path = tmp_path / "debate.db"
    first = Store(db_path)
    debate_id = first.create_debate(topic="Reopen test")
    first.close()

    second = Store(db_path)
    try:
        assert second.get_debate(debate_id).topic == "Reopen test"
    finally:
        second.close()


def test_create_and_get_debate(store):
    """A created debate round-trips every field through get_debate."""
    debate_id = store.create_debate(
        topic="Is AI net positive?",
        model="gpt-5",
        max_rebuttal_rounds=3,
        max_minutes=15,
        judge_enabled=False,
    )

    debate = store.get_debate(debate_id)

    assert debate.id == debate_id
    assert debate.topic == "Is AI net positive?"
    assert debate.model == "gpt-5"
    assert debate.max_rebuttal_rounds == 3
    assert debate.max_minutes == 15
    assert debate.judge_enabled is False
    assert debate.created_at


def test_get_debate_missing_returns_none(store):
    """get_debate returns None for an id that was never created."""
    assert store.get_debate(9999) is None


def test_create_and_list_questions(store):
    """Questions are listed in question_index order, regardless of insert order."""
    debate_id = store.create_debate(topic="Topic")
    q1 = store.create_question(debate_id, "First question?", question_index=0)
    q2 = store.create_question(debate_id, "Second question?", question_index=1)

    questions = store.list_questions(debate_id)

    assert [q.id for q in questions] == [q1, q2]
    assert [q.text for q in questions] == ["First question?", "Second question?"]
    assert [q.question_index for q in questions] == [0, 1]


def test_list_questions_scoped_to_debate(store):
    """list_questions never returns another debate's questions."""
    debate_a = store.create_debate(topic="A")
    debate_b = store.create_debate(topic="B")
    store.create_question(debate_a, "A question", question_index=0)
    store.create_question(debate_b, "B question", question_index=0)

    questions_a = store.list_questions(debate_a)

    assert len(questions_a) == 1
    assert questions_a[0].text == "A question"


def test_extract_citations_finds_urls():
    """extract_citations pulls every http(s) URL out of free text, in order."""
    text = (
        "See https://example.com/a and also (https://example.org/b) "
        "for details, no other links here."
    )
    assert extract_citations(text) == [
        "https://example.com/a",
        "https://example.org/b",
    ]


def test_extract_citations_empty_when_no_urls():
    """extract_citations returns an empty list when the text has no URL."""
    assert extract_citations("No links in this sentence at all.") == []


def test_create_turn_auto_extracts_citations(store):
    """create_turn derives citations from the turn's own text, not a param."""
    debate_id = store.create_debate(topic="Topic")
    question_id = store.create_question(debate_id, "Q?", question_index=0)

    turn_id = store.create_turn(
        question_id=question_id,
        role="lead",
        stage="opening",
        text="I cite https://example.com/evidence as proof.",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:00:05Z",
        truncated=False,
        side="FOR",
        model_used="gpt-5",
    )

    turns = store.list_turns(question_id)
    assert len(turns) == 1
    turn = turns[0]
    assert turn.id == turn_id
    assert turn.role == "lead"
    assert turn.text == "I cite https://example.com/evidence as proof."
    assert turn.model_used == "gpt-5"
    assert turn.started_at == "2026-01-01T00:00:00Z"
    assert turn.ended_at == "2026-01-01T00:00:05Z"
    assert turn.citations == ["https://example.com/evidence"]


def test_create_turn_no_urls_gives_empty_citations(store):
    """A turn whose text has no URL round-trips an empty citations list."""
    debate_id = store.create_debate(topic="Topic")
    question_id = store.create_question(debate_id, "Q?", question_index=0)

    store.create_turn(
        question_id=question_id,
        role="rebuttal",
        stage="rebuttal",
        text="No links in this argument.",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:00:05Z",
        truncated=False,
        side="AGAINST",
    )

    turn = store.list_turns(question_id)[0]
    assert turn.citations == []


@pytest.mark.parametrize("truncated_value", [True, False])
def test_create_turn_truncated_flag_round_trips(store, truncated_value):
    """The truncated flag survives storage and retrieval as the right bool."""
    debate_id = store.create_debate(topic="Topic")
    question_id = store.create_question(debate_id, "Q?", question_index=0)

    store.create_turn(
        question_id=question_id,
        role="judge",
        stage="verdict",
        text="Verdict text.",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-01-01T00:00:05Z",
        truncated=truncated_value,
    )

    turn = store.list_turns(question_id)[0]
    assert turn.truncated is truncated_value
    assert isinstance(turn.truncated, bool)


def test_list_turns_orders_by_creation_order(store):
    """list_turns returns turns in the order they were created (stage order)."""
    debate_id = store.create_debate(topic="Topic")
    question_id = store.create_question(debate_id, "Q?", question_index=0)

    store.create_turn(
        question_id=question_id,
        role="lead",
        stage="opening",
        text="FOR opens.",
        started_at="t0",
        ended_at="t1",
        truncated=False,
        side="FOR",
    )
    store.create_turn(
        question_id=question_id,
        role="lead",
        stage="opening",
        text="AGAINST opens.",
        started_at="t2",
        ended_at="t3",
        truncated=False,
        side="AGAINST",
    )
    store.create_turn(
        question_id=question_id,
        role="rebuttal",
        stage="rebuttal",
        text="AGAINST rebuts.",
        started_at="t4",
        ended_at="t5",
        truncated=False,
        side="AGAINST",
    )

    turns = store.list_turns(question_id)

    assert [t.stage for t in turns] == ["opening", "opening", "rebuttal"]
    assert [t.side for t in turns] == ["FOR", "AGAINST", "AGAINST"]


def test_list_turns_scoped_to_question(store):
    """list_turns never returns another question's turns."""
    debate_id = store.create_debate(topic="Topic")
    q1 = store.create_question(debate_id, "Q1?", question_index=0)
    q2 = store.create_question(debate_id, "Q2?", question_index=1)
    store.create_turn(
        question_id=q1,
        role="lead",
        stage="opening",
        text="Q1 turn.",
        started_at="t0",
        ended_at="t1",
        truncated=False,
    )

    assert len(store.list_turns(q1)) == 1
    assert store.list_turns(q2) == []


def test_list_debates_ordering_and_counts(store):
    """list_debates returns debates oldest-first with accurate question counts."""
    debate_a = store.create_debate(topic="A")
    debate_b = store.create_debate(topic="B")
    store.create_question(debate_a, "A-Q1", question_index=0)
    store.create_question(debate_a, "A-Q2", question_index=1)

    summaries = store.list_debates()

    assert [s.id for s in summaries] == [debate_a, debate_b]
    by_id = {s.id: s for s in summaries}
    assert by_id[debate_a].question_count == 2
    assert by_id[debate_b].question_count == 0
    assert by_id[debate_a].topic == "A"
    assert by_id[debate_a].created_at == store.get_debate(debate_a).created_at
    assert by_id[debate_b].created_at == store.get_debate(debate_b).created_at


def test_default_db_path_is_overridable(tmp_path):
    """A Store can be opened against a caller-supplied path, not just the default."""
    custom_path = tmp_path / "nested" / "mydebate.db"
    s = Store(custom_path)
    try:
        assert custom_path.exists()
    finally:
        s.close()
