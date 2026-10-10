"""Command line: ``omr-regress run``, ``compare`` and ``accept``."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from omr_regress.compare import compare_runs
from omr_regress.inputs import find_inputs, open_run, read_list
from omr_regress.report import summary_lines, write_html, write_json
from omr_regress.runner import run_set


def _run(args: argparse.Namespace) -> int:
    inputs = Path(args.inputs)
    ids = read_list(Path(args.list)) if args.list else find_inputs(inputs)
    if args.only:
        ids = [i for i in ids if any(s in i for s in args.only)]
    if not ids:
        print(f"no inputs found in {inputs}", file=sys.stderr)
        return 2
    results = run_set(
        Path(args.audiveris),
        inputs,
        ids,
        Path(args.out),
        label=args.label,
        options=args.options or [],
        jobs=args.jobs,
        timeout=args.timeout,
        force=args.force,
    )
    bad = [i for i, r in results.items() if r["status"] != "ok"]
    print(
        f"{len(results)} inputs run, {len(ids) - len(results)} already done, {len(bad)} without export"
    )
    return 0


def _compare(args: argparse.Namespace) -> int:
    run_a, run_b = open_run(Path(args.a)), open_run(Path(args.b))
    ids = None
    if args.only:
        ids = [
            i for i in sorted(set(run_a.ids()) & set(run_b.ids())) if any(s in i for s in args.only)
        ]
    comparison = compare_runs(
        run_a,
        run_b,
        ids,
        references=Path(args.references) if args.references else None,
        inputs=Path(args.inputs) if args.inputs else None,
    )
    print("\n".join(summary_lines(comparison)))
    if args.html:
        write_html(comparison, Path(args.html), limit=args.max_measures)
        print(f"report: {args.html}")
    if args.json:
        write_json(comparison, Path(args.json))
    failing = {
        "worse": ("worse", "failed", "mixed"),
        "change": ("worse", "failed", "mixed", "changed", "better", "recovered", "same"),
        "never": (),
    }[args.fail_on]
    return 1 if any(r.verdict in failing for r in comparison.results) else 0


def _accept(args: argparse.Namespace) -> int:
    run = open_run(Path(args.run))
    ids = args.ids or run.ids()
    references = Path(args.references)
    accepted = 0
    for input_id in ids:
        files = run.exports(input_id)
        if not files:
            print(f"{input_id}: no export, not accepted", file=sys.stderr)
            continue
        target = references / input_id
        if target.exists():
            if not args.replace:
                print(f"{input_id}: has a reference already (use --replace)", file=sys.stderr)
                continue
            shutil.rmtree(target)
        target.mkdir(parents=True)
        for f in files:
            shutil.copy2(f, target / f.name)
        accepted += 1
    print(f"{accepted} reference(s) written to {references}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="omr-regress",
        description="Run two builds of Audiveris on a test set and see what changed, "
        "measure by measure.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("run", help="transcribe every input of a test set with one build")
    p.add_argument("--audiveris", required=True, help="the Audiveris launcher (bin/Audiveris)")
    p.add_argument("--inputs", required=True, help="folder of input images and PDFs")
    p.add_argument("--out", required=True, help="folder of the run")
    p.add_argument("--label", help="name of the build in reports (default: the run's folder)")
    p.add_argument("--list", help="file listing the input ids to run, one per line")
    p.add_argument("--only", nargs="*", help="run only inputs whose id contains one of these")
    p.add_argument("--jobs", type=int, default=2, help="inputs transcribed at once (default 2)")
    p.add_argument("--timeout", type=float, default=900, help="seconds per input (default 900)")
    p.add_argument("--force", action="store_true", help="run inputs already done again")
    p.add_argument("options", nargs="*", help="more Audiveris options, after --")
    p.set_defaults(func=_run)

    p = sub.add_parser("compare", help="compare two runs, input by input and measure by measure")
    p.add_argument("a", help="the run before (the base build)")
    p.add_argument("b", help="the run after (the build under test)")
    p.add_argument("--references", help="folder of accepted references")
    p.add_argument("--inputs", help="the test set's folder, if not the one the runs record")
    p.add_argument("--only", nargs="*", help="compare only inputs whose id contains one of these")
    p.add_argument("--html", help="write an HTML report here")
    p.add_argument("--json", help="write the results as JSON here")
    p.add_argument("--max-measures", type=int, default=40, help="changed measures shown per input")
    p.add_argument(
        "--fail-on",
        choices=["worse", "change", "never"],
        default="worse",
        help="exit with 1 when an input got worse (default), changed at all, or never",
    )
    p.set_defaults(func=_compare)

    p = sub.add_parser("accept", help="keep a run's exports as the references of its inputs")
    p.add_argument("run", help="the run whose exports are correct")
    p.add_argument("ids", nargs="*", help="the inputs to accept (default: all)")
    p.add_argument("--references", required=True, help="folder of accepted references")
    p.add_argument("--replace", action="store_true", help="replace existing references")
    p.set_defaults(func=_accept)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
