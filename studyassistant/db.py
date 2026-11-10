"""SQLite log of questions and quiz scores, for the teacher view.

Everything stays on the lab PC; students are not identified.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    asked_at REAL NOT NULL,
    unit_id TEXT NOT NULL,
    question TEXT NOT NULL,
    language TEXT NOT NULL,
    answered INTEGER NOT NULL          -- 0 when "not in the textbook"
);
CREATE TABLE IF NOT EXISTS quizzes (
    id TEXT PRIMARY KEY,
    created_at REAL NOT NULL,
    unit_id TEXT NOT NULL,
    language TEXT NOT NULL,
    questions_json TEXT NOT NULL       -- includes answers; never sent to students
);
CREATE TABLE IF NOT EXISTS quiz_attempts (
    id INTEGER PRIMARY KEY,
    quiz_id TEXT NOT NULL REFERENCES quizzes(id),
    submitted_at REAL NOT NULL,
    score INTEGER NOT NULL,
    total INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden_units (
    unit_id TEXT PRIMARY KEY
);
CREATE INDEX IF NOT EXISTS idx_questions_unit ON questions(unit_id);
"""


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(_SCHEMA)

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    # ---------------------------------------------------------------- logging

    def log_question(self, unit_id: str, question: str, language: str, answered: bool) -> None:
        self._execute(
            "INSERT INTO questions (asked_at, unit_id, question, language, answered) VALUES (?, ?, ?, ?, ?)",
            (time.time(), unit_id, question.strip(), language, int(answered)),
        )

    def save_quiz(self, quiz_id: str, unit_id: str, language: str, questions: list[dict]) -> None:
        self._execute(
            "INSERT INTO quizzes (id, created_at, unit_id, language, questions_json) VALUES (?, ?, ?, ?, ?)",
            (quiz_id, time.time(), unit_id, language, json.dumps(questions, ensure_ascii=False)),
        )

    def get_quiz(self, quiz_id: str) -> dict | None:
        row = self._execute("SELECT * FROM quizzes WHERE id = ?", (quiz_id,)).fetchone()
        if row is None:
            return None
        return {
            "id": row["id"],
            "unit_id": row["unit_id"],
            "language": row["language"],
            "questions": json.loads(row["questions_json"]),
        }

    def log_attempt(self, quiz_id: str, score: int, total: int) -> None:
        self._execute(
            "INSERT INTO quiz_attempts (quiz_id, submitted_at, score, total) VALUES (?, ?, ?, ?)",
            (quiz_id, time.time(), score, total),
        )

    # ------------------------------------------------------------- visibility

    def hidden_units(self) -> set[str]:
        return {r["unit_id"] for r in self._execute("SELECT unit_id FROM hidden_units").fetchall()}

    def set_unit_hidden(self, unit_id: str, hidden: bool) -> None:
        if hidden:
            self._execute("INSERT OR IGNORE INTO hidden_units (unit_id) VALUES (?)", (unit_id,))
        else:
            self._execute("DELETE FROM hidden_units WHERE unit_id = ?", (unit_id,))

    # ------------------------------------------------------------ teacher view

    def unit_stats(self) -> dict[str, dict]:
        """Per unit: question counts, unanswered count, quiz attempts and average %."""
        stats: dict[str, dict] = {}
        for row in self._execute(
            """SELECT unit_id, COUNT(*) AS asked, SUM(1 - answered) AS unanswered
               FROM questions GROUP BY unit_id"""
        ).fetchall():
            stats.setdefault(row["unit_id"], {}).update(
                questions=row["asked"], unanswered=row["unanswered"] or 0
            )
        for row in self._execute(
            """SELECT q.unit_id, COUNT(a.id) AS attempts,
                      AVG(100.0 * a.score / a.total) AS avg_pct
               FROM quiz_attempts a JOIN quizzes q ON q.id = a.quiz_id
               WHERE a.total > 0 GROUP BY q.unit_id"""
        ).fetchall():
            stats.setdefault(row["unit_id"], {}).update(
                quiz_attempts=row["attempts"], quiz_average=round(row["avg_pct"], 1)
            )
        for value in stats.values():
            value.setdefault("questions", 0)
            value.setdefault("unanswered", 0)
            value.setdefault("quiz_attempts", 0)
            value.setdefault("quiz_average", None)
        return stats

    def top_questions(self, unit_id: str, limit: int = 5) -> list[dict]:
        """Most-asked questions in a unit (case and spacing ignored)."""
        rows = self._execute(
            """SELECT LOWER(TRIM(question)) AS q, COUNT(*) AS n,
                      MIN(answered) AS ever_unanswered_is_zero
               FROM questions WHERE unit_id = ?
               GROUP BY q ORDER BY n DESC, MAX(asked_at) DESC LIMIT ?""",
            (unit_id, limit),
        ).fetchall()
        return [
            {"question": r["q"], "count": r["n"], "answered": bool(r["ever_unanswered_is_zero"])}
            for r in rows
        ]
