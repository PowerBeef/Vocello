#!/usr/bin/env python3
"""Fixed-seed PCM identity and paired speed for a runtime change (RF-44).

`capture` runs `vocello bench` at one seed in an isolated data directory and
records each take's PCM SHA-256 with its bench timings. `compare` says whether
two captures produced the same samples and how their speeds differ.

A capture is local diagnostic evidence: it is bound to this host, this MLX
build and these model artifacts, so two captures are comparable only when they
were made on the same Mac. Nothing here is benchmark-history evidence.

Run it with the repository's Python, after `scripts/build.sh cli-optimized`:

    "$(python3 scripts/select_python.py)" scripts/pcm_identity.py capture --label before
    "$(python3 scripts/select_python.py)" scripts/pcm_identity.py compare <before> <after>

`compare` exits 0 when every take's samples are identical, 1 when they are not
and 2 on an error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from telemetry_overhead import (  # noqa: E402
    DEBUG_ROOT,
    ROOT,
    load_bench_results,
    managed_output_path,
    pcm_digest,
)

SCHEMA_VERSION = 1
DEFAULT_SEED = 19_790_615  # the gate bench's seed
CLONE_VOICE = "A_warm_elderly_woman"
# Keys MLX reads by itself. They are passed straight to the child process and
# recorded in the manifest, because the app's knob registry cannot see them.
PASS_THROUGH_PREFIXES = ("MLX_", "QWENVOICE_", "QVOICE_")


def utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def git_value(*arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments], cwd=ROOT, text=True, capture_output=True, check=False
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def parse_overrides(values: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    for value in values:
        name, separator, setting = value.partition("=")
        if not separator or not name or not name.startswith(PASS_THROUGH_PREFIXES):
            raise ValueError(
                f"--set-env takes KEY=VALUE with a {', '.join(PASS_THROUGH_PREFIXES)} key: {value!r}"
            )
        overrides[name] = setting
    return overrides


def take_key(take: dict) -> str:
    """One stable name per take: the bench cell plus its repetition."""
    return f"{take['cell']}"


def prepare_data_dir(data_dir: Path, modes: list[str]) -> None:
    source_models = DEBUG_ROOT / "models"
    if not source_models.exists():
        raise RuntimeError("the debug model root is missing; run scripts/macos_test.sh models ensure")
    data_dir.mkdir(parents=True)
    (data_dir / "models").symlink_to(source_models.resolve(), target_is_directory=True)
    if "clone" in modes:
        voices = data_dir / "voices"
        voices.mkdir()
        for suffix in (".wav", ".txt"):
            source = DEBUG_ROOT / "voices" / f"{CLONE_VOICE}{suffix}"
            if source.is_file():
                (voices / source.name).symlink_to(source.resolve())
        if not (voices / f"{CLONE_VOICE}.wav").exists():
            raise RuntimeError("the clone fixture voice is missing; run scripts/macos_test.sh models ensure")


def capture(args: argparse.Namespace) -> Path:
    modes = [mode for mode in args.modes.split(",") if mode]
    overrides = parse_overrides(args.set_env)
    vocello = managed_output_path("QVOICE_BUILD_ROOT") / "vocello"
    if not vocello.exists():
        raise RuntimeError("build/vocello is missing; run scripts/build.sh cli-optimized")
    run_dir = (
        managed_output_path("QVOICE_ARTIFACTS_MACOS") / "pcm-identity" / f"{args.label}-{utc_stamp()}"
    )
    data_dir = run_dir / "data"
    prepare_data_dir(data_dir, modes)

    command = [
        str(vocello), "bench",
        "--modes", ",".join(modes), "--variants", "speed", "--lengths", args.lengths,
        "--warm", str(args.warm), "--seed", str(args.seed),
        "--telemetry", "off", "--data-dir", str(data_dir), "--no-summary",
        "--label", args.label,
    ]
    if "clone" in modes:
        # The fixture is a Voice Design reference the repository generated itself.
        command += ["--voice", CLONE_VOICE, "--confirm-consent"]
    environment = dict(os.environ)
    environment.update(overrides)
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, env=environment)
    (run_dir / "bench.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (run_dir / "bench.stderr.log").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode:
        raise RuntimeError(
            f"vocello bench exited {completed.returncode}; see {run_dir / 'bench.stderr.log'}"
        )

    results = load_bench_results(data_dir)
    output_dir = data_dir / "outputs" / "bench"
    takes = []
    for take in results["takes"]:
        output_path = output_dir / take["outputFileName"]
        takes.append({
            "key": take_key(take),
            "mode": take["mode"],
            "length": take["length"],
            "warmState": take["warmState"],
            "pcmSHA256": pcm_digest(output_path),
            "audioSeconds": float(take["audioSeconds"]),
            "wallSeconds": float(take["wallSeconds"]),
            "firstChunkMS": take.get("firstChunkMS"),
            "thermalState": (take.get("environment") or {}).get("thermalState"),
            "loadAverage1Minute": (take.get("environment") or {}).get("loadAverage1Minute"),
        })
    keys = [take["key"] for take in takes]
    if len(set(keys)) != len(keys):
        raise RuntimeError("bench produced two takes with the same cell key")

    manifest = {
        "schemaVersion": SCHEMA_VERSION,
        "label": args.label,
        "seed": args.seed,
        "modes": modes,
        "lengths": args.lengths.split(","),
        "warm": args.warm,
        "environmentOverrides": overrides,
        "source": {
            "commit": git_value("rev-parse", "HEAD"),
            "dirtyPaths": len([line for line in git_value("status", "--porcelain").splitlines() if line]),
        },
        "executableSHA256": file_sha256(vocello.resolve()),
        "takes": takes,
    }
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def load_manifest(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != SCHEMA_VERSION or not isinstance(manifest.get("takes"), list):
        raise RuntimeError(f"not a PCM identity manifest: {path}")
    return manifest


def identity_report(baseline: dict, candidate: dict) -> dict:
    """Compare two manifests take by take. Pure, so the tests can pin it."""
    if baseline["seed"] != candidate["seed"]:
        raise RuntimeError("the two captures used different seeds")
    reference = {take["key"]: take for take in baseline["takes"]}
    observed = {take["key"]: take for take in candidate["takes"]}
    missing = sorted(set(reference) - set(observed))
    extra = sorted(set(observed) - set(reference))
    differing = sorted(
        key for key in set(reference) & set(observed)
        if reference[key]["pcmSHA256"] != observed[key]["pcmSHA256"]
    )
    cells: dict[str, dict] = {}
    for key in sorted(set(reference) & set(observed)):
        before, after = reference[key], observed[key]
        if before["warmState"] != "warm":
            continue
        cell = cells.setdefault(
            f"{before['mode']}/{before['length']}", {"before": [], "after": [], "firstBefore": [], "firstAfter": []}
        )
        cell["before"].append(before["wallSeconds"] / before["audioSeconds"])
        cell["after"].append(after["wallSeconds"] / after["audioSeconds"])
        if isinstance(before.get("firstChunkMS"), (int, float)) and isinstance(after.get("firstChunkMS"), (int, float)):
            cell["firstBefore"].append(float(before["firstChunkMS"]))
            cell["firstAfter"].append(float(after["firstChunkMS"]))
    speed = {}
    for name, cell in cells.items():
        before, after = statistics.median(cell["before"]), statistics.median(cell["after"])
        entry = {
            "takes": len(cell["before"]),
            "medianRTFBefore": before,
            "medianRTFAfter": after,
            "rtfChangePercent": (after / before - 1.0) * 100.0,
        }
        if cell["firstBefore"]:
            entry["medianFirstChunkMSBefore"] = statistics.median(cell["firstBefore"])
            entry["medianFirstChunkMSAfter"] = statistics.median(cell["firstAfter"])
        speed[name] = entry
    return {
        "identical": not (missing or extra or differing),
        "comparedTakes": len(set(reference) & set(observed)),
        "differing": differing,
        "missing": missing,
        "extra": extra,
        "warmSpeed": speed,
    }


def compare(args: argparse.Namespace) -> int:
    baseline = load_manifest(Path(args.baseline))
    candidate = load_manifest(Path(args.candidate))
    report = identity_report(baseline, candidate)
    print(json.dumps(report, indent=2))
    return 0 if report["identical"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture_parser = commands.add_parser("capture", help="run one seeded bench and record its PCM digests")
    capture_parser.add_argument("--label", required=True)
    capture_parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    capture_parser.add_argument("--modes", default="custom,design,clone")
    capture_parser.add_argument("--lengths", default="short,medium")
    capture_parser.add_argument("--warm", type=int, default=2)
    capture_parser.add_argument(
        "--set-env", action="append", default=[], metavar="KEY=VALUE",
        help="pass one environment override to the bench and record it (repeatable)",
    )
    compare_parser = commands.add_parser("compare", help="compare two captures' samples and speed")
    compare_parser.add_argument("baseline")
    compare_parser.add_argument("candidate")
    args = parser.parse_args()
    try:
        if args.command == "capture":
            print(capture(args))
            return 0
        return compare(args)
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as error:
        print(f"pcm_identity: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
