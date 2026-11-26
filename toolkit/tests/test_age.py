from drift.analysis import RunView, age_row

# Three rounds, four eval items. C1 is accepted, so the incumbent is p0 at round 0 and p1 after.
LABELS = {
    "p0": {"E1": [1, 0, 0, 0], "E4": [1, 1, 1, 0]},
    "p1": {"E1": [1, 1, 0, 0], "E4": [1, 1, 1, 0]},
    "p2": {"E1": [1, 0, 0, 1], "E4": [1, 1, 0, 0]},
    "p3": {"E1": [1, 0, 1, 0], "E4": [1, 1, 1, 0]},
}
# The reruns that do not repeat their stored labels: one reference and one candidate. A candidate's
# rerun is never read, so p3's must not change any result.
RERUN = {("p0", "E1"): [1, 1, 0, 0], ("p3", "E1"): [1, 1, 1, 0]}


def make_view(seed=1, labels=LABELS):
    run = {
        "seed": seed,
        # The trajectory drifts after round 0; age_row must ignore that and use the envs it is given.
        "config": {"n_eval": 4, "n_dev": 4, "schedule": {"0": "E1", "1": "E4"}},
        "snapshots": [{"round": 0, "prompt": "p0"}, {"round": 1, "prompt": "p1"}, {"round": 2, "prompt": "p1"}],
        "candidates": [{"round": 0, "prompt": "p1"}, {"round": 1, "prompt": "p2"}, {"round": 2, "prompt": "p3"}],
        "correct": {h: {e: {"current": lab, "rerun": RERUN.get((h, e), lab)} for e, lab in envs.items()}
                    for h, envs in labels.items()},
    }
    return RunView(run, stored_scoring="as_recorded")


def close(xs, expected):
    return len(xs) == len(expected) and all(abs(x - e) < 1e-9 for x, e in zip(xs, expected))


def test_pairs_shrink_with_age():
    assert [age_row([make_view()], a, "E1")["pairs"] for a in (0, 1, 2, 3)] == [3, 2, 1, 0]


def test_age_zero_unchanged_is_the_ground_truth_gate():
    r = age_row([make_view()], 0, "E1")
    assert (r["promoted"], r["false_accepts"]) == (1, 0)   # only C1 beats its incumbent
    assert (r["rerun_promoted"], r["rerun_false_accepts"]) == (0, 0)   # the noisy rerun hides C1's gain
    # p0's rerun differs from its stored labels on one item, and that is all the inflation there is.
    assert close(r["stored_win"], [1 / 4]) and close(r["rerun_win"], [1 / 6]) and close(r["inflation"], [1 / 12])


def test_changed_environment_inflates_against_stored_labels():
    r = age_row([make_view()], 0, "E4")
    assert close(r["stored_win"], [0.25]) and close(r["rerun_win"], [0.0]) and close(r["inflation"], [0.25])
    assert (r["promoted"], r["false_accepts"]) == (2, 2)   # neither beats its incumbent under E4
    assert (r["rerun_promoted"], r["rerun_false_accepts"]) == (0, 0)   # a refresh removes both


def test_false_accept_is_judged_against_the_incumbent_of_the_candidates_round():
    # At age 1, C2 beats the round-0 reference p0 but only ties p1, the incumbent at its own round.
    r = age_row([make_view()], 1, "E1")
    assert (r["pairs"], r["promoted"], r["false_accepts"]) == (2, 1, 1)


def test_old_reference_accepts_a_candidate_no_better_than_the_incumbent():
    # At age 2, C3 is compared with p0 and wins, but the incumbent is p1 and C3 only ties it.
    # The same candidate is rejected at age 0, with the same scoring environment in both cases.
    r = age_row([make_view()], 2, "E1")
    assert (r["pairs"], r["promoted"], r["false_accepts"]) == (1, 1, 1)


def test_promotions_are_pooled_over_seeds():
    # In the second seed C3 gets every item right under E4, so it is a real gain there.
    other = {**LABELS, "p3": {**LABELS["p3"], "E4": [1, 1, 1, 1]}}
    r = age_row([make_view(1), make_view(2, other)], 0, "E4")
    assert (r["pairs"], r["promoted"], r["false_accepts"]) == (6, 4, 3)
    assert close(r["stored_win"], [1 / 4, 1 / 3])
    assert (r["rerun_promoted"], r["rerun_false_accepts"]) == (1, 0)   # the second seed's real gain


def test_refreshing_an_old_reference_does_not_make_it_the_incumbent():
    # p0 stays weak under E4 here, so at age 2 C3 beats it stored or rerun, yet only ties p1.
    weak = {**LABELS, "p0": {"E1": [1, 0, 0, 0], "E4": [1, 0, 0, 0]}}
    r = age_row([make_view(1, weak)], 2, "E4")
    assert (r["promoted"], r["false_accepts"]) == (1, 1)
    assert (r["rerun_promoted"], r["rerun_false_accepts"]) == (1, 1)


def test_min_round_fixes_the_candidate_set():
    assert [age_row([make_view()], a, "E1", min_round=2)["pairs"] for a in (0, 1, 2)] == [1, 1, 1]
    r = age_row([make_view()], 0, "E4", min_round=2)        # C3 only
    assert close(r["stored_win"], [0.25]) and (r["promoted"], r["false_accepts"]) == (1, 1)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
    print(f"{len(tests)} age tests passed")

