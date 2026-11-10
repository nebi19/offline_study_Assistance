"""Curriculum structure: grade → unit → section, with textbook page ranges.

Two sources feed the same structure:

* Textbook PDFs, described in ``books.json`` (unit and section titles with
  their *printed* start pages, plus the offset from printed page to PDF page).
* Markdown lesson files in ``lessons/`` that teachers add (see README).

Each section is then split into short passages ("chunks") for search. Chunks
never cross a page, so every answer can cite an exact page.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .ingest.pages import Page

CHUNK_CHARS = 900
CHUNK_OVERLAP = 150


@dataclass
class Section:
    id: str  # e.g. "g7-math:u3:s3.2"
    number: str  # "3.2", or "S3" for a unit summary
    title: str
    first_page: int | None  # printed page numbers; None for lesson files
    last_page: int | None
    text_by_page: list[tuple[int | None, str]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(t for _, t in self.text_by_page)

    @property
    def pages_label(self) -> str:
        if self.first_page is None:
            return "lesson file"
        if self.first_page == self.last_page:
            return f"p. {self.first_page}"
        return f"pp. {self.first_page}–{self.last_page}"


@dataclass
class Unit:
    id: str  # e.g. "g7-math:u3"
    book_id: str
    book_title: str
    grade: int
    subject: str
    number: int
    title: str
    sections: list[Section] = field(default_factory=list)

    def section(self, number: str) -> Section | None:
        return next((s for s in self.sections if s.number == number), None)


@dataclass
class Chunk:
    id: str
    unit_id: str
    section_id: str
    grade: int
    unit_number: int
    unit_title: str
    section_number: str
    section_title: str
    page: int | None  # printed page; None for lesson files
    text: str

    def citation(self) -> dict:
        return {
            "unit": f"Unit {self.unit_number}: {self.unit_title}",
            "section": f"{self.section_number} {self.section_title}".strip(),
            "page": self.page,
            "grade": self.grade,
            "chunk_id": self.id,
        }


# --------------------------------------------------------------------------
# Textbooks


def load_books(books_file: Path) -> list[dict]:
    return json.loads(books_file.read_text(encoding="utf-8"))["books"]


def build_units(book: dict, pages: list[Page]) -> list[Unit]:
    """Map PDF pages onto the book's units and sections using ``books.json``."""
    offset = int(book.get("page_offset", 0))
    by_printed = {p.number - offset: p for p in pages if p.number - offset >= 1}
    last_printed = max(by_printed) if by_printed else 0

    units: list[Unit] = []
    book_units = book["units"]
    for u_index, u in enumerate(book_units):
        unit = Unit(
            id=f"{book['id']}:u{u['number']}",
            book_id=book["id"],
            book_title=book["title"],
            grade=int(book["grade"]),
            subject=book.get("subject", ""),
            number=int(u["number"]),
            title=u["title"],
        )
        next_unit_start = (
            book_units[u_index + 1]["start_page"]
            if u_index + 1 < len(book_units)
            else last_printed + 1
        )
        sections = u["sections"]
        for s_index, s in enumerate(sections):
            start = int(s["start_page"])
            end = (
                int(sections[s_index + 1]["start_page"]) - 1
                if s_index + 1 < len(sections)
                else next_unit_start - 1
            )
            # Two sections may start on the same page; keep that page in both.
            end = max(end, start)
            section = Section(
                id=f"{unit.id}:s{s['number']}",
                number=s["number"],
                title=s["title"],
                first_page=start,
                last_page=min(end, last_printed),
                text_by_page=[
                    (n, by_printed[n].text)
                    for n in range(start, end + 1)
                    if n in by_printed and by_printed[n].text.strip()
                ],
            )
            if section.text_by_page:
                unit.sections.append(section)
        if unit.sections:
            units.append(unit)
    return units


# --------------------------------------------------------------------------
# Teacher lesson files (Markdown)

_FRONT_MATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def parse_lesson(path: Path) -> tuple[dict, str]:
    """Front matter (simple ``key: value`` lines) and body of a lesson file."""
    raw = path.read_text(encoding="utf-8")
    meta: dict[str, str] = {}
    match = _FRONT_MATTER.match(raw)
    body = raw
    if match:
        for line in match.group(1).splitlines():
            if ":" in line:
                key, value = line.split(":", 1)
                meta[key.strip()] = value.strip().strip('"')
        body = raw[match.end() :]
    return meta, body.strip()


def load_lessons(lessons_dir: Path) -> list[Unit]:
    """Group lesson files into units: one file = one section."""
    units: dict[str, Unit] = {}
    for path in sorted(lessons_dir.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue
        meta, body = parse_lesson(path)
        try:
            grade = int(meta["grade"])
            unit_no = int(meta["unit"])
        except (KeyError, ValueError):
            raise ValueError(
                f"{path.name}: front matter needs numeric 'grade' and 'unit'"
            ) from None
        book_id = f"lessons-g{grade}"
        unit_id = f"{book_id}:u{unit_no}"
        unit = units.setdefault(
            unit_id,
            Unit(
                id=unit_id,
                book_id=book_id,
                book_title="Teacher lessons",
                grade=grade,
                subject=meta.get("subject", "Mathematics"),
                number=unit_no,
                title=meta.get("unit_title", f"Unit {unit_no}"),
            ),
        )
        number = meta.get("section", path.stem)
        unit.sections.append(
            Section(
                id=f"{unit_id}:s{number}",
                number=number,
                title=meta.get("section_title", path.stem.replace("-", " ")),
                first_page=None,
                last_page=None,
                text_by_page=[(None, body)],
            )
        )
    return list(units.values())


# --------------------------------------------------------------------------
# Chunking


def split_text(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split on line/sentence boundaries into pieces of about ``size`` chars."""
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = text[start:end]
            cut = max(window.rfind("\n"), window.rfind(". "))
            if cut > size // 2:
                end = start + cut + 1
        piece = text[start:end].strip()
        if piece:
            pieces.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return pieces


def chunk_units(units: list[Unit]) -> list[Chunk]:
    chunks: list[Chunk] = []
    for unit in units:
        for section in unit.sections:
            n = 0
            for page, text in section.text_by_page:
                for piece in split_text(text):
                    n += 1
                    chunks.append(
                        Chunk(
                            id=f"{section.id}:c{n}",
                            unit_id=unit.id,
                            section_id=section.id,
                            grade=unit.grade,
                            unit_number=unit.number,
                            unit_title=unit.title,
                            section_number=section.number,
                            section_title=section.title,
                            page=page,
                            text=piece,
                        )
                    )
    return chunks
