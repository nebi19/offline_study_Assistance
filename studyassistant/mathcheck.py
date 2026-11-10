"""A tiny safe calculator, used to check quiz answer keys.

Small models often mis-compute (e.g. "4 + (-8) = -12") but can write the
expression correctly. So quiz questions carry the expression for their
answer, and we evaluate it here instead of trusting the model's arithmetic.

Only numbers, + - * / ^, parentheses, sqrt() and cbrt() are allowed; the
expression is parsed with ``ast`` and never executed as code.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from fractions import Fraction

_NORMALIZE = str.maketrans({"×": "*", "·": "*", "÷": "/", "−": "-", "–": "-", "^": "**", "√": "sqrt"})
_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
}
_FUNCTIONS = {
    "sqrt": lambda x: math.sqrt(x),
    "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
}
_MAX_EXPONENT = 12
_MAX_LENGTH = 120

Number = Fraction | float


def evaluate(expression: str) -> float | None:
    """Value of a plain arithmetic expression, or None if it isn't one."""
    text = expression.strip().translate(_NORMALIZE)
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)  # 1,300 -> 1300
    if not text or len(text) > _MAX_LENGTH:
        return None
    try:
        tree = ast.parse(text, mode="eval")
        value = _eval(tree.body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError, OverflowError):
        return None
    return float(value)


def _eval(node: ast.AST) -> Number:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return Fraction(str(node.value))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        value = _eval(node.operand)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ValueError("exponent too large")
        if isinstance(node.op, ast.Pow) and isinstance(right, Fraction) and right.denominator != 1:
            return float(left) ** float(right)
        return _BINARY[type(node.op)](left, right)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in _FUNCTIONS
        and len(node.args) == 1
        and not node.keywords
    ):
        return _FUNCTIONS[node.func.id](float(_eval(node.args[0])))
    raise ValueError(f"not allowed: {ast.dump(node)[:40]}")


_NUMBER = re.compile(r"[-−–]?\s?\d[\d,]*(?:\.\d+)?(?:\s?/\s?\d+)?")


def option_value(option: str) -> float | None:
    """The number an answer option states, e.g. "-4", "1,300", "3/4", "125 cm³".

    None if the option has no number or several (like "5 > -6").
    """
    text = option.translate(_NORMALIZE)
    text = re.sub(r"(?<=\d)[²³]", "", text)  # unit exponents: cm² -> cm
    numbers = _NUMBER.findall(text)
    if len(numbers) != 1:
        return None
    return evaluate(numbers[0].replace(" ", ""))


def same(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-6) or (
        # Options are often rounded: accept agreement to 2 decimal places.
        abs(a) >= 0.01 and round(a, 2) == round(b, 2)
    )


def is_calculation(expression: str) -> bool:
    """True for "4 + (-8)" or "sqrt(169)"; False for a bare answer like "13".

    A bare number proves nothing: it is just the model's own answer again.
    """
    text = expression.strip().translate(_NORMALIZE).lstrip("+-( ")
    return bool(re.search(r"[-+*/]|sqrt|cbrt", text)) and evaluate(expression) is not None


_EQUATION_SIDE = r"[-−–+×÷*/^().,\d\s√²³]+"
_EQUATION = re.compile(rf"({_EQUATION_SIDE})=\s*([-−–]?\s?\d[\d,]*(?:\.\d+)?)(?![\d/^²³])")


def has_false_equation(text: str) -> bool:
    """True if the text states arithmetic that is wrong, like "-5 + 12 = -17"."""
    text = text.replace("²", "^2").replace("³", "^3")
    for left, right in _EQUATION.findall(text):
        left = left.strip().lstrip(".,").strip()
        if not re.search(r"\d", left) or not re.search(r"[-−–+×÷*/^√]", left.lstrip("-−– ")):
            continue  # "x = 5" or "= 5": nothing to check
        a, b = evaluate(left), evaluate(right)
        if a is not None and b is not None and not same(a, b):
            return True
    return False


_ASK = re.compile(
    r"^\s*(?:what is|what's|calculate|evaluate|compute|simplify|work out|find|solve)"
    r"(?: the (?:value|result) of)?\s*:?\s*(.+?)\s*(?:=\s*\??)?\s*[?.]?\s*$",
    re.I,
)


def asked_expression(question: str) -> str | None:
    """The calculation a question asks for outright.

    "What is 4 + (−8)?" gives "4 + (−8)". Anything with more words in it
    ("What is the opposite of 5 − 8?") gives None: we cannot be sure what
    is being asked.
    """
    match = _ASK.match(question)
    if not match:
        return None
    expression = match[1].replace("²", "^2").replace("³", "^3")
    return expression if is_calculation(expression) else None


def _is_prime(n: int) -> bool:
    return n > 1 and all(n % d for d in range(2, math.isqrt(n) + 1))


_PROPERTIES: dict[str, object] = {
    r"perfect square": lambda n, _: n >= 0 and math.isqrt(n) ** 2 == n,
    r"perfect cube": lambda n, _: round(abs(n) ** (1 / 3)) ** 3 == abs(n),
    r"prime(?: number)?": lambda n, _: _is_prime(n),
    r"even(?: number| integer)?": lambda n, _: n % 2 == 0,
    r"odd(?: number| integer)?": lambda n, _: n % 2 == 1,
    r"multiple of (\d+)": lambda n, k: k != 0 and n % k == 0,
    r"divisible by (\d+)": lambda n, k: k != 0 and n % k == 0,
    r"(?:factor|divisor) of (\d+)": lambda n, k: n != 0 and k % n == 0,
}
_PROPERTY = re.compile(r"^\s*which\b[^?]*?\bis (not )?(?:an? )?(.+?)\s*\??\s*$", re.I)


def options_with_property(question: str, values: list[float]) -> list[int] | None:
    """For "Which of these is a perfect square?", the options that are.

    Small models happily offer both 441 and 324. None if the question is
    not about a property we can test, or an option is not a whole number.
    """
    match = _PROPERTY.match(question)
    if not match or any(v != int(v) for v in values):
        return None
    for pattern, test in _PROPERTIES.items():
        found = re.fullmatch(pattern, match[2], re.I)
        if found:
            k = int(found[1]) if found.groups() else 0
            wanted = match[1] is None
            return [i for i, v in enumerate(values) if bool(test(int(v), k)) == wanted]
    return None
