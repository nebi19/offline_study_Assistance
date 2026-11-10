from pathlib import Path

import pytest

from studyassistant.curriculum import build_units, chunk_units, load_lessons, split_text
from studyassistant.index import SearchIndex
from studyassistant.ingest.pages import Page, clean

BOOK = {
    "id": "bk",
    "title": "Book",
    "grade": 8,
    "subject": "Mathematics",
    "page_offset": 2,
    "units": [
        {
            "number": 1,
            "title": "Squares",
            "start_page": 1,
            "sections": [
                {"number": "1.1", "title": "Squares", "start_page": 1},
                {"number": "1.2", "title": "Roots", "start_page": 3},
            ],
        },
        {"number": 2, "title": "Variables", "start_page": 5, "sections": [{"number": "2.1", "title": "Terms", "start_page": 5}]},
    ],
}


def pages(n: int) -> list[Page]:
    return [Page(number=i, text=f"text of pdf page {i}", source="text") for i in range(1, n + 1)]


def test_units_map_printed_pages_to_pdf_pages():
    units = build_units(BOOK, pages(9))  # pdf 3..9 = printed 1..7
    assert [u.id for u in units] == ["bk:u1", "bk:u2"]
    s11, s12 = units[0].sections
    assert (s11.first_page, s11.last_page) == (1, 2)
    assert [p for p, _ in s11.text_by_page] == [1, 2]
    assert s11.text_by_page[0][1] == "text of pdf page 3"  # printed 1 = pdf 3
    assert (s12.first_page, s12.last_page) == (3, 4)
    # Last unit runs to the last page of the PDF.
    assert units[1].sections[0].last_page == 7
    assert s12.pages_label == "pp. 3–4"


def test_front_matter_before_printed_page_one_is_ignored():
    units = build_units(BOOK, pages(9))
    all_text = " ".join(s.text for u in units for s in u.sections)
    assert "pdf page 1" not in all_text and "pdf page 2 " not in all_text


def test_chunks_stay_within_one_page_and_carry_citation():
    long_page = Page(number=3, text=("Sentence about squares. " * 120).strip(), source="ocr")
    units = build_units(BOOK, [long_page] + pages(9)[3:])
    chunks = chunk_units(units)
    first_page_chunks = [c for c in chunks if c.page == 1]
    assert len(first_page_chunks) > 1
    assert all(len(c.text) <= 900 for c in first_page_chunks)
    cite = first_page_chunks[0].citation()
    assert cite == {
        "unit": "Unit 1: Squares", "section": "1.1 Squares", "page": 1, "grade": 8,
        "chunk_id": first_page_chunks[0].id,
    }


def test_split_text_overlaps_and_covers_everything():
    text = "".join(f"Line number {i}.\n" for i in range(200))
    pieces = split_text(text, size=300, overlap=50)
    assert pieces[0].startswith("Line number 0.")
    assert pieces[-1].rstrip().endswith("Line number 199.")
    assert all(len(p) <= 300 for p in pieces)


def test_clean_removes_watermark_and_blank_lines():
    raw = "Ethiofetena.com Ethiopian No 1 Educational Website\n\n\n1.2 Relations   among sets"
    assert clean(raw) == "1.2 Relations among sets"


def test_lesson_files_become_units(tmp_path: Path):
    (tmp_path / "fractions.md").write_text(
        "---\ngrade: 7\nunit: 9\nunit_title: Fractions\nsection: 9.1\nsection_title: Equivalent fractions\n---\n"
        "Two fractions are equivalent when they name the same amount.",
        encoding="utf-8",
    )
    (tmp_path / "README.md").write_text("ignored", encoding="utf-8")
    [unit] = load_lessons(tmp_path)
    assert unit.id == "lessons-g7:u9"
    assert unit.title == "Fractions"
    assert unit.sections[0].title == "Equivalent fractions"
    assert unit.sections[0].pages_label == "lesson file"


def test_lesson_without_grade_is_rejected(tmp_path: Path):
    (tmp_path / "bad.md").write_text("---\nunit: 1\n---\nbody", encoding="utf-8")
    with pytest.raises(ValueError, match="grade"):
        load_lessons(tmp_path)


def test_index_round_trip_and_unit_filter(index, model, tmp_path):
    index.save(tmp_path)
    loaded = SearchIndex.load(tmp_path)
    assert len(loaded.chunks) == len(index.chunks)
    query = model.embed(["what is a proper subset"], "query")[0]
    hits = loaded.search(query, unit_id="g7-math:u1", top_k=2)
    assert hits and all(h.chunk.unit_id == "g7-math:u1" for h in hits)
    assert loaded.search(query, unit_id="missing") == []
    assert loaded.units["g7-math:u1"].sections[0].text_by_page[0][0] == 1
