import random

from studyassistant.assistant import StudyAssistant
from studyassistant.translate import protect_math, restore_math, split_sentences

from .test_assistant import quiz_reply, summary_replies


class FakeTranslator:
    """Marks translated text with «…» so tests can see what was translated."""

    available = True

    def __init__(self):
        self.calls: list[list[str]] = []

    def translate(self, texts, target="am"):
        self.calls.append(list(texts))
        return [f"«{t}»" for t in texts]


def make(index, model, db, tmp_path, translate_quizzes=False):
    translator = FakeTranslator()
    assistant = StudyAssistant(
        index, model, db, cache_dir=tmp_path / "s", top_k=3, min_score=0.2, translator=translator,
        translate_quizzes=translate_quizzes,
    )
    return assistant, translator


def test_math_is_protected_from_translation():
    text, found = protect_math("The area is A = πr², so with r = 2 it is about 12.56.")
    assert found == ["A = πr²", "r = 2", "12.56"]
    assert "π" not in text and "12.56" not in text
    assert restore_math(text, found).replace(" ", "") == "The area is A = πr², so with r = 2 it is about 12.56.".replace(" ", "")


def test_lone_letters_and_words_are_not_protected():
    text, found = protect_math("A set A is a proper subset of B.")
    assert found == [] and text == "A set A is a proper subset of B."


def test_split_sentences():
    assert split_sentences("One. Two? Three\nFour") == ["One.", "Two?", "Three", "Four"]


def test_amharic_answer_is_written_in_english_then_translated(index, model, db, tmp_path):
    assistant, translator = make(index, model, db, tmp_path)
    model.answer = "A proper subset is smaller. It is written A ⊂ B."
    events = list(assistant.ask("g7-math:u1", "What is a proper subset?", "am"))
    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert "English" in model.last_messages[0]["content"]  # model writes English
    assert text.strip() == "«A proper subset is smaller.» «It is written A ⊂ B.»"
    assert translator.calls == [["A proper subset is smaller."], ["It is written A ⊂ B."]]


def test_english_is_not_translated(index, model, db, tmp_path):
    assistant, translator = make(index, model, db, tmp_path)
    list(assistant.ask("g7-math:u1", "What is a proper subset?", "en"))
    assert translator.calls == []


def test_amharic_summary_translates_words_not_formulas(index, model, db, tmp_path):
    assistant, _ = make(index, model, db, tmp_path)
    model.json_replies = summary_replies()
    summary = assistant.summary("g7-math:u1", "am")
    assert summary["translated"] is True
    assert summary["overview"].startswith("«")
    assert summary["formulas"][0]["formula"] == "A ⊆ B"
    assert summary["key_terms"][0]["term"] == "«Element» (Element)"
    assert summary["topics"][0]["pages"] == "pp. 1–3"
    # The English summary was generated once and cached too.
    assert assistant.summary("g7-math:u1", "en")["overview"].startswith("Sets group objects")
    assert model.calls.count("json") == 3


def test_amharic_quiz_stays_english_unless_enabled(index, model, db, tmp_path):
    assistant, translator = make(index, model, db, tmp_path)
    model.json_replies = [quiz_reply(5)]
    quiz = assistant.create_quiz("g7-math:u1", "am", rng=random.Random(1))
    assert quiz["language"] == "en"
    assert not any(q["question"].startswith("«") for q in quiz["questions"])


def test_amharic_quiz_keeps_numeric_options(index, model, db, tmp_path):
    assistant, _ = make(index, model, db, tmp_path, translate_quizzes=True)
    reply = quiz_reply(5)
    reply["questions"][0].update(options=["-4", "4", "12", "-12"], answer_index=0, check="4 + (-8)")
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", "am", rng=random.Random(1))
    assert all(q["question"].startswith("«") for q in quiz["questions"])
    numeric = next(q for q in quiz["questions"] if "-4" in q["options"])
    assert sorted(numeric["options"]) == sorted(["-4", "4", "12", "-12"])
    stored = assistant.db.get_quiz(quiz["quiz_id"])["questions"]
    assert stored[0]["explanation"].startswith("«")
