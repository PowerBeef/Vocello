#!/usr/bin/env python3
"""The audio QC judge registry: license tiers, pins, independence and status.

`config/audio-qc-judges.json` describes every judge the audio QC and speech
analysis harness runs or has run (audit 2026-09-25, AQ-01, phase M0). This
module validates it and is the load-time gate for registered judges:

- No judge outside `retired` carries tier C or an unknown tier; tier C is
  retired, never quarantined or advisory (decision 1a).
- A tier-B judge records the decision-2a acceptance: internal evaluation that
  never ships.
- A judge from the generator's lab never votes (decision 3a).
- Every neural judge that can still run is pinned by file digest, or by every
  file of a Hugging Face snapshot at its revision (the LFS SHA-256 or the git
  blob ID), verified before each load.
- The exclusion list (audit section 4.9) is refused by model and package: no
  registered judge, execution candidate or runtime dependency may match it, and
  every model loader calls `require_loadable` with its registry judge and the
  repository it actually loads. Use restrictions bound how a judge may run.
- The output identity (what can change a judge's output, runtime versions and,
  until cross-host determinism is measured, the host included) and the
  envelope identity (how a run was supervised) never share a component.
- Retired judges stay out of every QC path: their adapters, cascade layers and
  guardrails appear in no live contract, their source files are deleted, and a
  legacy contract that still names a retired guardrail is frozen by digest.
- Adoption names the canonical host: two clean runs on the one canonical
  macOS profile of `benchmarks/hardware-profiles.json`.
- Admission (decision 9a, AQ-05) is budgeted: one memory budget, one GPU
  worker beside at most two CPU workers, and every orchestrated worker judge
  declares its lane, engine and thread count (part of its output identity) and
  has a ceiling the budget can hold. The child-attributed recovery rule stays
  report-only (`candidateBinding: false`, one worker host-wide) until the
  registry records the M6 evidence its promotion names.

Commands:
  validate   check the registry against the repository (the contract gate)
"""

from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import functools
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Iterable

REPO = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY = REPO / "config/audio-qc-judges.json"
CANDIDATES = "config/delivery-evaluator-v2-candidates.json"
EVALUATOR_CONTRACT = "config/delivery-evaluator-v2-contract.json"
EXPERIMENT_CONTRACT = "config/delivery-experiment-contract.json"
HARDWARE_PROFILES = "benchmarks/hardware-profiles.json"

SCHEMA_VERSION = 1
KIND = "audio-qc-judge-registry"
STATUSES = ("candidate", "shadow", "advisory", "warn", "gating", "retired", "quarantined")
# A quarantined judge is registered but blocked until a maintainer decision.
BLOCKED_STATUSES = frozenset({"retired", "quarantined"})
# Statuses whose verdicts can fail a take or a lane.
VERDICT_STATUSES = frozenset({"warn", "gating"})
KINDS = ("neural", "dsp", "platform", "fitted")
TIERS = ("A", "B", "C")
TIER_B_SCOPE = "internal-never-shipped-evaluation"
ADOPTION_REQUIREMENT = "two-clean-canonical-host-runs"
# The 8 GB-era adoption tokens (AQ-F40): no live contract may require them.
STALE_ADOPTION_MARKERS = ("eight-gib", "eight-gigabyte")
# The supervisor's source is envelope identity (AQ-F47); an output identity
# that names it would let a supervisor fix invalidate caches and calibrations.
ENVELOPE_ONLY_COMPONENTS = frozenset({"resourceSupervisorSHA256", "probeAlgorithmVersion", "supervisorOptions"})
# What can change a judge's output. An envelope that named one of these would
# let a change of weights, code, runtime or preprocessing serve a stale result.
OUTPUT_ONLY_COMPONENTS = frozenset({
    "adapterID", "modelID", "repository", "revision", "sourceRevision", "weightsSHA256",
    "binarySHA256", "snapshotFileDigests", "runtimeDependencies", "runtimeDependenciesDigest",
    "runtimeVersions", "torchVersion", "numpyVersion", "workerSourceSHA256", "adapterSourceSHA256",
    "adapterLayerSHA256", "analyzerSourceSHA256", "comparatorSourceSHA256", "commandTemplate",
    "labelMapDigest", "labelSet", "decodeOptions", "lockedLanguage", "preprocessing",
    "preprocessingConfigDigest", "outputFormat", "algorithm", "configuration", "resampler",
    "threads", "modelDigest", "featureNames",
})
# A runtime is part of the output identity under one of these names.
RUNTIME_COMPONENTS = ("runtimeDependencies", "runtimeDependenciesDigest", "runtimeVersions")
# A runtime dependency that is not pinned in the registry is read when the judge
# loads and recorded in its output identity as `runtimeVersions`.
RECORDED_AT_LOAD = "recorded-at-load"
# Until a judge's cross-host determinism is measured (AQ-06), the host is part
# of what produced its output.
HOST_COMPONENT = "hostProfile"
DIGEST_STATUS_BY_KIND = {
    "neural": ("pinned", "content-addressed-snapshot"),
    "dsp": ("no-learned-weights",),
    "platform": ("platform-managed",),
    "fitted": ("fitted-model-digest",),
}
# Admission (decision 9a). Lanes a worker is admitted in, and where the other
# judges run.
ADMISSION_POLICY = "budgeted-admission-after-generator-exit"
WORKER_LANES = ("gpu", "cpu", "dsp")
EXECUTION_LANES = (*WORKER_LANES, "engine", "device")
WHOLE_HOST_RECOVERY_RULE = "whole-host-free-percent-v1"
CANDIDATE_RECOVERY_RULE = "attributed-post-exit-recovery-v2"
IN_PROCESS_ENGINE = "in-process"
# What a promotion of the child-attributed recovery rule must cite per report.
RECOVERY_EVIDENCE_FIELDS = (
    "recoveryReportSHA256", "hardwareProfileID", "date", "serialEnvelopes",
    "serialCandidateWouldQualifyBindingFailure", "unattributed", "byJudge",
)
MINIMUM_RECOVERY_REPORTS = 2
SNAPSHOT_STATUS = "content-addressed-snapshot"
JUDGE_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*@[0-9]+$")
ROADMAP_ITEM = re.compile(r"^[A-Z]+-[0-9]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")


class JudgeRegistryError(ValueError):
    """The registry is invalid, or a judge may not run."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JudgeRegistryError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise JudgeRegistryError(f"{path.name} must contain an object")
    return value


def load_registry(path: Path = DEFAULT_REGISTRY) -> dict[str, Any]:
    return _read_json(path)


def _strings(value: Any) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _matches(value: str, patterns: Iterable[str]) -> str | None:
    lowered = value.lower()
    for pattern in patterns:
        if fnmatchcase(lowered, pattern.lower()):
            return pattern
    return None


def _is_blocked(judge: dict[str, Any]) -> bool:
    return judge.get("status") in BLOCKED_STATUSES


def _judge_models(judge: dict[str, Any]) -> list[str]:
    pins = judge.get("pins") if isinstance(judge.get("pins"), dict) else {}
    return [value for value in (pins.get("repository"), judge.get("modelID")) if isinstance(value, str)]


def _judge_packages(judge: dict[str, Any]) -> list[str]:
    pins = judge.get("pins") if isinstance(judge.get("pins"), dict) else {}
    runtime = pins.get("runtime")
    return list(runtime) if isinstance(runtime, dict) else []


def _exclusion_errors(label: str, models: Iterable[str], packages: Iterable[str],
                      exclusions: list[dict[str, Any]]) -> list[str]:
    errors = []
    for entry in exclusions:
        for model in models:
            if (pattern := _matches(model, _strings(entry.get("models")))) is not None:
                errors.append(f"{label}: model {model} is excluded ({entry.get('id')}: {pattern})")
        for package in packages:
            if _matches(package, _strings(entry.get("packages"))) is not None:
                errors.append(f"{label}: package {package} is excluded ({entry.get('id')})")
    return errors


def _snapshot_pin(value: Any) -> bool:
    """One snapshot file pin: the LFS SHA-256 or the git blob ID, and optionally its size."""
    if not isinstance(value, dict) or not set(value) <= {"lfsSHA256", "gitBlobID", "size"}:
        return False
    size = value.get("size", 0)
    if isinstance(size, bool) or not isinstance(size, int) or size < 0:
        return False
    if "lfsSHA256" in value:
        return "gitBlobID" not in value and bool(SHA256.match(str(value["lfsSHA256"])))
    return bool(GIT_REVISION.match(str(value.get("gitBlobID", ""))))


def _list_entry_errors(kind: str, entries: Any, required: tuple[str, ...]) -> list[str]:
    errors: list[str] = []
    if not isinstance(entries, list):
        return [f"the {kind} list is missing"]
    seen: set[str] = set()
    for entry in entries:
        identity = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(identity, str) or not identity or identity in seen:
            errors.append(f"every {kind} entry needs a unique id")
            continue
        seen.add(identity)
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            errors.append(f"{kind} {identity} needs a reason")
        for field in required:
            if not isinstance(entry.get(field), list) or len(_strings(entry[field])) != len(entry[field]):
                errors.append(f"{kind} {identity} needs a {field} list of strings")
    return errors


def validate_registry(registry: dict[str, Any], *, root: Path = REPO) -> list[str]:
    """Errors in the registry itself and in the files it names; empty when valid."""
    errors: list[str] = []
    if registry.get("schemaVersion") != SCHEMA_VERSION or registry.get("kind") != KIND:
        return [f"registry must be {KIND} schema {SCHEMA_VERSION}"]
    decisions = registry.get("decisions")
    if not isinstance(decisions, dict) or any(
        not isinstance(decisions.get(key), dict) or decisions[key].get("option") != "a"
        for key in ("1", "2", "3", "9")
    ):
        errors.append("decisions 1, 2, 3 and 9 must record option a")
    adoption = registry.get("adoption")
    if not isinstance(adoption, dict) or adoption.get("requirement") != ADOPTION_REQUIREMENT:
        errors.append(f"adoption must require {ADOPTION_REQUIREMENT}")
    exclusions = registry.get("excluded")
    if not isinstance(exclusions, list) or not exclusions:
        errors.append("the exclusion list is missing")
        exclusions = []
    errors.extend(_list_entry_errors("exclusion", exclusions, ("models", "packages")))
    for entry in exclusions:
        if isinstance(entry, dict) and entry.get("tier") not in (*TIERS, None):
            errors.append(f"exclusion {entry.get('id')} has an invalid tier")
    restrictions = registry.get("useRestrictions")
    errors.extend(_list_entry_errors("use restriction", restrictions, ("models",)))
    for entry in restrictions if isinstance(restrictions, list) else []:
        if isinstance(entry, dict) and not (
            isinstance(entry.get("forbiddenUse"), str) and entry["forbiddenUse"].strip()
            and isinstance(entry.get("permittedUse"), str) and entry["permittedUse"].strip()
        ):
            errors.append(f"use restriction {entry.get('id')} must name its forbidden and permitted use")
    judges = registry.get("judges")
    if not isinstance(judges, dict) or not judges:
        return errors + ["the registry lists no judges"]
    exclusions = [entry for entry in exclusions if isinstance(entry, dict)]
    restrictions = [entry for entry in restrictions or [] if isinstance(entry, dict)]
    for judge_id, judge in judges.items():
        errors.extend(_judge_errors(judge_id, judge, exclusions, restrictions, root))
    errors.extend(admission_errors(registry, root=root))
    return errors


def _positive_int(value: Any) -> bool:
    return type(value) is int and value > 0


def judge_admission_ceiling(judge: dict[str, Any]) -> int | None:
    """A worker judge's admission ceiling: measured peak x 1.2, else provisional."""
    resources = judge.get("resources") if isinstance(judge.get("resources"), dict) else {}
    measured = resources.get("canonicalHostPeakBytes")
    if _positive_int(measured):
        return -(-measured * 12 // 10)
    provisional = resources.get("provisionalCeilingBytes")
    return provisional if _positive_int(provisional) else None


def _recovery_evidence_errors(evidence: Any, registry: dict[str, Any], root: Path) -> list[str]:
    """The M6 evidence that alone may make the child-attributed rule binding."""
    if not isinstance(evidence, list) or len(evidence) < MINIMUM_RECOVERY_REPORTS:
        return [f"a binding child-attributed recovery rule cites at least {MINIMUM_RECOVERY_REPORTS} recovery reports"]
    errors: list[str] = []
    try:
        canonical = [profile.get("id") for profile in canonical_profiles(registry, root)]
    except JudgeRegistryError:
        canonical = []
    workers = sorted(
        judge_id for judge_id, judge in (registry.get("judges") or {}).items()
        if judge.get("status") not in BLOCKED_STATUSES and isinstance(judge.get("execution"), dict)
        and judge["execution"].get("orchestrated") is True and judge["execution"].get("lane") in ("gpu", "cpu")
    )
    digests = set()
    for index, report in enumerate(evidence):
        label = f"recovery evidence {index + 1}"
        if not isinstance(report, dict) or any(field not in report for field in RECOVERY_EVIDENCE_FIELDS):
            errors.append(f"{label} records {', '.join(RECOVERY_EVIDENCE_FIELDS)}")
            continue
        if not SHA256.match(str(report["recoveryReportSHA256"])):
            errors.append(f"{label} names its recovery report by SHA-256")
        digests.add(report["recoveryReportSHA256"])
        if report["hardwareProfileID"] not in canonical:
            errors.append(f"{label} was not measured on the canonical hardware profile")
        if not _positive_int(report["serialEnvelopes"]):
            errors.append(f"{label} holds no serial envelope")
        if report["serialCandidateWouldQualifyBindingFailure"] != 0:
            errors.append(f"{label}: the candidate blamed a serial post-exit drop on another allocator")
        if report["unattributed"] != 0:
            errors.append(f"{label} has unattributed envelopes")
        by_judge = report["byJudge"] if isinstance(report["byJudge"], dict) else {}
        missing = [judge_id for judge_id in workers if not _positive_int(by_judge.get(judge_id))]
        if missing:
            errors.append(f"{label} lacks envelopes of {', '.join(missing)}")
    if len(digests) < MINIMUM_RECOVERY_REPORTS:
        errors.append("recovery evidence reports must be distinct")
    return errors


def admission_errors(registry: dict[str, Any], *, root: Path = REPO) -> list[str]:
    """The budgeted admission block and every judge's execution declaration (decision 9a)."""
    admission = registry.get("admission")
    if not isinstance(admission, dict) or admission.get("policy") != ADMISSION_POLICY:
        return [f"admission must declare the {ADMISSION_POLICY} policy"]
    errors: list[str] = []
    budget, reservation = admission.get("budgetBytes"), admission.get("orchestratorReservationBytes")
    if not _positive_int(budget) or not _positive_int(reservation) or reservation >= budget:
        errors.append("admission needs a positive budget and a smaller orchestrator reservation")
        budget, reservation = 0, 0
    lanes = admission.get("lanes") if isinstance(admission.get("lanes"), dict) else {}
    limits = {lane: (lanes.get(lane) or {}).get("maximumConcurrent") if isinstance(lanes.get(lane), dict) else None
              for lane in WORKER_LANES}
    if set(lanes) != set(WORKER_LANES) or not all(_positive_int(limit) for limit in limits.values()):
        errors.append("admission lanes are gpu, cpu and dsp, each with a positive maximumConcurrent")
    elif limits["gpu"] != 1 or limits["cpu"] > 2:
        errors.append("admission runs one MLX GPU worker at a time beside at most two CPU workers")
    recovery = admission.get("recoveryRule") if isinstance(admission.get("recoveryRule"), dict) else {}
    if (recovery.get("binding") != WHOLE_HOST_RECOVERY_RULE or recovery.get("candidate") != CANDIDATE_RECOVERY_RULE
            or not isinstance(recovery.get("candidateBinding"), bool)):
        errors.append("admission.recoveryRule names the whole-host rule, the child-attributed candidate and the switch")
    promotion = recovery.get("promotion") if isinstance(recovery.get("promotion"), dict) else {}
    if not _strings(promotion.get("requires")) or not isinstance(promotion.get("evidence"), list):
        errors.append("the recovery-rule promotion lists what it requires and the evidence recorded")
    if recovery.get("candidateBinding") is True:
        errors.extend(_recovery_evidence_errors(promotion.get("evidence"), registry, root))
    elif recovery.get("candidateBinding") is False and recovery.get("workerCapWhileWholeHostBinding") != 1:
        errors.append("while the whole-host recovery rule binds, admission caps the host at one worker")
    for judge_id, judge in (registry.get("judges") or {}).items():
        if not isinstance(judge, dict):
            continue
        execution = judge.get("execution")
        label = f"judge {judge_id}"
        if judge.get("status") in BLOCKED_STATUSES:
            if execution is not None:
                errors.append(f"{label}: a retired or quarantined judge declares no execution")
            continue
        if not isinstance(execution, dict) or execution.get("lane") not in EXECUTION_LANES \
                or not isinstance(execution.get("orchestrated"), bool):
            errors.append(f"{label}: execution names its lane ({', '.join(EXECUTION_LANES)}) and whether the orchestrator runs it")
            continue
        if not execution["orchestrated"]:
            continue
        identity = judge.get("identity") if isinstance(judge.get("identity"), dict) else {}
        if not _positive_int(execution.get("threads")) or "threads" not in _strings(identity.get("output")):
            errors.append(f"{label}: an orchestrated judge declares its thread count, which is output identity")
        if execution.get("lane") not in WORKER_LANES or not isinstance(execution.get("engine"), str):
            errors.append(f"{label}: an orchestrated judge runs in a worker lane with a named engine")
            continue
        worker = execution.get("worker")
        if not isinstance(worker, str) or not (root / worker).is_file():
            errors.append(f"{label}: its worker source {worker} does not exist")
        if execution["engine"] == IN_PROCESS_ENGINE:
            continue
        ceiling = judge_admission_ceiling(judge)
        if ceiling is None:
            errors.append(f"{label}: an orchestrated worker has a measured or provisional ceiling")
        elif budget and ceiling + reservation > budget:
            errors.append(f"{label}: its ceiling never fits the admission budget")
    return errors


def _judge_errors(judge_id: str, judge: Any, exclusions: list[dict[str, Any]],
                  restrictions: list[dict[str, Any]], root: Path) -> list[str]:
    label = f"judge {judge_id}"
    if not JUDGE_ID.match(judge_id):
        return [f"{label}: id must read <name>@<version>"]
    if not isinstance(judge, dict):
        return [f"{label}: must be an object"]
    errors: list[str] = []
    status, kind = judge.get("status"), judge.get("kind")
    if status not in STATUSES:
        errors.append(f"{label}: unknown status {status!r}")
    if kind not in KINDS:
        errors.append(f"{label}: unknown kind {kind!r}")
    blocked = status in BLOCKED_STATUSES
    retired = status == "retired"
    license_ = judge.get("license") if isinstance(judge.get("license"), dict) else {}
    tier = license_.get("tier")
    for field in ("weights", "trainingData"):
        if not isinstance(license_.get(field), str) or not license_[field].strip():
            errors.append(f"{label}: license must record the {field} terms")
    if tier not in TIERS:
        errors.append(f"{label}: license tier is unknown")
    elif tier == "C" and not retired:
        errors.append(f"{label}: a tier-C judge must be retired")
    if not isinstance(license_.get("commercialUseCompatible"), bool):
        errors.append(f"{label}: commercialUseCompatible must be recorded")
    elif license_["commercialUseCompatible"] is (tier == "C"):
        errors.append(f"{label}: commercialUseCompatible contradicts tier {tier}")
    if tier == "B" and not blocked:
        acceptance = judge.get("tierBAcceptance")
        if (not isinstance(acceptance, dict) or acceptance.get("decision") != "2a"
                or acceptance.get("scope") != TIER_B_SCOPE):
            errors.append(f"{label}: tier B needs the decision-2a internal-evaluation acceptance")
        if judge.get("ships") is not False:
            errors.append(f"{label}: a tier-B judge never ships")
    independence = judge.get("independence") if isinstance(judge.get("independence"), dict) else {}
    for field in ("vendor", "architecture", "trainingData", "labelLineage"):
        if not isinstance(independence.get(field), str) or not independence[field].strip():
            errors.append(f"{label}: independence must record {field}")
    if not isinstance(independence.get("generatorLabCorrelated"), bool):
        errors.append(f"{label}: independence must record generatorLabCorrelated")
    if not isinstance(judge.get("voting"), bool):
        errors.append(f"{label}: voting must be recorded")
    elif judge["voting"] and (independence.get("generatorLabCorrelated") or blocked):
        errors.append(f"{label}: a same-lab, retired or quarantined judge never votes")
    calibration = judge.get("calibration")
    if retired:
        retirement = judge.get("retirement")
        if not isinstance(retirement, dict) or any(
            not isinstance(retirement.get(field), str) or not retirement[field]
            for field in ("date", "decision", "reason")
        ):
            errors.append(f"{label}: retirement needs a date, decision and reason")
        if calibration != "none":
            errors.append(f"{label}: a retired judge carries no calibration")
    elif calibration != "legacy-unqualified" and not (
        isinstance(calibration, dict) and SHA256.match(str(calibration.get("recordSHA256", "")))
    ):
        errors.append(f"{label}: calibration must be legacy-unqualified or a record digest")
    planned = judge.get("plannedRetirement")
    if planned is not None and not (
        isinstance(planned, dict) and ROADMAP_ITEM.match(str(planned.get("item", "")))
        and planned.get("status") == "deferred"
        and isinstance(planned.get("reason"), str) and planned["reason"].strip()
    ):
        errors.append(f"{label}: a planned retirement names its roadmap item, status deferred and a reason")
    errors.extend(_pin_errors(label, judge, kind, blocked))
    errors.extend(_identity_errors(label, judge, kind, blocked))
    legacy = judge.get("legacyIdentifiers") if isinstance(judge.get("legacyIdentifiers"), dict) else {}
    for path in _strings(legacy.get("sources")):
        exists = (root / path).exists()
        if retired and exists:
            errors.append(f"{label}: retired judge's {path} still exists")
        elif not retired and not exists:
            errors.append(f"{label}: {path} does not exist")
    if blocked:
        if tier == "C" and not any(
            _matches(model, _strings(entry.get("models"))) for entry in exclusions
            for model in _judge_models(judge)
        ):
            errors.append(f"{label}: a retired tier-C judge must be on the exclusion list")
        return errors
    errors.extend(_exclusion_errors(label, _judge_models(judge), _judge_packages(judge), exclusions))
    for entry in restrictions:
        if not any(_matches(model, _strings(entry.get("models"))) for model in _judge_models(judge)):
            continue
        if judge.get("useRestriction") != entry.get("id"):
            errors.append(f"{label}: matches use restriction {entry.get('id')} and must acknowledge it")
        if judge.get("voting") is not False or status in VERDICT_STATUSES:
            errors.append(f"{label}: use restriction {entry.get('id')} forbids votes and verdicts")
    return errors


def _pin_errors(label: str, judge: dict[str, Any], kind: Any, blocked: bool) -> list[str]:
    pins = judge.get("pins")
    if not isinstance(pins, dict):
        return [f"{label}: pins are missing"]
    status = pins.get("digestStatus")
    errors = []
    if not isinstance(pins.get("verification"), str) or not pins["verification"].strip():
        errors.append(f"{label}: pins must say how the judge is verified before it loads")
    if kind == "neural":
        if not isinstance(pins.get("repository"), str) or not GIT_REVISION.match(str(pins.get("revision", ""))):
            errors.append(f"{label}: a neural judge is pinned by repository and immutable revision")
        files = pins.get("files")
        if status == SNAPSHOT_STATUS:
            if not isinstance(files, dict) or any(not _snapshot_pin(value) for value in files.values()):
                errors.append(f"{label}: snapshot file pins name an LFS SHA-256 or a git blob ID")
            elif not files and not blocked:
                errors.append(f"{label}: a runnable snapshot judge pins every file of its snapshot")
        elif not isinstance(files, dict) or any(not SHA256.match(str(value)) for value in files.values()):
            errors.append(f"{label}: file pins must be SHA-256 digests")
        elif status == "pinned" and not files:
            errors.append(f"{label}: a pinned judge lists its file digests")
    runtime = pins.get("runtime")
    if runtime is not None and (not isinstance(runtime, dict) or any(
        not isinstance(value, str) or not value.strip() for value in runtime.values()
    )):
        errors.append(f"{label}: runtime pins map each package to a version or {RECORDED_AT_LOAD}")
    if blocked:
        return errors
    if status not in DIGEST_STATUS_BY_KIND.get(kind, ()):
        errors.append(f"{label}: a runnable {kind} judge cannot load with digest status {status!r}")
    return errors


def _identity_errors(label: str, judge: dict[str, Any], kind: Any, blocked: bool) -> list[str]:
    identity = judge.get("identity") if isinstance(judge.get("identity"), dict) else {}
    output, envelope = _strings(identity.get("output")), _strings(identity.get("envelope"))
    errors = []
    if not output or not isinstance(identity.get("envelope"), list):
        errors.append(f"{label}: identity needs output and envelope component lists")
    if set(output) & set(envelope):
        errors.append(f"{label}: a component is either output or envelope identity, never both")
    if set(output) & ENVELOPE_ONLY_COMPONENTS:
        errors.append(f"{label}: supervisor provenance is envelope identity, never output identity")
    if set(envelope) & OUTPUT_ONLY_COMPONENTS:
        errors.append(f"{label}: what can change the output is output identity, never envelope identity")
    if blocked:
        return errors
    pins = judge.get("pins") if isinstance(judge.get("pins"), dict) else {}
    runtime = pins.get("runtime") if isinstance(pins.get("runtime"), dict) else {}
    if runtime and not set(output) & set(RUNTIME_COMPONENTS):
        errors.append(f"{label}: its runtime is output identity ({', '.join(RUNTIME_COMPONENTS)})")
    if RECORDED_AT_LOAD in runtime.values() and "runtimeVersions" not in output:
        errors.append(f"{label}: runtime versions recorded at load are output identity (runtimeVersions)")
    if kind == "neural" and HOST_COMPONENT not in output:
        errors.append(f"{label}: until its cross-host determinism is measured, the host is output identity")
    return errors


def _frozen_contract_errors(judge_id: str, judge: dict[str, Any], root: Path) -> list[str]:
    """A legacy contract that names a retired guardrail is frozen: its bytes never change."""
    legacy = judge.get("legacyIdentifiers") if isinstance(judge.get("legacyIdentifiers"), dict) else {}
    guardrails = set(_strings(legacy.get("guardrails")))
    frozen = legacy.get("frozenContracts", [])
    if not isinstance(frozen, list):
        return [f"judge {judge_id}: frozenContracts must be a list"]
    errors = []
    for entry in frozen:
        path = entry.get("path") if isinstance(entry, dict) else None
        label = f"judge {judge_id}: frozen contract {path}"
        if not isinstance(path, str) or not SHA256.match(str(entry.get("sha256", ""))) or not _strings(
            entry.get("fields")
        ) or not isinstance(entry.get("reason"), str):
            errors.append(f"judge {judge_id}: a frozen contract records its path, SHA-256, fields and reason")
            continue
        if not (root / path).is_file() or _sha256(root / path) != entry["sha256"]:
            errors.append(f"{label} changed; a digest-bound legacy contract is never edited")
            continue
        value = _read_json(root / path)
        for field in _strings(entry["fields"]):
            node: Any = value
            for key in field.split("."):
                node = node.get(key) if isinstance(node, dict) else None
            if node is None or field.rsplit(".", 1)[-1] not in guardrails:
                errors.append(f"{label}: {field} is not a retired guardrail it carries")
    return errors


def _executable_errors(registry: dict[str, Any], root: Path) -> list[str]:
    """Cross-checks between the registry, the execution candidates and the contracts."""
    errors: list[str] = []
    judges = registry.get("judges") or {}
    exclusions = [entry for entry in registry.get("excluded") or [] if isinstance(entry, dict)]
    by_adapter: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for judge_id, judge in judges.items():
        legacy = judge.get("legacyIdentifiers") if isinstance(judge.get("legacyIdentifiers"), dict) else {}
        for adapter_id in _strings(legacy.get("adapterIDs")):
            by_adapter.setdefault(adapter_id, []).append((judge_id, judge))
    candidates = _read_json(root / CANDIDATES)
    evaluator = _read_json(root / EVALUATOR_CONTRACT)
    experiment = _read_json(root / EXPERIMENT_CONTRACT)
    executable = candidates.get("candidates") if isinstance(candidates.get("candidates"), dict) else {}
    for adapter_id in _strings(candidates.get("candidateOrder")):
        matches = by_adapter.get(adapter_id, [])
        candidate = executable.get(adapter_id) if isinstance(executable.get(adapter_id), dict) else {}
        label = f"candidate {adapter_id}"
        if len(matches) != 1:
            errors.append(f"{label}: needs exactly one registry judge")
            continue
        judge_id, judge = matches[0]
        pins = judge.get("pins") or {}
        if _is_blocked(judge):
            errors.append(f"{label}: registry judge {judge_id} is {judge.get('status')}")
        if (judge.get("license") or {}).get("tier") not in ("A", "B"):
            errors.append(f"{label}: registry judge {judge_id} is not tier A or B")
        if candidate.get("commercialUseCompatible") is not True:
            errors.append(f"{label}: an execution candidate must be commercially compatible")
        if candidate.get("sourceRevision") != pins.get("revision") or candidate.get(
            "weightsSHA256"
        ) not in (pins.get("files") or {}).values():
            errors.append(f"{label}: revision or weights digest differs from registry judge {judge_id}")
        errors.extend(_exclusion_errors(
            label, [str(candidate.get("modelID", ""))],
            list(candidate.get("runtimeDependencies") or {}), exclusions,
        ))
    retired_candidates = candidates.get("retiredCandidates")
    if not isinstance(retired_candidates, dict):
        errors.append("candidates file must keep its retiredCandidates provenance")
        retired_candidates = {}
    for adapter_id, candidate in retired_candidates.items():
        matches = by_adapter.get(adapter_id, [])
        if len(matches) != 1 or matches[0][1].get("status") != "retired":
            errors.append(f"retired candidate {adapter_id}: needs one retired registry judge")
            continue
        # A judge retired for its terms (tier C) records the corrected license;
        # one retired as a measurand (AQ-05) keeps its permissive one.
        tier = (matches[0][1].get("license") or {}).get("tier")
        if not isinstance(candidate, dict) or candidate.get("commercialUseCompatible") is not (tier != "C"):
            errors.append(f"retired candidate {adapter_id}: commercialUseCompatible must match its registry tier {tier}")
    cascade = evaluator.get("cascade") if isinstance(evaluator.get("cascade"), dict) else {}
    live_layers = {layer for values in cascade.values() for layer in _strings(values)}
    compact = evaluator.get("compactAdapters") if isinstance(evaluator.get("compactAdapters"), dict) else {}
    live_adapters = set(_strings(candidates.get("candidateOrder"))) | set(_strings(compact.get("candidateOrder")))
    guardrails = experiment.get("promotionGuardrails") if isinstance(experiment.get("promotionGuardrails"), dict) else {}
    for judge_id, judge in judges.items():
        if not _is_blocked(judge):
            continue
        legacy = judge.get("legacyIdentifiers") if isinstance(judge.get("legacyIdentifiers"), dict) else {}
        for adapter_id in set(_strings(legacy.get("adapterIDs"))) & live_adapters:
            errors.append(f"judge {judge_id}: adapter {adapter_id} is still a live candidate")
        for layer in set(_strings(legacy.get("cascadeLayers"))) & live_layers:
            errors.append(f"judge {judge_id}: cascade layer {layer} is still requested")
        for guardrail in set(_strings(legacy.get("guardrails"))) & set(guardrails):
            errors.append(f"judge {judge_id}: guardrail {guardrail} still gates promotion")
        errors.extend(_frozen_contract_errors(judge_id, judge, root))
    errors.extend(_adoption_errors(registry, root, candidates, evaluator, experiment))
    return errors


def canonical_profiles(registry: dict[str, Any], root: Path = REPO) -> list[dict[str, Any]]:
    """The hardware profiles the registry's adoption selector names (exactly one when valid)."""
    adoption = registry.get("adoption") if isinstance(registry.get("adoption"), dict) else {}
    selector = adoption.get("profileSelector") if isinstance(adoption.get("profileSelector"), dict) else {}
    profiles = _read_json(root / str(adoption.get("hardwareProfiles") or HARDWARE_PROFILES)).get("profiles")
    if not selector:
        return []
    return [
        profile for profile in profiles or [] if isinstance(profile, dict)
        and all(profile.get(key) == value for key, value in selector.items())
    ]


def _adoption_errors(registry: dict[str, Any], root: Path, candidates: dict[str, Any],
                     evaluator: dict[str, Any], experiment: dict[str, Any]) -> list[str]:
    errors = []
    if len(canonical_profiles(registry, root)) != 1:
        errors.append("adoption must select exactly one canonical hardware profile")
    compact = evaluator.get("compactAdapters") if isinstance(evaluator.get("compactAdapters"), dict) else {}
    external = experiment.get("externalModelPolicy") if isinstance(experiment.get("externalModelPolicy"), dict) else {}
    for label, requirements in (
        (CANDIDATES, candidates.get("adoptionRequirements")),
        (EVALUATOR_CONTRACT, compact.get("requiredBeforeAdoption")),
        (EXPERIMENT_CONTRACT, external.get("required")),
    ):
        values = _strings(requirements)
        if ADOPTION_REQUIREMENT not in values:
            errors.append(f"{label}: adoption must require {ADOPTION_REQUIREMENT}")
        if any(marker in value for value in values for marker in STALE_ADOPTION_MARKERS):
            errors.append(f"{label}: adoption still names the 8 GB host")
    return errors


def validate_repository(root: Path = REPO, registry: dict[str, Any] | None = None) -> list[str]:
    registry = registry if registry is not None else load_registry(root / "config/audio-qc-judges.json")
    errors = validate_registry(registry, root=root)
    if errors:
        return errors
    return _executable_errors(registry, root)


def require_executable(judge_id: str, judge: dict[str, Any]) -> dict[str, Any]:
    """Refuse a judge that may not run: retired, quarantined, tier C or unknown."""
    status = judge.get("status")
    tier = (judge.get("license") or {}).get("tier")
    if status in BLOCKED_STATUSES or status not in STATUSES:
        raise JudgeRegistryError(f"audio QC judge {judge_id} is {status}; it may not run")
    if tier not in ("A", "B"):
        raise JudgeRegistryError(f"audio QC judge {judge_id} is license tier {tier}; it may not run")
    return judge


def require_loadable(judge_id: str, repository: str, revision: str, *, packages: Iterable[str] = (),
                     registry: dict[str, Any] | None = None) -> dict[str, Any]:
    """The load-time gate every model loader calls with its registry judge.

    Refuses an unregistered judge, a judge that may not run (retired,
    quarantined, tier C or unknown), an excluded model or runtime package for
    what is actually being loaded, and a repository or revision other than the
    judge's pin. A `:variant` suffix on the repository names a file set inside
    it (the SenseVoice Q8 GGUF). Returns the registry judge.
    """
    registry = registry if registry is not None else load_registry()
    judge = (registry.get("judges") or {}).get(judge_id)
    if not isinstance(judge, dict):
        raise JudgeRegistryError(f"audio QC judge {judge_id} is not registered; it may not load")
    require_executable(judge_id, judge)
    exclusions = [entry for entry in registry.get("excluded") or [] if isinstance(entry, dict)]
    refused = _exclusion_errors(f"audio QC judge {judge_id}", [str(repository)], list(packages), exclusions)
    if refused:
        raise JudgeRegistryError(refused[0] + "; it may not load")
    pins = judge.get("pins") or {}
    if str(repository).split(":", 1)[0] != pins.get("repository") or revision != pins.get("revision"):
        raise JudgeRegistryError(
            f"audio QC judge {judge_id} is pinned to {pins.get('repository')}@{str(pins.get('revision'))[:12]}; "
            "it may not load another model or revision"
        )
    return judge


@functools.lru_cache(maxsize=1)
def _host() -> tuple[str, str, str | None]:
    model = None
    if platform.system() == "Darwin":
        try:
            result = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "hw.model"], capture_output=True, text=True,
                timeout=10, check=False,
            )
            model = result.stdout.strip() or None
        except (OSError, subprocess.SubprocessError):
            model = None
    return platform.system(), platform.machine(), model


def host_profile() -> dict[str, str | None]:
    """The host a judge runs on: its `hostProfile` output identity component.

    A neural judge's output keys on the host until its cross-host determinism
    is measured (AQ-06). The hardware model identifier names no person.
    """
    system, machine, model = _host()
    return {"system": system, "machine": machine, "modelIdentifier": model}


def _git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_hub_snapshot(snapshot: Path, pinned_files: dict[str, Any], *, revision: str) -> dict[str, str]:
    """Verify a local Hugging Face snapshot against its registry pins; return file SHA-256s.

    The directory must be the pinned revision's snapshot and hold exactly the
    pinned files: an unpinned or missing file refuses. Each file's bytes (the
    blob a cache symlink resolves to, or a plain copy) must match its pin, the
    LFS SHA-256 of a large file or the git blob ID of any other, and its size
    when recorded. The pins come from the Hub's tree metadata at the revision,
    so a fabricated snapshot cannot pass by naming its own blobs.
    """
    if not snapshot.is_dir():
        raise JudgeRegistryError("the pinned snapshot is not in the local cache")
    if snapshot.name != revision:
        raise JudgeRegistryError("the snapshot directory is not the pinned revision")
    if not pinned_files:
        raise JudgeRegistryError("the judge pins no snapshot files; it cannot be verified")
    present = {
        path.relative_to(snapshot).as_posix(): path
        for path in sorted(snapshot.rglob("*")) if not path.is_dir()
    }
    unpinned = sorted(set(present) - set(pinned_files))
    if unpinned:
        raise JudgeRegistryError(f"the snapshot holds unpinned files: {', '.join(unpinned)}")
    missing = sorted(set(pinned_files) - set(present))
    if missing:
        raise JudgeRegistryError(f"the snapshot lacks pinned files: {', '.join(missing)}")
    digests: dict[str, str] = {}
    for relative, path in present.items():
        pin = pinned_files[relative]
        if not _snapshot_pin(pin):
            raise JudgeRegistryError(f"snapshot file {relative} has no valid registry pin")
        blob = path.resolve()
        if not blob.is_file():
            raise JudgeRegistryError(f"snapshot file {relative} has no blob")
        if "size" in pin and blob.stat().st_size != pin["size"]:
            raise JudgeRegistryError(f"snapshot file {relative} differs from its registry pin")
        sha256 = _sha256(blob)
        verified = (sha256 == pin["lfsSHA256"]) if "lfsSHA256" in pin else (
            _git_blob_sha1(blob) == pin["gitBlobID"]
        )
        if not verified:
            raise JudgeRegistryError(f"snapshot file {relative} differs from its registry pin")
        digests[relative] = sha256
    return digests


def verify_judge_snapshot(judge_id: str, snapshot: Path, *, repository: str, revision: str,
                          packages: Iterable[str] = (),
                          registry: dict[str, Any] | None = None) -> dict[str, str]:
    """The load-time gate for a snapshot-loaded judge: loadable, then every file verified."""
    judge = require_loadable(judge_id, repository, revision, packages=packages, registry=registry)
    pins = judge.get("pins") or {}
    if pins.get("digestStatus") != SNAPSHOT_STATUS:
        raise JudgeRegistryError(f"audio QC judge {judge_id} is not pinned by snapshot")
    return verify_hub_snapshot(snapshot, pins.get("files") or {}, revision=revision)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    validate = commands.add_parser("validate", help="check the registry against the repository")
    validate.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    args = parser.parse_args()
    try:
        registry = load_registry(args.registry)
        errors = validate_repository(REPO, registry)
    except JudgeRegistryError as error:
        errors = [str(error)]
    if errors:
        print("Audio QC judge registry: FAIL", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    judges = registry["judges"]
    print(json.dumps({
        "status": "PASS",
        "judges": len(judges),
        "retired": sorted(judge_id for judge_id, judge in judges.items() if judge.get("status") == "retired"),
        "excluded": len(registry["excluded"]),
        "useRestrictions": len(registry["useRestrictions"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
