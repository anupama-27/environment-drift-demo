"""Record a self-improvement loop of your own, then audit it.

    python examples/record_your_own_loop.py [RUN.json]

Nothing here calls a model. `toy_model` stands in for one: it answers 60 addition questions,
gets some wrong depending on the instruction, and now and then writes the answer in a
sentence instead of a box. The optimizer tries one instruction after another and keeps the
reference it measured in the first round, which is the mistake the audit is meant to find:
before round 3 the answer scorer is replaced by a more lenient one, and from then on new
candidates are graded more generously than the stored reference was.

What to copy into your own loop are the four recorder calls: add_labels for every
evaluation, add_round for every decision, a rerun of each reference at the end, and save.
"""
from __future__ import annotations

import hashlib
import sys

import driftaudit as da
from driftaudit.render import render_audit
from driftaudit.scoring import score_outputs

QUESTIONS = [(a, b) for a in range(11, 21) for b in range(3, 9)]
GOLD = [float(a + b) for a, b in QUESTIONS]
INSTRUCTIONS = [
    "Add the two numbers. Put the result in \\boxed{}.",
    "Add the two numbers. Check the sum once. Put the result in \\boxed{}.",
    "Work from the larger number. Put the result in \\boxed{}.",
    "Add the tens first, then the ones. Put the result in \\boxed{}.",
    "Add the two numbers and double-check. Put the result in \\boxed{}.",
    "Count up from the first number. Put the result in \\boxed{}.",
    "Add the two numbers slowly. Put the result in \\boxed{}.",
]


def draw(*parts):
    """A number in [0, 1) that depends only on its arguments."""
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:8], 16) / 16 ** 8


def toy_model(instruction, a, b):
    skill = 0.55 + 0.25 * draw("skill", instruction)
    answer = a + b if draw("right", instruction, a, b) < skill else a + b + 1
    if draw("format", instruction, a, b) < 0.25:
        return f"The answer is {answer}."        # only the lenient scorer reads this
    return f"\\boxed{{{answer}}}"


def evaluate(instruction, env):
    """One 0/1 label per question: what your evaluation harness returns."""
    return score_outputs([toy_model(instruction, a, b) for a, b in QUESTIONS], GOLD, env.scorer)


def main(path="my-loop-run.json"):
    strict = da.Environment.make(name="Strict scorer", model="toy-adder", temperature=0, scorer="strict")
    lenient = da.Environment.make(name="Lenient scorer", model="toy-adder", temperature=0, scorer="lenient")
    rec = da.Recorder(task="toy-addition", n_items=len(QUESTIONS), model="toy-adder", source="synthetic")
    # "frozen" keeps the first reference for good. With "env_triggered", stale() turns true
    # when the environment's fingerprint changes and the loop below measures it again.
    store = da.ReferenceStore(policy="frozen")

    incumbent = INSTRUCTIONS[0]
    for round_idx, candidate in enumerate(INSTRUCTIONS[1:]):
        env = strict if round_idx < 3 else lenient
        if store.stale(env):
            store.set(incumbent, env, evaluate(incumbent, env))
            rec.add_labels(incumbent, env, store.reference.labels)
        labels = evaluate(candidate, env)
        rec.add_labels(candidate, env, labels)
        reference = store.reference
        wins = sum(c and r == "0" for c, r in zip(labels, reference.labels))
        losses = sum(not c and r == "1" for c, r in zip(labels, reference.labels))
        accepted = wins > losses
        rec.add_round(candidate=candidate, incumbent=incumbent, env=env, accepted=accepted,
                      reference=(reference.prompt, reference.env))
        if accepted:
            incumbent = candidate

    # What would a refresh have shown? Evaluate every instruction under both environments
    # again. The first evaluation of a pair is its stored pass; a repeat goes in as a rerun.
    for instruction in INSTRUCTIONS:
        for env in (strict, lenient):
            rec.add_labels(instruction, env, evaluate(instruction, env))
            rec.add_labels(instruction, env, evaluate(instruction, env), rerun=True)

    run = rec.save(path)
    result = da.audit(run)
    print(render_audit(result, policy="as_run"))
    return result


if __name__ == "__main__":
    main(*sys.argv[1:2])
