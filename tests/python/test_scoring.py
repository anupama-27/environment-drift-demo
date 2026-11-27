from __future__ import annotations

import json
import os

import pytest

from conftest import GOLDEN
from driftaudit import scoring
from driftaudit.errors import DriftAuditError
from driftaudit.scoring import Scorer, get_scorer, gold_answer, lenient_rule, score_outputs

strict = get_scorer("strict")
lenient = get_scorer("lenient")


@pytest.fixture(scope="module")
def cases():
    """Real model outputs from the paper runs with what the original extractors read."""
    with open(os.path.join(GOLDEN, "scorer_cases.json"), encoding="utf-8") as f:
        return json.load(f)


# Ported from toolkit/tests/test_extract.py.

def test_v1_plain():
    assert strict.extract("so \\(\\boxed{18}\\) dollars") == 18
    assert strict.extract("work\n#### 42") == 42


def test_v1_rejects_formats_v2_accepts():
    cases = [("\\boxed{70,000}", 70000), ("$\\boxed{\\$15}$", 15), ("\\boxed{540 \\text{ meters}}", 540),
             ("a total of **540** meters", 540), ("The answer is 1,200.", 1200), ("= 12 years", 12)]
    for text, val in cases:
        assert strict.extract(text) is None, text
        assert lenient.extract(text) == val, text


def test_gold():
    assert gold_answer("blah\n#### 1,234") == 1234


# The same answers the paper's extractors read, on real outputs.

def test_strict_reads_what_the_paper_extractor_read(cases):
    for case in cases:
        assert strict.extract(case["text"]) == case["strict"]
        assert strict.correct(strict.extract(case["text"]), case["gold"]) is case["strict_correct"]


def test_lenient_reads_what_the_paper_extractor_read(cases):
    for case in cases:
        assert lenient.extract(case["text"]) == case["lenient"]
        assert lenient.correct(lenient.extract(case["text"]), case["gold"]) is case["lenient_correct"]


def test_lenient_rule_names_the_rule_that_fired(cases):
    for case in cases:
        assert lenient_rule(case["text"]) == case["rule"]


def test_scorers_agree_with_the_toolkit_extractors(cases, toolkit):
    texts = [case["text"] for case in cases]
    texts += ["#### 1,234", "x\n#### 7 \n", "**$1,200 total**", "no number at all", "", "\\boxed{}",
              "\\boxed{\\frac{3}{4}}", "The answer is: -$ 5.50", "#### -3.5", "\\boxed{12} then \\boxed{1{2}3}",
              "ANSWER IS 9", "first 3 then 4.", "\\boxed{7}\n#### 8"]
    for text in texts:
        assert strict.extract(text) == toolkit.extract.extract_v1(text), text
        assert lenient.extract(text) == toolkit.extract.extract_v2(text), text


def test_lenient_rule_order_follows_the_extractor():
    assert lenient_rule("\\boxed{18}") == "v1"
    assert lenient_rule("\\boxed{70,000}") == "boxed_loose"
    assert lenient_rule("#### 1,234") == "hashes_loose"
    assert lenient_rule("a total of **540** meters") == "bold"
    assert lenient_rule("The answer is 1,200.") == "answer_is"
    assert lenient_rule("= 12 years") == "last_number"
    assert lenient_rule("no number at all") == "none"
    # A box the loose rule cannot read falls through to the later rules.
    assert lenient_rule("\\boxed{x} so the answer is 4") == "answer_is"


def test_lenient_never_loses_an_answer_strict_read(cases):
    for case in cases:
        value = strict.extract(case["text"])
        if value is not None:
            assert lenient.extract(case["text"]) == value


def test_numeric_match_uses_the_paper_tolerance():
    assert strict.correct(18.0, 18.0000001)
    assert not strict.correct(18.0, 18.00001)
    assert not strict.correct(None, 18.0)
    assert not strict.correct(18.0, None)


def test_numeric_scorers_take_the_gold_answer_as_text_too():
    assert strict.correct(1234.0, "1,234")
    assert strict.correct(72.0, "blah\n#### 72")
    assert not strict.correct(72.0, "not a number")


def test_paper_names_are_aliases():
    assert get_scorer("v1") is strict
    assert get_scorer("v2") is lenient
    assert (strict.id, lenient.id) == ("strict", "lenient")


def test_get_scorer_passes_a_scorer_through():
    assert get_scorer(strict) is strict


def test_unknown_scorer_lists_the_known_ones():
    with pytest.raises(DriftAuditError, match="exact-normalized"):
        get_scorer("fuzzy")


def test_exact_compares_stripped_text():
    exact = get_scorer("exact")
    assert exact.extract("  Paris \n") == "Paris"
    assert exact.correct(exact.extract("  Paris \n"), "Paris")
    assert not exact.correct(exact.extract("paris"), "Paris")
    assert exact.extract("   ") is None
    assert not exact.correct(None, "Paris")


def test_exact_normalized_ignores_case_spacing_punctuation_and_a_leading_article():
    norm = get_scorer("exact-normalized")
    assert norm.extract("  The  Eiffel   Tower. ") == "eiffel tower"
    assert norm.correct(norm.extract("the Eiffel Tower!"), "Eiffel tower")
    assert norm.correct(norm.extract("An apple"), "apple")
    assert norm.correct(norm.extract("STRASSE"), "straße")
    assert not norm.correct(norm.extract("Tower of the Eiffel"), "Tower of Eiffel")
    assert norm.extract("...") is None


def test_score_outputs_gives_one_label_per_output():
    texts = ["\\boxed{18}", "\\boxed{70,000}", "nothing"]
    assert score_outputs(texts, [18, 70000, 3], "strict") == [1, 0, 0]
    assert score_outputs(texts, [18, 70000, 3], lenient) == [1, 1, 0]


def test_score_outputs_needs_a_gold_answer_for_every_output():
    with pytest.raises(DriftAuditError, match="2 outputs"):
        score_outputs(["a", "b"], ["a"], "exact")


def test_register_adds_a_scorer_and_refuses_builtin_names():
    def extract(text):
        return text.strip().upper() or None

    shout = Scorer("test-shout", extract=extract)
    scoring.register(shout)
    try:
        assert get_scorer("test-shout") is shout
        assert score_outputs([" yes "], ["YES"], "test-shout") == [1]
    finally:
        scoring._REGISTRY.pop("test-shout", None)
    for name in ("strict", "v2", "exact"):
        with pytest.raises(DriftAuditError, match="built-in"):
            scoring.register(Scorer(name, extract=extract))


def test_a_scorer_can_be_written_as_a_subclass():
    class LastWord(Scorer):
        def extract(self, text):
            words = text.split()
            return words[-1] if words else None

    scorer = LastWord("last-word", version="1")
    assert scorer.extract("the answer is blue") == "blue"
    assert scorer.correct("blue", "blue") and not scorer.correct(None, "blue")


def test_source_version_is_stable_and_follows_the_source():
    def one(text):
        return text

    def two(text):
        return text or None

    assert scoring.source_version(one) == scoring.source_version(one)
    assert scoring.source_version(one) != scoring.source_version(two)
    assert len(scoring.source_version(one)) == 8
    int(scoring.source_version(one), 16)


def test_a_scorer_without_a_version_gets_its_source_version():
    def extract(text):
        return text

    assert Scorer("x", extract=extract).version == scoring.source_version(extract)
    assert Scorer("x", extract=extract, version="7").version == "7"


def test_source_version_says_what_to_do_when_there_is_no_source():
    with pytest.raises(DriftAuditError, match="version"):
        scoring.source_version(len)


def test_builtin_versions_are_fixed_strings():
    for name in ("strict", "lenient", "exact", "exact-normalized"):
        assert get_scorer(name).version == "1"
