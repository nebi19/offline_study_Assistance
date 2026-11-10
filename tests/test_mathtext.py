import pytest

from studyassistant.mathtext import plain_math, plain_math_stream


@pytest.mark.parametrize(
    ("latex", "plain"),
    [
        (r"The formula is \( A = \pi r^2 \), where \( r \) is the radius.", "The formula is A = πr² , where r is the radius."),
        (r"\frac{3}{4} + \frac{a+b}{2}", "3/4 + (a+b)/2"),
        (r"\sqrt{324} = 18", "√324 = 18"),
        (r"x \leq 5 and y \neq 0", "x ≤ 5 and y ≠ 0"),
        (r"A \cup B and A \subseteq B and x \in A", "A ∪ B and A ⊆ B and x ∈ A"),
        (r"$2^3 = 8$ and 10^{-2}", "2³ = 8 and 10⁻²"),
        (r"3 \times 4 \div 2", "3 × 4 ÷ 2"),
        ("No maths here.", "No maths here."),
    ],
)
def test_plain_math(latex, plain):
    assert plain_math(latex).replace(" ,", ",") == plain.replace(" ,", ",")


def test_stream_holds_back_only_unfinished_latex():
    tokens = ["The area ", "is ", "\\", "( A ", "= \\", "pi r", "^", "2 \\", ")", " for ", "a circle."]
    out = list(plain_math_stream(iter(tokens)))
    assert out[:2] == ["The area ", "is "]  # plain text streams straight through
    assert "".join(out).replace("  ", " ") == "The area is A = πr² for a circle."
    assert not any("\\" in piece for piece in out)
