"""Offline English → Amharic translation with Meta's NLLB-200 (600M, int8).

Small local chat models cannot write usable Amharic, so the assistant
answers in English and this module translates the result. NLLB-200 was built
for low-resource languages, including Amharic, and runs on a CPU through
CTranslate2. (Model licence: CC-BY-NC 4.0, i.e. non-commercial use.)

Maths is protected: expressions such as "A = πr²" or "x ≤ 5" are swapped for
placeholders before translation and put back afterwards, so the translation
model cannot change a number or a symbol.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

LANGUAGE_CODES = {"am": "amh_Ethi", "en": "eng_Latn"}

# A run of maths: numbers, single-letter variables, operators and brackets,
# containing at least one digit, operator or math symbol.
_MATH = re.compile(
    r"(?<![\w])"
    r"(?:[A-Za-z](?![a-z])|[-−]?\d[\d.,]*|[πθ√∞]|[()\[\]{}])"
    r"(?:\s*(?:[-+−×÷*/=<>≤≥≠≈⊂⊆⊄∪∩∈∉^²³⁻ⁿ|:]|\d[\d.,]*|[A-Za-z](?![a-z])|[πθ√∞]|[()\[\]{}])+)*"
)
_HAS_MATH_SIGN = re.compile(r"[\d=<>≤≥≠≈⊂⊆⊄∪∩∈∉+\-−×÷*/^²³√π]")
_SENTENCE_END = re.compile(r"(?<=[.!?:])\s+|\n+")


def protect_math(text: str) -> tuple[str, list[str]]:
    """Replace maths with ``<n>`` placeholders; return text and the originals."""
    found: list[str] = []

    def keep(match: re.Match) -> str:
        span = match.group(0)
        # Sentence punctuation after the maths stays outside the placeholder.
        core = span.rstrip(".,:; ")
        tail = span[len(core):]
        if not _HAS_MATH_SIGN.search(core):
            return span  # a lone letter like "a" or "B": translation keeps it
        found.append(core.strip())
        return f" <{len(found) - 1}> {tail.strip()}"

    return _MATH.sub(keep, text), found


def restore_math(text: str, found: list[str]) -> str:
    def put_back(match: re.Match) -> str:
        index = int(match.group(1))
        return found[index] if index < len(found) else match.group(0)

    text = re.sub(r"<\s*(\d+)\s*>", put_back, text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_END.split(text) if s.strip()]


class Translator:
    """English → Amharic. Loaded lazily; thread-safe for the web server."""

    def __init__(self, model_dir: Path, threads: int = 4) -> None:
        self.model_dir = Path(model_dir)
        self.threads = threads
        self._lock = threading.Lock()
        self._model = None
        self._tokenizer = None

    @property
    def available(self) -> bool:
        return (self.model_dir / "model.bin").exists() and (self.model_dir / "sentencepiece.bpe.model").exists()

    def _load(self) -> None:
        if self._model is not None:
            return
        import ctranslate2
        import sentencepiece

        self._model = ctranslate2.Translator(
            str(self.model_dir), device="cpu", compute_type="int8", intra_threads=self.threads
        )
        self._tokenizer = sentencepiece.SentencePieceProcessor(
            model_file=str(self.model_dir / "sentencepiece.bpe.model")
        )

    def translate(self, texts: list[str], target: str = "am") -> list[str]:
        """Translate each text (sentence by sentence), keeping maths unchanged."""
        if target == "en" or not texts:
            return list(texts)
        code = LANGUAGE_CODES[target]
        with self._lock:
            self._load()
            # Split every text into sentences, translate them in one batch.
            pieces: list[tuple[int, str, list[str]]] = []
            for i, text in enumerate(texts):
                for sentence in split_sentences(text):
                    protected, found = protect_math(sentence)
                    pieces.append((i, protected, found))
            if not pieces:
                return list(texts)
            batch = [["eng_Latn", *self._tokenizer.encode(p, out_type=str), "</s>"] for _, p, _ in pieces]
            results = self._model.translate_batch(
                batch,
                target_prefix=[[code]] * len(batch),
                beam_size=2,
                max_decoding_length=256,
                repetition_penalty=1.2,
            )
        out = [""] * len(texts)
        for (i, _, found), result in zip(pieces, results):
            tokens = [t for t in result.hypotheses[0] if t != code]
            sentence = restore_math(self._tokenizer.decode(tokens), found)
            out[i] = f"{out[i]} {sentence}".strip()
        return out

    def translate_one(self, text: str, target: str = "am") -> str:
        return self.translate([text], target)[0]
