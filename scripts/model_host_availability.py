#!/usr/bin/env python3
"""Validate and anonymously probe pinned iOS model-host availability."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parent.parent
POLICY = ROOT / "config/model-host-availability-policy.json"


class AvailabilityError(ValueError):
    pass


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AvailabilityError(f"cannot read {path.name}: {error}") from error
    if not isinstance(value, dict):
        raise AvailabilityError(f"{path.name} must contain a JSON object")
    return value


def _host_allowed(host: str, suffixes: list[str]) -> bool:
    normalized = host.lower().rstrip(".")
    return any(
        normalized == suffix.lower().lstrip(".")
        or normalized.endswith("." + suffix.lower().lstrip("."))
        for suffix in suffixes
    )


def validate(root: Path = ROOT) -> list[dict[str, Any]]:
    policy = _load_object(root / "config/model-host-availability-policy.json")
    if policy.get("schemaVersion") != 2:
        raise AvailabilityError("model-host policy schemaVersion must be 2")
    if policy.get("probeSelection") != "largest-file-per-model":
        raise AvailabilityError("unsupported probeSelection")
    if policy.get("rangeBytes") != "bytes=0-0":
        raise AvailabilityError("rangeBytes must remain a one-byte probe")
    timeout = policy.get("timeoutSeconds")
    if not isinstance(timeout, int) or not 1 <= timeout <= 60:
        raise AvailabilityError("timeoutSeconds must be between 1 and 60")
    chunk_bytes = policy.get("digestReadChunkBytes")
    if not isinstance(chunk_bytes, int) or not 64 * 1024 <= chunk_bytes <= 8 * 1024 * 1024:
        raise AvailabilityError("digestReadChunkBytes must be between 64 KiB and 8 MiB")
    if policy.get("regionalClosureRequiresFullDigest") is not True:
        raise AvailabilityError("regional closure must require full-content digest evidence")
    authorities = policy.get("regionalClosureExecutionAuthorities")
    if not isinstance(authorities, list) or not authorities or any(
        not isinstance(value, str) or not re.fullmatch(r"[a-z0-9-]+", value)
        for value in authorities
    ):
        raise AvailabilityError("regional closure execution authorities are invalid")
    regions = policy.get("representativeRegions")
    if not isinstance(regions, list) or len(regions) < 3 or any(
        not isinstance(region, str) or not re.fullmatch(r"[a-z0-9-]+", region)
        for region in regions
    ):
        raise AvailabilityError("representativeRegions must contain at least three stable labels")
    origins = policy.get("allowedOriginHosts")
    redirects = policy.get("allowedRedirectHostSuffixes")
    if not isinstance(origins, list) or not origins or not isinstance(redirects, list) or not redirects:
        raise AvailabilityError("host allowlists must be non-empty arrays")
    response = policy.get("outageResponse")
    if not isinstance(response, dict) or response.get("automaticHostFallbackAllowed") is not False:
        raise AvailabilityError("outage policy must prohibit automatic host fallback")
    if response.get("automaticArtifactSubstitutionAllowed") is not False:
        raise AvailabilityError("outage policy must prohibit automatic artifact substitution")

    catalog_relative = policy.get("catalog")
    if not isinstance(catalog_relative, str) or Path(catalog_relative).is_absolute():
        raise AvailabilityError("catalog must be a repository-relative path")
    catalog = _load_object(root / catalog_relative)
    models = catalog.get("models")
    if not isinstance(models, list) or not models:
        raise AvailabilityError("iOS model catalog must contain models")
    seen: set[str] = set()
    probes: list[dict[str, Any]] = []
    for model in models:
        if not isinstance(model, dict):
            raise AvailabilityError("model catalog row must be an object")
        model_id = model.get("modelID")
        base_url = model.get("baseURL")
        version = model.get("artifactVersion")
        files = model.get("files")
        if not isinstance(model_id, str) or not model_id or model_id in seen:
            raise AvailabilityError("model IDs must be unique non-empty strings")
        seen.add(model_id)
        if not isinstance(base_url, str):
            raise AvailabilityError(f"{model_id}: missing baseURL")
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "https" or parsed.username or parsed.password or parsed.query:
            raise AvailabilityError(f"{model_id}: baseURL must be credential-free immutable HTTPS")
        if parsed.hostname not in origins:
            raise AvailabilityError(f"{model_id}: origin host is not allowlisted")
        revision = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[0-9a-f]{40}", revision):
            raise AvailabilityError(f"{model_id}: baseURL is not pinned to a 40-character revision")
        if not isinstance(version, str) or not version:
            raise AvailabilityError(f"{model_id}: artifactVersion is missing")
        if not isinstance(files, list) or not files:
            raise AvailabilityError(f"{model_id}: files are missing")
        candidates: list[tuple[int, str, str]] = []
        calculated_total = 0
        for row in files:
            if not isinstance(row, dict):
                raise AvailabilityError(f"{model_id}: malformed file row")
            relative = row.get("relativePath")
            size = row.get("sizeBytes")
            digest = row.get("sha256")
            if (
                not isinstance(relative, str)
                or not relative
                or relative.startswith("/")
                or ".." in Path(relative).parts
                or not isinstance(size, int)
                or size <= 0
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)
            ):
                raise AvailabilityError(f"{model_id}: invalid file identity")
            calculated_total += size
            candidates.append((size, relative, digest))
        if model.get("totalBytes") != calculated_total:
            raise AvailabilityError(f"{model_id}: totalBytes does not match files")
        size, relative, digest = max(candidates)
        url = base_url.rstrip("/") + "/" + urllib.parse.quote(relative, safe="/")
        probes.append(
            {
                "modelID": model_id,
                "artifactVersion": version,
                "artifactRevisionDigest": hashlib.sha256(revision.encode()).hexdigest(),
                "fileIdentityDigest": hashlib.sha256(
                    f"{relative}\0{digest}\0{size}".encode()
                ).hexdigest(),
                "expectedBytes": size,
                "expectedSHA256": digest,
                "url": url,
                "allowedRedirectHostSuffixes": redirects,
            }
        )
    return probes


def _default_open(request: urllib.request.Request, timeout: int) -> Any:
    return urllib.request.urlopen(request, timeout=timeout)


def _content_range_total(value: str | None) -> int | None:
    if not value:
        return None
    match = re.fullmatch(r"bytes\s+0-0/(\d+)", value.strip(), re.IGNORECASE)
    return int(match.group(1)) if match else None


def probe(
    *,
    root: Path = ROOT,
    region: str,
    mode: str = "range",
    execution_authority: str = "operator-local",
    execution_identity_digest: str | None = None,
    opener: Callable[[urllib.request.Request, int], Any] = _default_open,
) -> dict[str, Any]:
    policy = _load_object(root / "config/model-host-availability-policy.json")
    probes = validate(root)
    if region not in policy["representativeRegions"]:
        raise AvailabilityError("region must be declared by the availability policy")
    if mode not in {"range", "full-digest"}:
        raise AvailabilityError("probe mode must be range or full-digest")
    if not re.fullmatch(r"[a-z0-9-]+", execution_authority):
        raise AvailabilityError("execution authority must be a stable token")
    if execution_authority != "operator-local" and not (
        isinstance(execution_identity_digest, str)
        and re.fullmatch(r"[0-9a-f]{64}", execution_identity_digest)
    ):
        raise AvailabilityError("non-local evidence requires an execution identity digest")
    rows: list[dict[str, Any]] = []
    for specification in probes:
        headers = {"User-Agent": "Vocello-Availability-Probe/2"}
        if mode == "range":
            headers["Range"] = policy["rangeBytes"]
        request = urllib.request.Request(specification["url"], headers=headers, method="GET")
        started = time.monotonic()
        try:
            with opener(request, policy["timeoutSeconds"]) as response:
                status = int(getattr(response, "status", response.getcode()))
                final_url = response.geturl()
                final_host = urllib.parse.urlparse(final_url).hostname or ""
                if mode == "range":
                    body = response.read(2)
                    observed_total = _content_range_total(response.headers.get("Content-Range"))
                    observed_digest = None
                else:
                    digest = hashlib.sha256()
                    observed_total = 0
                    while True:
                        chunk = response.read(policy["digestReadChunkBytes"])
                        if not chunk:
                            break
                        digest.update(chunk)
                        observed_total += len(chunk)
                    body = b""
                    observed_digest = digest.hexdigest()
        except (OSError, urllib.error.URLError) as error:
            raise AvailabilityError(f"{specification['modelID']}: anonymous probe failed") from error
        expected_status = 206 if mode == "range" else 200
        if status != expected_status:
            raise AvailabilityError(f"{specification['modelID']}: host returned an invalid probe status")
        if mode == "range" and len(body) != 1:
            raise AvailabilityError(f"{specification['modelID']}: range response was not exactly one byte")
        if not _host_allowed(final_host, specification["allowedRedirectHostSuffixes"]):
            raise AvailabilityError(f"{specification['modelID']}: redirect escaped the allowlist")
        if observed_total != specification["expectedBytes"]:
            raise AvailabilityError(f"{specification['modelID']}: remote byte total differs from the catalog")
        if mode == "full-digest" and observed_digest != specification["expectedSHA256"]:
            raise AvailabilityError(f"{specification['modelID']}: remote content digest differs from the catalog")
        rows.append(
            {
                key: value for key, value in specification.items()
                if key not in {"url", "allowedRedirectHostSuffixes", "expectedSHA256"}
            }
            | {
                "status": "PASS",
                "httpStatus": status,
                "observedBytes": observed_total,
                "redirectHostClass": "allowlisted",
                "contentDigestVerified": mode == "full-digest",
                "retryAfterPresent": response.headers.get("Retry-After") is not None,
                "rateLimitHeadersPresent": any(
                    response.headers.get(name) is not None
                    for name in ("RateLimit", "X-RateLimit-Limit", "X-RateLimit-Remaining")
                ),
                "latencyMilliseconds": round((time.monotonic() - started) * 1000),
            }
        )
    catalog_bytes = (root / policy["catalog"]).read_bytes()
    return {
        "schemaVersion": 2,
        "status": "PASS",
        "checkedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "region": region,
        "probeMode": mode,
        "executionAuthority": execution_authority,
        "executionIdentityDigest": execution_identity_digest,
        "catalogSHA256": hashlib.sha256(catalog_bytes).hexdigest(),
        "probeSelection": policy["probeSelection"],
        "anonymousAccess": True,
        "requestedBytesPerArtifact": 1 if mode == "range" else None,
        "mutationPerformed": False,
        "rows": rows,
    }


def compose(
    paths: list[Path],
    *,
    root: Path = ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    policy = _load_object(root / "config/model-host-availability-policy.json")
    specifications = validate(root)
    expected_models = {row["modelID"] for row in specifications}
    expected_catalog = hashlib.sha256((root / policy["catalog"]).read_bytes()).hexdigest()
    current = now or datetime.now(timezone.utc)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in paths:
        payload = _load_object(path)
        region = payload.get("region")
        if region not in policy["representativeRegions"] or region in seen:
            raise AvailabilityError("closure inputs must contain each declared region exactly once")
        seen.add(region)
        if (
            payload.get("schemaVersion") != 2
            or payload.get("status") != "PASS"
            or payload.get("probeMode") != "full-digest"
            or payload.get("catalogSHA256") != expected_catalog
        ):
            raise AvailabilityError(f"{region}: closure input is not matching full-digest evidence")
        if (
            payload.get("executionAuthority") not in policy["regionalClosureExecutionAuthorities"]
            or not isinstance(payload.get("executionIdentityDigest"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", payload["executionIdentityDigest"])
        ):
            raise AvailabilityError(f"{region}: execution provenance cannot authorize regional closure")
        checked = payload.get("checkedAtUTC")
        try:
            checked_at = datetime.fromisoformat(str(checked).replace("Z", "+00:00"))
        except ValueError as error:
            raise AvailabilityError(f"{region}: invalid checkedAtUTC") from error
        age_hours = (current - checked_at).total_seconds() / 3600
        if age_hours < 0 or age_hours > policy["freshnessHours"]:
            raise AvailabilityError(f"{region}: evidence is outside the freshness window")
        evidence_rows = payload.get("rows")
        if (
            not isinstance(evidence_rows, list)
            or {row.get("modelID") for row in evidence_rows if isinstance(row, dict)} != expected_models
            or not all(
                isinstance(row, dict)
                and row.get("status") == "PASS"
                and row.get("contentDigestVerified") is True
                for row in evidence_rows
            )
        ):
            raise AvailabilityError(f"{region}: model evidence is incomplete")
        rows.append(
            {
                "region": region,
                "checkedAtUTC": checked,
                "evidenceSHA256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "modelCount": len(evidence_rows),
            }
        )
    if seen != set(policy["representativeRegions"]):
        raise AvailabilityError("closure evidence is missing a representative region")
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "checkedAtUTC": current.isoformat().replace("+00:00", "Z"),
        "catalogSHA256": expected_catalog,
        "fullContentDigestVerified": True,
        "regions": sorted(rows, key=lambda row: row["region"]),
    }


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, sort_keys=True).encode() + b"\n"
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "probe", "compose"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--region")
    parser.add_argument("--mode", choices=("range", "full-digest"), default="range")
    parser.add_argument("--execution-authority", default="operator-local")
    parser.add_argument("--execution-identity-digest")
    parser.add_argument("--input", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            rows = validate(arguments.root.resolve())
            print(f"Model host availability contract: PASS ({len(rows)} pinned artifacts)")
            return 0
        if arguments.command == "compose":
            if not arguments.input or not arguments.output:
                raise AvailabilityError("compose requires --input and --output")
            result = compose(
                [path.resolve() for path in arguments.input],
                root=arguments.root.resolve(),
            )
            _atomic_json(arguments.output.resolve(), result)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0
        if not arguments.region or not arguments.output:
            raise AvailabilityError("probe requires --region and --output")
        result = probe(
            root=arguments.root.resolve(),
            region=arguments.region,
            mode=arguments.mode,
            execution_authority=arguments.execution_authority,
            execution_identity_digest=arguments.execution_identity_digest,
        )
        _atomic_json(arguments.output.resolve(), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, AvailabilityError) as error:
        print(f"Model host availability: FAIL\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
