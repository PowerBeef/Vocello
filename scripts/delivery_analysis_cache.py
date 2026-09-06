#!/usr/bin/env python3
"""Content-addressed, privacy-safe cache for operator-local delivery analysis.

The cache is not evidence by itself. Every entry is bound to the original WAV,
the canonical 16 kHz mono PCM derivative, executable/model provenance, and the
preprocessing configuration. Reports never contain audio bytes or local paths.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any, Callable, Iterator
import wave

import numpy as np


SCHEMA_VERSION = 1
CANONICAL_SAMPLE_RATE = 16_000
CANONICAL_CHANNELS = 1
CANONICAL_FORMAT = "pcm-s16le"
RESAMPLER_VERSION = "linear-rational-v1"
READ_FRAMES = 65_536
NO_MODEL_DIGEST = hashlib.sha256(b"vocello:no-external-model").hexdigest()
REPO = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_ROOT = Path(os.environ.get(
    "QVOICE_DELIVERY_ANALYSIS_CACHE", REPO / "build/cache/delivery-analysis"
))


class AnalysisCacheError(ValueError):
    """The cache is corrupt, ambiguous, unsafe, or has drifted."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, json.dumps(
        value, indent=2, sort_keys=True, ensure_ascii=False
    ).encode("utf-8") + b"\n")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AnalysisCacheError(f"cache JSON is unreadable: {path.name}") from error
    if not isinstance(value, dict):
        raise AnalysisCacheError(f"cache JSON must be an object: {path.name}")
    return value


def _validate_sha256(value: Any, label: str) -> str:
    if (
        not isinstance(value, str) or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AnalysisCacheError(f"{label} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True)
class CanonicalAudio:
    original_wav_sha256: str
    canonical_derivative_sha256: str
    sample_count: int
    duration_seconds: float
    derivative_path: Path

    def report(self) -> dict[str, Any]:
        return {
            "originalWAVSHA256": self.original_wav_sha256,
            "canonicalDerivativeSHA256": self.canonical_derivative_sha256,
            "sampleRateHz": CANONICAL_SAMPLE_RATE,
            "channels": CANONICAL_CHANNELS,
            "format": CANONICAL_FORMAT,
            "sampleCount": self.sample_count,
            "durationSeconds": self.duration_seconds,
            "resamplerVersion": RESAMPLER_VERSION,
        }


@dataclass(frozen=True)
class LayerIdentity:
    original_wav_sha256: str
    canonical_derivative_sha256: str
    layer_id: str
    layer_version: str
    binary_sha256: str
    model_id: str
    model_revision: str
    weights_sha256: str
    preprocessing_config_digest: str

    def __post_init__(self) -> None:
        for label, value in (
            ("originalWAVSHA256", self.original_wav_sha256),
            ("canonicalDerivativeSHA256", self.canonical_derivative_sha256),
            ("binarySHA256", self.binary_sha256),
            ("weightsSHA256", self.weights_sha256),
            ("preprocessingConfigDigest", self.preprocessing_config_digest),
        ):
            _validate_sha256(value, label)
        for label, value in (
            ("layerID", self.layer_id), ("layerVersion", self.layer_version),
            ("modelID", self.model_id), ("modelRevision", self.model_revision),
        ):
            if not isinstance(value, str) or not value.strip():
                raise AnalysisCacheError(f"{label} is required")

    def report(self) -> dict[str, str]:
        return {
            "originalWAVSHA256": self.original_wav_sha256,
            "canonicalDerivativeSHA256": self.canonical_derivative_sha256,
            "layerID": self.layer_id,
            "layerVersion": self.layer_version,
            "binarySHA256": self.binary_sha256,
            "modelID": self.model_id,
            "modelRevision": self.model_revision,
            "weightsSHA256": self.weights_sha256,
            "preprocessingConfigDigest": self.preprocessing_config_digest,
        }

    @property
    def key(self) -> str:
        return digest(self.report())


def _mono_pcm16(raw: bytes, channels: int) -> np.ndarray:
    interleaved = np.frombuffer(raw, dtype="<i2")
    if len(interleaved) % channels:
        raise AnalysisCacheError("WAV contains truncated interleaved PCM")
    if channels == 1:
        return interleaved.astype(np.float64)
    return interleaved.reshape(-1, channels).astype(np.float64).mean(axis=1)


def _canonical_pcm_blocks(path: Path) -> Iterator[bytes]:
    """Stream legacy-v1 PCM without retaining duration-sized encoded output.

    Keep interpolation and the historical omitted endpoint byte-identical. This
    is NOT an anti-aliased resampler: changing that requires a new preprocessing
    version and requalification of the neural adapters, not a cache refactor.
    """
    with wave.open(str(path), "rb") as reader:
        if reader.getsampwidth() != 2:
            raise AnalysisCacheError("canonicalization requires 16-bit PCM WAV")
        source_rate = reader.getframerate()
        channels = reader.getnchannels()
        expected_frames = reader.getnframes()
        if source_rate <= 0 or channels <= 0:
            raise AnalysisCacheError("WAV sample rate and channels must be positive")
        previous = np.empty(0, dtype=np.float64)
        global_start = 0
        output_index = 0
        while True:
            raw = reader.readframes(READ_FRAMES)
            if not raw:
                break
            block = _mono_pcm16(raw, channels)
            if previous.size:
                combined = np.concatenate((previous, block))
                combined_start = global_start - 1
            else:
                combined = block
                combined_start = global_start
            combined_end = combined_start + len(combined) - 1
            # Linear interpolation needs source floor+1. Leave the final sample
            # for the next block (or deliberately omit it at EOF).
            maximum_output = math.ceil(combined_end * CANONICAL_SAMPLE_RATE / source_rate)
            if maximum_output > output_index:
                indices = np.arange(output_index, maximum_output, dtype=np.int64)
                positions = indices.astype(np.float64) * source_rate / CANONICAL_SAMPLE_RATE
                valid = positions < combined_end
                indices = indices[valid]
                positions = positions[valid]
                if indices.size:
                    local = positions - combined_start
                    lower = np.floor(local).astype(np.int64)
                    fraction = local - lower
                    values = combined[lower] * (1.0 - fraction) + combined[lower + 1] * fraction
                    encoded = np.clip(np.rint(values), -32768, 32767).astype("<i2")
                    yield encoded.tobytes()
                    output_index = int(indices[-1]) + 1
            previous = combined[-1:].copy()
            global_start += len(block)
    if global_start != expected_frames:
        raise AnalysisCacheError("WAV declared frame count differs from readable PCM")
    if output_index == 0:
        raise AnalysisCacheError("WAV has no canonicalizable audio samples")


def _write_canonical_pcm(path: Path, destination: Path, original_digest: str) -> tuple[str, int]:
    """Hash/write one bounded stream; publish only after complete source validation."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}-", dir=destination.parent)
    hasher = hashlib.sha256()
    byte_count = 0
    try:
        with os.fdopen(descriptor, "wb") as output:
            for block in _canonical_pcm_blocks(path):
                output.write(block)
                hasher.update(block)
                byte_count += len(block)
            output.flush()
            os.fsync(output.fileno())
        if file_sha256(path) != original_digest:
            raise AnalysisCacheError("source WAV changed during canonicalization")
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
    return hasher.hexdigest(), byte_count // 2


def _validate_audio_metadata(body: dict[str, Any], original_digest: str) -> int:
    expected = {
        "schemaVersion": SCHEMA_VERSION, "kind": "canonical-delivery-analysis-audio",
        "originalWAVSHA256": original_digest, "sampleRateHz": CANONICAL_SAMPLE_RATE,
        "channels": CANONICAL_CHANNELS, "format": CANONICAL_FORMAT,
        "resamplerVersion": RESAMPLER_VERSION,
    }
    if any(type(body.get(key)) is not type(value) or body[key] != value
           for key, value in expected.items()):
        raise AnalysisCacheError("canonical audio preprocessing or identity mismatch")
    count = body.get("sampleCount")
    if type(count) is not int or count <= 0 or type(body.get("byteCount")) is not int:
        raise AnalysisCacheError("canonical audio sample count is invalid")
    duration = body.get("durationSeconds")
    if (body["byteCount"] != count * 2 or type(duration) not in (int, float)
            or not math.isfinite(duration) or duration != count / CANONICAL_SAMPLE_RATE):
        raise AnalysisCacheError("canonical audio sample count or duration mismatch")
    _validate_sha256(body.get("canonicalDerivativeSHA256"), "canonical derivative")
    return count


class DeliveryAnalysisCache:
    def __init__(self, root: Path) -> None:
        self.root = root

    def canonicalize(self, wav_path: Path) -> CanonicalAudio:
        if not wav_path.is_file():
            raise AnalysisCacheError("source WAV does not exist")
        original_digest = file_sha256(wav_path)
        audio_dir = self.root / "audio" / original_digest[:2]
        pcm_path = audio_dir / f"{original_digest}.pcm"
        metadata_path = audio_dir / f"{original_digest}.json"
        if metadata_path.exists():
            metadata = _read_json(metadata_path)
            stored_digest = metadata.get("recordDigest")
            body = dict(metadata)
            body.pop("recordDigest", None)
            if stored_digest != digest(body):
                raise AnalysisCacheError("canonical audio record digest mismatch")
            if body.get("originalWAVSHA256") != original_digest:
                raise AnalysisCacheError("canonical audio original identity mismatch")
            sample_count = _validate_audio_metadata(body, original_digest)
            if not pcm_path.is_file():
                raise AnalysisCacheError("canonical derivative is missing")
            derivative_digest = file_sha256(pcm_path)
            if derivative_digest != body.get("canonicalDerivativeSHA256"):
                raise AnalysisCacheError("canonical derivative digest mismatch")
            if pcm_path.stat().st_size != body.get("byteCount"):
                raise AnalysisCacheError("canonical derivative byte count mismatch")
            return CanonicalAudio(
                original_digest, derivative_digest, sample_count,
                float(body["durationSeconds"]), pcm_path,
            )
        derivative_digest, sample_count = _write_canonical_pcm(wav_path, pcm_path, original_digest)
        body = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "canonical-delivery-analysis-audio",
            "originalWAVSHA256": original_digest,
            "canonicalDerivativeSHA256": derivative_digest,
            "sampleRateHz": CANONICAL_SAMPLE_RATE,
            "channels": CANONICAL_CHANNELS,
            "format": CANONICAL_FORMAT,
            "resamplerVersion": RESAMPLER_VERSION,
            "sampleCount": sample_count,
            "byteCount": sample_count * 2,
            "durationSeconds": sample_count / CANONICAL_SAMPLE_RATE,
        }
        atomic_json(metadata_path, {**body, "recordDigest": digest(body)})
        return CanonicalAudio(
            original_digest, derivative_digest, sample_count,
            sample_count / CANONICAL_SAMPLE_RATE, pcm_path,
        )

    def _entry_path(self, identity: LayerIdentity) -> Path:
        return (
            self.root / "layers" / identity.canonical_derivative_sha256[:2]
            / identity.canonical_derivative_sha256 / f"{identity.key}.json"
        )

    def load(self, identity: LayerIdentity) -> dict[str, Any] | None:
        path = self._entry_path(identity)
        if not path.exists():
            return None
        record = _read_json(path)
        stored = record.get("recordDigest")
        body = dict(record)
        body.pop("recordDigest", None)
        if stored != digest(body):
            raise AnalysisCacheError("analysis cache record digest mismatch")
        if (type(body.get("schemaVersion")) is not int
                or body["schemaVersion"] != SCHEMA_VERSION
                or body.get("kind") != "delivery-analysis-layer"
                or body.get("promotionAuthority") is not False):
            raise AnalysisCacheError("analysis cache record schema mismatch")
        if body.get("identity") != identity.report():
            raise AnalysisCacheError("analysis cache identity mismatch")
        payload = body.get("payload")
        if not isinstance(payload, dict) or body.get("payloadDigest") != digest(payload):
            raise AnalysisCacheError("analysis cache payload digest mismatch")
        _assert_report_safe(payload)
        return payload

    def store(self, identity: LayerIdentity, payload: dict[str, Any]) -> dict[str, Any]:
        _assert_report_safe(payload)
        retained = self.load(identity)
        if retained is not None:
            if digest(retained) != digest(payload):
                raise AnalysisCacheError("cache key already contains different analysis bytes")
            return retained
        body = {
            "schemaVersion": SCHEMA_VERSION,
            "kind": "delivery-analysis-layer",
            "promotionAuthority": False,
            "identity": identity.report(),
            "payloadDigest": digest(payload),
            "payload": payload,
        }
        atomic_json(self._entry_path(identity), {**body, "recordDigest": digest(body)})
        return payload

    def get_or_compute(
        self, identity: LayerIdentity, compute: Callable[[], dict[str, Any]],
    ) -> tuple[dict[str, Any], bool]:
        retained = self.load(identity)
        if retained is not None:
            return retained, True
        return self.store(identity, compute()), False


def _assert_report_safe(value: Any, trail: str = "report") -> None:
    if isinstance(value, bytes):
        raise AnalysisCacheError(f"{trail} contains raw bytes")
    if isinstance(value, str):
        if value.startswith(("/", "file://")) or "/Users/" in value:
            raise AnalysisCacheError(f"{trail} contains a local path")
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise AnalysisCacheError(f"{trail} has a non-string key")
            lowered = key.lower()
            if lowered in {"path", "audiobytes", "rawaudio", "wavpath"}:
                raise AnalysisCacheError(f"{trail}.{key} is forbidden in cache reports")
            _assert_report_safe(child, f"{trail}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_report_safe(child, f"{trail}[{index}]")
        return
    if value is None or isinstance(value, (bool, int)):
        return
    if isinstance(value, float) and math.isfinite(value):
        return
    raise AnalysisCacheError(f"{trail} contains a non-finite or unsupported value")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_CACHE_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    canonical = commands.add_parser("canonicalize")
    canonical.add_argument("wav", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "canonicalize":
            result = DeliveryAnalysisCache(args.root).canonicalize(args.wav).report()
        else:  # pragma: no cover - argparse owns this branch
            raise AnalysisCacheError("unknown command")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except AnalysisCacheError as error:
        print(f"Delivery analysis cache: FAIL\n{error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
