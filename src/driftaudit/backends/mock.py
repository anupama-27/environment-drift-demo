"""A deterministic stand-in for a model, for trying the whole pipeline without a GPU or an API.

Nothing it produces is a measurement, and runs made with it are written as "synthetic". It is
shaped after what the paper's runs look like so that every part of an audit has something to
show:

- how often an instruction gets an item right depends on the instruction and on the item;
- sampling adds noise, so a stored pass and a rerun disagree on some items; greedy decoding
  is exactly repeatable here, which a real GPU is not;
- greedy decoding gets stuck repeating itself on a few items and runs out of tokens before
  it gives an answer, as small models do. Sampling usually gets out of the loop, which is
  why a reference stored under greedy decoding looks worse than its rerun once the loop
  samples;
- most answers come as a plain number in \\boxed{}, a few carry a dollar sign, commas or units,
  or skip the box, which the lenient scorer reads and the strict one does not. An instruction
  that asks for units gets many more of those;
- a proposer request gets back a rewritten instruction inside <prompt></prompt>.

Every draw is a sha1 of what it depends on. There is no random state, so the same call always
returns the same text, on any machine and any Python version.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Dict, List, Mapping, Sequence

from ..errors import DriftAuditError
from .base import Backend, Conversation

MODEL_ID = "driftaudit-mock"
# Raise this when the simulation changes, so cached text from an older version is not reused.
VERSION = "2"

# Answer formats. Only the first is read by the strict scorer.
STYLES = ("plain", "dollar", "commas", "units", "answer_is", "bold", "last_number")

_UNITS = ("dollars", "pages", "apples", "minutes", "miles")
_WORKING = (
    "Take the quantities in the order they appear and combine them.",
    "Set up the calculation from what is given, then carry it out.",
    "Go through the problem a step at a time and keep a running total.",
    "Write down how the quantities relate and solve for the unknown.",
)
# Share of items on which an instruction loops under greedy decoding, and how much rarer
# that is for a sample.
_LOOP_RATE = 0.035
_LOOP_SAMPLED = 0.25
_OFFSETS = (1, 2, 3, 5, 10, 12, 20, 100, -1, -2, -5)
_TIPS = (
    "Solve the problem one step at a time and show each step.",
    "List the quantities you are given before you calculate.",
    "Check each arithmetic step before you move on.",
    "Read the question again at the end and make sure you answered what was asked.",
    "If the problem has several parts, work through them in order.",
    "Do not skip a step because it looks obvious.",
    "Turn percentages and fractions into numbers before you use them.",
    "Estimate the result first, then compute it exactly.",
    "Keep intermediate results exact and round only at the end.",
    "Say what each number stands for when you introduce it.",
    "Compare your result with the numbers in the question to see whether it is plausible.",
    "Include units such as dollars or pages with the answer.",
)


def _u(*parts: object) -> float:
    """A number in [0, 1) fixed by its arguments."""
    digest = hashlib.sha1(json.dumps(parts).encode()).hexdigest()
    return int(digest[:13], 16) / 16 ** 13


def _number(value: float) -> str:
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.9f}".rstrip("0").rstrip(".")


def format_answer(value: float, style: str, unit: str = "dollars") -> str:
    """The last line of a reply giving `value` in one of STYLES."""
    n = _number(value)
    if style == "plain":
        return f"\\boxed{{{n}}}"
    if style == "dollar":
        return f"\\boxed{{\\${n}}}"
    if style == "commas":
        return f"\\boxed{{{int(value):,}}}"
    if style == "units":
        return f"\\boxed{{{n} \\text{{ {unit}}}}}"
    if style == "answer_is":
        return f"The answer is {n}."
    if style == "bold":
        return f"**{n}**"
    if style == "last_number":
        return f"That comes to {n} in total."
    raise ValueError(f"unknown answer style {style!r}")


def _loose_styles(value: float) -> List[str]:
    """The formats the strict scorer misses that can carry this value unchanged."""
    styles = ["units", "answer_is", "bold", "last_number"]
    if value >= 0:
        styles.append("dollar")
    if value == int(value) and 1000 <= abs(value) < 1e15:
        styles.append("commas")
    return styles


def _skill(system: str) -> float:
    # Rewrites of an instruction differ by a few points of accuracy, not by tens.
    return 0.65 + 0.10 * _u("skill", system)


def _slip_rate(system: str) -> float:
    """Share of answers this instruction gets in a format only the lenient scorer reads."""
    if re.search(r"\bunits?\b", system, flags=re.I):
        return 0.10 + 0.30 * _u("units", system)
    return 0.02 + 0.04 * _u("slip", system)


class MockBackend(Backend):
    name = "mock"
    synthetic = True

    def __init__(self, items: Sequence[Mapping[str, Any]]) -> None:
        super().__init__()
        self._gold: Dict[str, Any] = {}
        for item in items:
            gold = item["gold"]
            if isinstance(gold, (int, float)) and not isinstance(gold, bool):
                gold = float(gold)
            self._gold[item["question"]] = gold
        if not self._gold:
            raise DriftAuditError("The mock backend simulates answers from the gold answers, so it "
                                  "needs the task items: make_backend('mock', items=task.dev + task.eval).")
        self._strings = sorted({g for g in self._gold.values() if isinstance(g, str)})

    def describe(self) -> Dict[str, object]:
        return {"backend": self.name, "model": MODEL_ID, "revision": VERSION}

    @property
    def cache_id(self) -> str:
        return f"{MODEL_ID}@{VERSION}"

    def _chat(self, conversations: List[Conversation], temperature: float,
              seeds: List[int], max_new_tokens: int) -> List[str]:
        replies = []
        for messages, seed in zip(conversations, seeds):
            system = messages[0]["content"] if len(messages) > 1 else ""
            user = messages[-1]["content"]
            if user in self._gold:
                replies.append(self._answer(system, user, temperature, seed))
            else:
                replies.append(_rewrite(user, seed))
        return replies

    def _answer(self, system: str, question: str, temperature: float, seed: int) -> str:
        # Greedy text does not depend on the seed; a sampled reply is one draw per seed.
        draw = seed if temperature > 0 else 0
        margin = _skill(system) - _u("difficulty", question) - 0.6 * (_u("fit", system, question) - 0.5)
        if temperature > 0:
            margin += 1.35 * temperature * (_u("sample", system, question, draw) - 0.5)
            looped = _u("loop", system, question, draw) < _LOOP_RATE * _LOOP_SAMPLED
        else:
            looped = _u("loop", system, question) < _LOOP_RATE
        right = margin > 0
        slip = _u("slip-here", system, question, draw) < _slip_rate(system)
        pick = _u("pick", system, question, draw)
        gold = self._gold[question]
        if isinstance(gold, str):
            return self._string_answer(gold, right, slip, pick)
        working = _WORKING[int(_u("working", system, question) * len(_WORKING))]
        if looped:
            # No number anywhere, so neither scorer finds an answer.
            return " ".join([working] * 12)
        value = gold if gold is not None else 0.0
        if not right or gold is None:
            value += _OFFSETS[int(pick * len(_OFFSETS))]
        style = "plain"
        if slip:
            choices = _loose_styles(value)
            style = choices[int(_u("style", system, question, draw) * len(choices))]
        unit = _UNITS[int(_u("unit", question) * len(_UNITS))]
        return f"{working}\n{format_answer(value, style, unit)}"

    def _string_answer(self, gold: str, right: bool, slip: bool, pick: float) -> str:
        """Tasks graded by exact match: the reply is the answer and nothing else."""
        if not right:
            others = [s for s in self._strings if s.casefold() != gold.casefold()]
            return others[int(pick * len(others))] if others else "unknown"
        if not slip:
            return gold
        # Right, but only after normalization: different case or a trailing full stop.
        swapped = gold.lower() if gold != gold.lower() else gold.upper()
        return swapped if pick < 0.5 and swapped != gold else gold + "."


def _rewrite(request: str, seed: int) -> str:
    """Answer a proposer request the way a small model tends to.

    The new instruction keeps the first sentence of the current one, adds one to three pieces
    of advice, and keeps the closing sentence (usually the answer format) a little under half
    of the time. Now and then the reply is not an instruction at all.
    """
    if _u("unusable", request, seed) < 0.04:
        return "Looks fine."
    match = re.search(r"Current instruction:\n(.*?)\n\nThe model got", request, flags=re.S)
    sentences = re.split(r"(?<=[.!?])\s+", match.group(1).strip()) if match else []
    opening = sentences[0] if sentences and sentences[0] else "Answer the question with care."
    count = 1 + int(3 * _u("count", request, seed))
    ranked = sorted(range(len(_TIPS)), key=lambda i: _u("tip", request, seed, i))
    parts = [opening] + [_TIPS[i] for i in sorted(ranked[:count])]
    if len(sentences) > 1 and _u("closing", request, seed) < 0.42:
        parts.append(sentences[-1])
    return "<prompt>" + " ".join(parts) + "</prompt>"
