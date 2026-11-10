import random

import pytest

from studyassistant.assistant import (
    NOT_FOUND_MESSAGE,
    GenerationFailed,
    UnitNotFound,
    concept_map_mermaid,
)


def run(events):
    events = list(events)
    text = "".join(e["text"] for e in events if e["type"] == "token")
    sources = [e["sources"] for e in events if e["type"] == "sources"][-1]
    done = events[-1]
    return text, sources, done


# --------------------------------------------------------------------- ask


def test_answer_is_grounded_and_cites_unit_section_page(assistant, model, db):
    text, sources, done = run(assistant.ask("g7-math:u1", "What is a proper subset?"))
    assert text.strip() == model.answer
    assert done == {"type": "done", "answered": True}
    assert sources and all(s["unit"] == "Unit 1: Basic Concepts of Sets" for s in sources)
    assert {s["page"] for s in sources} <= {1, 2, 4}
    # Passages from the unit were given to the model.
    prompt = model.last_messages[1]["content"]
    assert "proper subset" in prompt and "Integers are the whole numbers" not in prompt
    assert db.unit_stats()["g7-math:u1"] == {"questions": 1, "unanswered": 0, "quiz_attempts": 0, "quiz_average": None}


def test_unrelated_question_is_refused_without_calling_the_model(assistant, model, db):
    text, sources, done = run(assistant.ask("g7-math:u1", "Who won the football world cup?"))
    assert text == NOT_FOUND_MESSAGE["en"]
    assert sources == []
    assert done["answered"] is False
    assert "chat" not in model.calls
    assert db.unit_stats()["g7-math:u1"]["unanswered"] == 1


def test_model_not_found_signal_becomes_polite_message(assistant, model):
    model.answer = "NOT_IN_TEXTBOOK"
    text, sources, done = run(assistant.ask("g7-math:u1", "What is the subset of a proper elephant?", "am"))
    assert text == NOT_FOUND_MESSAGE["am"]
    assert sources == []
    assert done["answered"] is False


def test_answer_language_is_requested(assistant, model):
    run(assistant.ask("g7-math:u1", "What is a set?", "am"))
    assert "Amharic" in model.last_messages[0]["content"]


def test_hidden_unit_cannot_be_used(assistant, db):
    db.set_unit_hidden("g7-math:u1", True)
    with pytest.raises(UnitNotFound):
        list(assistant.ask("g7-math:u1", "What is a set?"))


# ----------------------------------------------------------------- summary

def summary_replies() -> list[dict]:
    """What the model returns: one reply per section (1.1, 1.2), then the overview."""
    return [
        {
            "key_ideas": ["A set is a collection", "Elements", "", "x", "y"],
            "formulas": [],
            "key_terms": [{"term": "Element", "meaning": "An object in a set"}],
        },
        {
            "key_ideas": ["Every element of a subset is in the set", "A set is a subset of itself"],
            "formulas": [{"name": "Subset rule", "formula": "A ⊆ B", "meaning": "Every element of A is in B"}],
            "key_terms": [{"term": "element", "meaning": "Repeated term"}, {"term": "Subset", "meaning": "A set inside a set"}],
        },
        {"overview": "Sets group objects. Subsets are sets inside other sets."},
    ]


def test_summary_attaches_real_pages_and_is_cached(assistant, model):
    model.json_replies = summary_replies()
    summary = assistant.summary("g7-math:u1")
    first, second = summary["topics"]
    # Titles, section numbers and pages come from the book structure, not the model.
    assert first["title"] == "Introduction to sets"
    assert first["section"] == "1.1 Introduction to sets" and first["pages"] == "pp. 1–3"
    assert first["key_ideas"] == ["A set is a collection", "Elements", "x", "y"]
    assert second["pages"] == "pp. 4–7"
    assert summary["formulas"][0]["pages"] == "pp. 4–7"
    assert [t["term"] for t in summary["key_terms"]] == ["Element", "Subset"]  # repeat dropped
    assert summary["overview"].startswith("Sets group objects")
    assert summary["worked_example"] is None  # the fixture text has no example
    assert summary["concept_map"].startswith("flowchart LR")
    # Second call is served from the cache, without the model.
    assert assistant.summary("g7-math:u1") == summary
    assert model.calls.count("json") == 3


def test_summary_rewrites_a_worked_example_from_the_text(assistant, model):
    section = assistant.unit("g7-math:u1").sections[1]
    section.text_by_page = [(4, section.text + "\nExample 3: Is {1} a subset of {1, 2}? Give a reason for your answer.\n"
                      "Solution: 1 is an element of {1, 2}, so {1} is a subset of {1, 2}.")]
    model.json_replies = summary_replies() + [{"problem": "Is {1} a subset of {1, 2}?", "steps": ["1 is in {1, 2}"], "answer": "Yes"}]
    example = assistant.summary("g7-math:u1")["worked_example"]
    assert example["answer"] == "Yes" and example["pages"] == "pp. 4–7"
    assert "Example 3" in model.last_messages[-1]["content"]


def test_summary_survives_one_failed_section(assistant, model):
    replies = summary_replies()

    def chat_json(messages, schema, max_tokens=None):
        if "Section 1.1" in messages[-1]["content"]:
            raise ValueError("cut off")
        return replies.pop(1)

    model.chat_json = chat_json
    summary = assistant.summary("g7-math:u1")
    assert [t["title"] for t in summary["topics"]] == ["Relations among sets"]


def test_concept_map_escapes_labels():
    mermaid = concept_map_mermaid(
        {"unit": 'Unit 1: "Sets"', "topics": [{"title": "A <b> B", "section": "1.1 X", "key_ideas": ['say "hi"']}]}
    )
    assert '"' not in mermaid.split("U[", 1)[1].split("]")[0].strip('"')
    assert "<b>" not in mermaid and "#lt;b#gt;" in mermaid
    assert 'T1 --> T1I1["say #quot;hi#quot;"]' in mermaid


# -------------------------------------------------------------------- quiz


def quiz_reply(n: int, bad: int = 0) -> dict:
    questions = [
        {
            "passage": i % 3 + 1,  # the fixture unit yields 3 passages
            "question": f"Question {i}?",
            "options": [f"right {i}", "wrong 1", "wrong 2", "wrong 3"],  # distinct answers
            "answer_index": 0,
            "explanation": "Because.",
        }
        for i in range(n)
    ]
    questions += [{"passage": 1, "question": "Broken", "options": ["a", "a", "b"], "answer_index": 7, "explanation": ""}] * bad
    return {"questions": questions}


def test_quiz_hides_answers_and_scores_on_server(assistant, model, db):
    model.json_replies = [quiz_reply(5, bad=2)]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(1))
    assert len(quiz["questions"]) == 5
    assert all("answer_index" not in q and "explanation" not in q for q in quiz["questions"])
    assert all(q["source"]["unit"] == "Unit 1: Basic Concepts of Sets" for q in quiz["questions"])

    correct = [next(i for i, o in enumerate(q["options"]) if o.startswith("right")) for q in quiz["questions"]]
    answers = correct[:3] + [(c + 1) % 4 for c in correct[3:]]
    result = assistant.submit_quiz(quiz["quiz_id"], answers)
    assert (result["score"], result["total"]) == (3, 5)
    assert [r["correct"] for r in result["results"]] == [True, True, True, False, False]
    assert db.unit_stats()["g7-math:u1"]["quiz_average"] == 60.0


def test_quiz_options_are_shuffled(assistant, model):
    model.json_replies = [quiz_reply(5)]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(3))
    positions = {next(i for i, o in enumerate(q["options"]) if o.startswith("right")) for q in quiz["questions"]}
    assert len(positions) > 1


def test_quiz_drops_questions_with_a_wrong_answer_key(assistant, model):
    reply = quiz_reply(8)
    # Question 0 claims "wrong 1" is correct; the blind check disagrees.
    reply["questions"][0]["answer_index"] = 1
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(5))
    assert len(quiz["questions"]) == 5
    assert "Question 0?" not in [q["question"] for q in quiz["questions"]]
    assert model.calls == ["json", "verify"]


def test_quiz_tops_up_when_too_few_pass(assistant, model):
    first = quiz_reply(8)
    for q in first["questions"][:5]:
        q["answer_index"] = 2  # five bad keys: only 3 survive
    second = quiz_reply(5)
    for i, q in enumerate(second["questions"]):
        q["question"] = f"Extra {i}?"
    model.json_replies = [first, second]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(5))
    assert len(quiz["questions"]) == 5
    assert model.calls == ["json", "verify", "json", "verify"]


def test_quiz_retries_then_fails_cleanly(assistant, model):
    model.json_replies = [quiz_reply(0, bad=3), quiz_reply(0, bad=3)]
    with pytest.raises(GenerationFailed):
        assistant.create_quiz("g7-math:u1")
    assert model.calls.count("json") == 2


def test_unknown_quiz(assistant):
    with pytest.raises(UnitNotFound):
        assistant.submit_quiz("nope", [0])


def test_quiz_survives_one_unusable_model_reply(assistant, model):
    class Broken(dict):
        pass

    replies = [ValueError("cut off"), quiz_reply(8)]

    def chat_json(messages, schema):
        if "answers" in schema["properties"]:
            return {"answers": model.blind_answers(messages[-1]["content"])}
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    model.chat_json = chat_json
    assert len(assistant.create_quiz("g7-math:u1", rng=random.Random(1))["questions"]) == 5


def test_summary_failure_is_reported_cleanly(assistant, model):
    def chat_json(messages, schema, max_tokens=None):
        raise ValueError("not JSON")

    model.chat_json = chat_json
    with pytest.raises(GenerationFailed):
        assistant.summary("g7-math:u1")


def test_passages_sent_to_the_model_fit_the_budget(assistant, model):
    assistant.context_chars = 10  # smaller than any passage: the best one is still sent
    events = list(assistant.ask("g7-math:u1", "What is a proper subset?"))
    assert len(events[0]["sources"]) == 1
    assert model.last_messages[-1]["content"].count("[Passage ") == 1
    assistant.context_chars = 100_000
    list(assistant.ask("g7-math:u1", "What is a proper subset?"))
    assert model.last_messages[-1]["content"].count("[Passage ") == 3
