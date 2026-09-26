#!/usr/bin/env python3
"""The audio QC judge registry: license tiers, pins, independence and status.

`config/audio-qc-judges.json` describes every judge the audio QC and speech
analysis harness runs or has run (audit 2026-09-25, AQ-01, phase M0). This
module validates it and is the execution gate for registered judges:

- No judge outside `retired` carries tier C or an unknown tier; tier C is
  retired, never quarantined or advisory (decision 1a).
- A tier-B judge records the decision-2a acceptance: internal evaluation that
  never ships.
- A judge from the generator's lab never votes (decision 3a).
- Every neural judge that can still run is pinned by file digest or by a
  content-addressed local snapshot, verified before each load.
- The exclusion list (audit section 4.9) is refused by model, package and
  import: no registered judge, no execution candidate and no script under
  `scripts/` may use an excluded entry.
- Retired judges stay out of every QC path: their adapters, cascade layers
  and guardrails appear in no live contract, their source files are deleted
  and no script imports their modules.
- Adoption names the canonical host: two clean runs on the one canonical
  macOS profile of `benchmarks/hardware-profiles.json`.

Commands:
  validate   check the registry against the repository (the contract gate)
"""

from __future__ import annotations

import argparse
import ast
from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import re
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
KINDS = ("neural", "dsp", "platform")
TIERS = ("A", "B", "C")
TIER_B_SCOPE = "internal-never-shipped-evaluation"
ADOPTION_REQUIREMENT = "two-clean-canonical-host-runs"
# The 8 GB-era adoption tokens (AQ-F40): no live contract may require them.
STALE_ADOPTION_MARKERS = ("eight-gib", "eight-gigabyte")
# The supervisor's source is envelope identity (AQ-F47); an output identity
# that names it would let a supervisor fix invalidate caches and calibrations.
ENVELOPE_ONLY_COMPONENTS = frozenset({"resourceSupervisorSHA256", "probeAlgorithmVersion", "supervisorOptions"})
DIGEST_STATUS_BY_KIND = {
    "neural": ("pinned", "content-addressed-snapshot"),
    "dsp": ("no-learned-weights",),
    "platform": ("platform-managed",),
}
JUDGE_ID = re.compile(r"^[a-z0-9]+(?:[.-][a-z0-9]+)*@[0-9]+$")
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


def _module_matches(name: str, patterns: Iterable[str]) -> str | None:
    for pattern in patterns:
        if fnmatchcase(name, pattern) or name.startswith(pattern + "."):
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


def validate_registry(registry: dict[str, Any], *, root: Path = REPO) -> list[str]:
    """Errors in the registry itself and in the files it names; empty when valid."""
    errors: list[str] = []
    if registry.get("schemaVersion") != SCHEMA_VERSION or registry.get("kind") != KIND:
        return [f"registry must be {KIND} schema {SCHEMA_VERSION}"]
    decisions = registry.get("decisions")
    if not isinstance(decisions, dict) or any(
        not isinstance(decisions.get(key), dict) or decisions[key].get("option") != "a"
        for key in ("1", "2", "3")
    ):
        errors.append("decisions 1, 2 and 3 must record option a")
    adoption = registry.get("adoption")
    if not isinstance(adoption, dict) or adoption.get("requirement") != ADOPTION_REQUIREMENT:
        errors.append(f"adoption must require {ADOPTION_REQUIREMENT}")
    exclusions = registry.get("excluded")
    if not isinstance(exclusions, list) or not exclusions:
        errors.append("the exclusion list is missing")
        exclusions = []
    seen_exclusions: set[str] = set()
    for entry in exclusions:
        identity = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(identity, str) or not identity or identity in seen_exclusions:
            errors.append("every exclusion needs a unique id")
            continue
        seen_exclusions.add(identity)
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            errors.append(f"exclusion {identity} needs a reason")
        if entry.get("tier") not in (*TIERS, None):
            errors.append(f"exclusion {identity} has an invalid tier")
        for field in ("models", "packages", "pythonModules"):
            if not isinstance(entry.get(field), list) or len(_strings(entry[field])) != len(entry[field]):
                errors.append(f"exclusion {identity} needs a {field} list of strings")
    judges = registry.get("judges")
    if not isinstance(judges, dict) or not judges:
        return errors + ["the registry lists no judges"]
    for judge_id, judge in judges.items():
        errors.extend(_judge_errors(judge_id, judge, exclusions, root))
    return errors


def _judge_errors(judge_id: str, judge: Any, exclusions: list[dict[str, Any]], root: Path) -> list[str]:
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
    errors.extend(_pin_errors(label, judge, kind, blocked))
    identity = judge.get("identity") if isinstance(judge.get("identity"), dict) else {}
    output, envelope = _strings(identity.get("output")), _strings(identity.get("envelope"))
    if not output or not isinstance(identity.get("envelope"), list):
        errors.append(f"{label}: identity needs output and envelope component lists")
    if set(output) & set(envelope):
        errors.append(f"{label}: a component is either output or envelope identity, never both")
    if set(output) & ENVELOPE_ONLY_COMPONENTS:
        errors.append(f"{label}: supervisor provenance is envelope identity, never output identity")
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
    else:
        errors.extend(_exclusion_errors(label, _judge_models(judge), _judge_packages(judge), exclusions))
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
        if not isinstance(files, dict) or any(not SHA256.match(str(value)) for value in files.values()):
            errors.append(f"{label}: file pins must be SHA-256 digests")
        elif status == "pinned" and not files:
            errors.append(f"{label}: a pinned judge lists its file digests")
    if blocked:
        return errors
    if status not in DIGEST_STATUS_BY_KIND.get(kind, ()):
        errors.append(f"{label}: a runnable {kind} judge cannot load with digest status {status!r}")
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
        if not isinstance(candidate, dict) or candidate.get("commercialUseCompatible") is not False:
            errors.append(f"retired candidate {adapter_id}: must record commercialUseCompatible false")
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
    errors.extend(_adoption_errors(registry, root, candidates, evaluator, experiment))
    errors.extend(excluded_imports(root / "scripts", registry))
    return errors


def _adoption_errors(registry: dict[str, Any], root: Path, candidates: dict[str, Any],
                     evaluator: dict[str, Any], experiment: dict[str, Any]) -> list[str]:
    errors = []
    profiles = _read_json(root / HARDWARE_PROFILES).get("profiles")
    selector = (registry.get("adoption") or {}).get("profileSelector") or {}
    canonical = [
        profile for profile in profiles or [] if isinstance(profile, dict)
        and all(profile.get(key) == value for key, value in selector.items())
    ]
    if not selector or len(canonical) != 1:
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


def imported_modules(path: Path) -> set[str]:
    """Every absolute module a Python file imports, with `from a import b` also as `a.b`."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def excluded_imports(scripts_root: Path, registry: dict[str, Any]) -> list[str]:
    """Scripts importing an excluded package or a retired judge's module."""
    patterns = {
        pattern: f"exclusion {entry.get('id')}"
        for entry in registry.get("excluded") or [] if isinstance(entry, dict)
        for pattern in _strings(entry.get("pythonModules"))
    }
    for judge_id, judge in (registry.get("judges") or {}).items():
        if isinstance(judge, dict) and _is_blocked(judge):
            legacy = judge.get("legacyIdentifiers") if isinstance(judge.get("legacyIdentifiers"), dict) else {}
            patterns.update({pattern: f"judge {judge_id}" for pattern in _strings(legacy.get("pythonModules"))})
    errors = []
    for path in sorted(scripts_root.rglob("*.py")):
        for name in sorted(imported_modules(path)):
            if (pattern := _module_matches(name, patterns)) is not None:
                errors.append(f"{path.relative_to(scripts_root.parent).as_posix()}: imports {name} "
                              f"({patterns[pattern]})")
    return errors


def validate_repository(root: Path = REPO, registry: dict[str, Any] | None = None) -> list[str]:
    registry = registry if registry is not None else load_registry(root / "config/audio-qc-judges.json")
    errors = validate_registry(registry, root=root)
    if errors:
        return errors
    return _executable_errors(registry, root)


def judge_for_adapter(adapter_id: str, registry: dict[str, Any] | None = None) -> tuple[str, dict[str, Any]]:
    registry = registry if registry is not None else load_registry()
    matches = [
        (judge_id, judge) for judge_id, judge in (registry.get("judges") or {}).items()
        if adapter_id in _strings((judge.get("legacyIdentifiers") or {}).get("adapterIDs"))
    ]
    if len(matches) != 1:
        raise JudgeRegistryError(f"{adapter_id} is not registered as exactly one audio QC judge")
    return matches[0]


def require_executable(judge_id: str, judge: dict[str, Any]) -> dict[str, Any]:
    """Refuse a judge that may not run: retired, quarantined, tier C or unknown."""
    status = judge.get("status")
    tier = (judge.get("license") or {}).get("tier")
    if status in BLOCKED_STATUSES or status not in STATUSES:
        raise JudgeRegistryError(f"audio QC judge {judge_id} is {status}; it may not run")
    if tier not in ("A", "B"):
        raise JudgeRegistryError(f"audio QC judge {judge_id} is license tier {tier}; it may not run")
    return judge


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


def verify_hub_snapshot(snapshot: Path, pinned_files: dict[str, str] | None = None) -> dict[str, str]:
    """Verify a local Hugging Face snapshot before a judge loads it; return file SHA-256s.

    A snapshot file links to a blob named by its content address: the SHA-256
    of the bytes for a large-file (LFS) blob, the git blob SHA-1 otherwise.
    Every file must match its address, and every per-file pin the registry
    records must match exactly. A copied (unlinked) file cannot be checked
    against the Hub's address, so it needs a pin.
    """
    if not snapshot.is_dir():
        raise JudgeRegistryError("the pinned snapshot is not in the local cache")
    pins = dict(pinned_files or {})
    digests: dict[str, str] = {}
    for path in sorted(snapshot.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(snapshot).as_posix()
        blob = path.resolve()
        if not blob.is_file():
            raise JudgeRegistryError(f"snapshot file {relative} has no blob")
        sha256 = _sha256(blob)
        address = blob.name if path.is_symlink() else None
        if address is not None and SHA256.match(address):
            verified = sha256 == address
        elif address is not None and GIT_REVISION.match(address):
            verified = _git_blob_sha1(blob) == address
        else:
            verified = relative in pins
        if not verified:
            raise JudgeRegistryError(f"snapshot file {relative} does not match its content address")
        digests[relative] = sha256
    if not digests:
        raise JudgeRegistryError("the pinned snapshot is empty")
    for relative, expected in pins.items():
        if digests.get(relative) != expected:
            raise JudgeRegistryError(f"snapshot file {relative} differs from its registry pin")
    return digests


def verify_judge_snapshot(judge_id: str, snapshot: Path, *, repository: str, revision: str,
                          registry: dict[str, Any] | None = None) -> dict[str, str]:
    """The registry's gate for a snapshot-loaded judge: runnable, same pins, verified bytes."""
    registry = registry if registry is not None else load_registry()
    judge = (registry.get("judges") or {}).get(judge_id)
    if not isinstance(judge, dict):
        raise JudgeRegistryError(f"audio QC judge {judge_id} is not registered")
    require_executable(judge_id, judge)
    pins = judge.get("pins") or {}
    if pins.get("repository") != repository or pins.get("revision") != revision:
        raise JudgeRegistryError(f"audio QC judge {judge_id} is pinned to a different snapshot")
    return verify_hub_snapshot(snapshot, pins.get("files") or {})


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
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
