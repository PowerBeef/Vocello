#!/usr/bin/env python3
"""Create deterministic, untracked listener-attention anchors from real clips.

The original is the expected natural/intelligible choice. The comparison has
regular short dropouts. Anchors qualify listener attention only; they do not
claim that an emotion or delivery label is correct.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import struct
import tempfile
from typing import Any
import wave

from delivery_analysis_cache import digest, file_sha256


SCHEMA_VERSION = 1


class AnchorError(ValueError):
    """An attention anchor cannot be created without changing its meaning."""


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _dropout_comparison(source: Path, destination: Path) -> None:
    try:
        with wave.open(str(source), "rb") as input_audio:
            channels = input_audio.getnchannels()
            width = input_audio.getsampwidth()
            rate = input_audio.getframerate()
            frames = input_audio.readframes(input_audio.getnframes())
    except (OSError, wave.Error) as error:
        raise AnchorError(f"cannot read anchor source {source.name}") from error
    if channels != 1 or width != 2 or rate <= 0 or len(frames) % 2:
        raise AnchorError("listener anchors require mono PCM16 WAV input")
    samples = list(struct.unpack(f"<{len(frames) // 2}h", frames))
    if len(samples) < rate:
        raise AnchorError("listener anchor source must be at least one second")
    period = int(rate * 0.24)
    dropout = int(rate * 0.08)
    for start in range(period, len(samples), period):
        for index in range(start, min(start + dropout, len(samples))):
            samples[index] = 0
    destination.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(destination), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def prepare(*, sources: list[Path], output_dir: Path, output_language: str) -> dict[str, Any]:
    if not sources:
        raise AnchorError("listener anchor sources must be non-empty and byte-distinct")
    if any(not path.is_file() for path in sources):
        raise AnchorError("listener anchor source is missing")
    if len({file_sha256(path) for path in sources}) != len(sources):
        raise AnchorError("listener anchor sources must be non-empty and byte-distinct")
    anchors = []
    for index, source in enumerate(sources, start=1):
        if not source.is_file():
            raise AnchorError(f"listener anchor source {index} is missing")
        comparison = output_dir / "comparisons" / f"dropout-{index:02d}.wav"
        _dropout_comparison(source, comparison)
        anchors.append({
            "expectedPath": str(source.resolve()),
            "expectedSHA256": file_sha256(source),
            "comparisonPath": str(comparison.resolve()),
            "comparisonSHA256": file_sha256(comparison),
            "prompt": "Select the natural, uninterrupted, intelligible clip.",
            "outputLanguage": output_language,
            "anchorKind": "attention-naturalness-dropout-control",
        })
    body = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": "delivery-listener-attention-anchors",
        "promotionAuthority": False,
        "requestedDeliveryLabelsUsed": False,
        "anchors": anchors,
    }
    body["manifestDigest"] = digest(body)
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, action="append", required=True)
    parser.add_argument("--output-language", required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = prepare(
            sources=args.source, output_dir=args.out_dir,
            output_language=args.output_language,
        )
        output = args.out_dir / "anchors.json"
        _atomic_json(output, report)
        print(json.dumps({
            "status": "PASS", "anchorCount": len(report["anchors"]),
            "manifestDigest": report["manifestDigest"], "output": str(output),
        }, sort_keys=True))
        return 0
    except (AnchorError, OSError) as error:
        print(f"Delivery listener anchors: FAIL\n{error}", file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
