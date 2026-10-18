#!/usr/bin/env python3
"""Run the contract gate's validators in parallel, with grouped output and local selection.

`scripts/check_project_inputs.sh` runs every validator through this module. They are
read-only checks: none writes a file another reads, and the git commands they run
only read. So they run on a bounded worker pool (one per core by default). Each one's
combined stdout and stderr is printed as one block, in the order of VALIDATORS, as
soon as it and every validator before it have finished. Any failure fails the gate,
after every validator has run.

`--local` (`scripts/dev.sh check` and `contracts`) skips a validator when no changed
path falls under its declared inputs. Each input list was derived by reading the
validator: its own script, the repository modules it imports, and every file or
directory it reads, globs or tests for existence. A validator whose result also
depends on every tracked file, git history or the date declares no inputs (`always`)
and always runs. Everything runs when there is no changed-path information (a clean
tree, a git failure) or when the gate itself changed. Without `--local` (CI, release,
`scripts/dev.sh ci`) nothing is skipped. When a validator starts reading a new path,
its entry here changes in the same commit.

Changed paths: `$QVOICE_CHANGED_PATHS` (one path per line) when the caller sets it;
otherwise the dirty tree (unstaged, staged and untracked, renames as both sides) plus
everything committed since `$QVOICE_CHANGED_SINCE` (set by `scripts/dev.sh check
--since REF`), the set `scripts/dev.sh check` plans for.
"""

from __future__ import annotations

import argparse
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import IO, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
CHANGED_PATHS_ENV = "QVOICE_CHANGED_PATHS"
CHANGED_SINCE_ENV = "QVOICE_CHANGED_SINCE"
PYTHON = "python3"  # a command's leading python3 runs on this interpreter (sys.executable)

# The gate's own machinery: a change here runs every validator.
GATE_INPUTS = (
    "scripts/check_project_inputs.sh",
    "scripts/lib/contract_gate.py",
    "scripts/lib/python-bin/",
    "scripts/select_python.py",
)


@dataclass(frozen=True)
class Validator:
    command: tuple[str, ...]
    # Path prefixes (ending in "/") and exact paths the validator reads; None means `always`.
    inputs: tuple[str, ...] | None = None
    # Why a validator without inputs always runs.
    always: str = ""
    # Started first so the slowest validators do not finish last; output order is unchanged.
    heavy: bool = False

    @property
    def name(self) -> str:
        parts = self.command[1:] if self.command[0] == PYTHON else self.command
        return " ".join(part for part in parts if part != "{root}" and part != "--root")


def _always(*command: str, reason: str, heavy: bool = False) -> Validator:
    return Validator(tuple(command), None, reason, heavy)


def _reads(*command: str, inputs: Sequence[str], heavy: bool = False) -> Validator:
    return Validator(tuple(command), tuple(inputs), "", heavy)


JSONIO = ("scripts/lib/jsonio.py",)
LANGUAGE = ("scripts/lib/language_metrics.py", "config/language-normalization/")
SWIFT_LOCK = "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"
SPEAKER_CONTRACT = "Sources/Resources/qwenvoice_contract.json"
# benchmark_history.py and everything it imports or loads, plus the records it checks.
BENCHMARK_HISTORY = (
    "scripts/benchmark_history.py", "scripts/benchmark_memory.py", "scripts/build_output_policy.py",
    "scripts/lib/bench_seed.py", "scripts/lib/build_artifact_retention.py", "scripts/lib/build_provenance.py",
    "scripts/lib/lineage_identity.py", "scripts/lib/profile_trace_retention.py", "scripts/lib/rtf.py",
    "scripts/lib/trace_cpu.py", "scripts/lib/trace_intervals.py", *JSONIO, *LANGUAGE,
    "config/build-output-policy.json", "config/memory-qualification-policy.json",
    "config/ios-memory-budget-policy.json", SPEAKER_CONTRACT, "benchmarks/",
)
ATTRIBUTION = (
    "scripts/attribution_manifest.py", *JSONIO, "config/third-party-attribution-policy.json",
    "config/licenses/", "config/notices/", "config/language-normalization/", "LICENSE", "project.yml",
    "Packages/VocelloQwen3Core/LICENSE", "Packages/VocelloQwen3Core/NOTICES.md",
    "Packages/VocelloQwen3Core/ORIGINS.md", "Packages/VocelloQwen3Core/Package.resolved", SWIFT_LOCK,
    "Sources/Resources/qwenvoice_production_model_catalog.json",
    "Sources/Resources/third_party_attributions.json",
)
MODEL_CATALOG = (
    "scripts/model_catalog_contract.py", *JSONIO, SPEAKER_CONTRACT,
    "Sources/Resources/qwenvoice_ios_model_catalog.json",
    "Sources/Resources/qwenvoice_production_model_catalog.json",
    "config/model-catalog-schema-v2.json", "config/model-artifact-receipts.json",
)
ROADMAP_RENDER = ("scripts/roadmap.py", "config/roadmap.json", "config/roadmap-archive.json", "docs/ROADMAP.md")

VALIDATORS: tuple[Validator, ...] = (
    # Build-output ownership first in the output: it is the paths authority the others load.
    _always(PYTHON, "scripts/build_output_policy.py", "validate",
            reason="scans every tracked file for build-output references"),

    # Generated project surfaces and product identity.
    _reads(PYTHON, "scripts/generate_cli_scheme.py", "--check", inputs=(
        "scripts/generate_cli_scheme.py", "QwenVoice.xcodeproj/", "config/xcode-schemes/")),
    _reads(PYTHON, "scripts/generate_ios_logic_scheme.py", "--check", inputs=(
        "scripts/generate_ios_logic_scheme.py", "QwenVoice.xcodeproj/", "config/xcode-schemes/")),
    # The in-app copy of the Chinese fold table the language verdicts score with (AQ-02).
    _reads(PYTHON, "scripts/generate_hant_hans_fold_swift.py", "--check", inputs=(
        "scripts/generate_hant_hans_fold_swift.py", *LANGUAGE,
        "Sources/SharedSupport/Services/HantHansFoldTable.swift")),
    _reads(PYTHON, "scripts/cli_version_contract.py", "validate", inputs=(
        "scripts/cli_version_contract.py", "project.yml", "Sources/VocelloCLI/")),
    _reads(PYTHON, "scripts/localization_contract.py", "validate", inputs=(
        "scripts/localization_contract.py", "project.yml", "Sources/", "Tests/VocelloiOSUITests/",
        "Tests/VocelloMacUITests/", "config/localization-unlocalized-baseline.json")),
    _reads(PYTHON, "scripts/saved_voice_lifecycle_contract.py", "validate", inputs=(
        "scripts/saved_voice_lifecycle_contract.py", "scripts/ui_test.sh", "Sources/",
        "Tests/VocelloiOSUITests/")),
    _reads(PYTHON, "scripts/entitlement_contract.py", "validate", inputs=(
        "scripts/entitlement_contract.py", "scripts/release.sh", "scripts/verify_release_bundle.sh",
        "config/macos-entitlement-policy.json", "project.yml", SWIFT_LOCK,
        # The policy's scannedSourceRoots.
        "Sources/", "Packages/VocelloQwen3Core/Sources/")),
    _reads(PYTHON, "scripts/support_contact_contract.py", "validate", inputs=(
        "scripts/support_contact_contract.py", "config/support-contact.json", "website/public/",
        "website/src/", "Sources/iOS/")),
    _reads(PYTHON, "scripts/public_facts_contract.py", "validate", inputs=(
        "scripts/public_facts_contract.py", *JSONIO, "config/public-product-facts.json", "project.yml",
        "README.md", "benchmarks/hardware-profiles.json", "website/PRODUCT.md", "website/index.html",
        "website/public/", "website/src/",
        # README product imagery must exist.
        "docs/screenshots/", "docs/readme/", "docs/readme_banner_vocello.png")),
    _reads(PYTHON, "scripts/attribution_manifest.py", "rebuild", "--check", inputs=ATTRIBUTION),
    _reads(PYTHON, "scripts/attribution_manifest.py", "validate", inputs=ATTRIBUTION),

    # Runtime, concurrency and backend contracts.
    _always(PYTHON, "scripts/runtime_security_contract.py",
            reason="concurrency-safety reviews go stale with the date"),
    _reads(PYTHON, "scripts/qwen3_core_contract.py", "validate", heavy=True, inputs=(
        "scripts/qwen3_core_contract.py", *JSONIO, "Packages/VocelloQwen3Core/", "Sources/", "project.yml",
        "QwenVoice.xcodeproj/project.pbxproj", ".github/dependabot.yml", ".github/CODEOWNERS",
        "benchmarks/runs/", "config/backend-risk-spine.json")),
    _reads("scripts/check_backend_resource_contract.sh", "--project", inputs=(
        "scripts/check_backend_resource_contract.sh", "project.yml", "QwenVoice.xcodeproj/project.pbxproj")),
    _reads("scripts/check_qwen3_backend_only.sh", inputs=(
        "scripts/check_qwen3_backend_only.sh", "Packages/VocelloQwen3Core/Sources/", "Sources/", "Tests/",
        "project.yml")),
    _reads(PYTHON, "scripts/validate_backend_risk_spine.py", "--root", "{root}", inputs=(
        "scripts/validate_backend_risk_spine.py", "scripts/macos_test.sh", "config/backend-risk-spine.json",
        "Tests/VocelloCoreTests/", "Packages/VocelloQwen3Core/",
        # Item sources and the evidence report directory must resolve.
        "Sources/", "docs/audits/")),

    # Model delivery and App Store readiness.
    _reads(PYTHON, "scripts/model_catalog_contract.py", "rebuild", "--check", inputs=MODEL_CATALOG),
    _reads(PYTHON, "scripts/model_catalog_contract.py", "validate", inputs=MODEL_CATALOG),
    _reads(PYTHON, "scripts/model_host_availability.py", "validate", inputs=(
        "scripts/model_host_availability.py", "config/model-host-availability-policy.json",
        # The policy's catalog.
        "Sources/Resources/qwenvoice_ios_model_catalog.json")),
    _reads(PYTHON, "scripts/ios_storage_protection_policy.py", "validate", inputs=(
        "scripts/ios_storage_protection_policy.py", "config/ios-storage-protection-policy.json",
        "project.yml", "Sources/iOS/", "Sources/iOSSupport/")),
    _reads(PYTHON, "scripts/ios_device_eligibility.py", "validate", inputs=(
        "scripts/ios_device_eligibility.py", "scripts/verify_ios_release_artifacts.py", "project.yml",
        "Sources/iOS/", "Sources/iOSSupport/")),
    _reads(PYTHON, "scripts/ios_release_analyzer_warnings.py", "validate", inputs=(
        "scripts/ios_release_analyzer_warnings.py", "config/ios-release-analyzer-warning-policy.json",
        # Each warning's source must resolve.
        "Sources/", "Packages/")),

    # Release evidence, supply chain and benchmark history.
    _reads(PYTHON, "scripts/supply_chain_contract.py", inputs=(
        "scripts/supply_chain_contract.py", "config/toolchain.json", ".github/workflows/",
        ".github/dependabot.yml", "website/package.json")),
    _reads(PYTHON, "scripts/required_step_ledger.py", "validate-contract", inputs=(
        "scripts/required_step_ledger.py", *JSONIO, "config/orchestration-contract.json",
        # The contract's workflow producers must exist.
        ".github/workflows/release.yml", "scripts/ios_device.sh", "scripts/macos_test.sh",
        "scripts/ui_test.sh")),
    _reads(PYTHON, "scripts/quality_promotion.py", "validate-contract", inputs=(
        "scripts/quality_promotion.py", *BENCHMARK_HISTORY, "config/quality-promotion-contract.json",
        # Routing coverage lists the tracked files under these roots.
        "Sources/", "Packages/VocelloQwen3Core/Sources/", "project.yml")),
    _reads(PYTHON, "scripts/benchmark_history.py", "validate", "--all", heavy=True, inputs=BENCHMARK_HISTORY),
    _reads(PYTHON, "scripts/benchmark_history.py", "rebuild-index", "--check", heavy=True,
           inputs=BENCHMARK_HISTORY),
    _reads(PYTHON, "scripts/generate_readme_charts.py", "--check", inputs=(
        "scripts/generate_readme_charts.py", "scripts/lib/rtf.py", "README.md", "benchmarks/",
        "docs/charts/")),

    # Delivery copy and the audio QC take inputs (text-level; audio never gates ordinary CI).
    _reads(PYTHON, "scripts/check_delivery_instructions.py", inputs=(
        "scripts/check_delivery_instructions.py", "scripts/prosody_profile.py",
        "config/delivery-instruction-contract.json", "Sources/QwenVoiceCore/EmotionPreset.swift",
        "Sources/QwenVoiceCore/GenerationSemantics.swift", SPEAKER_CONTRACT)),
    _reads(PYTHON, "scripts/audio_qc_script_pool.py", "validate", inputs=(
        "scripts/audio_qc_script_pool.py", *JSONIO, *LANGUAGE, "config/audio-qc-script-pool.json",
        "config/audio-qc-script-pool-sources.json", "config/language-bench-corpus.json")),
    _reads(PYTHON, "scripts/audio_qc_calibration_takes.py", "validate-policy", inputs=(
        "scripts/audio_qc_calibration_takes.py", *JSONIO, *LANGUAGE, "scripts/qc/__init__.py",
        "scripts/qc/corpora.py", "config/audio-qc-calibration-takes.json", "config/audio-qc-corpora.json",
        "config/audio-qc-script-pool.json", SPEAKER_CONTRACT)),

    # Work authority: schema, blockers and a fresh render.
    _always(PYTHON, "scripts/roadmap.py", "validate",
            reason="reads git history (freeze subjects, evidence commits) and the date"),
    _reads(PYTHON, "scripts/roadmap.py", "render", "--check", inputs=ROADMAP_RENDER),

    # Exact product-invariant greps and the privacy scan.
    _always("scripts/repo_invariants.sh",
            reason="dated quarantine entries, ignored files under benchmarks/ and scripts/, most of the tree"),
    _always(PYTHON, "scripts/privacy_scan.py", reason="scans every tracked file", heavy=True),
)


@dataclass(frozen=True)
class Result:
    returncode: int
    output: bytes
    seconds: float


def touches(path: str, inputs: Sequence[str]) -> bool:
    """A changed path touches an input it equals, lies under, or (as a directory) contains."""
    directory = path.rstrip("/") + "/"
    return any(
        path == entry or (entry.endswith("/") and path.startswith(entry)) or entry.startswith(directory)
        for entry in inputs
    )


def select(validators: Sequence[Validator], changed: Sequence[str] | None, *,
           local: bool) -> tuple[list[bool], str]:
    """Which validators run, and the one line that explains a local selection ("" otherwise)."""
    everything = [True] * len(validators)
    if not local:
        return everything, ""
    if not changed:
        return everything, "no changed-path information (clean tree or git unavailable): every validator runs"
    if any(touches(path, GATE_INPUTS) for path in changed):
        return everything, "the contract gate itself changed: every validator runs"
    runs = [validator.inputs is None or any(touches(path, validator.inputs) for path in changed)
            for validator in validators]
    skipped = runs.count(False)
    return runs, (f"skipped {skipped} of {len(validators)} validators: none of their inputs is among the "
                  f"{len(changed)} changed path(s); CI and the full gate run every one")


def _git_paths(root: Path, *args: str) -> list[str] | None:
    try:
        completed = subprocess.run(["git", "-C", os.fspath(root), *args], stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return [part.decode("utf-8", errors="surrogateescape") for part in completed.stdout.split(b"\0") if part]


def changed_paths(root: Path = ROOT, environ: Mapping[str, str] | None = None) -> list[str] | None:
    """The changed paths, or None when git cannot tell (then everything runs)."""
    environ = os.environ if environ is None else environ
    explicit = environ.get(CHANGED_PATHS_ENV)
    if explicit is not None:
        return sorted({line.strip().removeprefix("./") for line in explicit.splitlines() if line.strip()})
    queries = [("diff", "--name-only", "--no-renames", "-z"),
               ("diff", "--cached", "--name-only", "--no-renames", "-z"),
               ("ls-files", "--others", "--exclude-standard", "-z")]
    since = environ.get(CHANGED_SINCE_ENV)
    if since:
        queries.append(("diff", "--name-only", "--no-renames", "-z", f"{since}...HEAD"))
    paths: set[str] = set()
    for query in queries:
        listed = _git_paths(root, *query)
        if listed is None:
            return None
        paths.update(listed)
    return sorted(paths)


def _argv(validator: Validator, root: Path) -> list[str]:
    """The command with its script made absolute, as the shell gate always ran it."""
    argv = [os.fspath(root) if part == "{root}" else part for part in validator.command]
    script = 1 if argv[0] == PYTHON else 0
    if script:
        argv[0] = sys.executable
    if len(argv) > script and not argv[script].startswith("-") and not os.path.isabs(argv[script]):
        argv[script] = os.fspath(root / argv[script])
    return argv


def _execute(validator: Validator, root: Path, environment: dict[str, str]) -> Result:
    started = time.monotonic()
    try:
        completed = subprocess.run(_argv(validator, root), cwd=root, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    except OSError as error:
        return Result(127, f"error: cannot run {validator.name}: {error}\n".encode(), time.monotonic() - started)
    return Result(completed.returncode, completed.stdout, time.monotonic() - started)


def run(validators: Sequence[Validator], *, root: Path = ROOT, changed: Sequence[str] | None = None,
        local: bool = False, jobs: int | None = None, out: IO[bytes] | None = None) -> int:
    """Run the selected validators; print each one's output as one block in declaration order."""
    out = out if out is not None else sys.stdout.buffer
    selected, note = select(validators, changed, local=local)

    def say(line: str) -> None:
        out.write(f"==> {line}\n".encode())
        out.flush()

    if note:
        say(f"local contract selection: {note}")
    environment = {**os.environ, "PYTHONUNBUFFERED": "1"}  # keep each block's stdout/stderr order
    workers = max(1, jobs or os.cpu_count() or 4)
    order = sorted((index for index, chosen in enumerate(selected) if chosen),
                   key=lambda index: (not validators[index].heavy, index))
    started = time.monotonic()
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="contract")
    futures: dict[int, Future[Result]] = {}
    failures: list[str] = []
    results: list[tuple[Validator, Result]] = []
    try:
        for index in order:
            futures[index] = pool.submit(_execute, validators[index], root, environment)
        for index, validator in enumerate(validators):
            if index not in futures:
                continue
            result = futures[index].result()
            results.append((validator, result))
            out.write(result.output)
            if result.output and not result.output.endswith(b"\n"):
                out.write(b"\n")
            if result.returncode != 0:
                failures.append(validator.name)
                say(f"FAILED (exit {result.returncode}, {result.seconds:.1f}s): {validator.name}")
            out.flush()
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    elapsed = time.monotonic() - started
    slowest = max(results, key=lambda item: item[1].seconds, default=None)
    summary = (f"contract validators: {len(results)} ran, {len(validators) - len(results)} skipped, "
               f"{len(failures)} failed in {elapsed:.1f}s ({min(workers, max(1, len(results)))} parallel")
    if slowest is not None:
        summary += f"; slowest {slowest[0].name} {slowest[1].seconds:.1f}s"
    say(summary + ")")
    if failures:
        say("failed: " + "; ".join(failures))
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--local", action="store_true",
                        help="skip validators whose declared inputs the change does not touch (refused in CI)")
    parser.add_argument("--jobs", type=int, help="parallel validators (default: one per core)")
    args = parser.parse_args(argv)
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be at least 1")
    if args.local and (os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS")):
        print("error: local contract selection is prohibited in CI", file=sys.stderr)
        return 2
    changed = changed_paths(ROOT) if args.local else None
    return run(VALIDATORS, root=ROOT, changed=changed, local=args.local, jobs=args.jobs)


if __name__ == "__main__":
    raise SystemExit(main())
