"""Build the search index: ``python -m studyassistant.build``.

1. Reads every textbook listed in books.json that is present in textbooks/
   (OCR for scanned pages; cached, so only the first run is slow).
2. Adds the teacher lesson files in lessons/.
3. Splits the text into passages, embeds them with the local embedding model,
   and saves the index to data/index/.
"""

from __future__ import annotations

import argparse
import sys
import time

from .config import get_settings
from .curriculum import build_units, chunk_units, load_books, load_lessons
from .index import SearchIndex
from .ingest.pages import extract_pages
from .llm import ModelUnavailable, OllamaModel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pages-only", action="store_true", help="only extract/OCR pages, no embeddings")
    args = parser.parse_args(argv)
    settings = get_settings()

    units = []
    for book in load_books(settings.books_file):
        pdf = settings.textbooks_dir / book["file"]
        if not pdf.exists():
            print(f"- skipped {book['id']}: {pdf.name} not found in {settings.textbooks_dir}")
            continue
        print(f"- reading {pdf.name} …")
        pages = extract_pages(pdf, settings.pages_dir / f"{book['id']}.jsonl")
        book_units = build_units(book, pages)
        units += book_units
        sections = sum(len(u.sections) for u in book_units)
        print(f"  grade {book['grade']}: {len(book_units)} units, {sections} sections")

    if settings.lessons_dir.exists():
        lesson_units = load_lessons(settings.lessons_dir)
        if lesson_units:
            units += lesson_units
            print(f"- lesson files: {sum(len(u.sections) for u in lesson_units)} sections")

    if args.pages_only:
        return 0
    if not units:
        print("No textbooks or lessons found. See README: Adding textbooks.", file=sys.stderr)
        return 1

    chunks = chunk_units(units)
    model = OllamaModel(settings.ollama_url, settings.chat_model, settings.embed_model)
    print(f"- embedding {len(chunks)} passages with {settings.embed_model} …")
    started = time.time()
    try:
        index = SearchIndex.build(units, chunks, model)
    except ModelUnavailable as exc:
        print(f"Cannot reach the embedding model: {exc}", file=sys.stderr)
        return 1
    index.save(settings.index_dir)
    print(f"- saved index to {settings.index_dir} ({time.time() - started:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
