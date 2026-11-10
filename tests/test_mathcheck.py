import random

import pytest

from studyassistant.mathcheck import evaluate, option_value, same

from .test_assistant import quiz_reply


@pytest.mark.parametrize(
    ("expression", "value"),
    [
        ("4 + (-8)", -4),
        ("-4 * 5 * -3 * 1", 60),
        ("(-1984) ÷ (-16)", 124),
        ("3 − 5 × 2", -7),
        ("2^3 + 1", 9),
        ("sqrt(324)", 18),
        ("cbrt(64)", 4),
        ("1,300 - 560", 740),
        ("1/3 + 1/6", 0.5),
        ("1.9^3", 6.859),
    ],
)
def test_evaluate(expression, value):
    assert evaluate(expression) == pytest.approx(value)


@pytest.mark.parametrize(
    "expression",
    ["", "__import__('os').system('ls')", "x + 1", "2 ** 1000", "open('f')", "1/0", "sqrt(1, 2)", "True + 1"],
)
def test_evaluate_rejects_anything_but_arithmetic(expression):
    assert evaluate(expression) is None


@pytest.mark.parametrize(
    ("option", "value"),
    [("-4", -4), ("−12", -12), ("1,300", 1300), ("3/4", 0.75), ("125 cm³", 125), ("x = 7", 7), ("7 meters", 7)],
)
def test_option_value(option, value):
    assert option_value(option) == pytest.approx(value)


@pytest.mark.parametrize("option", ["5 > -6", "None", "between 2 and 3"])
def test_option_value_none_when_ambiguous(option):
    assert option_value(option) is None


def test_same_tolerates_rounded_options():
    assert same(6.859, 6.86) and same(0.5, 0.5) and not same(4, -4)


def test_calculator_fixes_wrong_answer_key(assistant, model):
    reply = quiz_reply(5)
    q = reply["questions"][0]
    q.update(question="What is the sum of 4 and -8?", options=["-12", "4", "-4", "12"], answer_index=0, check="4 + (-8)")
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(2))
    stored = assistant.db.get_quiz(quiz["quiz_id"])["questions"]
    fixed = next(x for x in stored if x["question"].startswith("What is the sum"))
    assert fixed["options"][fixed["answer_index"]] == "-4"
    assert fixed["checked_by"] == "calculator"


def test_calculator_drops_question_without_a_correct_option(assistant, model):
    reply = quiz_reply(8)
    reply["questions"][0].update(question="What is 6 × 7?", options=["40", "41", "43", "44"], answer_index=0, check="6*7")
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(2))
    assert "What is 6 × 7?" not in [x["question"] for x in quiz["questions"]]


def test_calculator_only_decides_when_all_options_are_numbers(assistant, model):
    reply = quiz_reply(5)
    reply["questions"][0].update(
        question="What makes an integer even?",
        options=["It divides by 2 with no remainder", "right answer", "It is odd", "It has 1 factor"],
        answer_index=1,
        check="2",
    )
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(2))
    stored = assistant.db.get_quiz(quiz["quiz_id"])["questions"]
    q = next(x for x in stored if x["question"] == "What makes an integer even?")
    assert q["checked_by"] == "model"
    assert q["options"][q["answer_index"]] == "right answer"


# ------------------------------------------------- quiz quality safeguards
from studyassistant.assistant import _adds_variety, _sound_explanation  # noqa: E402
from studyassistant.mathcheck import has_false_equation, is_calculation  # noqa: E402


@pytest.mark.parametrize(("expression", "expected"), [("4 + (-8)", True), ("sqrt(169)", True), ("15*15", True), ("13", False), ("-17", False), ("0.004", False), ("even × even", False)])
def test_is_calculation(expression, expected):
    assert is_calculation(expression) is expected


@pytest.mark.parametrize(
    ("text", "false"),
    [
        ("Birr 5 debt + Birr 12 more = -5 + 12 = -17", True),
        ("4 + (-8) = -12", True),
        ("250 + (-250) = 0", False),
        ("The square root of 169 is 13 because 13² = 169.", False),
        ("Divide by 3 to get x = 5.", False),
        ("3 × 5 = 15, so the answer is 15.", False),
        ("No maths at all.", False),
    ],
)
def test_has_false_equation(text, false):
    assert has_false_equation(text) is false


def _q(answer="7", explanation="Because 3 + 4 = 7.", checked_by="calculator", chunk="c1"):
    return {"question": "?", "options": [answer, "1", "2", "3"], "answer_index": 0, "check": "3 + 4",
            "explanation": explanation, "checked_by": checked_by, "source": {"chunk_id": chunk}}


def test_explanation_with_wrong_maths_is_rebuilt_or_rejected():
    fixed = _sound_explanation(_q(explanation="3 + 4 = 8 from the passage example a."))
    assert fixed["explanation"] == "3 + 4 = 7"
    assert _sound_explanation(_q(explanation="3 + 4 = 8.", checked_by="model")) is None
    assert _sound_explanation(_q(explanation="3 + 4 = 7 from the passage example b"))["explanation"] == "3 + 4 = 7."


def test_variety_rule():
    accepted = [_q("7", chunk="c1"), _q("9", chunk="c1")]
    assert not _adds_variety(_q("7", chunk="c2"), accepted)  # same answer again
    assert not _adds_variety(_q("5", chunk="c1"), accepted)  # third from one passage
    assert _adds_variety(_q("5", chunk="c2"), accepted)


# ------------------------------------------ checks that need no "check" field
from studyassistant.assistant import _is_exercise_list  # noqa: E402
from studyassistant.mathcheck import asked_expression, options_with_property  # noqa: E402


@pytest.mark.parametrize(
    ("question", "expression"),
    [
        ("What is 4 + (−8)?", "4 + (−8)"),
        ("Calculate: −5 × (−3)", "−5 × (−3)"),
        ("What is the value of 3² + 4²?", "3^2 + 4^2"),
        ("Find 12 ÷ 4 = ?", "12 ÷ 4"),
        ("What is the opposite of 5 − 8?", None),  # not the value of 5 − 8
        ("What is the sum of -3 and 5?", None),
        ("What is 13?", None),
    ],
)
def test_asked_expression(question, expression):
    assert asked_expression(question) == expression


@pytest.mark.parametrize(
    ("question", "options", "matching"),
    [
        ("Which of the following is a perfect square?", [441, 324, 50, 7], [0, 1]),
        ("Which number is not a prime number?", [2, 3, 9, 5], [2]),
        ("Which of these is a multiple of 6?", [14, 18, 20, 25], [1]),
        ("Which is a factor of 12?", [5, 7, 4, 9], [2]),
        ("Which integer is the smallest?", [1, 2, 3, 4], None),
        ("Which of the following is a perfect square?", [4, 2.5, 3, 7], None),
    ],
)
def test_options_with_property(question, options, matching):
    assert options_with_property(question, [float(o) for o in options]) == matching


def test_question_with_two_correct_options_is_dropped(assistant, model):
    reply = quiz_reply(8)
    reply["questions"][0].update(
        question="Which of the following is a perfect square?", options=["441", "324", "50", "7"], answer_index=0
    )
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(2))
    assert len(quiz["questions"]) == 5
    assert "Which of the following is a perfect square?" not in [q["question"] for q in quiz["questions"]]


def test_calculation_in_the_question_is_checked_without_a_check_field(assistant, model):
    reply = quiz_reply(5)
    reply["questions"][0].update(question="What is 4 + (−8)?", options=["-12", "4", "-4", "12"], answer_index=0, check="-12")
    model.json_replies = [reply]
    quiz = assistant.create_quiz("g7-math:u1", rng=random.Random(2))
    stored = assistant.db.get_quiz(quiz["quiz_id"])["questions"]
    fixed = next(x for x in stored if x["question"] == "What is 4 + (−8)?")
    assert fixed["options"][fixed["answer_index"]] == "-4"
    assert fixed["checked_by"] == "calculator"


def test_exercise_lists_are_recognized():
    exercise = "Exercise 1.2.1\n1. State true or false.\na. {1} ⊆ {1,2}\nb. {2,6} ⊆ {6}\nc. {a} = {a}\n"
    assert _is_exercise_list(exercise)
    assert not _is_exercise_list("Definition 1.5 A set A is a proper subset of B if …\na. first\nb. second")
