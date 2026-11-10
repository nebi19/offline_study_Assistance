"""Local search index: chunk metadata (JSON) + embedding matrix (NumPy).

No database server is needed: search is cosine similarity over a normalized
matrix, which is fast enough for a few thousand textbook passages.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .curriculum import Chunk, Unit
from .llm import LanguageModel


@dataclass
class Hit:
    chunk: Chunk
    score: float


def _normalize(matrix: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return matrix / norms


class SearchIndex:
    def __init__(self, chunks: list[Chunk], vectors: np.ndarray, units: list[Unit]):
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        self.chunks = chunks
        self.vectors = _normalize(vectors.astype(np.float32)) if len(chunks) else vectors
        self.units = {u.id: u for u in units}
        rows_by_unit: dict[str, list[int]] = {}
        for i, chunk in enumerate(chunks):
            rows_by_unit.setdefault(chunk.unit_id, []).append(i)
        self._by_unit = {k: np.asarray(v) for k, v in rows_by_unit.items()}

    # ------------------------------------------------------------------ build

    @classmethod
    def build(cls, units: list[Unit], chunks: list[Chunk], model: LanguageModel) -> "SearchIndex":
        vectors = model.embed([c.text for c in chunks], kind="document") if chunks else np.zeros((0, 0))
        return cls(chunks, vectors, units)

    # ------------------------------------------------------------------ query

    def search(
        self,
        query_vector: np.ndarray,
        unit_id: str | None = None,
        top_k: int = 4,
    ) -> list[Hit]:
        if not self.chunks:
            return []
        if unit_id is not None:
            rows = self._by_unit.get(unit_id)
            if rows is None or len(rows) == 0:
                return []
        else:
            rows = np.arange(len(self.chunks))
        query = query_vector.astype(np.float32)
        query = query / (np.linalg.norm(query) or 1.0)
        scores = self.vectors[rows] @ query
        order = np.argsort(-scores)[:top_k]
        return [Hit(self.chunks[int(rows[i])], float(scores[i])) for i in order]

    def unit_chunks(self, unit_id: str) -> list[Chunk]:
        rows = self._by_unit.get(unit_id)
        return [] if rows is None else [self.chunks[int(i)] for i in rows]

    # ------------------------------------------------------------ persistence

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        np.save(directory / "vectors.npy", self.vectors)
        (directory / "chunks.json").write_text(
            json.dumps([asdict(c) for c in self.chunks], ensure_ascii=False),
            encoding="utf-8",
        )
        (directory / "units.json").write_text(
            json.dumps([_unit_to_json(u) for u in self.units.values()], ensure_ascii=False),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, directory: Path) -> "SearchIndex":
        chunks = [Chunk(**c) for c in json.loads((directory / "chunks.json").read_text(encoding="utf-8"))]
        vectors = np.load(directory / "vectors.npy")
        units = [_unit_from_json(u) for u in json.loads((directory / "units.json").read_text(encoding="utf-8"))]
        return cls(chunks, vectors, units)

    @staticmethod
    def exists(directory: Path) -> bool:
        return all((directory / n).exists() for n in ("vectors.npy", "chunks.json", "units.json"))


def _unit_to_json(unit: Unit) -> dict:
    data = asdict(unit)
    for section in data["sections"]:
        section["text_by_page"] = [list(p) for p in section["text_by_page"]]
    return data


def _unit_from_json(data: dict) -> Unit:
    from .curriculum import Section

    sections = [
        Section(**{**s, "text_by_page": [tuple(p) for p in s["text_by_page"]]})
        for s in data.pop("sections")
    ]
    return Unit(**data, sections=sections)
