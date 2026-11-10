"""Extract the text of every textbook page, with page numbers.

Pages with a text layer are read directly. Scanned pages (no text layer) are
read with RapidOCR, an offline OCR engine that runs on the CPU. Results are
cached as JSON Lines in ``data/pages/<book_id>.jsonl`` so OCR runs only once.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import pymupdf

log = logging.getLogger(__name__)

# Watermark printed on every page of some downloaded copies.
_WATERMARKS = [
    re.compile(r"Ethiofetena\.com\s*Ethiopian No 1 Educational Website", re.I),
]
_MIN_TEXT_CHARS = 200
_OCR_DPI = 150


@dataclass
class Page:
    number: int  # 1-based page number in the PDF
    text: str
    source: str  # "text" (text layer) or "ocr"


_SUPERSCRIPT = str.maketrans("0123456789+-−n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁻ⁿ")
# Private-use characters from the Symbol font. Two are clearly the length
# variable ("l × w = A"); the rest are bracket pieces or bullets, so drop them.
_SYMBOL_FONT = {"\uf06c": "l", "\uf052": "l"}
_PRIVATE_USE = re.compile(r"[\ue000-\uf8ff]")


def _superscript(text: str) -> str:
    """'2' -> '²'; anything without a Unicode superscript form -> '^(…)'."""
    stripped = text.strip()
    converted = stripped.translate(_SUPERSCRIPT)
    if all(c in "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ" for c in converted):
        return converted
    return "^" + stripped if len(stripped) == 1 else f"^({stripped})"


def page_text(page: pymupdf.Page) -> str:
    """Text layer of a page, keeping superscripts (so 3² doesn't become 32)."""
    lines: list[str] = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            parts = []
            for span in line["spans"]:
                is_super = span["flags"] & 1 and span["text"].strip() and parts
                parts.append(_superscript(span["text"]) if is_super else span["text"])
            lines.append("".join(parts))
    return "\n".join(lines)


def clean(text: str) -> str:
    for char, replacement in _SYMBOL_FONT.items():
        text = text.replace(char, replacement)
    text = _PRIVATE_USE.sub(" ", text)
    for pattern in _WATERMARKS:
        text = pattern.sub(" ", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


class _Ocr:
    """Lazily created, because loading the OCR models takes a few seconds."""

    _engine = None

    @classmethod
    def read(cls, page: pymupdf.Page) -> str:
        if cls._engine is None:
            from rapidocr import RapidOCR

            logging.getLogger("RapidOCR").setLevel(logging.WARNING)
            cls._engine = RapidOCR()
        png = page.get_pixmap(dpi=_OCR_DPI).tobytes("png")
        result = cls._engine(png)
        return "\n".join(result.txts or [])


def extract_pages(pdf_path: Path, cache_path: Path) -> list[Page]:
    """All pages of ``pdf_path``; reuses ``cache_path`` if already extracted."""
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as f:
            pages = [Page(**json.loads(line)) for line in f if line.strip()]
        log.info("Loaded %d cached pages from %s", len(pages), cache_path)
        return pages

    pymupdf.TOOLS.mupdf_display_errors(False)
    doc = pymupdf.open(pdf_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache_path.with_suffix(".partial")
    pages: list[Page] = []
    started = time.time()
    with tmp.open("w", encoding="utf-8") as out:
        for index, pdf_page in enumerate(doc):
            text = clean(page_text(pdf_page))
            source = "text"
            if len(text) < _MIN_TEXT_CHARS and pdf_page.get_images():
                text = clean(_Ocr.read(pdf_page))
                source = "ocr"
            page = Page(number=index + 1, text=text, source=source)
            pages.append(page)
            out.write(json.dumps(asdict(page), ensure_ascii=False) + "\n")
            if (index + 1) % 10 == 0 or index + 1 == doc.page_count:
                elapsed = time.time() - started
                print(
                    f"  {pdf_path.name}: {index + 1}/{doc.page_count} pages "
                    f"({elapsed:.0f}s)",
                    file=sys.stderr,
                    flush=True,
                )
    tmp.replace(cache_path)
    return pages
