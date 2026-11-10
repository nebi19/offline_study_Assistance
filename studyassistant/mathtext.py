"""Turn LaTeX maths into plain symbols a Grade 7 student can read.

The chat model is told to avoid LaTeX but sometimes writes it anyway, e.g.
``\\( A = \\pi r^2 \\)``. The page has no LaTeX renderer (it must work
offline and stay small), so we convert to ``A = πr²`` instead.
"""

from __future__ import annotations

import re
from collections.abc import Iterator

_COMMANDS = {
    r"\pi": "π", r"\times": "×", r"\cdot": "·", r"\div": "÷", r"\pm": "±",
    r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥", r"\neq": "≠", r"\ne": "≠",
    r"\approx": "≈", r"\cup": "∪", r"\cap": "∩", r"\subseteq": "⊆", r"\subset": "⊂",
    r"\notin": "∉", r"\in": "∈", r"\emptyset": "∅", r"\varnothing": "∅",
    r"\circ": "°", r"\degree": "°", r"\%": "%", r"\{": "{", r"\}": "}", r"\,": " ", r"\;": " ",
    r"\left": "", r"\right": "", r"\quad": " ",
}
# Longest first, so "\subseteq" is not read as "\subset" + "eq".
_COMMAND = re.compile(
    "|".join(re.escape(c) + (r"(?![A-Za-z])" if c[-1].isalpha() else "") for c in sorted(_COMMANDS, key=len, reverse=True))
)
_SUPERSCRIPTS = str.maketrans("0123456789+-n", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻ⁿ")


def plain_math(text: str) -> str:
    if "\\" not in text and "^" not in text and "$" not in text:
        return text
    text = re.sub(r"\\[()\[\]]", "", text)  # \( \) \[ \] delimiters
    text = re.sub(r"\$\$?([^$\n]+)\$\$?", r"\1", text)  # $...$
    text = re.sub(r"\\(?:text|mathrm|mathbf)\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\d?frac\{([^{}]+)\}\{([^{}]+)\}", lambda m: f"{_group(m[1])}/{_group(m[2])}", text)
    text = re.sub(r"\\sqrt\[3\]\{([^{}]+)\}", r"∛(\1)", text)
    text = re.sub(r"\\sqrt\{([^{}]+)\}", lambda m: "√" + _group(m[1]), text)
    text = _COMMAND.sub(lambda m: _COMMANDS[m[0]], text)
    text = re.sub(r"\^\{([0-9n+-]+)\}|\^([0-9n])", lambda m: (m[1] or m[2]).translate(_SUPERSCRIPTS), text)
    text = re.sub(r"(?<=[π×÷≤≥≠≈∪∩⊂⊆∈∉=]) (?=[²³])", "", text)
    text = re.sub(r"π ([a-zA-Z])(?![a-zA-Z])", r"π\1", text)  # "π r²" -> "πr²"
    return re.sub(r"[ \t]{2,}", " ", text)


def _group(expr: str) -> str:
    """Brackets around anything longer than one term: \\frac{a+b}{2} -> (a+b)/2."""
    expr = expr.strip()
    return expr if re.fullmatch(r"[\w.]+", expr) else f"({expr})"


def plain_math_stream(tokens: Iterator[str], max_hold: int = 240) -> Iterator[str]:
    """Like ``plain_math`` for a token stream: holds text back only while a
    LaTeX expression is still being written, so streaming stays live."""
    pending = ""
    for token in tokens:
        pending += token
        if _incomplete(pending) and len(pending) < max_hold:
            continue
        yield plain_math(pending)
        pending = ""
    if pending:
        yield plain_math(pending)


def _incomplete(text: str) -> bool:
    if "\\" not in text and "^" not in text and "$" not in text:
        return False
    return (
        text.count("\\(") != text.count("\\)")
        or text.count("\\[") != text.count("\\]")
        or text.count("$") % 2 == 1
        or text.count("{") != text.count("}")
        or bool(re.search(r"(\\[A-Za-z]*|\^)$", text))  # mid-command, or "^" awaiting its exponent
    )
