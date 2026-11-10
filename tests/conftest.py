"""Shared fixtures: a tiny curriculum, a fake model and a fresh database."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator

import numpy as np
import pytest

from studyassistant.assistant import StudyAssistant
from studyassistant.curriculum import Section, Unit, chunk_units
from studyassistant.db import Database
from studyassistant.index import SearchIndex

DIM = 256


def bag_of_words(text: str) -> np.ndarray:
    """Deterministic stand-in for an embedding model: hashed word counts."""
    vec = np.zeros(DIM, dtype=np.float32)
    for word in re.findall(r"[a-z]+", text.lower()):
        if len(word) > 2:
            vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1
    return vec


class FakeModel:
    """Implements the LanguageModel protocol with scripted replies."""

    def __init__(self) -> None:
        self.answer = "A proper subset has fewer elements than the set."
        self.json_replies: list[dict] = []
        self.calls: list[str] = []

    def embed(self, texts: list[str], kind: str) -> np.ndarray:
        return np.stack([bag_of_words(t) for t in texts]) if texts else np.zeros((0, DIM))

    def chat_stream(self, messages: list[dict]) -> Iterator[str]:
        self.calls.append("chat")
        self.last_messages = messages
        for word in self.answer.split(" "):
            yield word + " "

    def chat_json(self, messages: list[dict], schema: dict, max_tokens: int | None = None) -> dict:
        if "answers" in schema["properties"]:  # quiz verification pass
            self.calls.append("verify")
            return {"answers": self.blind_answers(messages[-1]["content"])}
        self.calls.append("json")
        self.last_messages = messages
        return self.json_replies.pop(0)

    @staticmethod
    def blind_answers(prompt: str) -> list[int]:
        """Answer each listed question by picking the option that starts with "right"."""
        answers = []
        for block in re.split(r"\nQuestion \d+: ", prompt.split("Questions:", 1)[1])[1:]:
            options = re.findall(r"^  (\d)\) (.*)$", block, re.M)
            answers.append(next((int(i) for i, text in options if text.startswith("right")), 0))
        return answers


SETS_TEXT = (
    "A set is a collection of well defined objects. The objects in a set are called elements. "
    "Set A is a subset of set B if every element of A is also an element of B. "
    "A proper subset of B is a subset of B that is not equal to B. "
) * 6
INTEGERS_TEXT = (
    "Integers are the whole numbers and their opposites. The sum of a positive integer and its "
    "opposite is zero. To add integers with different signs, subtract their absolute values. "
) * 6


def make_units() -> list[Unit]:
    sets = Unit(
        id="g7-math:u1", book_id="g7-math", book_title="Maths 7", grade=7, subject="Mathematics",
        number=1, title="Basic Concepts of Sets",
        sections=[
            Section("g7-math:u1:s1.1", "1.1", "Introduction to sets", 1, 3, [(1, SETS_TEXT[:400]), (2, SETS_TEXT[400:])]),
            Section("g7-math:u1:s1.2", "1.2", "Relations among sets", 4, 7, [(4, SETS_TEXT)]),
        ],
    )
    integers = Unit(
        id="g7-math:u2", book_id="g7-math", book_title="Maths 7", grade=7, subject="Mathematics",
        number=2, title="Integers",
        sections=[Section("g7-math:u2:s2.1", "2.1", "Introduction to integers", 11, 13, [(11, INTEGERS_TEXT)])],
    )
    return [sets, integers]


@pytest.fixture
def model() -> FakeModel:
    return FakeModel()


@pytest.fixture
def db() -> Database:
    return Database(":memory:")


@pytest.fixture
def index(model: FakeModel) -> SearchIndex:
    units = make_units()
    return SearchIndex.build(units, chunk_units(units), model)


@pytest.fixture
def assistant(index: SearchIndex, model: FakeModel, db: Database, tmp_path) -> StudyAssistant:
    return StudyAssistant(index, model, db, cache_dir=tmp_path / "summaries", top_k=3, min_score=0.2)
