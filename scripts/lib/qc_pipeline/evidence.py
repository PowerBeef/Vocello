"""The take-evidence schema and the private bundle (audit section 3.6).

A take-evidence record (`vocello.audioqc.take-evidence/1`) holds digests,
measurements and verdicts only: no transcript, reference text, path or audio.
`validate_take_evidence` enforces that shape and walks every key and string,
so a record that validates is safe to publish under a future evidence contract
(section 7.2); none is committed by this module.

Everything private stays in the **private bundle**, an untracked directory
(`build/artifacts/macos/audio-qc/<run>/` by default, under the owned build
root): `bundle.json` (the run's manifest digest, registries, admission policy,
cache counters, every worker launch with its resource envelope, and one entry
per take with its evidence and private file digests and whether it failed),
`evidence/NNNN.json` (the records) and `private/NNNN.json` (the take's audio
path, reference text and each judge's transcript). A failing take is data like
any other: its record and private file sit in the bundle, which Git never
tracks, and the bundle names it in `failingTakes`. `validate_private_bundle`
re-hashes every file, re-validates every record and refuses a bundle inside the
repository outside the build root.
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from typing import Any, Iterable, Mapping

from lib.jsonio import sha256_json
from lib.qc_qualification.composer import COMPOSITION, DETECTOR_STATUSES, LANE_GATING, TAKE_STATUSES

TAKE_EVIDENCE_SCHEMA = "vocello.audioqc.take-evidence/1"
BUNDLE_SCHEMA = "vocello.audioqc.private-bundle/1"
PRIVATE_SCHEMA = "vocello.audioqc.private-take/1"
MAXIMUM_RECORD_BYTES = 64 * 1024
MEASUREMENT_STATUSES = ("complete", "unavailable", "skipped", "out-of-scope")
CACHE_STATES = ("hit", "miss", "none")
# Keys a tracked record may never carry, at any depth (compared case-folded).
FORBIDDEN_KEYS = frozenset({
    "transcript", "transcripts", "text", "referencetext", "script", "prompt", "path", "audiopath",
    "wavpath", "pcmpath", "instructedwav", "neutralwav", "audiobytes", "rawaudio", "segments", "stdout",
})
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_JUDGE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*@[0-9]+$")
# Identifiers, codes, language names and versions: no whitespace, at most one
# slash, at most 128 characters. A transcript or a path cannot pass.
_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+=-]{0,127}$")


class EvidenceError(ValueError):
    """A record or a bundle is malformed or unsafe."""


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def is_token(value: Any) -> bool:
    return (isinstance(value, str) and _TOKEN.fullmatch(value) is not None and value.count("/") <= 1
            and "//" not in value)


def _scalar_errors(value: Any, trail: str) -> list[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, int):
        return []
    if isinstance(value, float):
        return [] if math.isfinite(value) else [f"{trail} is not finite"]
    if isinstance(value, str):
        return [] if is_token(value) else [f"{trail} is not a safe identifier or code"]
    return [f"{trail} is not a scalar"]


def privacy_errors(value: Any, trail: str = "record") -> list[str]:
    """Forbidden keys and unsafe strings anywhere in a tracked record."""
    errors: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str) or not key:
                errors.append(f"{trail} has a non-string key")
                continue
            if key.lower() in FORBIDDEN_KEYS:
                errors.append(f"{trail}.{key} may not appear in a tracked record")
                continue
            errors.extend(privacy_errors(child, f"{trail}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            errors.extend(privacy_errors(child, f"{trail}[{index}]"))
    else:
        errors.extend(_scalar_errors(value, trail))
    return errors


def _flat_metric_errors(metrics: Any, trail: str) -> list[str]:
    if not isinstance(metrics, Mapping):
        return [f"{trail} must be an object"]
    errors = []
    for key, value in metrics.items():
        if not isinstance(key, str) or not is_token(key):
            errors.append(f"{trail} has an unsafe metric name")
        elif isinstance(value, (Mapping, list, tuple)):
            errors.append(f"{trail}.{key} must be a scalar")
        else:
            errors.extend(_scalar_errors(value, f"{trail}.{key}"))
    return errors


def validate_take_evidence(record: Any) -> list[str]:
    """Errors in one take-evidence record; empty when it is valid and safe."""
    if not isinstance(record, Mapping) or record.get("schema") != TAKE_EVIDENCE_SCHEMA:
        return [f"a take-evidence record declares {TAKE_EVIDENCE_SCHEMA}"]
    errors: list[str] = []
    expected = {"schema", "take", "registries", "stage0", "measurements", "verdicts", "takeVerdict", "legacyVerdicts"}
    if set(record) != expected:
        errors.append(f"a take-evidence record has exactly {sorted(expected)}")
    size = len(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=True).encode("utf-8"))
    if size > MAXIMUM_RECORD_BYTES:
        errors.append(f"a take-evidence record is at most {MAXIMUM_RECORD_BYTES} bytes")
    take = record.get("take")
    if not isinstance(take, Mapping):
        return errors + ["take must be an object"]
    if not is_token(take.get("takeID")):
        errors.append("take.takeID must be a safe identifier")
    for field in ("audioSHA256", "canonicalPCMSHA256"):
        if not is_sha256(take.get(field)):
            errors.append(f"take.{field} must be a SHA-256")
    if take.get("textSHA256") is not None and not is_sha256(take.get("textSHA256")):
        errors.append("take.textSHA256 must be a SHA-256 or null")
    if type(take.get("canonicalSampleRateHz")) is not int or take["canonicalSampleRateHz"] <= 0:
        errors.append("take.canonicalSampleRateHz must be a positive integer")
    duration = take.get("durationSeconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not math.isfinite(duration) or duration <= 0:
        errors.append("take.durationSeconds must be positive and finite")
    if take.get("expectedOutcome") not in ("pass", "fail"):
        errors.append("take.expectedOutcome must be pass or fail")
    if not is_token(take.get("language")):
        errors.append("take.language must be a language name")
    registries = record.get("registries")
    if not isinstance(registries, Mapping) or not is_sha256(registries.get("judges")) or not is_sha256(
        registries.get("policy")
    ) or not (registries.get("detectors") is None or is_sha256(registries.get("detectors"))):
        errors.append("registries names the judge and policy digests (and the detector registry or null)")
    stage0 = record.get("stage0")
    if stage0 is not None and (not isinstance(stage0, Mapping) or set(stage0) != {"audioQC"}):
        errors.append("stage0 is null or carries audioQC only")
    measurements = record.get("measurements")
    if not isinstance(measurements, list):
        errors.append("measurements must be a list")
        measurements = []
    for index, measurement in enumerate(measurements):
        trail = f"measurements[{index}]"
        if not isinstance(measurement, Mapping):
            errors.append(f"{trail} must be an object")
            continue
        if not isinstance(measurement.get("judge"), str) or not _JUDGE_ID.fullmatch(measurement["judge"]):
            errors.append(f"{trail}.judge must be a registry judge id")
        if measurement.get("status") not in MEASUREMENT_STATUSES:
            errors.append(f"{trail}.status must be one of {MEASUREMENT_STATUSES}")
        if measurement.get("outputIdentity") is not None and not is_sha256(measurement.get("outputIdentity")):
            errors.append(f"{trail}.outputIdentity must be a SHA-256 or null")
        for field in ("metricsSHA256", "transcriptSHA256"):
            if measurement.get(field) is not None and not is_sha256(measurement.get(field)):
                errors.append(f"{trail}.{field} must be a SHA-256 or null")
        cache = measurement.get("cache")
        if not isinstance(cache, Mapping) or any(cache.get(layer) not in CACHE_STATES for layer in ("l1", "l2")):
            errors.append(f"{trail}.cache names the L1 and L2 state (hit, miss or none)")
        errors.extend(_flat_metric_errors(measurement.get("metrics"), f"{trail}.metrics"))
    verdicts = record.get("verdicts")
    if not isinstance(verdicts, list):
        errors.append("verdicts must be a list")
        verdicts = []
    for index, verdict in enumerate(verdicts):
        if not isinstance(verdict, Mapping) or verdict.get("status") not in DETECTOR_STATUSES:
            errors.append(f"verdicts[{index}] needs a composer detector status")
        elif not isinstance(verdict.get("detector"), str) or not _JUDGE_ID.fullmatch(verdict["detector"]):
            errors.append(f"verdicts[{index}].detector must be an id@version")
    take_verdict = record.get("takeVerdict")
    if (not isinstance(take_verdict, Mapping) or take_verdict.get("lane") not in LANE_GATING
            or take_verdict.get("status") not in TAKE_STATUSES
            or take_verdict.get("composition") != COMPOSITION):
        errors.append("takeVerdict names its lane, a take status and the composition")
    if not isinstance(record.get("legacyVerdicts"), Mapping):
        errors.append("legacyVerdicts must be an object")
    errors.extend(privacy_errors(record))
    return errors


def evidence_digest(record: Mapping[str, Any]) -> str:
    return sha256_json(record, ascii=False, allow_nan=False)


def failing(record: Mapping[str, Any]) -> bool:
    """A take that failed or missed its expectation: its evidence is data, never tracked audio.

    The composer's `fail`, a replayed verdict of fail, rejected or unqualified,
    or a single witness that contradicted the take's expected outcome. An
    inconclusive or unavailable take is not a failure.
    """
    take_verdict = (record.get("takeVerdict") or {}).get("status")
    legacy = [value for value in (record.get("legacyVerdicts") or {}).values() if isinstance(value, Mapping)]
    if take_verdict == "fail":
        return True
    for value in legacy:
        if value.get("status") in ("fail", "rejected", "unqualified"):
            return True
        if value.get("status") == "one-witness" and value.get("expectationMet") is False:
            return True
    return False


def _write_json(path: Path, value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    return _file_sha256(path)


def _file_sha256(path: Path) -> str:
    import hashlib
    return hashlib.sha256(path.read_bytes()).hexdigest()


def untracked_location_errors(root: Path, repository: Path) -> list[str]:
    resolved = root.resolve()
    repository = repository.resolve()
    try:
        relative = resolved.relative_to(repository)
    except ValueError:
        return []
    if relative.parts[:1] == ("build",):
        return []
    return ["a private bundle lives outside the repository or under its build root, never in tracked paths"]


def write_private_bundle(root: Path, *, header: Mapping[str, Any], takes: Iterable[tuple[Mapping[str, Any], Mapping[str, Any]]],
                         repository: Path) -> dict[str, Any]:
    """Write a new bundle: every record validated first, nothing overwritten."""
    location = untracked_location_errors(root, repository)
    if location:
        raise EvidenceError(location[0])
    if root.exists() and any(root.iterdir()):
        raise EvidenceError("a private bundle is written once into a new directory")
    header_errors = privacy_errors(dict(header), "bundle")
    if header_errors:
        raise EvidenceError("bundle header is unsafe: " + header_errors[0])
    pairs = list(takes)
    for record, private in pairs:
        problems = validate_take_evidence(record)
        if problems:
            raise EvidenceError(f"take {record.get('take', {}).get('takeID')}: " + "; ".join(problems[:3]))
        if not isinstance(private, Mapping) or private.get("schema") != PRIVATE_SCHEMA:
            raise EvidenceError("private take data declares its schema")
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for index, (record, private) in enumerate(pairs, start=1):
        name = f"{index:04d}.json"
        evidence_sha = _write_json(root / "evidence" / name, record)
        private_sha = _write_json(root / "private" / name, private)
        entries.append({
            "takeID": record["take"]["takeID"],
            "evidence": f"evidence/{name}", "evidenceSHA256": evidence_sha,
            "private": f"private/{name}", "privateSHA256": private_sha,
            "takeVerdict": record["takeVerdict"]["status"],
            "failing": failing(record),
        })
    body = {"schema": BUNDLE_SCHEMA, **dict(header), "takes": entries,
            "failingTakes": sum(1 for entry in entries if entry["failing"])}
    bundle = {**body, "bundleDigest": sha256_json(body, ascii=False, allow_nan=False)}
    _write_json(root / "bundle.json", bundle)
    return bundle


def validate_private_bundle(root: Path, *, repository: Path) -> list[str]:
    """Errors in a private bundle; empty when every file matches and every record validates."""
    errors = untracked_location_errors(root, repository)
    path = root / "bundle.json"
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return errors + [f"bundle.json is unreadable ({type(error).__name__})"]
    if not isinstance(bundle, dict) or bundle.get("schema") != BUNDLE_SCHEMA:
        return errors + [f"bundle.json declares {BUNDLE_SCHEMA}"]
    body = {key: value for key, value in bundle.items() if key != "bundleDigest"}
    if bundle.get("bundleDigest") != sha256_json(body, ascii=False, allow_nan=False):
        errors.append("bundle.json digest mismatch")
    header = {key: value for key, value in body.items() if key not in ("takes",)}
    errors.extend(privacy_errors(header, "bundle"))
    entries = bundle.get("takes")
    if not isinstance(entries, list) or not entries:
        return errors + ["the bundle lists no takes"]
    failing_count = 0
    base = root.resolve()
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("a bundle take entry must be an object")
            continue
        label = f"take {entry.get('takeID')}"
        for kind, digest_field in (("evidence", "evidenceSHA256"), ("private", "privateSHA256")):
            relative = entry.get(kind)
            target = (root / str(relative)).resolve()
            if not isinstance(relative, str) or os.path.isabs(relative) or base not in target.parents:
                errors.append(f"{label}: {kind} must be a file inside the bundle")
                continue
            if not target.is_file() or _file_sha256(target) != entry.get(digest_field):
                errors.append(f"{label}: {kind} file is missing or changed")
                continue
            payload = json.loads(target.read_text(encoding="utf-8"))
            if kind == "evidence":
                problems = validate_take_evidence(payload)
                errors.extend(f"{label}: {problem}" for problem in problems)
                if payload.get("take", {}).get("takeID") != entry.get("takeID"):
                    errors.append(f"{label}: evidence belongs to another take")
                if failing(payload) is not entry.get("failing"):
                    errors.append(f"{label}: failing flag differs from its evidence")
                failing_count += bool(entry.get("failing"))
            elif not isinstance(payload, dict) or payload.get("schema") != PRIVATE_SCHEMA or payload.get("takeID") != entry.get("takeID"):
                errors.append(f"{label}: private file belongs to another take")
    if bundle.get("failingTakes") != failing_count:
        errors.append("failingTakes differs from the take entries")
    return errors
