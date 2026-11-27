"""Scorers: how an answer is read out of a model output and compared with the gold answer.

The two numeric scorers are the paper's extractors, kept as they were when the runs were
made. Qwen2.5-Instruct puts its final answer in \\boxed{...} almost every time, so both read
the box. They differ in how forgiving they are:

strict  (v1): a plain number inside the last \\boxed{} or after '####'
              (digits, optional minus sign and decimal point; nothing else).
lenient (v2): everything strict accepts, plus commas, $, units or \\text{} inside the box,
              a loose number after '####', bold **n**, 'answer is n', and finally the last
              number in the response.

A scorer is part of the environment. Swapping strict for lenient changes grades on text that
did not change, which is the extraction drift the paper measures.
"""
from __future__ import annotations

import hashlib
import inspect
import re
import string
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .errors import DriftAuditError

PLAIN = r"-?\d+(?:\.\d+)?"
LOOSE = r"-?\$?\s*\d[\d,]*(?:\.\d+)?"

# The lenient rules that scan the whole response, in the order they are tried.
_TEXT_RULES = (("hashes_loose", r"####\s*(" + LOOSE + r")"),
               ("bold", r"\*\*\s*(" + LOOSE + r")[^*]{0,20}\*\*"),
               ("answer_is", r"answer is[:\s]*(" + LOOSE + r")"))


def _to_float(s):
    s = s.replace(",", "").replace("$", "").replace(" ", "").rstrip(".")
    try:
        return float(s)
    except ValueError:
        return None


def _last_boxed(text):
    """Content of the last \\boxed{...}, allowing one level of nested braces."""
    hits = re.findall(r"\\boxed\{((?:[^{}]|\{[^{}]*\})*)\}", text)
    return hits[-1].strip() if hits else None


def extract_v1(text):
    box = _last_boxed(text)
    if box is not None and re.fullmatch(PLAIN, box):
        return float(box)
    hits = re.findall(r"####\s*(" + PLAIN + r")\s*$", text, flags=re.M)
    return float(hits[-1]) if hits else None


def _lenient(text):
    """(value, rule) of the lenient extractor; one function so the two can never disagree."""
    v = extract_v1(text)
    if v is not None:
        return v, "v1"
    box = _last_boxed(text)
    if box is not None:
        cleaned = re.sub(r"\\text\{[^{}]*\}|\\[a-zA-Z]+|[{}%]", " ", box)
        m = re.search(LOOSE, cleaned)
        if m and _to_float(m.group(0)) is not None:
            return _to_float(m.group(0)), "boxed_loose"
    for rule, pat in _TEXT_RULES:
        hits = re.findall(pat, text, flags=re.I)
        for h in reversed(hits):
            if _to_float(h) is not None:
                return _to_float(h), rule
    nums = re.findall(LOOSE, text)
    for n in reversed(nums):
        if _to_float(n) is not None:
            return _to_float(n), "last_number"
    return None, "none"


def extract_v2(text):
    return _lenient(text)[0]


def lenient_rule(text: str) -> str:
    """Which rule of the lenient scorer produced its answer.

    One of v1, boxed_loose, hashes_loose, bold, answer_is, last_number, none. Anything but
    v1 is an answer the strict scorer does not read.
    """
    return _lenient(text)[1]


def gold_answer(answer_field: str) -> Optional[float]:
    """GSM8K answers end with '#### 72'."""
    return _to_float(answer_field.split("####")[-1].strip())


def _numeric_match(pred, gold):
    if isinstance(gold, str):
        gold = gold_answer(gold)
    return pred is not None and gold is not None and abs(pred - gold) < 1e-6


def _stripped(text):
    return text.strip() or None


def _same_text(pred, gold):
    return pred is not None and gold is not None and pred == str(gold).strip()


_PUNCTUATION = str.maketrans("", "", string.punctuation)


def normalize_text(text: str) -> Optional[str]:
    """Casefold, drop ASCII punctuation, collapse whitespace, drop one leading article."""
    words = text.casefold().translate(_PUNCTUATION).split()
    if words and words[0] in ("a", "an", "the"):
        words = words[1:]
    return " ".join(words) or None


def _same_normalized_text(pred, gold):
    return pred is not None and gold is not None and pred == normalize_text(str(gold))


def source_version(fn: Callable) -> str:
    """First 8 hex characters of the sha1 of a function's source.

    Editing a scorer changes this string, and with it the fingerprint of every environment
    that uses the scorer, so the edit shows up as an environment change.
    """
    try:
        source = inspect.getsource(fn)
    except (OSError, TypeError):
        raise DriftAuditError(f"cannot read the source of {getattr(fn, '__name__', fn)!r} to derive a version; "
                              "pass version='...' when you create the scorer") from None
    return hashlib.sha1(source.encode()).hexdigest()[:8]


class Scorer:
    """Reads an answer out of a model output and says whether it matches the gold answer.

    Pass extract (and optionally correct) as functions, or subclass and override the methods.
    version goes into the environment fingerprint; left out, it is derived from the source
    of the extract function.
    """

    def __init__(self, id: str, extract: Optional[Callable[[str], Any]] = None,
                 correct: Optional[Callable[[Any, Any], bool]] = None,
                 version: Optional[str] = None, name: Optional[str] = None):
        if extract is None and type(self).extract is Scorer.extract:
            raise DriftAuditError(f"scorer {id!r} needs an extract function (or a subclass that overrides extract)")
        self.id = id
        self.name = name or id
        self._extract = extract
        self._correct = correct
        self.version = version if version is not None else source_version(extract or type(self).extract)

    def extract(self, text: str) -> Any:
        """The answer found in text, or None when there is none."""
        return self._extract(text)

    def correct(self, pred: Any, gold: Any) -> bool:
        """Whether an extracted answer matches the gold answer. No answer is never correct."""
        if self._correct is not None:
            return bool(self._correct(pred, gold))
        return pred is not None and gold is not None and pred == gold

    def __repr__(self) -> str:
        return f"Scorer({self.id!r}, version={self.version!r})"


_BUILTIN = {
    "strict": Scorer("strict", extract_v1, _numeric_match, version="1", name="strict numeric"),
    "lenient": Scorer("lenient", extract_v2, _numeric_match, version="1", name="lenient numeric"),
    "exact": Scorer("exact", _stripped, _same_text, version="1", name="exact match"),
    "exact-normalized": Scorer("exact-normalized", normalize_text, _same_normalized_text, version="1",
                               name="normalized exact match"),
}
# The paper and its run files call the numeric scorers v1 and v2.
_ALIASES = {"v1": "strict", "v2": "lenient"}
_REGISTRY: Dict[str, Scorer] = {}


def register(scorer: Scorer) -> Scorer:
    """Make a scorer available to get_scorer under its id. Built-in names cannot be replaced."""
    if scorer.id in _BUILTIN or scorer.id in _ALIASES:
        raise DriftAuditError(f"{scorer.id!r} is a built-in scorer; register yours under another id")
    _REGISTRY[scorer.id] = scorer
    return scorer


def get_scorer(id: Union[str, Scorer]) -> Scorer:
    """The scorer registered under an id. v1 and v2 are the paper's names for strict and lenient."""
    if isinstance(id, Scorer):
        return id
    name = _ALIASES.get(id, id)
    if name in _BUILTIN:
        return _BUILTIN[name]
    if name in _REGISTRY:
        return _REGISTRY[name]
    known = ", ".join(list(_BUILTIN) + sorted(_REGISTRY))
    raise DriftAuditError(f"unknown scorer {id!r}; known scorers: {known}. Add your own with scoring.register().")


def score_outputs(texts: Sequence[str], golds: Sequence[Any], scorer: Union[str, Scorer]) -> List[int]:
    """One 0/1 label per output: 1 when the scorer reads the gold answer out of it."""
    if len(texts) != len(golds):
        raise DriftAuditError(f"{len(texts)} outputs but {len(golds)} gold answers; they must line up item by item")
    scorer = get_scorer(scorer)
    return [int(scorer.correct(scorer.extract(text), gold)) for text, gold in zip(texts, golds)]
