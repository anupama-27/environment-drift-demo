"""Text and Markdown views of audit and study results.

The engine returns unrounded numbers; this is the only place they are formatted. Fractions
become percentages with one decimal, differences become percentage points with two decimals
and a sign, counts get thousands separators.
"""
from __future__ import annotations

import re
import textwrap
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .engine import as_run_is_trivial

CAUSES = {
    "stale": "stale reference",
    "anyway": "would have been accepted anyway",
    "no_drift": "no environment change",
}
AS_RUN_NOTE = ("As run is not listed: the loop compared each candidate with its own incumbent in the same "
               "pass, so its decisions match the ground-truth check by construction.")
_TONES = {"bad": "31", "warn": "33", "strong": "1"}
WIDTH = 100

# Terminal escape sequences (CSI, OSC and the two-character forms), then any other C0 or C1
# control character except newline and tab.
_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x9b[0-?]*[ -/]*[@-~]|\x1b.?")
_CONTROLS = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")

Cell = Union[str, Tuple[str, str]]          # text, or (text, tone)
Block = Tuple[Any, ...]                     # ("title" | "heading" | "line", text) or ("table", headers, rows)


def _pct(fraction: Optional[float]) -> str:
    return "n/a" if fraction is None else f"{100 * fraction:.1f}%"


def _pp(points: Optional[float]) -> str:
    if points is None:
        return "n/a"
    return f"{0.0 if abs(points) < 0.005 else points:+.2f}"


def _count(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value:,.0f}" if float(value).is_integer() else f"{value:,.1f}"


def _pair(wins: Optional[int], losses: Optional[int]) -> str:
    return "n/a" if wins is None or losses is None else f"{wins}/{losses}"


def _plural(n: int, word: str) -> str:
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def _policy_name(policy: Mapping[str, Any], options: Mapping[str, Any]) -> str:
    if policy.get("id") == "periodic" and options.get("periodic_k"):
        return f"Every {options['periodic_k']} rounds"
    return str(policy.get("name") or policy.get("id"))


def _round_span(rounds: Sequence[int]) -> str:
    if not rounds:
        return "not scheduled"
    spans = []
    start = last = rounds[0]
    for r in rounds[1:]:
        if r != last + 1:
            spans.append((start, last))
            start = r
        last = r
    spans.append((start, last))
    return ("round " if len(rounds) == 1 else "rounds ") + ", ".join(
        str(a) if a == b else f"{a}-{b}" for a, b in spans)


def _what_if(options: Mapping[str, Any]) -> List[str]:
    """The options that differ from a plain audit, in words."""
    notes = []
    if options.get("schedule_overridden"):
        schedule = options.get("schedule") or {}
        notes.append("schedule " + ",".join(f"{r}:{schedule[r]}" for r in sorted(schedule, key=int)))
    if options.get("stored_scoring") not in (None, "as_recorded"):
        notes.append("stored references rescored with the current scorer")
    if options.get("margin"):
        notes.append(f"accept when wins exceed losses by more than {options['margin']}")
    if options.get("fixed_age") is not None:
        notes.append(f"every reference taken from {options['fixed_age']} rounds back")
    return notes


def _missing(policy: Mapping[str, Any], name: str) -> str:
    missing = policy.get("missing") or []
    total = policy.get("missing_count") or len(missing)
    if not total:
        if policy.get("id") == "as_run":
            return f"{name}: the run log does not say which reference the loop compared each candidate with"
        return f"{name}: cannot be replayed on this run log"
    first = missing[0] if missing else None
    example = ""
    if first:
        kind = "rerun" if first.get("pass") == "rerun" else "stored labels"
        example = f", for example the {kind} of prompt {first.get('prompt')} under {first.get('env')}"
    return f"{name}: needs {_plural(total, 'label vector')} the run log does not have{example}"


def _default_policy(result: Mapping[str, Any], policy: Optional[str], hidden: Sequence[str] = ()) -> Optional[str]:
    policies = result.get("policies") or {}
    if policy is not None:
        return policy if policy in policies else None
    usable = [pid for pid, p in policies.items() if p.get("available", True) and pid not in hidden]
    return "frozen" if "frozen" in usable else (usable[0] if usable else None)


def _decision_rows(decisions: Sequence[Mapping[str, Any]], kind: str) -> List[List[Cell]]:
    rows: List[List[Cell]] = []
    for d in decisions:
        if not d.get(kind):
            continue
        reference = f"{d.get('ref_env')} " + ("rerun" if d.get("ref_fresh") else f"age {d.get('ref_age')}")
        if kind == "false_accept":
            cause = d.get("cause")
            why: Cell = (CAUSES.get(cause, str(cause)) if cause is not None else "rerun not recorded",
                         "warn" if cause == "stale" else "")
        elif d.get("rerun_accepts") is None:
            why = "n/a"
        else:
            why = "accepted against the rerun reference" if d["rerun_accepts"] else "rejected against the rerun reference too"
        inflation = d.get("inflation")
        rows.append([str(d.get("round")), str(d.get("env")), reference, _pair(d.get("wins"), d.get("losses")),
                     _pair(d.get("rerun_wins"), d.get("rerun_losses")),
                     _pp(None if inflation is None else 100 * inflation), _pp(d.get("delta_pp")), why])
    return rows


def _audit_blocks(result: Mapping[str, Any], policy: Optional[str], hide: Sequence[str] = ()) -> List[Block]:
    run, options = result.get("run") or {}, result.get("options") or {}
    task, model = run.get("task") or {}, run.get("model") or {}
    tool = result.get("tool") or {}
    synthetic = run.get("source") == "synthetic"
    blocks: List[Block] = [("title", f"DriftAudit {tool.get('version', '')}".strip() + f": audit of {run.get('id')}")]
    source: Cell = ("synthetic: simulated model, not a measurement", "warn") if synthetic else "measured"
    blocks.append(("cells", ["source: ", source]))
    subject = ", ".join(str(x) for x in (task.get("name"), model.get("id")) if x)
    seed = f", seed {run.get('seed')}" if run.get("seed") is not None else ""
    blocks.append(("line", f"{subject}{seed}: {_plural(run.get('n_items') or 0, 'item')}, "
                           f"{_plural(run.get('n_rounds') or 0, 'round')}, "
                           f"{_plural(run.get('n_candidates') or 0, 'candidate')}"))
    for note in _what_if(options):
        blocks.append(("line", f"what-if: {note}"))

    blocks.append(("heading", "Environments"))
    rows: List[List[Cell]] = []
    for env in result.get("environments") or []:
        rows.append([str(env.get("id")), str(env.get("name") or ""), _round_span(env.get("rounds") or []),
                     str(env.get("decoding")), str(env.get("scorer"))])
    blocks.append(("table", ["id", "name", "in force", "decoding", "scorer"], rows, "lllll"))
    blocks.append(("line", ""))
    blocks.append(("line", "Fingerprints, the settings a refresh policy can compare:"))
    blocks.append(("literals", [(str(env.get("id")), str(env.get("fingerprint")))
                                for env in result.get("environments") or []]))

    policies = result.get("policies") or {}
    # Asking for as_run by name shows it in full; otherwise a trivial one is left out.
    hidden = [pid for pid in hide if pid != policy]
    trivial = policy != "as_run" and as_run_is_trivial(policies.get("as_run"))
    if trivial:
        hidden.append("as_run")
    blocks.append(("heading", "Policies"))
    rows = []
    for pid, p in policies.items():
        if not p.get("available", True) or pid in hidden:
            continue
        false_accepts = p.get("false_accepts") or 0
        rows.append([_policy_name(p, options), _count(p.get("accepted")),
                     (_count(false_accepts), "bad" if false_accepts else ""), _count(p.get("false_rejects")),
                     _pct(p.get("final_acc")), _count(p.get("refreshes")), _count(p.get("total_calls"))])
    blocks.append(("table", ["policy", "accepts", "false accepts", "false rejects", "final accuracy",
                             "reruns", "model calls"], rows, "lrrrrrr"))
    if trivial:
        blocks.append(("line", AS_RUN_NOTE))
    unavailable = [_missing(p, _policy_name(p, options)) for p in policies.values() if not p.get("available", True)]
    if unavailable:
        blocks.append(("line", "Not available on this run log:"))
        blocks.extend(("line", "  " + text) for text in unavailable)

    chosen = _default_policy(result, policy, hidden)
    if policy is not None and chosen is None:
        blocks.append(("line", f"Policy {policy!r} is not part of this audit."))
    elif chosen is not None:
        p = policies[chosen]
        name = _policy_name(p, options)
        if not p.get("available", True):
            blocks.append(("heading", name))
            blocks.append(("line", _missing(p, name)))
        else:
            decisions = p.get("decisions") or []
            rule = str(p.get("rule") or "").rstrip(".")
            blocks.append(("heading", f"{name}: {rule[:1].lower()}{rule[1:]}"))
            causes = p.get("causes") or {}
            by_cause = ", ".join(f"{causes[c]} {CAUSES[c]}" for c in CAUSES if causes.get(c))
            blocks.append(("line", f"{_plural(p.get('false_accepts') or 0, 'false accept')}"
                                   + (f" ({by_cause})" if by_cause else "")
                                   + f" and {_plural(p.get('false_rejects') or 0, 'false reject')} "
                                   f"in {_plural(len(decisions), 'decision')}."))
            blocks.append(("line", "Mean drift inflation "
                                   f"{_pp(None if p.get('inflation') is None else 100 * p['inflation'])} pp."))
            headers = ["round", "env", "reference", "stored", "rerun", "inflation", "change"]
            for kind, label, last in (("false_accept", "False accepts", "cause"), ("false_reject", "False rejects", "note")):
                rows = _decision_rows(decisions, kind)
                if rows:
                    blocks.append(("line", ""))
                    blocks.append(("line", f"{label}. stored and rerun: wins/losses against the stored and the "
                                           "rerun reference;"))
                    blocks.append(("line", "inflation: drift inflation in pp; change: candidate accuracy minus "
                                           "incumbent accuracy in pp."))
                    blocks.append(("table", headers + [last], rows, "rllrrrrl"))

    flips = [f for f in result.get("scorer_flips") or [] if f.get("items")]
    if flips:
        blocks.append(("heading", "Scorer changes"))
        for f in flips:
            blocks.append(("line", f"{f.get('from_env')} to {f.get('to_env')}: {_count(f.get('wrong_to_right'))} of "
                                   f"{_count(f.get('items'))} labels go from wrong to right and "
                                   f"{_count(f.get('right_to_wrong'))} from right to wrong on the same outputs"))
    completeness = result.get("completeness") or {}
    notes = list(completeness.get("notes") or [])
    if completeness.get("full_bank") is False:
        notes.insert(0, "The label bank is sparse: some prompts lack labels under some environments or passes.")
    if notes:
        blocks.append(("heading", "Notes"))
        blocks.extend(("line", str(note)) for note in notes)
    return blocks


def _mean_sd(stat: Optional[Mapping[str, Any]], scale: float = 1.0, digits: int = 1, unit: str = "") -> str:
    if not stat or stat.get("mean") is None:
        return "n/a"
    sd = stat.get("sd")
    spread = "" if sd is None else f" ± {scale * sd:,.{digits}f}"
    return f"{scale * stat['mean']:,.{digits}f}{spread}{unit}"


def _study_blocks(result: Mapping[str, Any], policy: Optional[str], trivial_as_run: bool,
                  hide: Sequence[str] = ()) -> List[Block]:
    tool, options = result.get("tool") or {}, result.get("options") or {}
    runs = result.get("runs") or []
    blocks: List[Block] = [("title", f"DriftAudit {tool.get('version', '')}".strip()
                            + f": study of {_plural(result.get('n_runs') or len(runs), 'run')}")]
    kind = result.get("source")
    synthetic = sum(r.get("source") == "synthetic" for r in runs)
    if kind == "synthetic":
        source: Cell = ("synthetic: every run is simulated, none of these numbers is a measurement", "warn")
    elif kind == "mixed":
        source = (f"mixed: {synthetic} of {_plural(len(runs), 'run')} simulated, the rest measured; "
                  "the pooled numbers are not a measurement", "warn")
    else:
        source = str(kind or "not recorded")
    blocks.append(("cells", ["source: ", source]))
    blocks.append(("line", f"{_plural(result.get('n_decisions') or 0, 'decision')} in total."))
    blocks.append(("line", "Counts are summed over the runs. Final accuracy is the mean ± sd over runs; "
                           "reruns and model"))
    blocks.append(("line", "calls are means per run."))
    for note in _what_if(options):
        blocks.append(("line", f"what-if: {note}"))

    policies = result.get("policies") or {}
    hidden = [pid for pid in hide if pid != policy]
    trivial = trivial_as_run and policy != "as_run" and "as_run" in policies
    if trivial:
        hidden.append("as_run")
    blocks.append(("heading", "Policies"))
    rows: List[List[Cell]] = []
    for pid, p in policies.items():
        if pid in hidden:
            continue
        false_accepts = p.get("false_accepts") or 0
        rows.append([_policy_name(dict(p, id=pid), options), _count(p.get("accepted")),
                     (_count(false_accepts), "bad" if false_accepts else ""), _count(p.get("false_rejects")),
                     _mean_sd(p.get("final_acc"), 100, 1, "%"), _count((p.get("refreshes") or {}).get("mean")),
                     _count((p.get("total_calls") or {}).get("mean"))])
    blocks.append(("table", ["policy", "accepts", "false accepts", "false rejects", "final accuracy",
                             "reruns", "model calls"], rows, "lrrrrrr"))
    if trivial:
        blocks.append(("line", AS_RUN_NOTE))

    chosen = _default_policy(result, policy, hidden)
    if chosen is not None:
        p = policies[chosen]
        name = _policy_name(dict(p, id=chosen), options)
        causes = p.get("causes") or {}
        by_cause = ", ".join(f"{causes[c]} {CAUSES[c]}" for c in CAUSES if causes.get(c))
        blocks.append(("heading", f"{name}, run by run"))
        if by_cause:
            blocks.append(("line", f"By cause: {by_cause}."))
        # The run id goes last, where its length cannot push the numbers out of line.
        rows = [["" if r.get("seed") is None else str(r.get("seed")), _count(r.get("accepted")),
                 (_count(r.get("false_accepts")), "bad" if r.get("false_accepts") else ""),
                 _count(r.get("false_rejects")), _pct(r.get("final_acc")), _count(r.get("total_calls")),
                 str(r.get("id"))] for r in p.get("per_run") or []]
        blocks.append(("table", ["seed", "accepts", "false accepts", "false rejects", "final accuracy",
                                 "model calls", "run"], rows, "rrrrrrl"))

    tests = [t for t in result.get("policy_tests") or [] if t.get("a") not in hidden and t.get("b") not in hidden]
    if tests:
        blocks.append(("heading", "Decision errors compared (Fisher exact test, decisions treated as independent)"))
        rows = []
        for t in tests:
            names = [_policy_name(dict(policies.get(t.get(side)) or {}, id=t.get(side)), options) for side in ("a", "b")]
            p_value = t.get("fisher_p")
            rows.append([names[0], _count(t.get("errors_a")), names[1], _count(t.get("errors_b")),
                         _count(t.get("n")), "n/a" if p_value is None else f"{p_value:.3f}"])
        blocks.append(("table", ["policy", "errors", "against", "errors", "decisions each", "p"], rows, "lrlrrr"))

    probe = result.get("probe") or {}
    if probe.get("by_env"):
        blocks.append(("heading", f"Drift inflation at reference age {probe.get('age')}, reference stored under "
                                  f"{probe.get('stored_env')} (pp)"))
        rows = []
        for env, cell in probe["by_env"].items():
            n = len(cell.get("per_run") or [])
            rows.append([str(env), _pp(cell.get("mean")), f"[{_pp(cell.get('lo'))}, {_pp(cell.get('hi'))}]",
                         f"{cell.get('n_positive')} of {n}"])
        blocks.append(("table", ["scored under", "mean", "95% interval", "runs above zero"], rows, "lrrr"))
    age = result.get("age") or {}
    for env, cells in (age.get("by_env") or {}).items():
        blocks.append(("heading", f"Drift inflation by reference age, scored under {env}, reference stored under "
                                  f"{age.get('stored_env')} (pp)"))
        rows = [[str(c.get("age")), _count(c.get("pairs")), _pp(c.get("mean")),
                 f"[{_pp(c.get('lo'))}, {_pp(c.get('hi'))}]", _count(c.get("promoted")), _count(c.get("false_accepts"))]
                for c in cells]
        blocks.append(("table", ["age", "pairs", "mean", "95% interval", "accepted", "false accepts"], rows, "rrrrrr"))
    flips = result.get("verdict_flips") or {}
    if flips.get("n"):
        blocks.append(("line", ""))
        blocks.append(("line", f"{_count(flips.get('flipped'))} of {_count(flips.get('n'))} decisions come out "
                               "differently against the rerun reference than against the stored one."))
    return blocks


def clean(text: str) -> str:
    """Text from a run log made safe to print: escape sequences removed, other control
    characters shown as \\xNN, so a run log cannot retitle, recolour or redraw the terminal."""
    text = _ESCAPES.sub("", text)
    return _CONTROLS.sub(lambda m: f"\\x{ord(m.group(0)):02x}", text)


def _clean_block(block: Block) -> Block:
    def cell(c: Any) -> Any:
        if isinstance(c, str):
            return clean(c)
        if isinstance(c, tuple):
            return (clean(c[0]),) + tuple(c[1:])
        return c

    kind = block[0]
    if kind in ("title", "heading", "line"):
        return (kind, clean(block[1]))
    if kind == "cells":
        return (kind, [cell(c) for c in block[1]])
    if kind == "literals":
        return (kind, [(clean(label), clean(value)) for label, value in block[1]])
    return (kind, [clean(h) for h in block[1]], [[cell(c) for c in row] for row in block[2]]) + tuple(block[3:])


def _text(cell: Cell) -> str:
    return cell if isinstance(cell, str) else cell[0]


def _to_text(blocks: Sequence[Block], color: bool) -> str:
    def paint(text: str, tone: str) -> str:
        return f"\x1b[{_TONES[tone]}m{text}\x1b[0m" if color and tone in _TONES else text

    lines: List[str] = []
    for block in map(_clean_block, blocks):
        kind = block[0]
        if kind == "title":
            lines.append(paint(block[1], "strong"))
        elif kind == "heading":
            lines += ["", paint(block[1], "strong")]
        elif kind == "line":
            # A sentence built from counts and causes can outgrow the terminal; wrap it there.
            text = block[1]
            indent = " " * (len(text) - len(text.lstrip(" ")))
            lines += textwrap.wrap(text, WIDTH, subsequent_indent=indent, break_long_words=False,
                                   break_on_hyphens=False) or [text]
        elif kind == "cells":
            lines.append("".join(paint(_text(c), "" if isinstance(c, str) else c[1]) for c in block[1]))
        elif kind == "literals":
            for label, value in block[1]:
                # Long fingerprints break after a ";" so that every line fits 100 columns.
                indent, line = "  " + label + "  ", ""
                for part in [p + ";" for p in value.split(";")[:-1]] + [value.split(";")[-1]]:
                    if line and len(indent) + len(line) + len(part) > WIDTH:
                        lines.append(indent + line)
                        indent, line = " " * len(indent), ""
                    line += part
                lines.append(indent + line)
        else:
            headers, rows, align = block[1], block[2], block[3]
            # The last column is not padded, so a long fingerprint or cause never forces
            # trailing spaces onto the other rows.
            widths = [max(len(h), *(len(_text(r[i])) for r in rows)) if rows else len(h) for i, h in enumerate(headers)]
            for cells in [headers] + list(rows):
                parts = []
                for i, cell in enumerate(cells):
                    text = _text(cell)
                    last = i == len(cells) - 1
                    padded = text.rjust(widths[i]) if align[i] == "r" else (text if last else text.ljust(widths[i]))
                    tone = cell[1] if not isinstance(cell, str) else ""
                    parts.append(padded.replace(text, paint(text, tone), 1) if tone else padded)
                lines.append(("  " + "  ".join(parts)).rstrip())
    return "\n".join(lines) + "\n"


def _to_markdown(blocks: Sequence[Block]) -> str:
    def escape(text: str) -> str:
        return text.replace("|", "\\|")

    lines: List[str] = []
    for block in map(_clean_block, blocks):
        kind = block[0]
        if kind == "title":
            lines += [f"# {block[1]}", ""]
        elif kind == "heading":
            lines += ["", f"## {block[1]}", ""]
        elif kind == "line":
            lines.append(block[1].strip() + ("  " if block[1].strip() else ""))
        elif kind == "cells":
            lines.append("".join(_text(c) for c in block[1]) + "  ")
        elif kind == "literals":
            lines += [""] + [f"- {label}: `{value}`" for label, value in block[1]]
        else:
            headers, rows, align = block[1], block[2], block[3]
            lines.append("| " + " | ".join(headers) + " |")
            lines.append("| " + " | ".join("---:" if a == "r" else "---" for a in align) + " |")
            for row in rows:
                lines.append("| " + " | ".join(escape(_text(c)) for c in row) + " |")
    return "\n".join(lines).rstrip() + "\n"


def render_audit(result: Mapping[str, Any], policy: Optional[str] = None, color: bool = False,
                 hide: Sequence[str] = ()) -> str:
    """One audit as aligned text. `policy` picks whose errors are listed (frozen when it can be replayed).

    Policies in `hide` are left out of the tables unless `policy` names them.
    """
    return _to_text(_audit_blocks(result, policy, hide), color)


def render_study(result: Mapping[str, Any], color: bool = False, policy: Optional[str] = None,
                 trivial_as_run: bool = False, hide: Sequence[str] = ()) -> str:
    """A study of several runs as aligned text, with one line per run for `policy`.

    A study does not keep the decisions, so the caller says whether the as_run policy was
    trivial in every run (engine.as_run_is_trivial on each audit); it is then left out.
    """
    return _to_text(_study_blocks(result, policy, trivial_as_run, hide), color)


def audit_markdown(result: Mapping[str, Any], policy: Optional[str] = None, hide: Sequence[str] = ()) -> str:
    return _to_markdown(_audit_blocks(result, policy, hide))


def study_markdown(result: Mapping[str, Any], policy: Optional[str] = None, trivial_as_run: bool = False,
                   hide: Sequence[str] = ()) -> str:
    return _to_markdown(_study_blocks(result, policy, trivial_as_run, hide))
