"""Settings, read from environment variables with offline-friendly defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    ollama_url: str = field(
        default_factory=lambda: os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
    )
    # Small models that run on a CPU-only 8 GB lab PC.
    chat_model: str = field(
        default_factory=lambda: os.getenv("CHAT_MODEL", "qwen2.5:3b")
    )
    embed_model: str = field(
        default_factory=lambda: os.getenv("EMBED_MODEL", "nomic-embed-text")
    )
    # GPU layers for the chat model: "0" = CPU only (the lab-PC target),
    # "auto" = let Ollama use a GPU if it has one.
    num_gpu: int | None = field(
        default_factory=lambda: None
        if os.getenv("NUM_GPU", "0") == "auto"
        else int(os.getenv("NUM_GPU", "0"))
    )
    textbooks_dir: Path = field(
        default_factory=lambda: Path(os.getenv("TEXTBOOKS_DIR", ROOT / "textbooks"))
    )
    lessons_dir: Path = field(
        default_factory=lambda: Path(os.getenv("LESSONS_DIR", ROOT / "lessons"))
    )
    data_dir: Path = field(
        default_factory=lambda: Path(os.getenv("DATA_DIR", ROOT / "data"))
    )
    # Offline English → Amharic translation model (see README).
    translation_model_dir: Path = field(
        default_factory=lambda: Path(os.getenv("TRANSLATION_MODEL_DIR", ROOT / "models" / "nllb-600m-int8"))
    )
    books_file: Path = field(
        default_factory=lambda: Path(os.getenv("BOOKS_FILE", ROOT / "books.json"))
    )
    # Retrieval: how many passages to give the model, and the minimum
    # similarity for a passage to count as "in the textbook".
    # Amharic quizzes are off until their quality is good enough (see README).
    translate_quizzes: bool = field(default_factory=lambda: os.getenv("TRANSLATE_QUIZZES", "0") == "1")
    # Passage text sent with a question. More text = better grounded, slower first word.
    context_chars: int = field(default_factory=lambda: int(os.getenv("CONTEXT_CHARS", "1800")))
    top_k: int = field(default_factory=lambda: int(os.getenv("TOP_K", "4")))
    min_score: float = field(
        default_factory=lambda: float(os.getenv("MIN_SCORE", "0.62"))
    )

    @property
    def pages_dir(self) -> Path:
        return self.data_dir / "pages"

    @property
    def index_dir(self) -> Path:
        return self.data_dir / "index"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"


def get_settings() -> Settings:
    return Settings()
