"""The extracted speaker corpora that the take generator's clone cell reads.

`config/audio-qc-corpora.json` pins the speaker corpora the clone cell draws its
reference clips from. Each source's extraction lives under the corpora cache
(`build/cache/audio-qc-corpora`, entry `audio-qc-corpora-cache` of
`config/build-output-policy.json`) as `<source>/<revision>/extracted/` (or
`<source>/zenodo-<record>/extracted/`), with one `manifest.json` that lists
every clip (WAV path, digest, speaker, gender, language and transcript).

This module only reads those extractions: it finds a source's directory and
checks that the manifest is intact and was extracted from the source's current
pins. The extractor that wrote them (`audio-qc-corpora-extract-v1`) retired with
QC v1 on 2026-10-01; the identity below is that extractor's, byte for byte, so
the existing extractions stay usable. See docs/reference/qc.md.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from lib import jsonio

REPO = Path(__file__).resolve().parents[2]
REGISTRY_PATH = REPO / "config" / "audio-qc-corpora.json"
# Points the corpora cache elsewhere (tests and alternate volumes).
CACHE_ENV = "QVOICE_AUDIO_QC_CORPORA_CACHE"

REGISTRY_KIND = "audio-qc-corpora"
SCHEMA_VERSION = 1
MANIFEST_KIND = "audio-qc-corpus"
EXTRACTOR = "audio-qc-corpora-extract-v1"
MANIFEST_NAME = "manifest.json"
EXTRACTED_DIRECTORY = "extracted"
HOSTS: dict[str, str] = {"huggingface.co": "hub", "media.githubusercontent.com": "github-lfs",
                         "zenodo.org": "zenodo"}


class CorporaError(RuntimeError):
    """The corpora registry cannot be read."""


def load_registry(path: Path = REGISTRY_PATH) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise CorporaError(f"{Path(path).name} cannot be read: {type(error).__name__}") from None
    if not isinstance(value, dict) or value.get("kind") != REGISTRY_KIND or not isinstance(value.get("sources"), dict):
        raise CorporaError(f"{Path(path).name} is not an {REGISTRY_KIND} registry")
    return value


def host_kind(entry: Mapping[str, Any]) -> str:
    return HOSTS.get(str(entry.get("host")), "")


def cache_root() -> Path:
    override = os.environ.get(CACHE_ENV)
    return Path(override) if override else REPO / "build" / "cache" / "audio-qc-corpora"


def source_directory(registry: Mapping[str, Any], source: str, root: Path | None = None) -> Path:
    """Where a source's files and extraction live: `<source>/<revision>` or `<source>/zenodo-<record>`."""
    base = root or cache_root()
    entry = registry["sources"][source]
    if host_kind(entry) == "zenodo":
        return base / source / f"zenodo-{entry['record']}"
    return base / source / entry["revision"]


def extraction_identity(registry: Mapping[str, Any], source: str) -> str:
    """What an extraction is bound to: the pins, the extraction spec (its estimate aside) and the languages."""
    entry = registry["sources"][source]
    spec = {key: value for key, value in entry["extract"].items() if key not in ("estimatedBytes", "estimateBasis")}
    return jsonio.sha256_json({"extractor": EXTRACTOR, "source": source, "languages": entry["languages"],
                               "extract": spec, "files": entry.get("files") or [],
                               "pinFile": (entry.get("pinFile") or {}).get("sha256")}, ascii=False)


def self_digest(value: Mapping[str, Any], field: str) -> str:
    """The digest of a record without its own digest field."""
    unsigned = dict(value)
    unsigned.pop(field, None)
    return jsonio.sha256_json(unsigned, ascii=False)


def manifest_issues(manifest: Any, identity: str | None = None) -> list[str]:
    """Why an extraction manifest is unusable: not one, edited, or extracted from other pins."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != SCHEMA_VERSION \
            or manifest.get("kind") != MANIFEST_KIND or manifest.get("extractor") != EXTRACTOR:
        return [f"the manifest is not an {MANIFEST_KIND} manifest of {EXTRACTOR}"]
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return ["the manifest digest does not match its content"]
    if identity is not None and manifest.get("extractionSHA256") != identity:
        return ["the manifest was extracted from other pins or another extraction spec"]
    if not isinstance(manifest.get("clips"), list):
        return ["the manifest lists no clips"]
    return []
