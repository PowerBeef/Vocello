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
    if policy.get("schemaVersion") != 1:
        raise AvailabilityError("model-host policy schemaVersion must be 1")
    if policy.get("probeSelection") != "largest-file-per-model":
        raise AvailabilityError("unsupported probeSelection")
    if policy.get("rangeBytes") != "bytes=0-0":
        raise AvailabilityError("rangeBytes must remain a one-byte probe")
    timeout = policy.get("timeoutSeconds")
    if not isinstance(timeout, int) or not 1 <= timeout <= 60:
        raise AvailabilityError("timeoutSeconds must be between 1 and 60")
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
    opener: Callable[[urllib.request.Request, int], Any] = _default_open,
) -> dict[str, Any]:
    policy = _load_object(root / "config/model-host-availability-policy.json")
    probes = validate(root)
    if not re.fullmatch(r"[a-z0-9-]+", region):
        raise AvailabilityError("region label must contain only lowercase letters, digits, and hyphens")
    rows: list[dict[str, Any]] = []
    for specification in probes:
        request = urllib.request.Request(
            specification["url"],
            headers={"Range": policy["rangeBytes"], "User-Agent": "Vocello-Availability-Probe/1"},
            method="GET",
        )
        started = time.monotonic()
        try:
            with opener(request, policy["timeoutSeconds"]) as response:
                status = int(getattr(response, "status", response.getcode()))
                final_url = response.geturl()
                final_host = urllib.parse.urlparse(final_url).hostname or ""
                body = response.read(2)
                observed_total = _content_range_total(response.headers.get("Content-Range"))
        except (OSError, urllib.error.URLError) as error:
            raise AvailabilityError(f"{specification['modelID']}: anonymous range probe failed") from error
        if status != 206:
            raise AvailabilityError(f"{specification['modelID']}: host did not honor the byte range")
        if len(body) != 1:
            raise AvailabilityError(f"{specification['modelID']}: range response was not exactly one byte")
        if not _host_allowed(final_host, specification["allowedRedirectHostSuffixes"]):
            raise AvailabilityError(f"{specification['modelID']}: redirect escaped the allowlist")
        if observed_total != specification["expectedBytes"]:
            raise AvailabilityError(f"{specification['modelID']}: remote byte total differs from the catalog")
        rows.append(
            {
                key: value for key, value in specification.items()
                if key not in {"url", "allowedRedirectHostSuffixes"}
            }
            | {
                "status": "PASS",
                "rangeStatus": status,
                "observedBytes": observed_total,
                "redirectHostClass": "allowlisted",
                "latencyMilliseconds": round((time.monotonic() - started) * 1000),
            }
        )
    catalog_bytes = (root / policy["catalog"]).read_bytes()
    return {
        "schemaVersion": 1,
        "status": "PASS",
        "checkedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "region": region,
        "catalogSHA256": hashlib.sha256(catalog_bytes).hexdigest(),
        "probeSelection": policy["probeSelection"],
        "anonymousAccess": True,
        "requestedBytesPerArtifact": 1,
        "mutationPerformed": False,
        "rows": rows,
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
    parser.add_argument("command", choices=("validate", "probe"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--region")
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "validate":
            rows = validate(arguments.root.resolve())
            print(f"Model host availability contract: PASS ({len(rows)} pinned artifacts)")
            return 0
        if not arguments.region or not arguments.output:
            raise AvailabilityError("probe requires --region and --output")
        result = probe(root=arguments.root.resolve(), region=arguments.region)
        _atomic_json(arguments.output.resolve(), result)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (OSError, AvailabilityError) as error:
        print(f"Model host availability: FAIL\n{error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
