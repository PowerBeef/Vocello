#!/usr/bin/env python3
"""Vocello QC v2: the audio QC harness command line.

    python3 scripts/qc.py models list|fetch|verify
    python3 scripts/qc.py runtimes setup|verify
    python3 scripts/qc.py label sample|serve|export
    python3 scripts/qc.py run | gate | queue | fit | eval

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
                        acoustic_only_languages=_csv(args.acoustic_only_languages or ""))
        except (ValueError, OSError) as error:
            print(f"qc label serve: {error}", file=sys.stderr)
            return EXIT_ERROR
        return EXIT_OK
    try:
        summary = label.export_summary(layout, args.batch)
    except (ValueError, OSError) as error:
        print(f"qc label export: {error}", file=sys.stderr)
        return EXIT_ERROR
    if args.output:
        store.write_json_atomic(args.output, summary)
    _print_json(summary)
    return EXIT_OK


# --- phase 2 ------------------------------------------------------------------------

def cmd_not_implemented(args: argparse.Namespace, layout: Layout) -> int:
    print(f"qc {args.command}: not implemented yet", file=sys.stderr)
    return EXIT_ERROR


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
    export = label_actions.add_parser("export", help="counts per class, severity and language, plus intra-rater kappa")
    export.add_argument("--batch", required=True)
    export.add_argument("--output", help="also write the summary JSON here")
    label.set_defaults(handler=cmd_label)

    run = commands.add_parser("run", help="run the models and detectors over a takes manifest")
    run.add_argument("--takes", required=True, help="takes manifest or qc-takes run directory")
    run.add_argument("--lane", required=True)
    run.add_argument("--models", help="comma-separated model ids (default every model the detectors read)")
    run.add_argument("--thresholds", help="thresholds file (default the newest config/qc/thresholds-v<N>.json)")
    run.set_defaults(handler=cmd_not_implemented)

    gate = commands.add_parser("gate", help="exit 0 pass, 3 warn, 1 fail, 2 error for a lane run")
    gate.add_argument("--lane", required=True)
    gate.add_argument("--run", help="run id (default the lane's newest)")
    gate.set_defaults(handler=cmd_not_implemented)

    queue = commands.add_parser("queue", help="write a listening queue the label tool opens as a batch")
    queue.add_argument("--top", type=int, default=40)
    queue.add_argument("--run", help="run id (default the newest)")
    queue.add_argument("--batch", help="batch name for the queue")
    queue.set_defaults(handler=cmd_not_implemented)

    fit = commands.add_parser("fit", help="fit detector thresholds from the train-split labels")
    fit.add_argument("--batches", nargs="+", help="label batches (default every batch)")
    fit.set_defaults(handler=cmd_not_implemented)

    evaluate = commands.add_parser("eval", help="score the held-out split once against committed thresholds")
    evaluate.add_argument("--thresholds", help="thresholds file (default the newest)")
    evaluate.add_argument("--batches", nargs="+")
    evaluate.set_defaults(handler=cmd_not_implemented)
    return parser


def main(argv: list[str] | None = None, *, layout: Layout | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args, layout or Layout())


if __name__ == "__main__":
    sys.exit(main())
