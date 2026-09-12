"""Read and verify the `last-build.json` receipts written by `write_build_provenance`.

A benchmark record's `toolchain.optimization` must describe the binary that
actually ran. The build scripts write a receipt beside every build with the
optimization level and, when the caller names the executable, its SHA-256.
This module refuses a receipt that is incomplete, failed, for another
platform, or whose executable no longer matches the bytes on disk, so a
label can never outlive a rebuild.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
OPTIMIZATIONS = {"O": "-O", "Onone": "-Onone"}


class ProvenanceError(ValueError):
    pass


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_build_provenance(
    path: Path,
    *,
    platform: str,
    root: Path = REPO_ROOT,
    executed_sha256: str | None = None,
    producer_prefix: str | None = None,
) -> dict[str, Any]:
    """Return the verified receipt; `optimization` is normalised to `-O` / `-Onone`."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProvenanceError(f"build provenance is unreadable: {path}") from error
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ProvenanceError(f"build provenance has an unsupported shape: {path}")
    if payload.get("status") != "passed":
        raise ProvenanceError("build provenance does not describe a passed build")
    if payload.get("platform") != platform:
        raise ProvenanceError(
            f"build provenance is for {payload.get('platform')!r}, expected {platform!r}"
        )
    producer = str(payload.get("producer") or "")
    if producer_prefix is not None and not producer.startswith(producer_prefix):
        raise ProvenanceError(f"build provenance producer {producer!r} is not {producer_prefix!r}")
    optimization = OPTIMIZATIONS.get(str(payload.get("optimization")))
    if optimization is None:
        raise ProvenanceError(f"build provenance optimization {payload.get('optimization')!r} is unknown")
    relative = payload.get("executableRelativePath")
    recorded = payload.get("executableSHA256")
    if not isinstance(relative, str) or not isinstance(recorded, str):
        raise ProvenanceError("build provenance does not name its executable and digest")
    executable = (root / relative).resolve()
    if root.resolve() not in executable.parents or not executable.is_file():
        raise ProvenanceError(f"build provenance executable is outside the repository or missing: {relative}")
    current = digest_file(executable)
    if current != recorded:
        raise ProvenanceError(
            f"executable {relative} has changed since the build receipt was written"
        )
    if executed_sha256 is not None and executed_sha256.lower() != recorded.lower():
        raise ProvenanceError(
            "the binary that produced the evidence is not the one the build receipt describes"
        )
    result = dict(payload)
    result["optimization"] = optimization
    result["executable"] = executable
    return result
