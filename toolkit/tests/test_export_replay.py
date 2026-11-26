from export_replay import check_trace


def test_trace_recomputes_chains_and_latex():
    text = r"She has \(16 - 3 - 4 = 9\) eggs, earning \(9 \times 2 = 18\) dollars, not 18 / 3 = 5."
    assert [(s["text"], s["ok"]) for s in check_trace(text)] == [
        ("16 - 3 - 4 = 9", True), ("9 * 2 = 18", True), ("18 / 3 = 5", False)]


def test_trace_ignores_text_without_arithmetic():
    assert check_trace(r"So the answer is \boxed{18}.") == []


def test_false_promotion_cause_uses_a_fresh_reference():
    from export_replay import cause
    base = {"false_accept": True, "env": "E4", "fresh_wins": 16, "fresh_losses": 22}
    assert cause(base) == "stale"
    assert cause({**base, "fresh_wins": 25, "fresh_losses": 21}) == "anyway"
    assert cause({**base, "env": "E1"}) == "before_change"
    assert cause({**base, "false_accept": False}) is None

