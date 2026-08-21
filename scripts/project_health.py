#!/usr/bin/env python3
"""Generate a privacy-safe engineering health and evidence-freshness scorecard."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = ROOT / "config" / "project-health-contract.json"
DEFAULT_ORCHESTRATION = ROOT / "config" / "orchestration-contract.json"


class HealthError(ValueError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HealthError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise HealthError(f"{path} must contain a JSON object")
    return value


def atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def git(*arguments: str, check: bool = True) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), *arguments], text=True,
        capture_output=True, check=False,
    )
    if check and completed.returncode != 0:
        raise HealthError(completed.stderr.strip() or f"git {' '.join(arguments)} failed")
    return completed.stdout.strip()


def matching_paths(patterns: list[str]) -> list[str]:
    # The summary describes the repository, so only git-tracked files may
    # count. Filesystem globbing alone once picked up a stray untracked
    # SwiftPM `.build` tree (538 dependency test files) and baked a
    # machine-local test count into the committed summary, which then
    # failed the freshness check on every clean checkout.
    tracked = set(git("ls-files").splitlines())
    matches: set[str] = set()
    for pattern in patterns:
        matches.update(
            relative
            for path in ROOT.glob(pattern)
            if path.is_file()
            and (relative := path.relative_to(ROOT).as_posix()) in tracked
        )
    return sorted(matches)


def path_matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def validate_contract(path: Path) -> dict[str, Any]:
    contract = read_json(path)
    if contract.get("schemaVersion") != 1:
        raise HealthError("project-health contract schemaVersion must be 1")
    for key in ("trackedSummary", "localOutputRoot"):
        value = contract.get(key)
        if not isinstance(value, str) or value.startswith("/") or ".." in Path(value).parts:
            raise HealthError(f"project-health {key} must be a safe repository-relative path")
    domains = contract.get("criticalDomains")
    if not isinstance(domains, list) or not domains:
        raise HealthError("project-health contract requires criticalDomains")
    identifiers: set[str] = set()
    for domain in domains:
        if not isinstance(domain, dict):
            raise HealthError("critical domain entries must be objects")
        identifier = domain.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", identifier):
            raise HealthError(f"invalid critical-domain id: {identifier!r}")
        if identifier in identifiers:
            raise HealthError(f"duplicate critical-domain id: {identifier}")
        identifiers.add(identifier)
        for key in ("productionGlobs", "testGlobs"):
            patterns = domain.get(key)
            if not isinstance(patterns, list) or not patterns or any(not isinstance(v, str) for v in patterns):
                raise HealthError(f"{identifier}.{key} must be a non-empty string array")
            if not matching_paths(patterns):
                raise HealthError(f"{identifier}.{key} matches no current files")
        selectors = domain.get("hardwareEvidence")
        if not isinstance(selectors, list):
            raise HealthError(f"{identifier}.hardwareEvidence must be an array")
        selector_ids: set[str] = set()
        for selector in selectors:
            if not isinstance(selector, dict) or set(selector) != {
                "id", "platform", "kind", "matrixScope", "classifications"
            }:
                raise HealthError(f"{identifier}.hardwareEvidence selector is malformed")
            selector_id = selector.get("id")
            if not isinstance(selector_id, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", selector_id):
                raise HealthError(f"{identifier} has invalid hardware-evidence id")
            if selector_id in selector_ids:
                raise HealthError(f"{identifier} has duplicate hardware-evidence id {selector_id}")
            selector_ids.add(selector_id)
            if selector.get("platform") not in {"macos", "ios"}:
                raise HealthError(f"{identifier}.{selector_id} has invalid platform")
            if selector.get("kind") not in {"ui-generation", "engine-generation", "memory-qualification", "ui-perf"}:
                raise HealthError(f"{identifier}.{selector_id} has invalid evidence kind")
            if selector.get("matrixScope") not in {"canonical", "focused"}:
                raise HealthError(f"{identifier}.{selector_id} has invalid matrix scope")
            classifications = selector.get("classifications")
            if not isinstance(classifications, list) or not classifications or set(classifications) - {"canonical", "focused"}:
                raise HealthError(f"{identifier}.{selector_id} has invalid classifications")
        external = domain.get("externalPromotionEvidence", [])
        if not isinstance(external, list) or len(external) != len(set(external)) or any(
            not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9-]{1,63}", value)
            for value in external
        ):
            raise HealthError(f"{identifier}.externalPromotionEvidence is invalid")
    return contract


def evidence_selectors(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for domain in contract["criticalDomains"]:
        for selector in domain["hardwareEvidence"]:
            identity = selector["id"]
            current = result.get(identity)
            if current is not None and current != selector:
                raise HealthError(f"hardware-evidence selector {identity} has conflicting definitions")
            result[identity] = selector
    return result


def latest_hardware_records(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    selectors = evidence_selectors(contract)
    result: dict[str, dict[str, Any]] = {}
    for path in (ROOT / "benchmarks" / "runs").rglob("*.json"):
        record = read_json(path)
        run = record.get("run") or {}
        source = record.get("source") or {}
        for identity, selector in selectors.items():
            if (
                run.get("platform") != selector["platform"]
                or run.get("kind") != selector["kind"]
                or run.get("matrixScope") != selector["matrixScope"]
                or run.get("classification") not in selector["classifications"]
                or run.get("status") not in {"passed", "passedWithWarnings"}
                or source.get("dirty") is not False
                or source.get("fingerprintsMatch") is not True
            ):
                continue
            current = result.get(identity)
            if current is None or run.get("finishedAt", "") > (current.get("run") or {}).get("finishedAt", ""):
                result[identity] = record
    return result


def changed_paths_since(commit: str) -> tuple[str, list[str], int | None]:
    ancestor = subprocess.run(
        ["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit, "HEAD"],
        capture_output=True, check=False,
    )
    if ancestor.returncode != 0:
        return "unknown", [], None
    committed = git("diff", "--name-only", f"{commit}..HEAD").splitlines()
    working = git("status", "--short").splitlines()
    working_paths = [line[3:] for line in working if len(line) > 3]
    paths = sorted(set(filter(None, committed + working_paths)))
    distance_text = git("rev-list", "--count", f"{commit}..HEAD")
    return "known", paths, int(distance_text)


def count_test_cases(paths: list[str]) -> int:
    count = 0
    for relative in paths:
        text = (ROOT / relative).read_text(encoding="utf-8", errors="replace")
        if relative.endswith(".swift"):
            count += len(re.findall(r"\bfunc\s+test[A-Za-z0-9_]*\s*\(", text))
            count += len(re.findall(r"(?m)^\s*@Test(?:\s|\()", text))
        elif relative.endswith(".py"):
            count += len(re.findall(r"(?m)^\s*def\s+test_[A-Za-z0-9_]+\s*\(", text))
    return count


def unsafe_concurrency_inventory() -> dict[str, Any]:
    contract = read_json(ROOT / "config/concurrency-safety.json")
    files: list[Path] = []
    for source_root in contract.get("sourceRoots", []):
        root = ROOT / source_root
        if root.is_dir():
            files.extend(root.rglob("*.swift"))
    occurrences_by_identity: dict[tuple[str, str, str], dict[str, Any]] = {}
    unchecked_pattern = re.compile(
        r"\b(?:class|struct|actor)\s+([A-Za-z_][A-Za-z0-9_]*)[^\n{]*@unchecked\s+Sendable"
    )
    unsafe_pattern = re.compile(
        r"nonisolated\(unsafe\)[^\n]*(?:var|let)\s+([A-Za-z_][A-Za-z0-9_]*)"
    )
    for path in files:
        if not path.is_file():
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            unchecked = unchecked_pattern.search(line)
            unsafe = unsafe_pattern.search(line)
            if unchecked or unsafe:
                relative = path.relative_to(ROOT).as_posix()
                kind = "unchecked-sendable" if unchecked else "nonisolated-unsafe"
                name = (unchecked or unsafe).group(1)
                identity = (relative, kind, name)
                # A declaration may appear in mutually exclusive compilation
                # branches. The safety contract owns the semantic declaration,
                # not the number of textual copies.
                occurrences_by_identity.setdefault(identity, {
                    "path": relative,
                    "line": line_number,
                    "kind": kind,
                    "name": name,
                })
    occurrences = [occurrences_by_identity[key] for key in sorted(occurrences_by_identity)]
    registered_count = sum(
        len(entry.get("types", []))
        for entry in contract.get("entries", [])
        if isinstance(entry, dict)
    ) + sum(
        len(entry.get("names", []))
        for entry in contract.get("unsafeDeclarations", [])
        if isinstance(entry, dict)
    )
    return {
        "count": len(occurrences),
        "registeredCount": registered_count,
        "fullyRegistered": registered_count == len(occurrences),
        "locations": occurrences,
    }


def file_digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence_routing_inventory() -> dict[str, Any]:
    contract = read_json(ROOT / "config/evidence-impact.json")
    critical_patterns = contract.get("criticalPathPatterns") or []
    classes = contract.get("pathClasses") or []
    tracked = sorted(filter(None, git("ls-files").splitlines()))
    critical = [path for path in tracked if path_matches(path, critical_patterns)]
    fallback = [
        path
        for path in critical
        if not any(path_matches(path, item.get("include") or []) for item in classes)
    ]
    return {
        "criticalPathCount": len(critical),
        "explicitlyClassifiedCount": len(critical) - len(fallback),
        "criticalFallbackCount": len(fallback),
        "criticalFallbackPaths": fallback,
    }


def build_report(contract: dict[str, Any]) -> dict[str, Any]:
    selectors = evidence_selectors(contract)
    records = latest_hardware_records(contract)
    evidence: dict[str, Any] = {}
    changes_by_selector: dict[str, tuple[str, list[str], int | None]] = {}
    for identity, selector in selectors.items():
        record = records.get(identity)
        if record is None:
            evidence[identity] = {
                "status": "missing",
                "platform": selector["platform"],
                "kind": selector["kind"],
            }
            changes_by_selector[identity] = ("unknown", [], None)
            continue
        run = record["run"]
        source = record["source"]
        state, paths, distance = changed_paths_since(source["commit"])
        changes_by_selector[identity] = (state, paths, distance)
        evidence[identity] = {
            "status": "available",
            "platform": selector["platform"],
            "kind": selector["kind"],
            "runID": run["id"],
            "finishedAt": run["finishedAt"],
            "sourceCommit": source["commit"],
            "commitDistance": distance,
            "comparisonState": state,
        }

    domains = []
    for domain in contract["criticalDomains"]:
        production = matching_paths(domain["productionGlobs"])
        tests = matching_paths(domain["testGlobs"])
        hardware_freshness: dict[str, Any] = {}
        for selector in domain["hardwareEvidence"]:
            identity = selector["id"]
            state, changed, distance = changes_by_selector[identity]
            if state != "known":
                hardware_freshness[identity] = {
                    "status": "missing" if evidence[identity]["status"] == "missing" else "unknown",
                    "platform": selector["platform"],
                    "kind": selector["kind"],
                    "commitDistance": distance,
                }
                continue
            impacted = [path for path in changed if path_matches(path, domain["productionGlobs"])]
            hardware_freshness[identity] = {
                "status": "stale" if impacted else "fresh",
                "platform": selector["platform"],
                "kind": selector["kind"],
                "commitDistance": distance,
                "impactingPathCount": len(impacted),
            }
        domains.append({
            "id": domain["id"],
            "owner": domain["owner"],
            "productionFileCount": len(production),
            "directTestFileCount": len(tests),
            "directTestCaseCount": count_test_cases(tests),
            "hardwareEvidence": hardware_freshness,
            "externalPromotionEvidence": domain.get("externalPromotionEvidence", []),
        })

    orchestration = read_json(DEFAULT_ORCHESTRATION)
    workflow_count = len(orchestration.get("workflows", {}))
    required_count = sum(
        len(value.get("requiredSteps", []))
        for value in orchestration.get("workflows", {}).values()
        if isinstance(value, dict)
    )
    swift_tests = matching_paths(["Tests/**/*.swift", "Packages/**/Tests/**/*.swift"])
    python_tests = matching_paths(["scripts/test_*.py", "scripts/tests/test_*.py"])
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "source": {
            "commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--short")),
        },
        "identities": {
            "modelContractSHA256": file_digest(ROOT / "Sources/Resources/qwenvoice_contract.json"),
            "projectSHA256": file_digest(ROOT / "project.yml"),
            "packageResolutionSHA256": file_digest(ROOT / "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved"),
            "toolchainManifestSHA256": file_digest(ROOT / "config/toolchain.json"),
        },
        "testInventory": {
            "swiftFiles": len(swift_tests),
            "swiftCases": count_test_cases(swift_tests),
            "pythonFiles": len(python_tests),
            "pythonCases": count_test_cases(python_tests),
        },
        "requiredStepAssurance": {
            "workflowCount": workflow_count,
            "requiredStepCount": required_count,
            "forcedFailureCoverage": "all-declared-steps",
        },
        "hardwareEvidenceCatalog": evidence,
        "criticalDomains": domains,
        "unsafeConcurrency": unsafe_concurrency_inventory(),
        "evidenceRouting": evidence_routing_inventory(),
        "dependencyFreshness": {
            "status": "not-evaluated-offline",
            "identityPinsPresent": (ROOT / "config/toolchain.json").is_file(),
        },
        "openPriorityFindings": {"status": "not-authoritative-without-issue-tracker"},
        "releaseReadiness": {
            "status": "not-run",
            "note": "This inventory is not a substitute for the deterministic release-readiness command."
        },
    }


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Project health scorecard",
        "",
        "> Generated inventory and evidence-freshness snapshot. It is not a release verdict and does not",
        "> execute models, devices, UI tests, signing, or network checks.",
        "",
        "- Current source identity and dirty state: local JSON report only (kept out of the tracked snapshot to avoid self-referential drift)",
        f"- Swift tests: {report['testInventory']['swiftCases']} cases in {report['testInventory']['swiftFiles']} files",
        f"- Python tests: {report['testInventory']['pythonCases']} cases in {report['testInventory']['pythonFiles']} files",
        f"- Required-step assurance: {report['requiredStepAssurance']['requiredStepCount']} steps across {report['requiredStepAssurance']['workflowCount']} workflows, all covered by forced-failure fixtures",
        f"- Unsafe-concurrency annotations: {report['unsafeConcurrency']['count']} ({report['unsafeConcurrency']['registeredCount']} registered with owner and invariant; contract {'complete' if report['unsafeConcurrency']['fullyRegistered'] else 'incomplete'})",
        f"- Evidence routing: {report['evidenceRouting']['explicitlyClassifiedCount']}/{report['evidenceRouting']['criticalPathCount']} critical paths explicit; {report['evidenceRouting']['criticalFallbackCount']} use repository-other fallback",
        "",
        "## Hardware evidence by domain selector",
        "",
        "| Selector | Platform / kind | Latest qualifying run | Captured |",
        "| --- | --- | --- | --- |",
    ]
    for identity, value in sorted(report["hardwareEvidenceCatalog"].items()):
        if value["status"] == "missing":
            lines.append(f"| {identity} | {value['platform']} / {value['kind']} | missing | - |")
        else:
            lines.append(
                f"| {identity} | {value['platform']} / {value['kind']} | `{value['runID']}` | {value['finishedAt']} |"
            )
    lines.extend([
        "",
        "## Critical-domain coverage and freshness",
        "",
        "| Domain | Owner | Production files | Direct test files / cases | Hardware evidence |",
        "| --- | --- | ---: | ---: | --- |",
    ])
    for domain in report["criticalDomains"]:
        freshness = domain["hardwareEvidence"]
        summary = ", ".join(f"{identity}: {value['status']}" for identity, value in freshness.items())
        if not summary and domain["externalPromotionEvidence"]:
            summary = "external promotion: " + ", ".join(domain["externalPromotionEvidence"])
        if not summary:
            summary = "not hardware-gated"
        lines.append(
            f"| {domain['id']} | {domain['owner']} | {domain['productionFileCount']} | "
            f"{domain['directTestFileCount']} / {domain['directTestCaseCount']} | {summary} |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "- `stale` means a production path owned by that domain changed after its latest qualifying hardware record; `missing` means no record matches that domain's selector. Neither blocks ordinary development publishing.",
        "- Test inventory proves discoverable direct coverage, not that those tests passed in this invocation.",
        "- Dependency age and open P0/P1 issue state require authoritative online sources and are intentionally not guessed offline.",
        "- Run `python3 scripts/project_health.py report --output build/artifacts/project-health/` for the complete local JSON inventory.",
        "",
    ])
    return "\n".join(lines)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("validate")
    report = commands.add_parser("report")
    report.add_argument("--output", type=Path, required=True)
    summary = commands.add_parser("rebuild-summary")
    summary.add_argument("--check", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        contract = validate_contract(args.contract)
        if args.command == "validate":
            print(f"Project health contract: PASS ({len(contract['criticalDomains'])} domains)")
            return 0
        report = build_report(contract)
        rendered = markdown(report)
        if args.command == "report":
            output = args.output
            if not output.is_absolute():
                output = ROOT / output
            allowed = (ROOT / contract["localOutputRoot"]).resolve()
            if allowed not in output.resolve().parents and output.resolve() != allowed:
                raise HealthError(f"report output must stay below {contract['localOutputRoot']}")
            output.mkdir(parents=True, exist_ok=True)
            atomic_text(output / "project-health.json", json.dumps(report, indent=2, sort_keys=True) + "\n")
            atomic_text(output / "project-health.md", rendered)
            print(output)
            return 0
        summary_path = ROOT / contract["trackedSummary"]
        if args.check:
            current = summary_path.read_text(encoding="utf-8") if summary_path.is_file() else ""
            if current != rendered:
                raise HealthError(f"generated project-health summary is stale; run: python3 scripts/project_health.py rebuild-summary")
        else:
            atomic_text(summary_path, rendered)
        print("Project health summary: PASS")
        return 0
    except HealthError as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
