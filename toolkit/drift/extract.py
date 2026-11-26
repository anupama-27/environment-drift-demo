"""Answer extractors. Both versions are frozen; do not edit them after runs start.

Qwen2.5-Instruct puts its final answer in \\boxed{...} almost every time, so both
versions read the box. They differ in how forgiving they are:

v1 (strict): a plain number inside the last \\boxed{} or after '####'
             (digits, optional minus sign and decimal point; nothing else).
v2 (lenient): everything v1 accepts, plus commas, $, units or \\text{} inside the box,
             bold **n**, 'answer is n', and finally the last number in the response.
"""
import re

PLAIN = r"-?\d+(?:\.\d+)?"
LOOSE = r"-?\$?\s*\d[\d,]*(?:\.\d+)?"


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


def extract_v2(text):
    v = extract_v1(text)
    if v is not None:
        return v
    box = _last_boxed(text)
    if box is not None:
        cleaned = re.sub(r"\\text\{[^{}]*\}|\\[a-zA-Z]+|[{}%]", " ", box)
        m = re.search(LOOSE, cleaned)
        if m and _to_float(m.group(0)) is not None:
            return _to_float(m.group(0))
    for pat in (r"####\s*(" + LOOSE + r")", r"\*\*\s*(" + LOOSE + r")[^*]{0,20}\*\*",
                r"answer is[:\s]*(" + LOOSE + r")"):
        hits = re.findall(pat, text, flags=re.I)
        for h in reversed(hits):
            if _to_float(h) is not None:
                return _to_float(h)
    nums = re.findall(LOOSE, text)
    for n in reversed(nums):
        if _to_float(n) is not None:
            return _to_float(n)
    return None


EXTRACTORS = {"v1": extract_v1, "v2": extract_v2}


def gold_answer(answer_field):
    """GSM8K answers end with '#### 72'."""
    return _to_float(answer_field.split("####")[-1].strip())


def is_correct(pred, gold):
    return pred is not None and gold is not None and abs(pred - gold) < 1e-6

