#!/usr/bin/env python3
"""Vocello QC v2: the audio QC harness command line.

    python3 scripts/qc.py models list|fetch|verify
    python3 scripts/qc.py runtimes setup|verify
    python3 scripts/qc.py label sample|serve|export
    python3 scripts/qc.py run | gate | queue | fit | eval | norms
    python3 scripts/qc.py language-bench takes|evidence

Exit codes: 0 success (gate: pass), 1 failure (gate: fail), 2 error or usage,
3 gate warn. See docs/reference/qc.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from qc import store  # noqa: E402
from qc.store import Layout  # noqa: E402

EXIT_OK, EXIT_FAIL, EXIT_ERROR, EXIT_WARN = 0, 1, 2, 3


def _print_json(value) -> None:
    print(json.dumps(value, indent=1, ensure_ascii=False, sort_keys=True))


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


# --- models -------------------------------------------------------------------

def cmd_models(args: argparse.Namespace, layout: Layout) -> int:
    from qc import models as registry

    entries = registry.load_registry(layout)
    if args.action == "list":
        rows = []
        for model in entries:
            statuses = {row["status"] for row in registry.verify_models(layout, [model])} if args.verify else set()
            rows.append({"id": model["id"], "kind": model["kind"], "runtime": model["runtime"],
                         "role": model.get("role", "primary"), "license": model["license"],
                         "memoryGB": model.get("memoryGB"), "bytes": registry.fetch_size([model]),
                         "fetched": (statuses == {"ok"}) if args.verify else
                         all(item.destination.is_file() for item in registry.model_files(layout, model))})
        if args.json:
            _print_json(rows)
        else:
            if not rows:
                print("no models registered (config/qc/models.json)")
            for row in rows:
                memory = f"{row['memoryGB']:>5} GB" if row["memoryGB"] else "     -  "
                print(f"{row['id']:<40} {row['kind']:<10} {row['runtime']:<9} {row['role']:<9} {memory} "
                      f"{row['bytes'] / 1024**3:7.2f} GB  {'fetched' if row['fetched'] else 'missing'}  {row['license']}")
        return EXIT_OK

    selected = _select_models(registry, entries, args)
    if selected is None:
        return EXIT_ERROR
    if args.action == "fetch":
        seeds = tuple(Path(path) for path in args.seed_dir or ())
        missing = [str(path) for path in seeds if not path.is_dir()]
        if missing:
            print(f"qc fetch: seed directory not found: {', '.join(missing)}", file=sys.stderr)
            return EXIT_ERROR
        try:
            summary = registry.Fetcher(layout=layout, seed_dirs=seeds).fetch(selected)
        except (registry.FetchError, OSError) as error:
            print(f"qc fetch: {error}", file=sys.stderr)
            return EXIT_FAIL
        print(f"qc fetch: done, {summary['downloaded']} files downloaded ({summary['bytes']} bytes), "
              f"{summary['seeded']} seeded locally")
        return EXIT_OK

    rows = registry.verify_models(layout, selected)
    problems = [row for row in rows if row["status"] != "ok"]
    for row in rows:
        if row["status"] != "ok" or args.verbose:
            print(f"{row['status']:<16} {row['model']}/{row['path']}")
    print(f"qc verify: {len(rows) - len(problems)}/{len(rows)} files verified")
    return EXIT_FAIL if problems else EXIT_OK


def _select_models(registry, entries, args):
    """--model ids, or for --all (fetch) the models of --role (default primary); verify defaults to all."""

    if getattr(args, "all", False) or not args.model:
        if args.action == "fetch" and not args.all:
            print("qc fetch: name --model ID (repeatable) or --all", file=sys.stderr)
            return None
        role = getattr(args, "role", "any")
        return [model for model in entries if role == "any" or model.get("role", "primary") == role]
    try:
        return [registry.find_model(entries, model_id) for model_id in args.model]
    except KeyError as error:
        print(f"qc: {error.args[0]}", file=sys.stderr)
        return None


# --- runtimes -------------------------------------------------------------------

def cmd_runtimes(args: argparse.Namespace, layout: Layout) -> int:
    from qc import runtime

    if args.action == "setup":
        try:
            receipt = runtime.setup_runtime(layout, args.runtime)
        except (runtime.RuntimeSetupError, OSError) as error:
            print(f"qc runtimes: {error}", file=sys.stderr)
            return EXIT_FAIL
        except Exception as error:  # a failed venv or pip step
            print(f"qc runtimes: setup failed: {error}", file=sys.stderr)
            return EXIT_FAIL
        _print_json(receipt)
        return EXIT_OK
    names = [args.runtime] if args.runtime else list(runtime.RUNTIMES)
    problems = []
    for name in names:
        try:
            found = runtime.verify_runtime(layout, name)
        except (runtime.RuntimeSetupError, OSError) as error:
            found = [f"{name}: {error}"]
        problems.extend(found)
        print(f"{'ok' if not found else 'problem':<8} {name}")
    for problem in problems:
        print(f"  {problem}")
    return EXIT_FAIL if problems else EXIT_OK


# --- label ------------------------------------------------------------------------

def cmd_label(args: argparse.Namespace, layout: Layout) -> int:
    from qc import label

    if args.action == "sample":
        try:
            summary = label.sample_command(
                layout, args.runs, name=args.batch, size=args.size, languages=_csv(args.languages),
                enrich_file=args.enrich_file, blind=args.blind, seed=args.seed, overwrite=args.overwrite)
        except (FileExistsError, ValueError, OSError) as error:
            print(f"qc label sample: {error}", file=sys.stderr)
            return EXIT_ERROR
        _print_json(summary)
        return EXIT_OK
    if args.action == "serve":
        try:
            label.serve(layout, args.batch, port=args.port,
                        acoustic_only_languages=_csv(args.acoustic_only_languages or ""), rater=args.rater)
        except (ValueError, OSError) as error:
            print(f"qc label serve: {error}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK
    try:
        summary = label.export_summary(layout, args.batch, args.rater)
    except (ValueError, OSError) as error:
        print(f"qc label export: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.output:
        store.write_json_atomic(args.output, summary)
    _print_json(summary)
    return EXIT_OK


# --- lanes and calibration ------------------------------------------------------------

def cmd_run(args: argparse.Namespace, layout: Layout) -> int:
    from qc import detectors, lanes, runtime

    try:
        roles = lanes.parse_roles(args.models, detectors.load_config(layout))
        directory = lanes.run(layout, args.takes, args.lane, roles=roles)
    except runtime.LockBusy as error:
        print(f"qc run: {error}", file=sys.stderr)
        return EXIT_ERROR
    except (ValueError, OSError) as error:
        print(f"qc run: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(directory.name)
    return EXIT_OK


def cmd_gate(args: argparse.Namespace, layout: Layout) -> int:
    from qc import lanes

    try:
        return lanes.gate(layout, args.lane, args.run)
    except (ValueError, OSError) as error:
        print(f"qc gate: {error}", file=sys.stderr)
        return EXIT_ERROR


def cmd_queue(args: argparse.Namespace, layout: Layout) -> int:
    from qc import lanes

    try:
        path = lanes.queue(layout, args.top, run_id=args.run, name=args.batch)
    except (ValueError, OSError) as error:
        print(f"qc queue: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(f"qc queue: wrote batch {path.stem}; open it with: python3 scripts/qc.py label serve --batch {path.stem}")
    return EXIT_OK


def cmd_language_bench(args: argparse.Namespace, layout: Layout) -> int:
    from qc import language

    if args.action == "takes":
        try:
            manifest = language.build_takes(
                platform=args.platform, run_id=args.run_id, plan=Path(args.plan), corpus=Path(args.corpus),
                diagnostics=Path(args.diagnostics), wav_dir=Path(args.wav_dir) if args.wav_dir else None)
        except (language.LanguageBenchError, ValueError, OSError) as error:
            print(f"qc language-bench takes: {error}", file=sys.stderr)
            return EXIT_FAIL
        store.write_json_atomic(args.output, manifest)
        controls = sum(1 for take in manifest["takes"] if take["control"])
        print(f"qc language-bench takes: {len(manifest['takes'])} takes ({controls} negative controls) "
              f"for lane {language.LANES[args.platform]}")
        return EXIT_OK
    try:
        evidence = language.build_evidence(layout, args.run)
    except (language.LanguageBenchError, ValueError, OSError) as error:
        print(f"qc language-bench evidence: {error}", file=sys.stderr)
        return EXIT_ERROR
    store.write_json_atomic(args.output, evidence)
    for line in language.summary_lines(evidence):
        print(line)
    return language.exit_code(evidence)


def cmd_fit(args: argparse.Namespace, layout: Layout) -> int:
    from qc import fit

    try:
        path = fit.fit(layout, batches=args.batches, runs=args.runs)
    except (fit.FitError, ValueError, OSError) as error:
        print(f"qc fit: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(f"qc fit: wrote {path.relative_to(layout.root)}; commit it before qc.py eval")
    return EXIT_OK


def cmd_eval(args: argparse.Namespace, layout: Layout) -> int:
    from qc import fit

    try:
        path = fit.evaluate(layout, thresholds=Path(args.thresholds) if args.thresholds else None,
                            batches=args.batches, runs=args.runs)
    except (fit.FitError, ValueError, OSError) as error:
        print(f"qc eval: {error}", file=sys.stderr)
        return EXIT_ERROR
    print(f"qc eval: wrote {path.relative_to(layout.root)}")
    return EXIT_OK


def cmd_norms(args: argparse.Namespace, layout: Layout) -> int:
    from qc import norms

    try:
        document, path = norms.command(layout, args.takes, min_count=args.min_count, dry_run=args.dry_run)
    except (ValueError, OSError) as error:
        print(f"qc norms: {error}", file=sys.stderr)
        return EXIT_ERROR
    for line in norms.summary_lines(document):
        print(line)
    if path is not None:
        print(f"qc norms: wrote {path.relative_to(layout.root)}; the provisional rules read the newest norms file")
    return EXIT_OK


# --- parser ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="qc.py", description="Vocello QC v2 audio QC harness.")
    commands = parser.add_subparsers(dest="command", required=True)

    models = commands.add_parser("models", help="the model registry: list, fetch, verify")
    models_actions = models.add_subparsers(dest="action", required=True)
    listing = models_actions.add_parser("list", help="registered models and whether they are fetched")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--verify", action="store_true", help="re-hash files to decide fetched")
    fetch = models_actions.add_parser("fetch", help="download pinned model files (https, sha256-verified)")
    fetch.add_argument("--model", action="append", help="model id (repeatable)")
    fetch.add_argument("--all", action="store_true", help="every registered model of --role")
    fetch.add_argument("--role", default="primary", choices=("primary", "fallback", "alternate", "any"),
                       help="with --all: which models (default primary)")
    fetch.add_argument("--seed-dir", action="append",
                       help="reuse local files with the pinned digest from this directory (repeatable)")
    verify = models_actions.add_parser("verify", help="re-hash fetched files; report missing ones")
    verify.add_argument("--model", action="append", help="model id (repeatable); default every model")
    verify.add_argument("--verbose", action="store_true")
    models.set_defaults(handler=cmd_models)

    runtimes = commands.add_parser("runtimes", help="pinned runner venvs and the llama.cpp release")
    runtime_actions = runtimes.add_subparsers(dest="action", required=True)
    setup = runtime_actions.add_parser("setup", help="build a runtime from its pinned requirements")
    setup.add_argument("--runtime", required=True, choices=("mlx", "onnx", "torch", "llamacpp"))
    check = runtime_actions.add_parser("verify", help="check runtimes against their pins")
    check.add_argument("--runtime", choices=("mlx", "onnx", "torch", "llamacpp"))
    runtimes.set_defaults(handler=cmd_runtimes)

    label = commands.add_parser("label", help="the maintainer's labels: sample, serve, export")
    label_actions = label.add_subparsers(dest="action", required=True)
    sample = label_actions.add_parser("sample", help="draw a stratified, enriched batch from qc-takes runs")
    sample.add_argument("--runs", nargs="+", required=True, help="qc-takes run directories or takes manifests")
    sample.add_argument("--batch", required=True, help="batch name")
    sample.add_argument("--size", type=int, default=96, help="takes before blind repeats (default 96)")
    sample.add_argument("--languages", default="french,english", help="comma-separated (default french,english)")
    sample.add_argument("--enrich-file", help="JSON of suspicious takes with reasons")
    sample.add_argument("--blind", type=float, default=0.1, help="blind-repeat fraction (default 0.1)")
    sample.add_argument("--seed", type=int, default=0)
    sample.add_argument("--overwrite", action="store_true", help="replace an existing batch of that name")
    serve = label_actions.add_parser("serve", help="serve the listening page on 127.0.0.1")
    serve.add_argument("--batch", required=True)
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--acoustic-only-languages", default="", help="e.g. zh,ja,ko,ru: hide the script and linguistic classes")
    serve.add_argument("--rater", help="who is labelling (default the protocol's rater); each rater keeps their own labels")
    export = label_actions.add_parser("export", help="counts per class, severity and language, plus intra-rater kappa")
    export.add_argument("--batch", required=True)
    export.add_argument("--rater", help="whose labels (default the protocol's rater)")
    export.add_argument("--output", help="also write the summary JSON here")
    label.set_defaults(handler=cmd_label)

    run = commands.add_parser("run", help="run the models and detectors over a takes manifest")
    run.add_argument("--takes", required=True, help="takes manifest or qc-takes run directory")
    run.add_argument("--lane", required=True,
                     help="lane name: one of the `lanes` of config/qc/detectors.json (language-bench, "
                          "ios-language-bench, qc-takes, clone-lane, voice-reliability), or any other "
                          "name, such as pool, for every role")
    run.add_argument("--models", help="comma-separated roles or model ids to run now (default the lane's "
                                      "models); the others are read from the cache")
    run.set_defaults(handler=cmd_run)

    bench = commands.add_parser("language-bench", help="the language lanes: takes manifest and recognitions")
    bench_actions = bench.add_subparsers(dest="action", required=True)
    takes = bench_actions.add_parser("takes", help="a lang-bench run's planned takes as a takes manifest")
    takes.add_argument("--platform", required=True, choices=("macos", "ios"))
    takes.add_argument("--run-id", required=True)
    takes.add_argument("--plan", required=True, help="the run's immutable language-run-plan.json")
    takes.add_argument("--corpus", required=True)
    takes.add_argument("--diagnostics", required=True,
                       help="macOS: the engine diagnostics root; iOS: the collected exact evidence tree")
    takes.add_argument("--wav-dir", help="macOS: the directory of <cell>.wav takes")
    takes.add_argument("--output", required=True)
    evidence = bench_actions.add_parser(
        "evidence", help="the two ASR families' recognitions of a QC run, with each take's verdict "
                         "(exit 0 every take met its outcome, 1 one did not, 2 a recognition is missing)")
    evidence.add_argument("--run", required=True, help="the QC run id `qc.py run` printed")
    evidence.add_argument("--output", required=True)
    bench.set_defaults(handler=cmd_language_bench)

    gate = commands.add_parser("gate", help="exit 0 pass, 3 warn, 1 fail, 2 error for a lane run")
    gate.add_argument("--lane", required=True)
    gate.add_argument("--run", help="run id (default the lane's newest)")
    gate.set_defaults(handler=cmd_gate)

    queue = commands.add_parser("queue", help="write a listening queue the label tool opens as a batch")
    queue.add_argument("--top", type=int, default=40)
    queue.add_argument("--run", help="run id (default the newest)")
    queue.add_argument("--batch", help="batch name for the queue (default queue-<run id>)")
    queue.set_defaults(handler=cmd_queue)

    fit = commands.add_parser("fit", help="fit detector thresholds from the train-split labels")
    fit.add_argument("--batches", nargs="+", help="label batches (default every batch)")
    fit.add_argument("--runs", nargs="+", help="run ids whose features to use (default every run)")
    fit.set_defaults(handler=cmd_fit)

    evaluate = commands.add_parser("eval", help="score the held-out split once against committed thresholds")
    evaluate.add_argument("--thresholds", help="thresholds file (default the newest)")
    evaluate.add_argument("--batches", nargs="+")
    evaluate.add_argument("--runs", nargs="+")
    evaluate.set_defaults(handler=cmd_eval)

    norms = commands.add_parser("norms", help="per-language pause, pace and ending percentiles of a takes pool")
    norms.add_argument("--takes", nargs="+", required=True, help="qc-takes run directories or takes manifests")
    norms.add_argument("--min-count", type=int, default=100,
                       help="values a language needs before it gets a feature's norms (default 100)")
    norms.add_argument("--dry-run", action="store_true", help="print the summary without writing config/qc/norms-v<N>.json")
    norms.set_defaults(handler=cmd_norms)
    return parser


def main(argv: list[str] | None = None, *, layout: Layout | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args, layout or Layout())


if __name__ == "__main__":
    sys.exit(main())
