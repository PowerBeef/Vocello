#!/usr/bin/env python3
"""Read-only host inventory and offline triage of retained workflow evidence."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = {"python3": ["--version"], "git": ["--version"], "xcodegen": ["--version"],
         "rg": ["--version"], "shellcheck": ["--version"], "xcbeautify": ["--version"],
         "swiftlint": ["version"], "node": ["--version"], "npm": ["--version"],
         "gh": ["--version"], "codex": ["--version"]}


def _probe(command: list[str]) -> dict:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
        lines = result.stdout.strip().splitlines()
        line = next((entry for entry in lines if re.search(r"\d+\.\d+", entry)), lines[0] if lines else None)
        return {"exitCode": result.returncode, "version": line}
    except (OSError, subprocess.SubprocessError):
        return {"exitCode": None, "version": None}


def doctor(root: Path = ROOT) -> dict:
    """Inventory only: do not resolve packages, start a device, install, or write."""
    tools = {}
    manifest_path = root / "config/toolchain.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    for tool, flags in TOOLS.items():
        executable = shutil.which(tool)
        probe = _probe([executable, *flags]) if executable else {"exitCode": None, "version": None}
        pin = manifest.get("artifactPins", {}).get("ripgrep" if tool == "rg" else tool, {}).get("version")
        version = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", probe["version"] or "")
        matches = (version[1] == pin) if pin and version else None
        tools[tool] = {"available": executable is not None, "path": executable, **probe,
                       "pinnedVersion": pin, "matchesPin": matches}
    xcode = {"available": False, "developerDirectory": None, "version": None}
    if executable := shutil.which("xcode-select"):
        selection = _probe([executable, "-p"])
        developer = selection["version"] if selection["exitCode"] == 0 else None
        if developer:
            xcode["developerDirectory"] = developer
            version_file = Path(developer).parent / "version.plist"
            if version_file.is_file():
                with version_file.open("rb") as stream:
                    xcode["version"] = plistlib.load(stream).get("CFBundleShortVersionString")
                xcode["available"] = True
    xcode["pinnedVersion"] = manifest.get("native", {}).get("xcode", {}).get("version")
    xcode["matchesPin"] = (xcode["version"] == xcode["pinnedVersion"]
                            if xcode["version"] and xcode["pinnedVersion"] else None)
    # Capability presence is not proof that a plugin/server is exposed to this chat.
    helper_root = Path.home() / ".codex/plugins/cache/axiom-marketplace/axiom"
    helpers = {}
    versions = sorted(helper_root.glob("*/bin")) if helper_root.is_dir() else []
    for name in ("axbuild", "xclog", "xcprof", "xcproject", "xcsym", "xcui"):
        candidates = [directory / name for directory in versions if (directory / name).is_file()]
        path = candidates[-1] if candidates else None
        executable = bool(path and os.access(path, os.X_OK))
        probe = _probe([os.fspath(path), "--help"]) if executable else {"exitCode": None}
        helpers[name] = {"path": os.fspath(path) if path else None, "executable": executable,
                         "helpProbePassed": probe["exitCode"] == 0}
    hooks = root / ".codex/hooks.json"
    return {"schemaVersion": 1, "readOnly": True, "tools": tools, "xcode": xcode,
            "pythonModules": {name: importlib.util.find_spec(name) is not None for name in ("pytest", "xdist", "numpy")},
            "codex": {"instructionsPresent": (root / "AGENTS.md").is_file(),
                      "skills": sorted(path.parent.name for path in (root / ".agents/skills").glob("*/SKILL.md")),
                      "agentDefinitions": sorted(path.name for path in (root / ".codex/agents").glob("*.toml")),
                      "hooksConfigured": hooks.is_file(), "hookActivation": "unconfirmed",
                      "hookActivationNote": "A fresh trusted Codex session must confirm hook activation; file presence is insufficient.",
                      "mcpAvailability": "session-only; inspect exposed tools in the active Codex chat"},
            "axiomHelpers": helpers,
            "notes": ["No installations, downloads, package resolution, native builds or device probes were performed.",
                      "Optional plugins and helpers never replace repository checks or their native lock."]}


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def triage(run_directory: Path) -> dict:
    """Summarize recorded outcomes; never execute classifiers, rerun, or edit evidence."""
    root = run_directory.resolve()
    if not root.is_dir():
        raise ValueError(f"run directory does not exist: {run_directory}")
    issues: list[str] = []
    evidence: list[str] = []
    failed_steps: list[dict] = []
    failed_tests: list[dict] = []
    missing_steps: list[str] = []

    def read_json(relative: str) -> dict | None:
        path = root / relative
        if not path.exists():
            return None
        if not path.is_file() or not path.resolve().is_relative_to(root) or path.stat().st_size > 4 * 1024 * 1024:
            issues.append(f"unreadable or oversized JSON: {relative}")
            return None
        evidence.append(relative)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError("expected object")
            return value
        except (OSError, ValueError):
            issues.append(f"malformed JSON: {relative}")
            return None

    run = read_json("run.json")
    ledger = read_json("required-steps.json")
    diagnostic = read_json("verdict.json")
    diagnostic_status = None
    if diagnostic:
        # The telemetry-overhead lane has a terminal local verdict rather than
        # UI run metadata/a step ledger. Report it without requalifying timings.
        summary = diagnostic.get("summary")
        diagnostic_id = diagnostic.get("runID")
        candidate = diagnostic.get("status")
        if (diagnostic.get("schemaVersion") != 2
                or not isinstance(diagnostic_id, str) or not diagnostic_id.startswith("telemetry-overhead-")
                or candidate not in ("pass", "fail", "inconclusive")
                or not isinstance(diagnostic.get("completedAt"), str) or not diagnostic["completedAt"]
                or not isinstance(summary, dict) or not isinstance(summary.get("failures"), list)
                or not isinstance(diagnostic.get("inconclusiveReasons"), list)):
            issues.append("unsupported or incomplete diagnostic verdict")
        elif (candidate != "fail" and summary["failures"]
              or candidate == "pass" and diagnostic["inconclusiveReasons"]):
            issues.append("diagnostic verdict contradicts recorded failures or inconclusive reasons")
        else:
            diagnostic_status = candidate
            if candidate == "fail":
                failed_steps.append({"step": "telemetry-overhead", "exitCode": None, "evidence": "verdict.json"})
    ledger_valid = False
    interrupted = False
    if run and ledger is None:
        issues.append("run metadata has no readable required-step ledger")
    if run and (run.get("status") in ("running", None) or not run.get("finishedAt")):
        issues.append("run metadata has no terminal completion")
    if run and (not isinstance(run.get("status"), str) or not isinstance(run.get("finishedAt"), str)):
        issues.append("malformed run completion metadata")
    if run and run.get("status") == "passed" and (run.get("exitCode") != 0 or isinstance(run.get("exitCode"), bool)):
        issues.append("passed run metadata has a nonzero or missing exit code")
    if ledger:
        expected, results = ledger.get("expectedSteps"), ledger.get("results")
        if (not isinstance(expected, list) or not expected or not isinstance(results, dict)
                or any(not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                       or not isinstance(entry.get("required"), bool) for entry in expected)):
            issues.append("malformed required-step ledger")
        else:
            ledger_valid = True
            required = [entry["id"] for entry in expected if entry["required"]]
            if not required:
                ledger_valid = False
                issues.append("required-step ledger declares no required steps")
            if len(set(entry["id"] for entry in expected)) != len(expected):
                ledger_valid = False
                issues.append("duplicate required-step identifiers")
            for step in required:
                result = results.get(step)
                if not isinstance(result, dict):
                    missing_steps.append(step)
                    continue
                code, state = result.get("exitCode"), result.get("status")
                if not isinstance(code, int) or isinstance(code, bool) or state not in ("passed", "failed"):
                    ledger_valid = False
                    issues.append(f"malformed required-step result: {step}")
                elif code != 0 or state != "passed":
                    failed_steps.append({"step": step, "status": state, "exitCode": code,
                                         "evidence": "required-steps.json"})
                    interrupted |= code in {130, 143, -2, -15}
                if result.get("executionMode") == "managed-subprocess" and not isinstance(result.get("manifest"), str):
                    ledger_valid = False
                    issues.append(f"missing managed-step manifest: {step}")
                if isinstance(relative := result.get("manifest"), str):
                    if Path(relative).is_absolute() or ".." in Path(relative).parts:
                        issues.append(f"unsafe step manifest: {step}")
                        ledger_valid = False
                        continue
                    step_manifest = read_json(relative)
                    if step_manifest is None:
                        ledger_valid = False
                        issues.append(f"missing step manifest: {step}")
                    else:
                        if (claimed := result.get("manifestSHA256")) and _digest(root / relative) != claimed:
                            ledger_valid = False
                            issues.append(f"step manifest digest mismatch: {step}")
                        interrupted |= step_manifest.get("outcome") == "terminated"
    test_files = sorted({*root.glob("*.test-results.json"), *root.glob("test-results.json")})
    for path in test_files:
        summary = read_json(path.name)
        if not summary:
            continue
        if summary.get("consistent") is False:
            issues.append(f"inconsistent test summary: {path.name}")
        tests = summary.get("tests", [])
        if not isinstance(tests, list):
            issues.append(f"malformed test list: {path.name}")
            continue
        for test in tests:
            if isinstance(test, dict) and test.get("verdict") == "failed":
                failed_tests.append({"suite": test.get("suite"), "test": test.get("test"), "evidence": path.name})

    classification = None
    for filename, expected_status in (("xcui-bootstrap-classification.json", "infrastructure_bootstrap_failure"),
                                       ("xcui-external-interruption-classification.json", "infrastructure_external_interruption")):
        record = read_json(filename)
        if not record:
            continue
        bound = record.get("status") == expected_status and (not run or record.get("runID") == run.get("runID"))
        for relative, field in (("xcodebuild.log", "xcodebuildLogSHA256"),
                                ("xcresult-test-summary.json", "xcresultSummarySHA256")):
            path = root / relative
            bound = bound and path.is_file() and path.resolve().is_relative_to(root) and record.get(field) == _digest(path)
        if bound:
            classification = "infrastructure-failure" if "bootstrap" in filename else "external-interruption"
            evidence.extend(["xcodebuild.log", "xcresult-test-summary.json"])
        else:
            issues.append(f"unbound infrastructure classification: {filename}")

    verdict_text = ""
    verdict_file = root / "verdict.txt"
    if verdict_file.is_file() and verdict_file.resolve().is_relative_to(root):
        evidence.append("verdict.txt")
        with verdict_file.open(encoding="utf-8", errors="replace") as stream:
            verdict_text = stream.read(65536)
        if verdict_file.stat().st_size > 65536:
            issues.append("oversized verdict.txt; only the opening 64 KiB was inspected")
    crash_delta = root / "new-crashes.txt"
    if crash_delta.is_file() and crash_delta.resolve().is_relative_to(root) and crash_delta.stat().st_size:
        evidence.append("new-crashes.txt")
        issues.append("nonempty crash-delta marker requires inspection; it may contain a crash or a collection failure")
    codes = {key: int(value) for key, value in re.findall(r"^(test_build|build|core|runtime)=(-?\d+)\s*$", verdict_text, re.M)}
    for step, code in codes.items():
        if code:
            failed_steps.append({"step": step, "exitCode": code, "evidence": "verdict.txt"})
            interrupted |= code in {130, 143, -2, -15}
    status = run.get("status") if run else diagnostic_status
    interrupted |= bool(run and run.get("exitCode") in (130, 143, -2, -15))
    restoration = any("restor" in entry["step"] for entry in failed_steps) or any("restor" in step for step in missing_steps)
    native_terminal = {"test_build", "core", "runtime"} <= codes.keys() or {"build", "core"} <= codes.keys()
    recorded_pass = bool((run and status == "passed" and run.get("exitCode") == 0 and run.get("finishedAt"))
                         or (ledger_valid and ledger and ledger.get("status") == "passed" and ledger.get("completedAt"))
                         or (native_terminal and not any(codes.values()))
                         or diagnostic_status == "pass"
                         or re.search(r"^(GATE|RELEASE READINESS): PASS\s*$", verdict_text, re.M))
    if classification and not any("crash" in entry["step"] for entry in failed_steps):
        verdict = classification
    elif interrupted:
        verdict = "interrupted"
    elif restoration:
        verdict = "restoration-gap"
    elif failed_tests or status == "diagnosedFailure":
        verdict = "product-failure"
    elif failed_steps or status == "failed" or (ledger and ledger.get("status") == "failed" and not missing_steps) or re.search(r"^(GATE|RELEASE READINESS): FAIL\s*$", verdict_text, re.M):
        verdict = "failure-unclassified"
    elif diagnostic_status == "inconclusive" or re.search(r"^GATE: INCONCLUSIVE\s*$", verdict_text, re.M):
        verdict = "inconclusive"
    elif recorded_pass and not missing_steps and not issues and (not ledger or ledger_valid and ledger.get("status") == "passed"):
        verdict = "PASS"
    else:
        verdict = "incomplete"
    if not run and not ledger and not verdict_text and not diagnostic:
        issues.append("no runner verdict or required-step ledger; passing tests alone cannot prove run completion")
    artifacts: list[str] = []
    truncated = False
    for directory, children, files in os.walk(root):
        base = Path(directory)
        result_bundles = [name for name in children if name.endswith((".xcresult", ".trace"))]
        artifacts.extend((base / name).relative_to(root).as_posix() for name in result_bundles)
        children[:] = sorted(name for name in children if name not in result_bundles and not name.startswith(".")
                             and len((base / name).relative_to(root).parts) < 4)
        artifacts.extend((base / name).relative_to(root).as_posix() for name in sorted(files)
                         if name.endswith((".json", ".log", ".txt", ".ips", ".crash")))
        if len(artifacts) > 200:
            artifacts = artifacts[:200]
            truncated = True
            break
    return {"schemaVersion": 1, "readOnly": True, "runDirectory": os.fspath(root),
            "runID": run.get("runID") if run else ledger.get("runID") if ledger else diagnostic.get("runID") if diagnostic else None,
            "verdict": verdict, "recordedStatus": status, "failedSteps": failed_steps, "failedTests": failed_tests,
            "missingRequiredSteps": missing_steps, "issues": issues, "evidence": sorted(set(evidence)),
            "artifacts": artifacts, "artifactsTruncated": truncated,
            "qualification": "recorded outcomes only; no benchmark requalification or human listening verdict",
            "nextAction": "Inspect retained evidence. A justified rerun uses a new run identity; no rerun was performed."}


def print_report(report: dict) -> None:
    if "verdict" in report:
        print(f"Verdict: {report['verdict']}")
        print(f"Run: {report['runDirectory']}")
        for entry in report["failedSteps"]:
            print(f"  failed step: {entry['step']} (exit {entry.get('exitCode')}); {entry['evidence']}")
        for entry in report["failedTests"]:
            print(f"  failed test: {entry.get('suite')}/{entry.get('test')}; {entry['evidence']}")
        for step in report["missingRequiredSteps"]:
            print(f"  missing required step: {step}")
        for issue in report["issues"]:
            print(f"  evidence gap: {issue}")
        print(f"Evidence: {', '.join(report['evidence']) or 'none'}")
        print(report["nextAction"])
    else:
        for name, tool in report["tools"].items():
            drift = f" (pin: {tool['pinnedVersion']}; differs)" if tool["matchesPin"] is False else ""
            print(f"{name}: {tool['version'] or ('present; version probe failed' if tool['available'] else 'missing')}{drift}")
        xcode_drift = f" (CI pin: {report['xcode']['pinnedVersion']}; differs)" if report["xcode"]["matchesPin"] is False else ""
        print(f"Xcode: {report['xcode']['version'] or 'not detected'}{xcode_drift}")
        print(f"Codex hooks: {'configured' if report['codex']['hooksConfigured'] else 'missing'}; activation unconfirmed")
        print(report["codex"]["hookActivationNote"])
        print(f"MCP availability: {report['codex']['mcpAvailability']}")
        for note in report["notes"]:
            print(note)
