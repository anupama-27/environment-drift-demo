from drift.extract import extract_v1, extract_v2, gold_answer

def test_v1_plain():
    assert extract_v1("so \\(\\boxed{18}\\) dollars") == 18
    assert extract_v1("work\n#### 42") == 42

def test_v1_rejects_formats_v2_accepts():
    cases = [("\\boxed{70,000}", 70000), ("$\\boxed{\\$15}$", 15), ("\\boxed{540 \\text{ meters}}", 540),
             ("a total of **540** meters", 540), ("The answer is 1,200.", 1200), ("= 12 years", 12)]
    for text, val in cases:
        assert extract_v1(text) is None, text
        assert extract_v2(text) == val, text

def test_gold():
    assert gold_answer("blah\n#### 1,234") == 1234

if __name__ == "__main__":
    test_v1_plain(); test_v1_rejects_formats_v2_accepts(); test_gold(); print("extractor tests passed")

