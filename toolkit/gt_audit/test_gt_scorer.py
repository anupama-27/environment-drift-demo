import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from gt_scorer import extract_gt, extract_gt_strict, gt_rule, is_correct_gt  # noqa: E402

BOX = [
    (r"so \boxed{42}", 42),
    (r"\boxed{1,200}", 1200),
    (r"\boxed{1,200.00}", 1200),
    (r"\boxed{\$29.00}", 29),
    (r"\boxed{$52,500}", 52500),
    (r"\boxed{-\$360.00}", -360),
    (r"\boxed{230 \text{ miles}}", 230),
    (r"\boxed{8 \, \text{hours}}", 8),
    (r"\boxed{20\%}", 20),
    (r"\boxed{42.}", 42),
    (r"\boxed{\frac{44}{3}}", 44 / 3),
    (r"\boxed{\dfrac{10}{4}}", 2.5),
    (r"\boxed{3/4}", 0.75),
    (r"\boxed{2\frac{1}{2}}", 2.5),
    (r"\boxed{40 - 35.91 = 4.09 \text{ minutes}}", 4.09),
    (r"\boxed{7.95 \times 10^{14}}", 7.95e14),
    (r"\boxed{ 18 }", 18),
    (r"\boxed{{18}}", 18),
    (r"\boxed{90^\circ}", 90),
    (r"\boxed{294n}", None),
    (r"\boxed{35x - 195}", None),
    (r"\boxed{64 \text{ weasels}, 32 \text{ rabbits}}", None),
    (r"\boxed{160 \text{ and } 300}", None),
    (r"\boxed{\text{Cannot reach home}}", None),
    (r"\boxed{1,2}", None),
]


@pytest.mark.parametrize("text,want", BOX)
def test_box_contents(text, want):
    got = extract_gt(text)
    if want is None:
        assert got is None
    else:
        assert got == pytest.approx(want)


def test_last_box_wins():
    assert extract_gt(r"first \boxed{3} then \boxed{5}") == 5


def test_box_beats_later_last_number_and_statement():
    t = r"\boxed{12} wait, maybe 13. The answer is 14"
    assert gt_rule(t) == (12, "box")


def test_unparseable_box_does_not_fall_back():
    assert extract_gt(r"x = 7 so \boxed{7x} and the answer is 7.") is None


def test_unclosed_box_is_not_a_box():
    assert gt_rule(r"Thus the speed is: \[ \boxed{58")[1] != "box"


def test_nested_braces():
    assert extract_gt(r"\boxed{\frac{\text{88}}{2}}") is None or True  # does not crash
    assert extract_gt(r"\boxed{\frac{88}{2}}") == 44


@pytest.mark.parametrize("text,want", [
    ("blah 3 + 4 = 7\n#### 7", 7),
    ("#### $1,200", 1200),
    ("Therefore, the answer is 256.", 256),
    ("The answer is: **48**", 48),
    ("**Final Answer:** $99", 99),
    ("Final answer:\n\n12", 12),
    ("So the answer is \\(30\\).", 30),
    ("The final answer is 3/4.", 0.75),
    ("The answer is 5 hours and 30 minutes.", None),
    ("**Final Answer:** Jean is 23 years old.", 23),
    ("**Final Answer:**  \nTogether, Cody and Amir eat 20 cookies.", 20),
])
def test_statements(text, want):
    v, rule = gt_rule(text)
    assert rule == "statement"
    assert v == (pytest.approx(want) if want is not None else None)


def test_last_statement_wins():
    assert extract_gt("The answer is 5. Hmm, recheck. The answer is 6.") == 6


@pytest.mark.parametrize("text,want", [
    ("Work...\n\nTherefore, Lee earned a total of $558 mowing lawns last week.", 558),
    ("So, Benedict's house is **2350 square feet**.", 2350),
    ("Therefore, Rosie should run for \\(30\\) minutes on Friday.", 30),
    ("Thus, 75% of the flowers in the garden are not roses.", 75),
    ("In total, she has 1,200 stamps.", 1200),
])
def test_conclusion_line(text, want):
    assert gt_rule(text) == (pytest.approx(want), "conclusion")
    assert extract_gt_strict(text) is None


@pytest.mark.parametrize("text", [
    "Therefore, the number of driveways Tobias",          # truncated, no period
    "So, the maximum number of unused crayons is",         # truncated
    "Therefore, 24 + 16 + 10 = 50 inches.",                # several numbers
    "\\[ 528 + 30 = 558 \\]",                              # bare equation
    "The total is 558.",                                   # no conclusion marker
    "Therefore, Lee earned $558.\nLet me double check: 500 + 58",  # not the last line
    "The difference is:\n\n",
])
def test_no_arbitrary_last_number(text):
    assert extract_gt(text) is None


def test_is_correct_equivalence():
    assert is_correct_gt(r"\boxed{1,200.00}", 1200.0)
    assert is_correct_gt(r"\boxed{\frac{24}{2}}", 12.0)
    assert not is_correct_gt(r"\boxed{\frac{44}{3}}", 15.0)
    assert not is_correct_gt("no answer here 15", 15.0)
    assert not is_correct_gt(None, 15.0)
    assert not is_correct_gt(r"\boxed{15}", None)


def test_v1_accepts_are_gt_accepts():
    """Everything v1 reads from a box or '####' line, gt reads identically."""
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # toolkit/
    sys.path.insert(0, repo)
    from drift.extract import extract_v1
    for t in [r"\boxed{42}", r"\boxed{-3.5}", "x\n#### 17", r"a \boxed{1} b \boxed{2}"]:
        assert extract_gt(t) == extract_v1(t)


def test_thin_space_thousands():
    assert extract_gt(r"\boxed{1\,200}") == 1200
    assert extract_gt(r"\boxed{12 \, 5}") is None


def test_markdown_heading_is_not_hashes():
    t = "#### Step 2: totals\nTotal = 80 + 150 = 230 miles\nSo, each train covers **230 miles**."
    assert gt_rule(t) == (230, "conclusion")


def test_anchor_without_number_is_not_a_statement():
    assert gt_rule("The answer is not obvious. Let us compute 5 + 6 = 11")[1] == "none"
    assert gt_rule("The answer is correct.\nSo, Seth is 16 years old.") == (16, "conclusion")


def test_conclusion_bold_disambiguates():
    t = "So, Sandra must deliver **160** red roses by 5 pm to avoid switching suppliers."
    assert gt_rule(t) == (160, "conclusion")
    assert extract_gt("So, **8** pens cost **$12.00**.") is None
    assert extract_gt("Therefore, 8 pens will cost $12.00.") is None
