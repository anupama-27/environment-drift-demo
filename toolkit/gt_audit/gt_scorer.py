"""Frozen, environment-independent ground-truth (GT) answer scorer for the drift experiment.

FROZEN: do not edit after the audit (2026-10-24). It is never bound to an environment;
E1-E4 keep using drift/extract.py v1/v2. Change it only with a new name (extract_gt2).

Principle: credit only the model's committed final answer, read format-tolerantly.
Never credit an arbitrary last number in free text.

Precedence (the first rule that applies decides; later rules are not consulted):
  1. BOX       The last closed \\boxed{...} (or \\fbox{...}). Its content must reduce to a single
               numeric value after removing $, \\$, commas between digit groups, %, \\text{...}
               and \\mathrm{...} (units), LaTeX spacing, a trailing period, and anything before a
               final '=' or '\\approx'. \\frac{a}{b}, a/b, mixed numbers and a\\times10^{b} are
               evaluated. A box holding several numbers ("64 weasels, 32 rabbits") or a variable
               ("294n") yields None: it is the committed answer and it is not a number.
  2. STATEMENT No closed box: the last explicit final-answer statement: a GSM8K line '#### N', or
               an anchor '(final) answer is', '(final) answer:' or 'Final Answer' (markdown allowed)
               followed by a sentence (which may start on the next line) holding a number. Exactly
               one number in that sentence -> its value ('**Final Answer:** Jean is 23 years old');
               several -> None ('the answer is 5 hours and 30 minutes'). An anchor whose sentence
               holds no number ('the answer is correct') is not a statement.
  3. CONCLUSION No box and no statement: the response's last non-empty line, if it is a complete
               concluding sentence: starts with Therefore/Thus/So/Hence/In conclusion/In total/
               In summary/Overall/Finally/Consequently/Altogether, ends with '.' or '!', and
               contains exactly one number, or exactly one **bold** span holding one number.
               A truncated tail, a bare equation, a trailing non-conclusion paragraph or a line
               with several unemphasised numbers yields None.
Equivalence: numeric, |pred - gold| <= 1e-6 * max(1, |gold|).

extract_gt_strict() = rules 1-2 only (the literal mentor spec), kept for sensitivity analysis.
"""
import re
from fractions import Fraction

__all__ = ["extract_gt", "extract_gt_strict", "gt_rule", "is_correct_gt", "numeric_equal"]

NUM = r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\.\d+"
_NUM_RE = re.compile(NUM)


# ---------------------------------------------------------------- helpers
def _boxes(text):
    """Contents of every closed \\boxed{...}/\\fbox{...} in order (arbitrary brace nesting)."""
    out = []
    for m in re.finditer(r"\\(?:boxed|fbox)\s*\{", text):
        i, depth = m.end(), 1
        while i < len(text) and depth:
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
            i += 1
        if depth == 0:
            out.append((m.start(), text[m.end():i - 1]))
    return out


def _num(s):
    s = s.replace(",", "")
    try:
        return float(Fraction(s))
    except (ValueError, ZeroDivisionError):
        return None


def _clean_latex(s):
    s = s.replace("\u2212", "-").replace("\u2013", "-")
    s = re.sub(r"(\d)\\,(?=\d{3}\b)", r"\1", s)  # LaTeX thin-space thousands separator 1\,200
    s = re.sub(r"\\(?:text|mathrm|textbf|mbox|operatorname)\s*\{[^{}]*\}", " ", s)  # units
    s = re.sub(r"\\(?:left|right|displaystyle)\b", "", s)
    s = re.sub(r"\\[,;:! ]|\\quad|\\qquad|~", " ", s)
    s = s.replace("\\$", " ").replace("$", " ").replace("\\%", " ").replace("%", " ")
    s = re.sub(r"\\[dt]frac", r"\\frac", s)
    s = re.sub(r"\^\s*\{?\s*\\circ\s*\}?|°", " ", s)  # degrees
    return s


def parse_value(content):
    """Single numeric value of a box's content, or None."""
    s = _clean_latex(content)
    s = re.split(r"=|\\approx|\\equiv", s)[-1]
    s = s.strip().rstrip(".").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"^\{(.*)\}$", r"\1", s).strip()
    neg = False
    if s.startswith("-"):
        neg, s = True, s[1:].strip()
    if re.search(r"\d\s+[\d.]", s):  # two separate numbers, e.g. "160 and 300" after unit removal
        return None
    s = s.replace(" ", "")
    v = None
    if re.fullmatch(r"\d+(?:,\d{3})*(?:\.\d+)?|\.\d+", s):
        v = _num(s)
    elif m := re.fullmatch(r"\\frac\{(" + NUM + r")\}\{(" + NUM + r")\}", s):
        a, b = _num(m.group(1)), _num(m.group(2))
        v = a / b if a is not None and b else None
    elif m := re.fullmatch(r"(\d+)\\frac\{(\d+)\}\{(\d+)\}", s):  # mixed number 2\frac{1}{2}
        b = _num(m.group(3))
        v = _num(m.group(1)) + _num(m.group(2)) / b if b else None
    elif m := re.fullmatch(r"(\d+(?:\.\d+)?)/(\d+(?:\.\d+)?)", s):
        b = _num(m.group(2))
        v = _num(m.group(1)) / b if b else None
    elif m := re.fullmatch(r"(\d+(?:\.\d+)?)(?:\\times|\\cdot|\*|x)10\^\{?(-?\d+)\}?", s):
        v = _num(m.group(1)) * 10 ** int(m.group(2))
    if v is None:
        return None
    return -v if neg else v


def _numbers_in(s):
    s = re.sub(r"\\(?:text|mathrm|textbf|mbox)\s*\{([^{}]*)\}", r" \1 ", s)  # keep content here
    s = _clean_latex(s)
    vals = []
    for m in re.finditer(r"\\frac\{(" + NUM + r")\}\{(" + NUM + r")\}|(" + NUM + r")(?:\s*/\s*(\d+(?:\.\d+)?))?", s):
        if m.group(3) is not None:
            v = _num(m.group(3))
            if m.group(4) is not None:
                d = _num(m.group(4))
                v = v / d if d else None
            vals.append(v)
        else:
            a, b = _num(m.group(1)), _num(m.group(2))
            vals.append(a / b if b else None)
    return vals


_HASHES = re.compile(r"^[ \t]*####[ \t]*(?:\\?\$)?[ \t]*(" + NUM + r")[ \t]*\.?[ \t]*$", re.M)
_ANCHOR = re.compile(r"\b(?:final\s+answer|answer)\s*(?:is|:|=)|\bfinal\s+answer\b", re.I)


def _statement(text):
    """(position, value) of the last final-answer statement, or None if there is none.

    '#### N' (GSM8K style, N alone on the line) always counts. For an 'answer is/answer:/final
    answer' anchor, the sentence after it (may start on the next line) must contain a number to
    count as a statement; exactly one number -> that value, several -> None (not a single answer).
    """
    found = [(m.start(), _num(m.group(1))) for m in _HASHES.finditer(text)]
    for m in _ANCHOR.finditer(text):
        rest = re.sub(r"^[\s:*_]*", "", text[m.end():])  # may cross one line break
        sent = re.split(r"\n|(?<!\d)\.(?!\d)|\.(?=\s|$)", rest, maxsplit=1)[0]
        vals = _numbers_in(sent)
        if vals:
            found.append((m.start(), vals[0] if len(vals) == 1 else None))
    return max(found) if found else None


_CONCL = re.compile(r"(?:therefore|thus|so|hence|consequently|in conclusion|in total|in summary|"
                    r"overall|finally|altogether)\b", re.I)


def _conclusion(text):
    lines = [l.strip() for l in text.strip().splitlines() if l.strip()]
    if not lines:
        return None
    line = re.sub(r"^[\s>#*\-_]+", "", lines[-1])
    if not _CONCL.match(line):
        return None
    if not re.search(r"[.!](?:\*\*|\$|\\\)|\\\]|\s)*$", line):
        return None
    vals = _numbers_in(line)
    if len(vals) == 1:
        return vals[0]
    bold = [v for b in re.findall(r"\*\*(.+?)\*\*", line) for v in [_numbers_in(b)] if v]
    if len(bold) == 1 and len(bold[0]) == 1:  # one emphasised number: "deliver **160** roses by 5 pm."
        return bold[0][0]
    return None


# ---------------------------------------------------------------- public API
def gt_rule(text):
    """(value, rule) with rule in {'box', 'statement', 'conclusion', 'none'}."""
    if text is None:
        return None, "none"
    boxes = _boxes(text)
    if boxes:
        return parse_value(boxes[-1][1]), "box"
    st = _statement(text)
    if st is not None:
        return st[1], "statement"
    c = _conclusion(text)
    if c is not None:
        return c, "conclusion"
    return None, "none"


def extract_gt(text):
    return gt_rule(text)[0]


def extract_gt_strict(text):
    v, rule = gt_rule(text)
    return v if rule in ("box", "statement") else None


def numeric_equal(pred, gold):
    return pred is not None and gold is not None and abs(pred - gold) <= 1e-6 * max(1.0, abs(gold))


def is_correct_gt(text, gold):
    return numeric_equal(extract_gt(text), gold)
