#!/usr/bin/env python3
"""Refresh fail-closed derived catalogs that CI validates for freshness.

This helper rebuilds machine-checked inventories and generated indexes. It does
**not** rewrite narrative progress prose (`docs/development-progress.md`, ADRs).
When `config/runtime-refactor-contract.json` or other meaning-bearing contracts
change, agents must still sync those docs in the same change.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class DerivedArtifact:
    artifact_id: str
    description: str
    check: tuple[str, ...]
    rebuild: tuple[str, ...]
    stale_markers: tuple[str, ...]


# Order matters: owned-runtime inventories feed project-health digests.
ARTIFACTS: tuple[DerivedArtifact, ...] = (
    DerivedArtifact(
        artifact_id="vendor-current-inventory",
        description="Packages/VocelloQwen3Core/CURRENT_INVENTORY.json",
        check=("python3", "scripts/vendor_runtime_contract.py", "validate"),
        rebuild=("python3", "scripts/vendor_runtime_contract.py", "rebuild-current-inventory"),
        stale_markers=("CURRENT_INVENTORY is stale",),
    ),
    DerivedArtifact(
        artifact_id="vendor-facade-api-baseline",
        description="Packages/VocelloQwen3Core/FACADE_API_BASELINE.json",
        check=("python3", "scripts/vendor_runtime_contract.py", "validate"),
        rebuild=("python3", "scripts/vendor_runtime_contract.py", "rebuild-facade-api-baseline"),
        stale_markers=("FACADE_API_BASELINE is stale",),
    ),
    DerivedArtifact(
        artifact_id="project-health-summary",
        description="docs/project-health.md",
        check=("python3", "scripts/project_health.py", "rebuild-summary", "--check"),
        rebuild=("python3", "scripts/project_health.py", "rebuild-summary"),
        stale_markers=("project-health summary is stale",),
    ),
    DerivedArtifact(
        artifact_id="documentation-index",
        description="docs/INDEX.md",
        check=("python3", "scripts/documentation_contract.py", "rebuild-index", "--check"),
        rebuild=("python3", "scripts/documentation_contract.py", "rebuild-index"),
        stale_markers=("documentation index is stale", "generated documentation index is stale"),
    ),
    DerivedArtifact(
        artifact_id="model-catalog",
        description="Sources/Resources/qwenvoice_production_model_catalog.json",
        check=("python3", "scripts/model_catalog_contract.py", "rebuild", "--check"),
        rebuild=("python3", "scripts/model_catalog_contract.py", "rebuild"),
        stale_markers=("is stale; run model_catalog_contract.py rebuild",),
    ),
    DerivedArtifact(
        artifact_id="readme-charts",
        description="docs/charts/*.svg (README performance charts)",
        check=("python3", "scripts/generate_readme_charts.py", "--check"),
        rebuild=("python3", "scripts/generate_readme_charts.py"),
        stale_markers=("README charts are stale",),
    ),
)


def run_command(command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def combined_output(result: subprocess.CompletedProcess[str]) -> str:
    return f"{result.stdout}\n{result.stderr}"


def is_stale(artifact: DerivedArtifact, result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return False
    text = combined_output(result)
    return any(marker in text for marker in artifact.stale_markers)


def check_status(root: Path) -> list[tuple[DerivedArtifact, str, str]]:
    """Return (artifact, state, detail) rows. state is ok|stale|error."""
    rows: list[tuple[DerivedArtifact, str, str]] = []
    # Share one vendor validate when both inventory artifacts need it.
    vendor_result: subprocess.CompletedProcess[str] | None = None
    for artifact in ARTIFACTS:
        if artifact.check[1:3] == ("scripts/vendor_runtime_contract.py", "validate"):
            if vendor_result is None:
                vendor_result = run_command(artifact.check, cwd=root)
            result = vendor_result
        else:
            result = run_command(artifact.check, cwd=root)
        if result.returncode == 0:
            rows.append((artifact, "ok", "fresh"))
            continue
        if is_stale(artifact, result):
            rows.append((artifact, "stale", "needs rebuild"))
            continue
        detail = combined_output(result).strip().splitlines()
        message = detail[-1] if detail else f"exit {result.returncode}"
        rows.append((artifact, "error", message[:160]))
    return rows


def refresh(
    root: Path,
    *,
    all_artifacts: bool,
    dry_run: bool,
    only: set[str] | None,
) -> int:
    rows = check_status(root)
    selected = []
    for artifact, state, _detail in rows:
        if only is not None and artifact.artifact_id not in only:
            continue
        if all_artifacts or state == "stale":
            selected.append(artifact)
        elif state == "error":
            print(f"error: {artifact.artifact_id}: {_detail}", file=sys.stderr)
            return 1

    if not selected:
        print("Derived artifacts: nothing to refresh")
        return 0

    # De-duplicate rebuilds while preserving order (facade/inventory share validate).
    seen: set[tuple[str, ...]] = set()
    for artifact in selected:
        if artifact.rebuild in seen:
            continue
        seen.add(artifact.rebuild)
        print(f"{'dry-run' if dry_run else 'refresh'}: {artifact.artifact_id} ({artifact.description})")
        if dry_run:
            continue
        result = run_command(artifact.rebuild, cwd=root)
        if result.returncode != 0:
            print(combined_output(result), file=sys.stderr)
            return 1
        if result.stdout.strip():
            print(result.stdout.rstrip())
    return 0


def print_status(root: Path) -> int:
    rows = check_status(root)
    width = max(len(artifact.artifact_id) for artifact, _, _ in rows)
    exit_code = 0
    for artifact, state, detail in rows:
        print(f"{artifact.artifact_id:<{width}}  {state:<5}  {detail}")
        if state != "ok":
            exit_code = 1
    return exit_code


def validate_all(root: Path) -> int:
    commands = (
        ("python3", "scripts/vendor_runtime_contract.py", "validate"),
        ("python3", "scripts/project_health.py", "rebuild-summary", "--check"),
        ("python3", "scripts/documentation_contract.py", "rebuild-index", "--check"),
        ("python3", "scripts/model_catalog_contract.py", "rebuild", "--check"),
    )
    for command in commands:
        result = run_command(command, cwd=root)
        if result.returncode != 0:
            print(combined_output(result), file=sys.stderr)
            return 1
        label = " ".join(command[1:])
        print(f"validate: {label}: PASS")
    print("Derived artifacts: PASS")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help=argparse.SUPPRESS,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="report freshness without rewriting files")

    refresh_parser = subparsers.add_parser(
        "refresh",
        help="rebuild stale derived artifacts (or all with --all)",
    )
    refresh_parser.add_argument(
        "--all",
        action="store_true",
        help="rebuild every governed artifact even when currently fresh",
    )
    refresh_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the refresh plan without writing",
    )
    refresh_parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="limit to one or more artifact ids (repeatable)",
    )

    subparsers.add_parser(
        "validate",
        help="fail closed if any governed derived artifact is stale or invalid",
    )

    args = parser.parse_args(argv)
    root = args.repo_root.resolve()
    if args.command == "status":
        return print_status(root)
    if args.command == "validate":
        return validate_all(root)
    only = set(args.only) if args.only else None
    if only:
        known = {artifact.artifact_id for artifact in ARTIFACTS}
        unknown = sorted(only - known)
        if unknown:
            print(f"error: unknown artifact id(s): {', '.join(unknown)}", file=sys.stderr)
            return 1
    code = refresh(root, all_artifacts=args.all, dry_run=args.dry_run, only=only)
    if code != 0 or args.dry_run:
        return code
    return validate_all(root)


if __name__ == "__main__":
    raise SystemExit(main())
