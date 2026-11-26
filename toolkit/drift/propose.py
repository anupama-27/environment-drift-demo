"""Candidate generation: the model reads a few dev errors and rewrites the system prompt."""
import re

from . import config

PROPOSER_SYSTEM = ("You improve instructions for a small model that solves "
                   "grade-school math word problems.")


def proposer_messages(current_prompt, failures):
    lines = [f"Current instruction:\n{current_prompt}\n", "The model got these problems wrong:\n"]
    for i, f in enumerate(failures, 1):
        lines.append(f"Problem {i}: {f['question']}")
        lines.append(f"Model's answer: {f['output'][-600:]}")
        lines.append(f"Correct final answer: {f['gold']:g}\n")
    lines.append("Write an improved instruction that would help the model avoid these mistakes. "
                 "Keep it under 120 words. Return only the new instruction inside <prompt></prompt>.")
    return [{"role": "system", "content": PROPOSER_SYSTEM},
            {"role": "user", "content": "\n".join(lines)}]


def parse_candidate(text, current_prompt):
    """Returns (candidate_prompt, note). Falls back to the current prompt if parsing fails."""
    m = re.search(r"<prompt>(.*?)</prompt>", text, flags=re.S)
    cand = m.group(1).strip() if m else ""
    if not cand and "<prompt>" in text:
        cand = text.split("<prompt>", 1)[1].strip()
    if not cand and len(text.strip()) < 1200:
        cand = text.strip()   # the model sometimes skips the tags
    cand = re.sub(r"^\s*(\*\*)?(new |improved )?(prompt|instruction)s?:?(\*\*)?\s*", "", cand, flags=re.I).strip()
    if len(cand) < 20:
        return current_prompt, "fallback_unparsed"
    note = "ok"
    if "boxed" not in cand:
        # Keep the answer format fixed so prompt edits don't change what the extractor sees.
        cand = cand + " " + config.FORMAT_LINE
        note = "format_line_added"
    return cand, note


def pick_failures(dev_items, dev_outputs, dev_correct, round_idx, k=config.N_FAILURES_SHOWN):
    wrong = [i for i, ok in enumerate(dev_correct) if not ok]
    if not wrong:
        return []
    start = (round_idx * k) % len(wrong)   # rotate so each round sees different errors
    chosen = (wrong[start:] + wrong[:start])[:k]
    return [{"question": dev_items[i]["question"], "output": dev_outputs[i],
             "gold": dev_items[i]["gold"]} for i in chosen]

