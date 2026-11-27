"""Command line entry point: `driftaudit <command>`.

Exit codes: 0 when the command did its job, 1 for anything that stopped it (a file that is
not a run log, a bad option, a server that did not answer) and 2 when `audit --fail-on` found
what it was asked to look for. Messages for the user go to stderr as `driftaudit: ...`, results
go to stdout.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

from . import __version__
from .errors import DriftAuditError, RunLogError

FAIL_EXIT = 2


class _Parser(argparse.ArgumentParser):
    # argparse would exit with 2, which this tool keeps for --fail-on.
    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(1, f"driftaudit: {message}\n")


def _say(message: str) -> None:
    from .render import clean
    print(clean(message), file=sys.stderr, flush=True)


def _out(line: str) -> None:
    """A line of output that quotes a run log: ids, environment names and problems."""
    from .render import clean
    print(clean(line))


def _color() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def _emit(text: str, output: Optional[str]) -> None:
    if output is None:
        sys.stdout.write(text)
        return
    from ._paths import write_atomic
    write_atomic(output, text.encode("utf-8"))
    _say(f"Wrote {output}")


def _port(text: str) -> int:
    port = int(text)
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError("a port is a number from 0 to 65535")
    return port


def _positive(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return value


def build_parser() -> argparse.ArgumentParser:
    from .backends import BACKENDS
    from .engine import POLICIES
    from .loop import DEFAULT_SCHEDULE
    from .server import DEFAULT_PORT

    parser = _Parser(prog="driftaudit", description="Audit stale references in self-improving LLM loops.")
    parser.add_argument("--version", action="version", version=f"driftaudit {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", required=True)

    def serving(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--port", type=_port, default=DEFAULT_PORT, help=f"port to listen on (default {DEFAULT_PORT}; "
                         "the next free one is used if it is taken)")
        sub.add_argument("--host", default="127.0.0.1", help="address to listen on (default 127.0.0.1, this machine only)")
        sub.add_argument("--no-open", action="store_true", help="do not open a browser")

    sub = commands.add_parser("demo", help="open the workbench on the bundled paper runs")
    serving(sub)
    sub.set_defaults(handler=_demo)

    sub = commands.add_parser("view", help="open the workbench on your run logs")
    sub.add_argument("runs", nargs="+", metavar="RUN", help="run log (v1 or a toolkit run file)")
    sub.add_argument("--title", help="name shown for this group of runs")
    serving(sub)
    sub.set_defaults(handler=_view)

    sub = commands.add_parser("audit", help="replay the reference policies on a run log and print the result",
                              description="One run prints its audit; several runs print a study of them.")
    sub.add_argument("runs", nargs="+", metavar="RUN")
    sub.add_argument("--policy", choices=list(POLICIES), help="policy whose errors are listed (default frozen)")
    sub.add_argument("--format", choices=["text", "md", "json"], default="text")
    sub.add_argument("-o", "--output", metavar="FILE", help="write the result to FILE instead of printing it")
    sub.add_argument("--schedule", metavar="SPEC", help="what-if: replace the environment schedule, e.g. 0:E1,4:E3")
    sub.add_argument("--stored-scoring", choices=["as_recorded", "rescore"], default="as_recorded",
                     help="rescore reads a stored reference's text with the current scorer")
    sub.add_argument("--margin", type=float, default=0.0, help="accept when wins - losses exceeds this (default 0)")
    sub.add_argument("--periodic-k", type=_positive, metavar="K",
                     help="list the periodic policy, which reruns a reference once it is K rounds old "
                          "(K is 3 when only --policy periodic is given)")
    sub.add_argument("--allow-mixed", action="store_true",
                     help="pool runs that differ in task, size, rounds, schedule or environments (with a warning)")
    sub.add_argument("--fail-on", choices=["stale-accept", "false-accept"],
                     help=f"exit with {FAIL_EXIT} if the policy made such a decision (the run's own decisions "
                          "when it recorded them, otherwise frozen, unless --policy is given)")
    sub.set_defaults(handler=_audit)

    sub = commands.add_parser("report", help="write a single-file HTML report")
    sub.add_argument("runs", nargs="+", metavar="RUN")
    sub.add_argument("-o", "--output", metavar="FILE", required=True)
    sub.add_argument("--title")
    sub.set_defaults(handler=_report)

    sub = commands.add_parser("run", help="run the built-in self-improvement loop and write a run log",
                              description="With no options this runs the bundled GSM8K sample against the mock "
                                          "backend, a simulator, and writes a synthetic run to try the tool on.")
    sub.add_argument("--task", default="gsm8k", metavar="gsm8k|FILE.jsonl",
                     help='bundled gsm8k, or JSON lines of {"question": ..., "answer": ...}')
    sub.add_argument("--dev-file", metavar="FILE.jsonl", help="take the development items from this file instead")
    sub.add_argument("--n-dev", type=_positive, default=200, help="development items (default 200)")
    sub.add_argument("--n-eval", type=_positive, default=200, help="evaluation items (default 200)")
    sub.add_argument("--backend", choices=list(BACKENDS), default="mock")
    sub.add_argument("--model", metavar="ID", help="model id (hf default: Qwen/Qwen2.5-1.5B-Instruct; required for openai)")
    sub.add_argument("--base-url", metavar="URL", help="OpenAI-compatible endpoint (default https://api.openai.com/v1)")
    sub.add_argument("--concurrency", type=_positive, default=8, help="parallel requests for openai (default 8)")
    sub.add_argument("--allow-insecure-http", action="store_true",
                     help="let --base-url use plain http to a host other than this machine")
    sub.add_argument("--rounds", type=_positive, default=11)
    sub.add_argument("--seed", type=int, default=1)
    sub.add_argument("--schedule", metavar="SPEC",
                     help=f"ROUND:DECODING/SCORER,... (default {DEFAULT_SCHEDULE} at 11 rounds, "
                          "with the two changes moved in proportion for other --rounds)")
    sub.add_argument("--max-new-tokens", type=_positive, default=640)
    sub.add_argument("--batch-size", type=_positive, default=64)
    sub.add_argument("--cache", metavar="FILE", help="generation cache; a second run with the same file resumes "
                     "(default for hf and openai: next to the run log)")
    sub.add_argument("--initial-prompt", metavar="TEXT", help="instruction the loop starts from")
    sub.add_argument("-o", "--output", metavar="RUN.json", default="driftaudit-run.json")
    sub.set_defaults(handler=_run)

    sub = commands.add_parser("convert", help="write a toolkit run file as a v1 run log")
    sub.add_argument("legacy", metavar="LEGACY.json")
    sub.add_argument("-o", "--output", metavar="RUN.json", required=True)
    sub.add_argument("--slim", action="store_true", help="leave out the batch layout (meta.config.passes)")
    sub.set_defaults(handler=_convert)

    sub = commands.add_parser("validate", help="check run logs against the v1 format and say what an audit can use")
    sub.add_argument("runs", nargs="+", metavar="RUN")
    sub.set_defaults(handler=_validate)

    sub = commands.add_parser("rescore", help="grade the saved outputs of a run again and compare with its labels")
    sub.add_argument("run", metavar="RUN")
    sub.add_argument("--scorer", required=True, metavar="ID", help="strict, lenient, exact or exact-normalized")
    sub.add_argument("--env", metavar="ENV", help="only this environment (default: all)")
    sub.add_argument("--outputs", metavar="FILE", help="outputs file (default: the one next to RUN)")
    sub.set_defaults(handler=_rescore)
    return parser


def _demo(args: argparse.Namespace) -> int:
    from .server import serve
    serve(None, host=args.host, port=args.port, open_browser=not args.no_open, announce=_say)
    return 0


def _view(args: argparse.Namespace) -> int:
    from .server import serve
    serve(args.runs, host=args.host, port=args.port, open_browser=not args.no_open, title=args.title, announce=_say)
    return 0


def _audit_schedule(spec: str) -> Dict[int, str]:
    schedule: Dict[int, str] = {}
    for part in spec.split(","):
        start, sep, env = part.strip().partition(":")
        if not sep or not start.strip().isdigit() or not env.strip():
            raise DriftAuditError(f"Cannot read the schedule entry {part.strip()!r}. Write ROUND:ENV, for example "
                                  "0:E1,4:E3, with environment ids from the run log.")
        schedule[int(start)] = env.strip()
    return schedule


def _audit(args: argparse.Namespace) -> int:
    from . import engine, render, schema

    # The periodic policy is a tuning knob, not one of the paper's policies: it is listed only
    # when asked for.
    hide = [] if args.periodic_k is not None else ["periodic"]
    options: Dict[str, Any] = {"stored_scoring": args.stored_scoring, "periodic_k": args.periodic_k or 3,
                               "margin": int(args.margin) if args.margin.is_integer() else args.margin}
    if args.schedule:
        options["schedule"] = _audit_schedule(args.schedule)
    runs = [schema.load(path) for path in args.runs]
    if len(runs) > 1:
        problems = engine.compatibility(runs, names=args.runs)
        if problems and not args.allow_mixed:
            raise DriftAuditError("These runs cannot be pooled in one study: " + "; ".join(problems)
                                  + ". Audit them one at a time, or pass --allow-mixed to pool them anyway.")
        if problems:
            _say(f"driftaudit: warning: pooling runs that differ: {'; '.join(problems)}")
    audits = [engine.audit(run, **options) for run in runs]

    policy = args.policy
    trivial = all(engine.as_run_is_trivial(a["policies"].get("as_run")) for a in audits)
    if policy is None and args.fail_on:
        # A gate in CI asks about what the loop itself decided, when the run log says so and
        # the loop compared with real references. A loop that compared each candidate with
        # its own incumbent in the same pass cannot fail the check, so frozen is asked instead.
        recorded = all(a["policies"]["as_run"]["available"] and not engine.as_run_is_trivial(a["policies"]["as_run"])
                       for a in audits)
        policy = "as_run" if recorded else "frozen"

    result = audits[0] if len(runs) == 1 else engine.study(runs, **options)
    if args.format == "json":
        text = json.dumps(result, indent=2) + "\n"
    elif len(runs) == 1:
        text = render.audit_markdown(result, policy, hide=hide) if args.format == "md" else \
            render.render_audit(result, policy, color=_color() and args.output is None, hide=hide)
    else:
        text = render.study_markdown(result, policy, trivial_as_run=trivial, hide=hide) if args.format == "md" else \
            render.render_study(result, color=_color() and args.output is None, policy=policy,
                                trivial_as_run=trivial, hide=hide)
    _emit(text, args.output)

    if not args.fail_on:
        return 0
    found: List[str] = []
    for path, audit in zip(args.runs, audits):
        block = audit["policies"][policy]
        if not block["available"]:
            raise DriftAuditError(f"--fail-on cannot check {path}: the {block['name']} policy cannot be replayed "
                                  "on it. Choose another with --policy.")
        rounds = [str(d["round"]) for d in block["decisions"]
                  if d["false_accept"] and (args.fail_on == "false-accept" or d["cause"] == "stale")]
        if rounds:
            found.append(f"{path} round{'s' if len(rounds) > 1 else ''} {', '.join(rounds)}")
    if not found:
        return 0
    what = "a false accept on a stale reference" if args.fail_on == "stale-accept" else "a false accept"
    _say(f"driftaudit: {what} under the {audits[0]['policies'][policy]['name']} policy: {'; '.join(found)}")
    return FAIL_EXIT


def _report(args: argparse.Namespace) -> int:
    from .report import build_report
    out = build_report(args.runs, args.output, title=args.title)
    _say(f"Wrote {out} ({out.stat().st_size / 1024:,.0f} KB). It opens from disk; nothing else is needed.")
    return 0


def _sidecar_path(run_path: Path) -> Path:
    stem = run_path.name[:-5] if run_path.name.endswith(".json") else run_path.name
    return run_path.with_name(f"{stem}.outputs.jsonl.gz")


def _run(args: argparse.Namespace) -> int:
    from . import schema
    from .backends import make_backend
    from .loop import default_schedule, gold_kind, parse_schedule, run_loop, write_outputs
    from .tasks import load_task

    if args.backend == "mock" and (args.model or args.base_url):
        raise DriftAuditError("--model and --base-url go with a real backend. Add --backend openai or --backend hf, "
                              "or drop them to use the mock backend.")
    if args.backend == "openai" and not args.model:
        raise DriftAuditError("--backend openai needs --model, the name the endpoint knows the model by "
                              "(for example --model llama3.2 with --base-url http://localhost:11434/v1).")
    if args.backend == "hf" and args.base_url:
        raise DriftAuditError("--base-url only applies to --backend openai.")
    if args.backend != "openai" and args.allow_insecure_http:
        raise DriftAuditError("--allow-insecure-http only applies to --backend openai.")
    schedule = parse_schedule(default_schedule(args.rounds) if args.schedule is None else args.schedule)
    task = load_task(args.task, args.n_dev, args.n_eval, dev_file=args.dev_file, gold=gold_kind(schedule))

    out = Path(args.output)
    sidecar = _sidecar_path(out)
    cache = args.cache
    if args.backend == "mock":
        backend = make_backend("mock", items=task.dev + task.eval)
    else:
        if args.backend == "hf":
            backend = make_backend("hf", **({"model": args.model} if args.model else {}))
        else:
            options: Dict[str, Any] = {"model": args.model, "concurrency": args.concurrency,
                                       "allow_insecure_http": args.allow_insecure_http}
            if args.base_url:
                options["base_url"] = args.base_url
            backend = make_backend("openai", **options)
            if backend.key_variable:
                _say(f"Sending the key in {backend.key_variable} to {backend.key_host}.")
            else:
                _say(f"No API key is sent to {backend.key_host}.")
        if cache is None:
            cache = str(sidecar.with_name(sidecar.name.replace(".outputs.jsonl.gz", ".cache.jsonl")))
        _say(f"Generations are cached in {cache}; run the same command again to resume an interrupted run.")

    run, outputs = run_loop(task, backend, schedule=schedule, rounds=args.rounds, seed=args.seed,
                            max_new_tokens=args.max_new_tokens, batch_size=args.batch_size, cache_path=cache,
                            initial_prompt=args.initial_prompt, progress=_say)
    # The outputs go first, so the run log never points at a file that is not there yet.
    write_outputs(sidecar, outputs)
    run["outputs"] = {"layout": "sidecar", "file": sidecar.name}
    schema.save(run, out)

    kind = "synthetic run: the mock backend simulates a model, so none of its numbers are measurements" \
        if run["source"] == "synthetic" else "measured run"
    print(f"Wrote {out} and {sidecar.name} ({kind}).")
    print("Next:")
    print(f"  driftaudit audit {shlex.quote(str(out))}")
    print(f"  driftaudit view {shlex.quote(str(out))}")
    return 0


def _convert(args: argparse.Namespace) -> int:
    from . import schema
    from .report import without_passes
    run = schema.load(args.legacy)
    if args.slim:
        run = without_passes(run)
    schema.save(run, args.output)
    _say(f"Wrote {args.output} (run log v1, id {run['id']})")
    return 0


def _validate(args: argparse.Namespace) -> int:
    from . import engine, schema
    failed = 0
    for path in args.runs:
        try:
            run = schema.load(path)
        except RunLogError as exc:
            failed += 1
            problems = exc.problems or [str(exc)]
            _out(f"{path}: {len(problems)} problem{'s' if len(problems) != 1 else ''}")
            for problem in problems:
                _out(f"  - {problem}")
            continue
        audit = engine.audit(run)
        bank = "complete label bank" if audit["completeness"]["full_bank"] else "sparse label bank"
        _out(f"{path}: valid run log ({run['source']}, {audit['run']['n_rounds']} rounds, "
              f"{audit['run']['n_items']} items, {len(run['prompts'])} prompts, {bank})")
        for block in audit["policies"].values():
            if not block["available"]:
                count = block.get("missing_count") or len(block["missing"])
                reason = f"{count} label vector{'s' if count != 1 else ''} missing" if count else "no reference recorded for the candidates"
                _out(f"  - the {block['name']} policy cannot be replayed: {reason}")
        for note in audit["completeness"]["notes"]:
            _out(f"  - {note}")
    return 1 if failed else 0


def _gold_answers(run: Dict[str, Any], numeric: bool) -> List[Any]:
    """Gold answers of a run's evaluation items: stored by `driftaudit run`, or the bundled task's."""
    from .tasks import load_task
    n_items = run["task"]["n_items"]
    gold = (run.get("meta") or {}).get("gold")
    if isinstance(gold, list) and len(gold) == n_items:
        return gold
    if str(run["task"].get("items", "")).startswith("gsm8k/"):
        return [item["gold"] for item in load_task("gsm8k", 1, n_items, gold="number" if numeric else "text").eval]
    raise DriftAuditError("This run log does not carry the gold answers (meta.gold), so its outputs cannot be "
                          "graded again. Run logs written by `driftaudit run` do.")


def _rescore(args: argparse.Namespace) -> int:
    from . import schema
    from .loop import read_outputs
    from .scoring import get_scorer, score_outputs
    from .server import find_sidecar

    run = schema.load(args.run)
    scorer = get_scorer(args.scorer)
    sidecar = Path(args.outputs) if args.outputs else find_sidecar(Path(args.run), run)
    if sidecar is None:
        raise DriftAuditError(f"No outputs file next to {args.run} (expected {_sidecar_path(Path(args.run)).name}). "
                              "Pass it with --outputs.")
    if args.env and args.env not in run["environments"]:
        raise DriftAuditError(f"{args.run} has no environment {args.env!r}; it has {', '.join(run['environments'])}.")
    texts = read_outputs(sidecar)
    gold = _gold_answers(run, numeric=scorer.id in ("strict", "lenient"))

    _out(f"{args.run}: outputs from {sidecar.name} graded with the {scorer.id} scorer (version {scorer.version})")
    rows = [["env", "stored scorer", "labels", "match", "wrong to right", "right to wrong", "no outputs"]]
    for env_id in [args.env] if args.env else list(run["environments"]):
        env = run["environments"][env_id]
        same = up = down = absent = 0
        for prompt, per_env in run["labels"].items():
            for tag, stored in per_env.get(env_id, {}).items():
                saved = texts.get((prompt, env["decoding"], tag))
                if saved is None or len(saved) != len(stored):
                    absent += len(stored)
                    continue
                fresh = schema.encode_labels(score_outputs(saved, gold, scorer))
                same += sum(1 for a, b in zip(stored, fresh) if a == b)
                up += sum(1 for a, b in zip(stored, fresh) if a == "0" and b == "1")
                down += sum(1 for a, b in zip(stored, fresh) if a == "1" and b == "0")
        rows.append([env_id, env["scorer"], f"{same + up + down:,}", f"{same:,}", f"{up:,}", f"{down:,}", f"{absent:,}"])
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        _out("  " + "  ".join(cell.ljust(widths[i]) if i < 2 else cell.rjust(widths[i]) for i, cell in enumerate(row)).rstrip())
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as exc:   # argparse has printed --help, --version or a usage error
        return exc.code if isinstance(exc.code, int) else 1
    handler: Callable[[argparse.Namespace], int] = args.handler
    try:
        return handler(args)
    except DriftAuditError as exc:
        _say(f"driftaudit: {exc}")
    except BrokenPipeError:
        # The reader went away (driftaudit audit ... | head). Point stdout at nothing so that
        # Python does not complain again while shutting down.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    except OSError as exc:
        _say(f"driftaudit: {exc.strerror or exc}" + (f": {exc.filename}" if exc.filename else ""))
    except KeyboardInterrupt:
        _say("driftaudit: interrupted")
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
