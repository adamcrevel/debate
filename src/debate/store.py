"""SQLite persistence for debates, questions, and turns.

Uses only the stdlib `sqlite3` module -- no ORM. Schema creation is
idempotent (`CREATE TABLE IF NOT EXISTS`), so opening a `Store` against an
existing database file is safe to repeat.

Citation handling: `Store.create_turn` always extracts citation URLs from the
turn's own `text` itself (via `extract_citations`) rather than accepting a
pre-extracted list -- this keeps the citations column a derived fact of the
stored text, so it can never drift out of sync with it.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DEFAULT_DB_PATH = Path.home() / ".debate" / "debate.db"

_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS debates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    model TEXT,
    max_rebuttal_rounds INTEGER NOT NULL,
    max_minutes REAL NOT NULL,
    judge_enabled INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    debate_id INTEGER NOT NULL REFERENCES debates(id),
    text TEXT NOT NULL,
    question_index INTEGER NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    side TEXT,
    role TEXT NOT NULL,
    stage TEXT NOT NULL,
    model_used TEXT,
    text TEXT NOT NULL,
    citations TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ended_at TEXT NOT NULL,
    truncated INTEGER NOT NULL
);
"""


def extract_citations(text: str) -> list[str]:
    """Extract citation URLs from free-form turn text.

    Finds every `http://` or `https://` substring, stopping at whitespace or
    an enclosing bracket/quote character, and returns them in the order they
    appear. Duplicate URLs are preserved (a turn may cite the same source
    twice); callers that want uniqueness should dedupe themselves.

    Args:
        text: The turn's full text.

    Returns:
        A list of URL strings, possibly empty.
    """
    return _URL_RE.findall(text)


def _now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


@dataclass
class Debate:
    """A persisted debate row."""

    id: int
    topic: str
    model: str | None
    max_rebuttal_rounds: int
    max_minutes: float
    judge_enabled: bool
    created_at: str


@dataclass
class DebateSummary:
    """A debate row annotated with its question count, for `debate list`."""

    id: int
    topic: str
    created_at: str
    question_count: int


@dataclass
class Question:
    """A persisted question row."""

    id: int
    debate_id: int
    text: str
    question_index: int
    created_at: str


@dataclass
class Turn:
    """A persisted turn row."""

    id: int
    question_id: int
    side: str | None
    role: str
    stage: str
    model_used: str | None
    text: str
    citations: list[str]
    started_at: str
    ended_at: str
    truncated: bool


class Store:
    """Wraps a SQLite connection and provides CRUD for debates/questions/turns.

    Opening a `Store` creates the database file's parent directory and the
    schema (idempotently) if they do not already exist. Pass `":memory:"` or
    a `tmp_path`-based file for test isolation.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        """Open (or create) the database at `db_path` and ensure its schema.

        Args:
            db_path: Filesystem path to the SQLite file, or the special
                string `":memory:"` for an in-memory database. Defaults to
                `~/.debate/debate.db`.
        """
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        """Close the underlying SQLite connection."""
        self._conn.close()

    def __enter__(self) -> "Store":
        """Return self, so `Store` can be used as a context manager."""
        return self

    def __exit__(self, *exc_info: object) -> None:
        """Close the connection on context-manager exit."""
        self.close()

    def create_debate(
        self,
        topic: str,
        model: str | None = None,
        max_rebuttal_rounds: int = 2,
        max_minutes: float = 10,
        judge_enabled: bool = True,
    ) -> int:
        """Insert a new debate row and return its id.

        Args:
            topic: The debate's topic.
            model: The model name used for this debate, or `None`.
            max_rebuttal_rounds: Configured rebuttal-round limit.
            max_minutes: Configured wall-clock budget for the rebuttal loop.
            judge_enabled: Whether a verdict stage runs for this debate.

        Returns:
            The new debate's row id.
        """
        cur = self._conn.execute(
            "INSERT INTO debates "
            "(topic, model, max_rebuttal_rounds, max_minutes, judge_enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (topic, model, max_rebuttal_rounds, max_minutes, int(judge_enabled), _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    def get_debate(self, debate_id: int) -> Debate | None:
        """Fetch one debate by id, or `None` if it does not exist.

        Args:
            debate_id: The debate's row id.

        Returns:
            A `Debate`, or `None` if no such debate exists.
        """
        row = self._conn.execute(
            "SELECT * FROM debates WHERE id = ?", (debate_id,)
        ).fetchone()
        if row is None:
            return None
        return Debate(
            id=row["id"],
            topic=row["topic"],
            model=row["model"],
            max_rebuttal_rounds=row["max_rebuttal_rounds"],
            max_minutes=row["max_minutes"],
            judge_enabled=bool(row["judge_enabled"]),
            created_at=row["created_at"],
        )

    def list_debates(self) -> list[DebateSummary]:
        """List every persisted debate, oldest first, with its question count.

        Returns:
            A list of `DebateSummary`, ordered by `created_at` ascending
            (ties broken by id), each carrying its topic, question count,
            and creation time -- what `debate list` (Requirement 12) needs.
        """
        rows = self._conn.execute(
            "SELECT d.id, d.topic, d.created_at, COUNT(q.id) AS question_count "
            "FROM debates d LEFT JOIN questions q ON q.debate_id = d.id "
            "GROUP BY d.id ORDER BY d.created_at ASC, d.id ASC"
        ).fetchall()
        return [
            DebateSummary(
                id=row["id"],
                topic=row["topic"],
                created_at=row["created_at"],
                question_count=row["question_count"],
            )
            for row in rows
        ]

    def create_question(self, debate_id: int, text: str, question_index: int) -> int:
        """Insert a new question row under `debate_id` and return its id.

        Args:
            debate_id: The owning debate's row id.
            text: The question text.
            question_index: This question's position within its debate
                (0-based), used to order `debate auto`-generated questions.

        Returns:
            The new question's row id.
        """
        cur = self._conn.execute(
            "INSERT INTO questions (debate_id, text, question_index, created_at) "
            "VALUES (?, ?, ?, ?)",
            (debate_id, text, question_index, _now()),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_questions(self, debate_id: int) -> list[Question]:
        """List every question in a debate, ordered by `question_index`.

        Args:
            debate_id: The owning debate's row id.

        Returns:
            A list of `Question`, ordered by `question_index` ascending.
        """
        rows = self._conn.execute(
            "SELECT * FROM questions WHERE debate_id = ? ORDER BY question_index ASC, id ASC",
            (debate_id,),
        ).fetchall()
        return [
            Question(
                id=row["id"],
                debate_id=row["debate_id"],
                text=row["text"],
                question_index=row["question_index"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def create_turn(
        self,
        question_id: int,
        role: str,
        stage: str,
        text: str,
        started_at: str,
        ended_at: str,
        truncated: bool,
        side: str | None = None,
        model_used: str | None = None,
    ) -> int:
        """Insert a new turn row and return its id.

        Citations are always derived from `text` via `extract_citations` --
        callers never pass citations directly, so the stored list can never
        diverge from what the turn's own text actually contains.

        Args:
            question_id: The owning question's row id.
            role: The speaking agent's role (e.g. "lead", "researcher",
                "rebuttal", "judge", "host").
            stage: The pipeline stage this turn belongs to (e.g. "huddle",
                "opening", "rebuttal", "closing", "verdict").
            text: The turn's full (already-truncated-if-applicable) text.
            started_at: ISO-8601 timestamp when the turn began.
            ended_at: ISO-8601 timestamp when the turn ended.
            truncated: Whether the 200-word truncation backstop fired for
                this turn.
            side: "FOR" or "AGAINST", or `None` for a non-team speaker (the
                Judge or the Host).
            model_used: The model name actually used for this turn.

        Returns:
            The new turn's row id.
        """
        citations = extract_citations(text)
        cur = self._conn.execute(
            "INSERT INTO turns "
            "(question_id, side, role, stage, model_used, text, citations, "
            " started_at, ended_at, truncated) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                question_id,
                side,
                role,
                stage,
                model_used,
                text,
                json.dumps(citations),
                started_at,
                ended_at,
                int(truncated),
            ),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_turns(self, question_id: int) -> list[Turn]:
        """List every turn for a question, in the order they were created.

        Insertion order is turn creation order, which is the actual stage
        order the pipeline ran in -- so this is also the order a transcript
        should render in for `debate show` (Requirement 11).

        Args:
            question_id: The owning question's row id.

        Returns:
            A list of `Turn`, ordered by row id ascending.
        """
        rows = self._conn.execute(
            "SELECT * FROM turns WHERE question_id = ? ORDER BY id ASC",
            (question_id,),
        ).fetchall()
        return [
            Turn(
                id=row["id"],
                question_id=row["question_id"],
                side=row["side"],
                role=row["role"],
                stage=row["stage"],
                model_used=row["model_used"],
                text=row["text"],
                citations=json.loads(row["citations"]),
                started_at=row["started_at"],
                ended_at=row["ended_at"],
                truncated=bool(row["truncated"]),
            )
            for row in rows
        ]
