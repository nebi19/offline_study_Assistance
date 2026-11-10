"""The three AI features: grounded answers, visual unit summaries and quizzes.

All model output is grounded in textbook passages from the search index, and
every answer, summary topic and quiz question carries its source (unit,
section and printed page).
"""

from __future__ import annotations

import json
import random
import re
import uuid
from collections.abc import Iterator
from pathlib import Path

from .curriculum import Chunk, Unit
from .db import Database
from .index import Hit, SearchIndex
from .llm import LanguageModel
from .mathcheck import (
    asked_expression,
    evaluate,
    has_false_equation,
    is_calculation,
    option_value,
    options_with_property,
    same,
)
from .mathtext import plain_math, plain_math_stream
from .translate import Translator

LANGUAGES = {"en": "English", "am": "Amharic (አማርኛ)"}

NOT_FOUND_TOKEN = "NOT_IN_TEXTBOOK"

NOT_FOUND_MESSAGE = {
    "en": (
        "I couldn't find that in your textbook for this unit. "
        "Try asking about a topic from the lesson, or ask your teacher."
    ),
    "am": (
        "ይህንን በዚህ ምዕራፍ የመማሪያ መጽሐፍ ውስጥ አላገኘሁትም። "
        "ከትምህርቱ ርዕስ ጋር የተያያዘ ጥያቄ ይጠይቁ፣ ወይም መምህርዎን ይጠይቁ።"
    ),
}

QUIZ_SIZE = 5
QUIZ_SPARE = 3  # extra questions written, to replace ones that fail checking
# "A. ", "b) ", "(C) " option labels; options get shuffled, so labels go.
_OPTION_PREFIX = re.compile(r"^\s*\(?[A-Da-d][.):]\s+")
_SUMMARY_SECTION_CHARS = 2400  # textbook text read per section
_SUMMARY_SECTION_TOKENS = 500  # output cap per section: a runaway reply costs seconds, not minutes
_SUMMARY_MAX_SECTIONS = 8
_EXAMPLE = re.compile(r"\bExample\s*\d*\s*[:.]?.{40,900}?\bSolution\b.{20,500}", re.S)
_TEXT = {"type": "string", "maxLength": 200}
SECTION_SCHEMA = {
    "type": "object",
    "properties": {
        "key_ideas": {"type": "array", "minItems": 2, "maxItems": 3, "items": _TEXT},
        "formulas": {
            "type": "array",
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {"name": _TEXT, "formula": _TEXT, "meaning": _TEXT},
                "required": ["name", "formula", "meaning"],
            },
        },
        "key_terms": {
            "type": "array",
            "minItems": 1,
            "maxItems": 2,
            "items": {
                "type": "object",
                "properties": {"term": _TEXT, "meaning": _TEXT},
                "required": ["term", "meaning"],
            },
        },
    },
    "required": ["key_ideas", "formulas", "key_terms"],
}
OVERVIEW_SCHEMA = {
    "type": "object",
    "properties": {"overview": {"type": "string", "maxLength": 400}},
    "required": ["overview"],
}
EXAMPLE_SCHEMA = {
    "type": "object",
    "properties": {
        "problem": {"type": "string", "maxLength": 300},
        "steps": {"type": "array", "minItems": 1, "maxItems": 5, "items": _TEXT},
        "answer": _TEXT,
    },
    "required": ["problem", "steps", "answer"],
}


class UnitNotFound(LookupError):
    pass


class GenerationFailed(RuntimeError):
    pass


def _is_not_found(text: str) -> bool:
    """True if the model answered with the "not in the textbook" signal."""
    return re.sub(r"[^A-Z]", "", text.upper()).startswith("NOTINTEXTBOOK")


_PASSAGE_REFERENCE = re.compile(r",?\s*\b(?:from|as (?:shown|stated) in|according to|in) the passage\b.*$", re.I | re.S)


def _sound_explanation(question: dict) -> dict | None:
    """Tidy the explanation; reject one that states wrong arithmetic.

    A calculator-checked question gets its explanation rebuilt from the
    checked expression; any other question with false maths is dropped.
    """
    explanation = _PASSAGE_REFERENCE.sub("", question["explanation"]).strip()
    if explanation and explanation[-1] not in ".!?":
        explanation += "."
    if has_false_equation(explanation):
        if question.get("checked_by") != "calculator" or not question["check"]:
            return None
        answer = question["options"][question["answer_index"]]
        explanation = f"{question['check']} = {answer}"
    return {**question, "explanation": explanation}


def _adds_variety(question: dict, accepted: list[dict]) -> bool:
    """No repeated correct answer, and at most 2 questions per passage."""
    answer = question["options"][question["answer_index"]].strip().lower()
    passage = question["source"]["chunk_id"]
    same_answer = any(q["options"][q["answer_index"]].strip().lower() == answer for q in accepted)
    from_passage = sum(q["source"]["chunk_id"] == passage for q in accepted)
    return not same_answer and from_passage < 2


_LIST_ITEM = re.compile(r"^\s*\(?[a-z][.)]\s", re.M)


def _is_exercise_list(text: str) -> bool:
    """True for a passage that is mostly "a. … b. … c. …" exercise items."""
    items = len(_LIST_ITEM.findall(text))
    return items >= 6 or (items >= 3 and "exercise" in text.lower())


def _unique(items: list[dict], key: str) -> list[dict]:
    """Drop items that repeat an earlier one's ``key`` (ignoring case and spaces)."""
    seen: set[str] = set()
    kept = []
    for item in items:
        mark = re.sub(r"\s+", "", str(item.get(key, "")).lower())
        if mark and mark not in seen:
            seen.add(mark)
            kept.append(item)
    return kept


def _plain(value):
    """``plain_math`` applied to every string in model JSON (except 'check')."""
    if isinstance(value, str):
        return plain_math(value)
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, dict):
        return {k: v if k == "check" else _plain(v) for k, v in value.items()}
    return value


def _prepend(first: str, rest: Iterator[str]) -> Iterator[str]:
    if first:
        yield first
    yield from rest


def _sentences(tokens: Iterator[str]) -> Iterator[str]:
    """Group a token stream into complete sentences (or lines)."""
    pending = ""
    for token in tokens:
        pending += token
        while True:
            match = re.search(r"[.!?](?=\s)|\n", pending)
            if not match:
                break
            sentence, pending = pending[: match.end()], pending[match.end() :]
            if sentence.strip():
                yield sentence.strip()
    if pending.strip():
        yield pending.strip()


def _question_key(question: str) -> str:
    """Normalized question text, to spot duplicates."""
    return re.sub(r"\W+", " ", question.lower()).strip()


def _language(code: str) -> str:
    return code if code in LANGUAGES else "en"


def _within_budget(hits: list[Hit], budget: int) -> list[Hit]:
    """The best passages that fit in ``budget`` characters (always at least one)."""
    kept: list[Hit] = []
    used = 0
    for hit in hits:
        if kept and used + len(hit.chunk.text) > budget:
            break
        kept.append(hit)
        used += len(hit.chunk.text)
    return kept


def _sources(hits: list[Hit]) -> list[dict]:
    """Citations for the passages used, one per section/page."""
    seen: set[tuple] = set()
    sources = []
    for hit in hits:
        key = (hit.chunk.section_id, hit.chunk.page)
        if key in seen:
            continue
        seen.add(key)
        sources.append({**hit.chunk.citation(), "score": round(hit.score, 3)})
    return sources


class StudyAssistant:
    def __init__(
        self,
        index: SearchIndex,
        model: LanguageModel,
        db: Database,
        cache_dir: Path,
        top_k: int = 4,
        min_score: float = 0.62,
        translator: Translator | None = None,
        translate_quizzes: bool = False,
        context_chars: int = 1800,
    ) -> None:
        self.index = index
        # Amharic: the model writes English, NLLB translates (if installed).
        self.translator = translator if translator is not None and translator.available else None
        self.model = model
        self.db = db
        self.cache_dir = cache_dir
        self.top_k = top_k
        self.min_score = min_score
        self.translate_quizzes = translate_quizzes
        # A CPU reads about 95 tokens a second, so every passage sent to the
        # model delays the first word of the answer by 3-4 seconds.
        self.context_chars = context_chars

    def _model_language(self, language: str) -> str:
        """Language the chat model writes in: English when we translate."""
        return "en" if language != "en" and self.translator else language

    def _translate(self, texts: list[str], language: str) -> list[str]:
        if language == "en" or not self.translator:
            return texts
        return self.translator.translate(texts, language)

    # ------------------------------------------------------------------ units

    def unit(self, unit_id: str, include_hidden: bool = False) -> Unit:
        unit = self.index.units.get(unit_id)
        if unit is None or (not include_hidden and unit_id in self.db.hidden_units()):
            raise UnitNotFound(unit_id)
        return unit

    # -------------------------------------------------------------------- ask

    def ask(self, unit_id: str, question: str, language: str = "en") -> Iterator[dict]:
        """Stream events: ``sources``, then ``token``s, then ``done``.

        If no passage is close enough to the question, or the model reports
        that the passages do not contain the answer, a polite "not in the
        textbook" message is sent instead of a guess.
        """
        language = _language(language)
        unit = self.unit(unit_id)
        question = question.strip()
        query = self.model.embed([question], kind="query")[0]
        hits = [h for h in self.index.search(query, unit.id, self.top_k) if h.score >= self.min_score]
        hits = _within_budget(hits, self.context_chars)

        if not hits:
            yield {"type": "sources", "sources": []}
            yield {"type": "token", "text": NOT_FOUND_MESSAGE[language]}
            self.db.log_question(unit.id, question, language, answered=False)
            yield {"type": "done", "answered": False}
            return

        yield {"type": "sources", "sources": _sources(hits)}
        model_language = self._model_language(language)
        stream = plain_math_stream(
            iter(self.model.chat_stream(self._answer_messages(unit, question, hits, model_language)))
        )
        # Hold back the first characters to catch the model's "not found" signal.
        buffer = ""
        for token in stream:
            buffer += token
            if len(buffer.strip()) > len(NOT_FOUND_TOKEN):
                break
        answered = not _is_not_found(buffer)
        if answered and model_language != language:
            # Translate each sentence as soon as it is complete.
            for sentence in _sentences(_prepend(buffer, stream)):
                yield {"type": "token", "text": self._translate([sentence], language)[0] + " "}
        elif answered:
            if buffer:
                yield {"type": "token", "text": buffer}
            for token in stream:
                yield {"type": "token", "text": token}
        else:
            close = getattr(stream, "close", None)
            if close:
                close()
            yield {"type": "sources", "sources": []}
            yield {"type": "token", "text": NOT_FOUND_MESSAGE[language]}
        self.db.log_question(unit.id, question, language, answered=answered)
        yield {"type": "done", "answered": answered}

    @staticmethod
    def _answer_messages(unit: Unit, question: str, hits: list[Hit], language: str) -> list[dict]:
        passages = "\n\n".join(
            f"[Passage {i}: section {h.chunk.section_number} "
            f"{h.chunk.section_title}, page {h.chunk.page or '-'}]\n{h.chunk.text}"
            for i, h in enumerate(hits, 1)
        )
        # No unit or grade here: an unchanged system prompt stays in the
        # model's cache from one question to the next.
        system = (
            "You are a friendly mathematics tutor for school students in Ethiopia. "
            "Answer ONLY using the textbook passages provided. "
            f"If the passages do not contain the answer, reply with exactly {NOT_FOUND_TOKEN} and nothing else. "
            "Keep answers short and simple (at most 5 sentences, or short numbered steps for a calculation). "
            "Do not mention 'passages'; speak to the student directly. "
            "Write math with plain symbols (for example πr², 3/4, x ≤ 5), never LaTeX. "
            f"Write the answer in {LANGUAGES[language]}; keep numbers and math symbols as they are."
        )
        user = (
            f"Grade {unit.grade}, Unit {unit.number}: {unit.title}\n\nTextbook passages:\n{passages}\n\n"
            f"Student's question: {question}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # ---------------------------------------------------------------- summary

    def summary(self, unit_id: str, language: str = "en", refresh: bool = False) -> dict:
        """Visual summary of a unit, cached on disk (generation is slow on a CPU)."""
        language = _language(language)
        unit = self.unit(unit_id)
        cache = self.cache_dir / f"{unit.id.replace(':', '_')}-{language}.json"
        if cache.exists() and not refresh:
            return json.loads(cache.read_text(encoding="utf-8"))

        if self._model_language(language) != language:
            result = self._translate_summary(self.summary(unit_id, "en", refresh=refresh), language)
        else:
            result = self._clean_summary(unit, self._write_summary(unit, language))
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result

    def _translate_summary(self, summary: dict, language: str) -> dict:
        """Translate the words of an English summary; formulas stay as they are."""
        texts: list[str] = [summary["overview"]]
        for t in summary["topics"]:
            texts += [t["title"], *t["key_ideas"]]
        for f in summary["formulas"]:
            texts += [f["name"], f["meaning"]]
        for k in summary["key_terms"]:
            texts += [k["term"], k["meaning"]]
        example = summary["worked_example"]
        if example:
            texts += [example["problem"], *example["steps"], example["answer"]]
        translated = iter(self._translate(texts, language))

        result = json.loads(json.dumps(summary))
        result["overview"] = next(translated)
        for t in result["topics"]:
            t["title"] = next(translated)
            t["key_ideas"] = [next(translated) for _ in t["key_ideas"]]
        for f in result["formulas"]:
            f["name"], f["meaning"] = next(translated), next(translated)
        for k in result["key_terms"]:
            # Keep the English term too: students meet it in the textbook.
            k["term"] = f"{next(translated)} ({k['term']})"
            k["meaning"] = next(translated)
        if result["worked_example"]:
            ex = result["worked_example"]
            ex["problem"] = next(translated)
            ex["steps"] = [next(translated) for _ in ex["steps"]]
            ex["answer"] = next(translated)
        result["translated"] = True
        result["concept_map"] = concept_map_mermaid(result)
        return result

    def _write_summary(self, unit: Unit, language: str) -> dict:
        """Build the summary from several small model calls.

        One call per section (key ideas, formulas, terms), one for the
        overview and one for a worked example. One big reply for the whole
        unit sometimes ran away on a 3B model and took minutes to fail; small
        capped replies fail fast, are retried, and read more of each section.
        Section titles and numbers come from our structure, not the model.
        """
        sections = [s for s in unit.sections if s.text.strip()]
        sections = ([s for s in sections if not s.number.startswith("S")] or sections)[:_SUMMARY_MAX_SECTIONS]
        raw: dict = {"overview": "", "topics": [], "formulas": [], "key_terms": [], "worked_example": None}
        for section in sections:
            notes = self._small_json(self._section_messages(unit, section, language), SECTION_SCHEMA)
            if notes is None:
                continue
            number = section.number
            raw["topics"].append({"section": number, "title": section.title, "key_ideas": notes.get("key_ideas", [])})
            raw["formulas"] += [{**f, "section": number} for f in notes.get("formulas", []) if isinstance(f, dict)]
            raw["key_terms"] += [{**t, "section": number} for t in notes.get("key_terms", []) if isinstance(t, dict)]
        if len(raw["topics"]) * 2 < len(sections) or not raw["topics"]:
            raise GenerationFailed("The model did not produce a usable summary. Please try again.")
        raw["formulas"] = _unique(raw["formulas"], "formula")
        raw["key_terms"] = _unique(raw["key_terms"], "term")

        ideas = "\n".join(f"- {t['title']}: {'; '.join(map(str, t['key_ideas']))}" for t in raw["topics"])
        overview = self._small_json(
            [
                {
                    "role": "system",
                    "content": (
                        f"Write a 2-sentence overview of this Grade {unit.grade} mathematics unit for students, "
                        f"using only the notes given. Write in {LANGUAGES[language]}."
                    ),
                },
                {"role": "user", "content": f"Unit {unit.number}: {unit.title}\n\n{ideas}"},
            ],
            OVERVIEW_SCHEMA,
        )
        raw["overview"] = (overview or {}).get("overview") or "This unit covers: " + ", ".join(
            t["title"] for t in raw["topics"]
        ) + "."

        found = next(((s, m[0]) for s in sections if (m := _EXAMPLE.search(s.text))), None)
        if found:
            section, text = found
            example = self._small_json(
                [
                    {
                        "role": "system",
                        "content": (
                            "Rewrite this worked example from a mathematics textbook for a Grade "
                            f"{unit.grade} student: the problem, 1-5 short steps, and the answer. "
                            "Use only what the text says. Write math with plain symbols, never LaTeX. "
                            f"Write in {LANGUAGES[language]}; keep numbers and math symbols as they are."
                        ),
                    },
                    {"role": "user", "content": text},
                ],
                EXAMPLE_SCHEMA,
            )
            if example:
                raw["worked_example"] = {**example, "section": section.number}
        return raw

    def _small_json(self, messages: list[dict], schema: dict) -> dict | None:
        """A short structured reply, tried twice; None if both tries are unusable."""
        for _attempt in range(2):
            try:
                reply = _plain(self.model.chat_json(messages, schema, max_tokens=_SUMMARY_SECTION_TOKENS))
            except ValueError:  # cut off at the cap, or not valid JSON
                continue
            if isinstance(reply, dict):
                return reply
        return None

    @staticmethod
    def _section_messages(unit: Unit, section, language: str) -> list[dict]:
        system = (
            f"You help Grade {unit.grade} students revise one section of their mathematics textbook. "
            "Use ONLY the textbook text given. Return JSON with: 2-3 key ideas, each one short sentence "
            "that states the fact or rule itself (write 'The sum of an integer and its opposite is 0', "
            "not 'Understanding opposites'); up to 2 formulas or rules from the text, written with plain "
            "symbols (for example a × (b + c) = a × b + a × c), never LaTeX, or an empty list if the text "
            "has none; and 1-2 key terms with simple meanings. "
            f"Write all text in {LANGUAGES[language]}; keep math symbols as they are."
        )
        user = (
            f"Unit {unit.number}: {unit.title}\nSection {section.number}: {section.title}\n\n"
            f"{section.text[:_SUMMARY_SECTION_CHARS]}"
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    @staticmethod
    def _clean_summary(unit: Unit, raw: dict) -> dict:
        """Trim the model's JSON and attach real page numbers from our structure."""

        def source(section_number: str) -> dict:
            section = unit.section(str(section_number).strip())
            if section is None:
                return {"section": None, "pages": None}
            return {
                "section": f"{section.number} {section.title}",
                "pages": section.pages_label,
            }

        topics = []
        for topic in raw.get("topics", [])[:8]:
            ideas = [i.strip() for i in topic.get("key_ideas", []) if str(i).strip()][:4]
            title = str(topic.get("title", "")).strip()
            if title:
                topics.append({"title": title, "key_ideas": ideas, **source(topic.get("section", ""))})
        formulas = [
            {
                "name": str(f.get("name", "")).strip(),
                "formula": str(f.get("formula", "")).strip(),
                "meaning": str(f.get("meaning", "")).strip(),
                **source(f.get("section", "")),
            }
            for f in raw.get("formulas", [])[:6]
            if str(f.get("formula", "")).strip()
        ]
        terms = [
            {
                "term": str(t.get("term", "")).strip(),
                "meaning": str(t.get("meaning", "")).strip(),
                **source(t.get("section", "")),
            }
            for t in raw.get("key_terms", [])[:8]
            if str(t.get("term", "")).strip()
        ]
        example = raw.get("worked_example") or {}
        worked = None
        if str(example.get("problem", "")).strip():
            worked = {
                "problem": str(example["problem"]).strip(),
                "steps": [str(s).strip() for s in example.get("steps", []) if str(s).strip()][:8],
                "answer": str(example.get("answer", "")).strip(),
                **source(example.get("section", "")),
            }
        result = {
            "unit_id": unit.id,
            "unit": f"Unit {unit.number}: {unit.title}",
            "grade": unit.grade,
            "overview": str(raw.get("overview", "")).strip(),
            "topics": topics,
            "formulas": formulas,
            "key_terms": terms,
            "worked_example": worked,
        }
        result["concept_map"] = concept_map_mermaid(result)
        return result

    # ------------------------------------------------------------------- quiz

    @staticmethod
    def quiz_schema(size: int, passages: int) -> dict:
        """Exactly ``size`` questions, each with exactly 4 options."""
        return {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "minItems": size,
                    "maxItems": size,
                    "items": {
                        "type": "object",
                        "properties": {
                            "passage": {"type": "integer", "enum": list(range(1, passages + 1))},
                            "question": {"type": "string"},
                            # Before the options, so it is worked out, not copied from them.
                            "check": {"type": "string"},
                            "options": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "string"}},
                            "answer_index": {"type": "integer", "enum": [0, 1, 2, 3]},
                            "explanation": {"type": "string"},
                        },
                        "required": ["passage", "question", "options", "answer_index", "explanation", "check"],
                    },
                }
            },
            "required": ["questions"],
        }

    def create_quiz(
        self,
        unit_id: str,
        language: str = "en",
        size: int = QUIZ_SIZE,
        rng: random.Random | None = None,
    ) -> dict:
        """A new multiple-choice quiz. Answers are kept on the server."""
        language = _language(language)
        rng = rng or random.Random()
        unit = self.unit(unit_id)
        passages = self._quiz_passages(unit, size, rng)
        if not passages:
            raise GenerationFailed("This unit has no text to make a quiz from.")

        # Small models sometimes mark the wrong option as correct, or write
        # questions with two right answers. So: write a few spare questions,
        # let the model answer them without seeing the key, and keep only the
        # ones where both agree.
        questions: list[dict] = []
        for _attempt in range(2):
            wanted = size - len(questions) + QUIZ_SPARE
            try:
                raw = self.model.chat_json(
                    self._quiz_messages(unit, passages, wanted, self._model_language(language)),
                    self.quiz_schema(wanted, len(passages)),
                )
            except ValueError:  # output cut off or not valid JSON: try again
                continue
            candidates = self._valid_questions(_plain(raw), passages, rng)
            seen = {_question_key(q["question"]) for q in questions}
            unique = []
            for q in candidates:
                if _question_key(q["question"]) not in seen:
                    seen.add(_question_key(q["question"]))
                    unique.append(q)
            candidates = unique
            for q in self._verified(unit, passages, candidates):
                if _adds_variety(q, questions):
                    questions.append(q)
            if len(questions) >= size:
                break
        if not questions:
            raise GenerationFailed("The model did not produce usable questions. Please try again.")
        questions = questions[:size]
        # Translated quizzes read badly so far, so they are opt-in; without
        # the option an Amharic student gets the quiz in English.
        if self._model_language(language) != language and self.translate_quizzes:
            questions = self._translate_questions(questions, language)
        else:
            language = self._model_language(language)

        quiz_id = uuid.uuid4().hex[:12]
        self.db.save_quiz(quiz_id, unit.id, language, questions)
        return {
            "quiz_id": quiz_id,
            "language": language,
            "unit": f"Unit {unit.number}: {unit.title}",
            "questions": [
                {"question": q["question"], "options": q["options"], "source": q["source"]}
                for q in questions
            ],
        }

    def _verified(self, unit: Unit, passages: list[Chunk], questions: list[dict]) -> list[dict]:
        """Questions whose answer key is checked.

        When all four options are numbers, a calculator decides where it
        can: the option equal to the value of the calculation becomes the key,
        and the question is dropped if no single option matches. The
        calculation is the one the question asks for outright ("What is
        4 + (−8)?") or else the model's ``check`` expression. "Which of these
        is a perfect square?" is tested option by option. Other questions keep
        their key only if the model, answering blind, picks the same option.
        """
        calculated: dict[int, dict] = {}
        rest: list[dict] = []
        for n, q in enumerate(questions):
            values = [option_value(o) for o in q["options"]]
            # The calculator decides only when every option is a number.
            if any(v is None for v in values):
                rest.append(q)
                continue
            # A bare number in "check" is only the model repeating itself.
            check = asked_expression(q["question"]) or (q["check"] if is_calculation(q["check"]) else "")
            if check:
                value = evaluate(check)
                matches = [i for i, v in enumerate(values) if same(v, value)]
            else:
                matches = options_with_property(q["question"], values)
            if matches is None:
                rest.append(q)
            elif len(matches) == 1:
                calculated[n] = {**q, "check": check, "answer_index": matches[0], "checked_by": "calculator"}
        blind = {id(q) for q in self._blind_check(unit, passages, rest)}
        checked = [
            calculated.get(n) or {**q, "checked_by": "model"}
            for n, q in enumerate(questions)
            if n in calculated or id(q) in blind
        ]
        return [q for q in map(_sound_explanation, checked) if q is not None]

    def _translate_questions(self, questions: list[dict], language: str) -> list[dict]:
        """Translate checked questions; numeric options are left as they are."""
        texts: list[str] = []
        for q in questions:
            texts += [q["question"], q["explanation"]]
            texts += [o for o in q["options"] if option_value(o) is None]
        translated = iter(self._translate(texts, language))
        result = []
        for q in questions:
            new = {**q, "question": next(translated), "explanation": next(translated)}
            new["options"] = [next(translated) if option_value(o) is None else o for o in q["options"]]
            result.append(new)
        return result

    def _blind_check(self, unit: Unit, passages: list[Chunk], questions: list[dict]) -> list[dict]:
        """Questions whose answer key matches the model's own blind answer."""
        if not questions:
            return []
        schema = {
            "type": "object",
            "properties": {
                "answers": {
                    "type": "array",
                    "minItems": len(questions),
                    "maxItems": len(questions),
                    "items": {"type": "integer", "enum": [0, 1, 2, 3]},
                }
            },
            "required": ["answers"],
        }
        text = "\n\n".join(f"[Passage {i}]\n{c.text}" for i, c in enumerate(passages, 1))
        listing = "\n\n".join(
            f"Question {n}: {q['question']}\n" + "\n".join(f"  {i}) {o}" for i, o in enumerate(q["options"]))
            for n, q in enumerate(questions, 1)
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a careful Grade {unit.grade} mathematics teacher. Solve each question "
                    "step by step in your head, then give the number (0-3) of the one correct option. "
                    "Use the passages and correct mathematics."
                ),
            },
            {"role": "user", "content": f"Passages:\n{text}\n\nQuestions:\n{listing}"},
        ]
        try:
            answers = self.model.chat_json(messages, schema).get("answers", [])
        except ValueError:
            return []
        return [q for q, a in zip(questions, answers) if a == q["answer_index"]]

    def submit_quiz(self, quiz_id: str, answers: list[int | None]) -> dict:
        quiz = self.db.get_quiz(quiz_id)
        if quiz is None:
            raise UnitNotFound(quiz_id)
        results = []
        score = 0
        for i, q in enumerate(quiz["questions"]):
            chosen = answers[i] if i < len(answers) else None
            correct = chosen == q["answer_index"]
            score += int(correct)
            results.append(
                {
                    "correct": correct,
                    "chosen": chosen,
                    "answer_index": q["answer_index"],
                    "explanation": q["explanation"],
                    "source": q["source"],
                }
            )
        total = len(quiz["questions"])
        self.db.log_attempt(quiz_id, score, total)
        return {"score": score, "total": total, "results": results}

    def _quiz_passages(self, unit: Unit, size: int, rng: random.Random) -> list[Chunk]:
        """One substantial passage from each of up to ``size`` sections."""
        chunks = [c for c in self.index.unit_chunks(unit.id) if len(c.text) >= 300]
        # Exercise lists make poor questions ("b and c"); use them only if a
        # unit has nothing else.
        chunks = [c for c in chunks if not _is_exercise_list(c.text)] or chunks
        by_section: dict[str, list[Chunk]] = {}
        for chunk in chunks:
            by_section.setdefault(chunk.section_id, []).append(chunk)
        lesson_sections = [k for k in by_section if not k.rsplit(":s", 1)[-1].startswith("S")]
        keys = lesson_sections or list(by_section)
        rng.shuffle(keys)
        picked = [rng.choice(by_section[k]) for k in keys[:size]]
        while len(picked) < size and len(picked) < len(chunks):
            extra = rng.choice(chunks)
            if extra not in picked:
                picked.append(extra)
        return picked

    @staticmethod
    def _quiz_messages(unit: Unit, passages: list[Chunk], size: int, language: str) -> list[dict]:
        text = "\n\n".join(
            f"[Passage {i}: section {c.section_number} {c.section_title}]\n{c.text}"
            for i, c in enumerate(passages, 1)
        )
        system = (
            f"You write multiple-choice quiz questions for Grade {unit.grade} mathematics students. "
            f"Write {size} questions using ONLY the passages; each question tests one idea from one passage. "
            "Each question has exactly 4 short options with exactly one correct option. "
            "Prefer small calculations or checking understanding of a rule; avoid trick questions. "
            "Every question must make sense on its own, without the textbook: never refer to "
            "'the table', 'the figure', 'the passage' or 'the example'; include any numbers needed. "
            "All questions must be different: every question needs a different correct answer, "
            "and write at most 2 questions from the same passage. "
            "Give 'passage' as the passage number, 'answer_index' as 0-3, and a one-sentence explanation. "
            "Write math with plain symbols, never LaTeX. "
            "In 'check', write the arithmetic expression whose value is the correct answer, using only numbers, "
            "+ - * / ^ ( ) and sqrt( ) (for example '4 + (-8)' or 'sqrt(324)'), never just the answer itself; "
            "write '' if the answer is not a number. "
            f"Write questions, options and explanations in {LANGUAGES[language]}; keep math symbols as they are."
        )
        user = f"Unit {unit.number}: {unit.title}\n\n{text}"
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    @staticmethod
    def _valid_questions(raw: dict, passages: list[Chunk], rng: random.Random) -> list[dict]:
        """Keep well-formed questions; shuffle options so the answer isn't always A."""
        valid = []
        for q in raw.get("questions", []):
            options = [_OPTION_PREFIX.sub("", str(o)).strip() for o in q.get("options", [])]
            answer = q.get("answer_index")
            question = str(q.get("question", "")).strip()
            if (
                not question
                or len(options) != 4
                or any(not o for o in options)
                or len({o.lower() for o in options}) != 4
                or not isinstance(answer, int)
                or not 0 <= answer < 4
            ):
                continue
            passage_no = q.get("passage")
            chunk = passages[passage_no - 1] if isinstance(passage_no, int) and 1 <= passage_no <= len(passages) else passages[0]
            order = list(range(4))
            rng.shuffle(order)
            valid.append(
                {
                    "question": question,
                    "options": [options[i] for i in order],
                    "answer_index": order.index(answer),
                    "explanation": str(q.get("explanation", "")).strip(),
                    "check": str(q.get("check", "")).strip(),
                    "source": chunk.citation(),
                }
            )
        return valid


# --------------------------------------------------------------------------
# Concept map


def _label(text: str, limit: int = 60) -> str:
    """Text safe inside a quoted Mermaid label."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text.replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def concept_map_mermaid(summary: dict) -> str:
    """Mermaid flowchart: unit → topics → key ideas (drawn offline in the page)."""
    lines = ["flowchart LR", f'  U["{_label(summary["unit"], 50)}"]:::unit']
    for t_index, topic in enumerate(summary["topics"], 1):
        topic_id = f"T{t_index}"
        prefix = (topic.get("section") or "").split(" ", 1)[0]
        title = f"{prefix} {topic['title']}".strip() if prefix and not topic["title"].startswith(prefix) else topic["title"]
        lines.append(f'  U --> {topic_id}["{_label(title, 45)}"]:::topic')
        for i_index, idea in enumerate(topic["key_ideas"], 1):
            lines.append(f'  {topic_id} --> {topic_id}I{i_index}["{_label(idea)}"]:::idea')
    lines += [
        "  classDef unit fill:#1d4ed8,stroke:#1e3a8a,color:#fff,font-weight:bold",
        "  classDef topic fill:#dbeafe,stroke:#1d4ed8,color:#0f172a",
        "  classDef idea fill:#fff,stroke:#94a3b8,color:#334155",
    ]
    return "\n".join(lines)
