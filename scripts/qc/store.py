"""Paths, the content-addressed result cache, the private store and takes I/O.

Everything QC v2 writes lives in two governed roots of
`config/build-output-policy.json`:

- `build/cache/qc/` (entry `qc-cache`): fetched models, runtime venvs and the
  runner results, re-creatable from the registry;
- `build/private/qc/` (entry `qc-private`): labels, batches, jobs, runs and
  queues. These hold take paths, scripts and the maintainer's judgements, so
  they stay git-ignored under `build/` and never enter Git.

Standard library only: runners import this module from their own venvs.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[2]

LANGUAGES = (
    "chinese", "english", "french", "german", "italian",
    "japanese", "korean", "portuguese", "russian", "spanish",
)
LANGUAGE_CODES = {
    "zh": "chinese", "en": "english", "fr": "french", "de": "german", "it": "italian",
    "ja": "japanese", "ko": "korean", "pt": "portuguese", "ru": "russian", "es": "spanish",
}

RESULT_SCHEMA = "vocello.qc.result/1"
TAKES_SCHEMA = "vocello.qc.takes/1"

# Model kinds whose output depends on the take's text, language or reference
# clip: their results carry a variant key next to the audio digest.
VARIANT_KINDS = frozenset({"align", "llm", "speaker"})


@dataclass(frozen=True)
class Layout:
    """Every QC v2 path, relative to one repository root (tests use a temporary one)."""

    root: Path = REPO_ROOT

    @property
    def config(self) -> Path:
        return self.root / "config/qc"

    @property
    def registry(self) -> Path:
        return self.config / "models.json"

    @property
    def protocol(self) -> Path:
        return self.config / "protocol.json"

    @property
    def runtime_requirements(self) -> Path:
        return self.config / "runtimes"

    @property
    def scripts(self) -> Path:
        return self.root / "scripts"

    @property
    def cache(self) -> Path:
        return self.root / "build/cache/qc"

    @property
    def models(self) -> Path:
        return self.cache / "models"

    @property
    def runtimes(self) -> Path:
        return self.cache / "runtimes"

    @property
    def results(self) -> Path:
        return self.cache / "results"

    @property
    def work(self) -> Path:
        """Derived audio (muted variants for the pause mute test), content-addressed by name."""

        return self.cache / "work"

    @property
    def run_lock(self) -> Path:
        return self.cache / "run.lock"

    @property
    def private(self) -> Path:
        return self.root / "build/private/qc"

    @property
    def labels(self) -> Path:
        return self.private / "labels"

    @property
    def batches(self) -> Path:
        return self.private / "batches"

    @property
    def jobs(self) -> Path:
        return self.private / "jobs"

    @property
    def runs(self) -> Path:
        return self.private / "runs"

    @property
    def queues(self) -> Path:
        return self.private / "queues"

    def model_dir(self, model_id: str) -> Path:
        return self.models / model_id

    def results_dir(self, model_id: str) -> Path:
        return self.results / model_id


def normalize_language(value: str) -> str:
    """Map `fr` or `French` to the repository's full lowercase name."""

    lowered = value.strip().lower()
    if lowered in LANGUAGES:
        return lowered
    if lowered in LANGUAGE_CODES:
        return LANGUAGE_CODES[lowered]
    raise ValueError(f"unknown language: {value!r}")


# --- digests and JSON ------------------------------------------------------

_DIGEST_MEMO: dict[tuple[str, int, int], str] = {}


def sha256_file(path: Path | str) -> str:
    """SHA-256 of the file's bytes, memoized on (path, size, mtime)."""

    path = Path(path)
    stat = path.stat()
    key = (str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    cached = _DIGEST_MEMO.get(key)
    if cached:
        return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    _DIGEST_MEMO[key] = value
    return value


def audio_sha256(path: Path | str) -> str:
    """The content address of a take: the SHA-256 of the WAV file bytes."""

    return sha256_file(path)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json(path: Path | str) -> Any:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def write_json_atomic(path: Path | str, value: Any, *, indent: int | None = 1) -> None:
    """Write JSON beside its destination, then `os.replace` it into place."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=indent, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def append_jsonl(path: Path | str, value: Any) -> None:
    """Append one JSON line and flush it to disk (labels are append-only)."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = canonical_json(value) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path | str) -> list[Any]:
    path = Path(path)
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --- the result cache ------------------------------------------------------

def variant_key(text: str | None, language: str | None, reference_sha256: str | None) -> str:
    """Short hex of (text, language, reference) for results that depend on them.

    Runners and the host must agree on this key: runners read it from the job's
    `variantKey` field, or call this function with the job take's `text`,
    `language` and `referenceSHA256`.
    """

    payload = canonical_json({"language": language, "reference": reference_sha256, "text": text})
    return sha256_text(payload)[:16]


def model_uses_variant(model: dict[str, Any]) -> bool:
    if "variant" in model:
        return bool(model["variant"])
    return model.get("kind") in VARIANT_KINDS


def take_variant(model: dict[str, Any], take: dict[str, Any]) -> str | None:
    if not model_uses_variant(model):
        return None
    return variant_key(take.get("text"), take.get("language"), take.get("referenceSHA256"))


def result_stem(audio_sha: str, variant: str | None) -> str:
    return f"{audio_sha}.{variant}" if variant else audio_sha


def result_path(layout: Layout, model_id: str, audio_sha: str, variant: str | None = None) -> Path:
    return layout.results_dir(model_id) / f"{result_stem(audio_sha, variant)}.json"


def result_npz_path(layout: Layout, model_id: str, audio_sha: str, variant: str | None = None) -> Path:
    return layout.results_dir(model_id) / f"{result_stem(audio_sha, variant)}.npz"


def read_result(
    layout: Layout, model_id: str, audio_sha: str, variant: str | None, runner_sha: str
) -> dict[str, Any] | None:
    """The cached result for this runner identity, or None when absent or stale."""

    path = result_path(layout, model_id, audio_sha, variant)
    try:
        value = read_json(path)
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or value.get("schema") != RESULT_SCHEMA:
        return None
    if value.get("model") != model_id or value.get("runnerSHA256") != runner_sha:
        return None
    if value.get("audioSHA256") != audio_sha or value.get("variantKey") != variant:
        return None
    if "outputs" not in value and "error" not in value:
        return None
    return value


def write_result(
    output_dir: Path | str,
    *,
    model: str,
    runner_sha: str,
    audio_sha: str,
    variant: str | None,
    duration_seconds: float | None,
    outputs: dict[str, Any] | None = None,
    error: str | None = None,
    **extra: Any,
) -> Path:
    """Write one runner result atomically (a helper runners may use)."""

    if (outputs is None) == (error is None):
        raise ValueError("a result carries either outputs or an error")
    record: dict[str, Any] = {
        "schema": RESULT_SCHEMA, "model": model, "runnerSHA256": runner_sha,
        "audioSHA256": audio_sha, "variantKey": variant, "durationSeconds": duration_seconds,
    }
    if error is not None:
        record["error"] = error
        record.update(extra)
    else:
        record["outputs"] = outputs
    path = Path(output_dir) / f"{result_stem(audio_sha, variant)}.json"
    write_json_atomic(path, record, indent=None)
    return path


# --- takes ----------------------------------------------------------------

def take_token(source: str, take_id: str) -> str:
    return sha256_text(source + take_id)[:16]


def _voice_name(take: dict[str, Any]) -> str:
    voice = take.get("voice") or {}
    kind = voice.get("kind")
    if kind == "design":
        return f"design-{voice.get('briefID') or 'unnamed'}"
    if kind == "clone":
        return f"clone-{voice.get('referenceKey') or 'unknown'}"
    return str(voice.get("id") or kind or "unknown")


def _batch_reference_transcripts(run_dir: Path) -> dict[str, str]:
    """Clone transcripts by batch id, from the lane's unit-separated batch index.

    Fields: batch id, mode, variant, variation, seed, speaker, brief, count,
    lines file, reference clip, reference transcript, long-form flag.
    """

    index = run_dir / "batches/index.tsv"
    if not index.is_file():
        return {}
    transcripts: dict[str, str] = {}
    for line in index.read_text(encoding="utf-8").splitlines():
        fields = line.split("\x1f")
        if len(fields) >= 11 and fields[1] == "clone" and fields[10]:
            transcripts[fields[0]] = fields[10]
    return transcripts


def takes_from_qc_takes_run(run_dir: Path | str, *, verify_audio: bool = False) -> dict[str, Any]:
    """Convert a qc-takes run (`takes-manifest.json`, `wav/`, `references/`) to a takes manifest.

    Only generated takes whose WAV exists are listed. `family` is the script id,
    so every take of one script lands on the same side of a split.
    """

    run_dir = Path(run_dir).resolve()
    manifest = read_json(run_dir / "takes-manifest.json")
    source = str(manifest.get("runID") or run_dir.name)
    transcripts = _batch_reference_transcripts(run_dir)
    takes: list[dict[str, Any]] = []
    for take in manifest.get("takes", []):
        if take.get("status", "generated") != "generated" or not take.get("wavPath"):
            continue
        audio = run_dir / take["wavPath"]
        if not audio.is_file():
            continue
        audio_digest = take.get("wavSHA256")
        if verify_audio or not audio_digest:
            audio_digest = audio_sha256(audio)
        reference = take.get("reference") or None
        reference_path = None
        reference_digest = None
        if isinstance(reference, dict) and reference.get("wavPath"):
            reference_path = str(run_dir / reference["wavPath"])
            reference_digest = reference.get("wavSHA256")
        takes.append({
            "takeID": take["takeID"],
            "token": take_token(source, take["takeID"]),
            "audio": str(audio),
            "audioSHA256": audio_digest,
            "language": take.get("language"),
            "text": take.get("text"),
            "mode": take.get("mode"),
            "voice": _voice_name(take),
            "cell": take.get("cell"),
            "reference": reference_path,
            "referenceSHA256": reference_digest,
            "referenceText": transcripts.get(take.get("batchID", "")) if reference_path else None,
            "finishReason": take.get("finishReason"),
            "seed": take.get("seed"),
            "family": take.get("scriptID") or take["takeID"].split("--")[0],
        })
    return {"schema": TAKES_SCHEMA, "source": source, "takes": takes}


def load_takes(path: Path | str) -> dict[str, Any]:
    """A takes manifest from a manifest file or a qc-takes run directory."""

    path = Path(path)
    if path.is_dir():
        return takes_from_qc_takes_run(path)
    manifest = read_json(path)
    if not isinstance(manifest, dict) or manifest.get("schema") != TAKES_SCHEMA:
        raise ValueError(f"not a {TAKES_SCHEMA} manifest: {path.name}")
    return manifest


def merge_takes(manifests: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """All takes of several manifests, unique by token."""

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for manifest in manifests:
        for take in manifest["takes"]:
            if take["token"] not in seen:
                seen.add(take["token"])
                merged.append(take)
    return merged
