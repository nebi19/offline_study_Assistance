# Offline AI Study Assistant

A study assistant for Ethiopian Grade 7 and 8 Mathematics that runs **without
internet** on one school-lab computer. Students open it in a browser on any
lab PC or tablet and can:

- **read** the textbook by grade, unit and section,
- see a **visual summary** of a unit: concept map, key formulas, key terms and a worked example,
- **ask questions** and get short answers taken only from the textbook, with the unit, section and page shown,
- take a **5-question quiz** with scoring and explanations,
- switch between **English and Amharic**.

Teachers get a view of the most-asked questions and average quiz scores per
unit, and can hide units from students.

Everything (the AI model, the search index, the database) lives on the lab
PC. No student data leaves the machine and students do not log in.

## How it works

```
 Browser (lab PCs, tablets)          One lab PC, no internet
 ┌──────────────────────┐   LAN   ┌──────────────────────────────────────────┐
 │ Lessons · Ask · Quiz │ ──────▶ │ FastAPI app  (studyassistant/app.py)     │
 │ Teacher view         │         │   ├─ search index: NumPy cosine search   │
 └──────────────────────┘         │   ├─ Ollama: qwen2.5:3b + nomic-embed    │
                                  │   ├─ NLLB-200: English → Amharic         │
                                  │   └─ SQLite: questions, quiz scores      │
                                  └──────────────────────────────────────────┘
```

1. **Import.** `studyassistant/ingest/pages.py` reads each textbook PDF page
   by page. Scanned pages (the Grade 7 book has no text layer) are read with
   RapidOCR, an offline OCR engine. `books.json` maps pages to units and
   sections, so every passage knows its printed page number.
2. **Index.** Sections are split into short passages and embedded with
   `nomic-embed-text`. The vectors are stored in one NumPy file; search is a
   cosine similarity, so no database server is needed.
3. **Ask (RAG).** The question is embedded, the closest passages *from the
   selected unit* are retrieved, and the local model answers from those
   passages only. The answer is streamed, with its sources.
4. **Stay on curriculum.** If no passage is close enough to the question, the
   model is not called at all and the student gets a polite "not in your
   textbook" message. The model can also signal that the passages do not
   contain the answer.
5. **Summaries.** The model returns the summary as JSON constrained by a
   schema (section numbers can only be ones that exist in the unit). Page
   numbers come from `books.json`, never from the model. The page draws the
   concept map with a bundled copy of Mermaid.
6. **Quizzes.** Small models make arithmetic mistakes, so generated questions
   are checked before a student sees them (see below).
7. **Amharic.** Small local models cannot write usable Amharic, so the model
   answers in English and Meta's NLLB-200 translates it offline. Maths is
   swapped for placeholders before translation and restored afterwards, so a
   number or symbol can never be changed by the translator.

### Quiz checking

A 3B model often writes a good question and then marks the wrong answer
(for example "4 + (−8) = −12"). Each generated question therefore goes
through these checks, and the model writes a few spare questions so that
rejected ones can be replaced:

| Check | What it does |
| --- | --- |
| Calculator | The model must give the arithmetic expression for its answer. `mathcheck.py` evaluates it with a small safe parser (no `eval`) and the matching option becomes the answer key. If no single option matches, the question is dropped. |
| Blind answer | Questions without a calculation are answered again by the model without the key. The question is kept only if both agree. |
| Explanation | An explanation that states wrong arithmetic is rebuilt from the checked expression, or the question is dropped. |
| Variety | No two questions with the same correct answer, and at most two from one passage. |

## Setup (once, with internet)

Requirements: Linux, Python 3.12+, about 8 GB RAM and 6 GB of disk. No GPU
is needed; the app uses the CPU by default.

```bash
# 1. Install Ollama (runs the AI model locally)
curl -fsSL https://ollama.com/install.sh | sh
#    No admin rights? Unpack the standalone build instead:
#    mkdir -p ~/.local/ollama && curl -L https://ollama.com/download/ollama-linux-amd64.tar.zst \
#      | tar --zstd -x -C ~/.local/ollama

# 2. Add the textbooks (see textbooks/README.md for the download commands)

# 3. Install everything else and build the search index
scripts/setup.sh
```

`setup.sh` installs the Python packages, downloads the two models
(`qwen2.5:3b`, 1.9 GB, and `nomic-embed-text`, 274 MB), reads the textbooks
and builds the index. The first run OCRs the scanned Grade 7 book, which
takes about five minutes; later runs reuse the cached text.

**Amharic (optional).** Download the translation model (620 MB) into
`models/nllb-600m-int8/`:

```bash
mkdir -p models/nllb-600m-int8 && cd models/nllb-600m-int8
for f in config.json model.bin sentencepiece.bpe.model shared_vocabulary.txt; do
  curl -LO "https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8/resolve/main/$f"
done
```

Without it, the app still runs and the Amharic button only changes the
interface language. NLLB-200 is licensed CC-BY-NC 4.0 (non-commercial use).

## Run (offline)

```bash
scripts/start.sh
```

The script prints the addresses to open, for example `http://localhost:8000`
on the lab PC and `http://192.168.1.20:8000` from other computers and
tablets on the lab network. Unplug the network cable and it keeps working.

Options (environment variables):

| Variable | Default | Meaning |
| --- | --- | --- |
| `PORT` | `8000` | Port of the web app |
| `TEACHER_PIN` | not set | If set, the teacher view asks for this PIN |
| `CHAT_MODEL` | `qwen2.5:3b` | Any Ollama chat model |
| `NUM_GPU` | `0` | `0` = CPU only. `auto` lets Ollama use a GPU |
| `MIN_SCORE` | `0.62` | How close a passage must be to count as "in the textbook" |

## Adding content

**A lesson (teachers).** Drop a Markdown file in `lessons/` and run
`scripts/setup.sh` again. The file starts with a short header:

```markdown
---
grade: 7
unit: 8
unit_title: Linear Inequalities
section: 8.1
section_title: Solving linear inequalities
---

Lesson text here …
```

`lessons/g7-linear-inequalities.md` is an example.

**A textbook.** Put the PDF in `textbooks/` and describe it in `books.json`:
its units and sections with the printed start page of each (from the table
of contents), and `page_offset` (PDF page number minus printed page number).

## Content in this demo

| Book | Units | Notes |
| --- | --- | --- |
| Mathematics Student Textbook, Grade 7 (new curriculum, Addis Ababa City Administration Education Bureau) | 7 units, 34 sections | Scanned PDF, read with OCR |
| Mathematics Student Textbook, Grade 8 (Ministry of Education, GEQIP edition) | Units 1–3 | The copy published by Camara Ethiopia contains only these units |
| Teacher lesson: Linear Inequalities | 1 section | Example of a Markdown lesson |

The textbook PDFs are copyrighted and are **not** in this repository. See
`textbooks/README.md` for where to download them.

## Speed

Measured on a laptop CPU (AMD Ryzen, 16 threads, GPU not used). A typical
lab PC will be slower.

| Feature | Time |
| --- | --- |
| Answer: first words | 10–19 s (about 5 s when the same passages were just used) |
| "Not in your textbook" reply | under 1 s (the model is not called) |
| Quiz in English (written and checked) | 2–3 min, 4–5 questions |
| Quiz in Amharic | about 6 min, 3 questions, poor quality (see Known limits) |
| Unit summary | 1–5 min when it works; not reliable yet (see Known limits) |

Most of the wait for an answer is the model reading the retrieved passages,
not writing. The target of first words within 10 seconds is not met yet.

The model is kept in memory between questions and loaded when the server
starts, so the first student does not wait for it.

## Known limits

- **Summaries can fail.** On the latest CPU run the summary for Grade 7
  Unit 2 ran until the output cap and returned an error after 5 minutes.
  Earlier runs for Unit 1 worked. The cause is not yet found.
- **Amharic quizzes are not usable yet.** The Unit 1 quiz came back with 3
  questions built from multi-part textbook exercises, with confusing options
  and explanations. Amharic answers and the Amharic interface work.
- **Quiz questions can still be flawed.** One generated question had two
  correct options ("which is a perfect square?" with both 441 and 324), and
  the model usually gives a bare answer instead of a calculation, so most
  questions are checked by the weaker blind re-answer, not the calculator.
- **OCR and formulas.** The Grade 7 book is a scan. OCR reads its text well
  but loses the layout of fractions and some symbols, and figures are not
  read at all. Questions about a diagram cannot be answered.
- **Small model.** A 3B model sometimes writes a weak or awkward quiz
  question. The checks above remove wrong answer keys, not dull questions. A
  teacher approval step is the natural next feature.
- **Amharic quality.** Translation is understandable but not polished, and
  mathematical terms are not always the ones Ethiopian textbooks use.
  Students can ask in Amharic only if the question matches English textbook
  text closely enough; asking in English works better.
- **Grade 8** has units 1–3 only (see above), from the earlier curriculum.
- **One model at a time.** Ten students asking at once will queue.

## Development

```bash
uv sync
uv run pytest          # 95 tests; they use a fake model, so no Ollama needed
```

| Path | What it is |
| --- | --- |
| `studyassistant/ingest/pages.py` | PDF text and OCR, with page numbers |
| `studyassistant/curriculum.py` | Units, sections, passages; Markdown lessons |
| `studyassistant/index.py` | Embedding index and search |
| `studyassistant/assistant.py` | Ask, summary and quiz logic |
| `studyassistant/mathcheck.py` | Safe calculator for checking quiz answers |
| `studyassistant/mathtext.py` | LaTeX to plain maths symbols |
| `studyassistant/translate.py` | Offline English → Amharic |
| `studyassistant/llm.py` | Ollama client |
| `studyassistant/db.py` | SQLite log for the teacher view |
| `studyassistant/app.py` | HTTP API |
| `static/` | The web page (no build step) |
# offline_study_Assistance
# offline_study_Assistance
