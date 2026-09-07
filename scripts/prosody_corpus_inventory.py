"""Read-only retained-audio discovery for the existing prosody calibration route.

No feature extraction, quality labels, split selection, resampling or model imports.
File hashes bind containers; PCM hashes include format and ignore RIFF metadata.
All discovered material is development-only: discovery cannot prove an untouched
holdout. The separate private map is never suitable for repository publication.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import wave
from collections import Counter
from pathlib import Path


READ_BYTES = 131_072
MAX_WAV_BYTES = 512 * 1024 * 1024


def audio_identity(path: Path) -> dict:
    """Stream PCM without modifying amplitude, pauses, pitch or source bytes."""
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if not 0 < before.st_size <= MAX_WAV_BYTES:
            raise ValueError("audio-size-outside-inventory-bound")
        wav_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        stream.seek(0)
        with wave.open(stream, "rb") as wav:
            channels, width, rate, frames, compression, _ = wav.getparams()
            if compression != "NONE" or channels not in (1, 2) or width not in (1, 2, 3, 4):
                raise ValueError("unsupported-PCM-format")
            if not 8_000 <= rate <= 192_000 or frames <= 0:
                raise ValueError("invalid-PCM-metadata")
            frame_bytes = channels * width
            metadata = {"sampleRate": rate, "channels": channels,
                        "sampleWidthBytes": width, "frameCount": frames}
            pcm_digest = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode())
            remaining = frames
            while remaining:
                requested = min(remaining, READ_BYTES // frame_bytes)
                block = wav.readframes(requested)
                if len(block) != requested * frame_bytes:
                    raise ValueError("truncated-PCM")
                pcm_digest.update(block)
                remaining -= requested
        after = os.fstat(stream.fileno())
        if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise ValueError("audio-changed-during-inventory")
    return {**metadata, "audioSHA256": wav_digest, "pcmSHA256": pcm_digest.hexdigest(),
            "byteCount": before.st_size, "durationSeconds": frames / rate}


def inventory_audio(roots: list[Path], *, max_files: int = 5000,
                    max_entries: int = 100_000, timeout_seconds: float = 120) -> tuple[dict, dict]:
    """Explicit-root walk, bounded report/traversal memory, no symlink following.

    Timeout is checked between files/entries (one capped file may finish afterward).
    Missing/unreadable files are evidence gaps, never inferred audio defects.
    """
    if not roots or type(max_files) is not int or not 1 <= max_files <= 100_000:
        raise ValueError("explicit roots and a bounded positive file count are required")
    if type(max_entries) is not int or not 1 <= max_entries <= 1_000_000:
        raise ValueError("invalid traversal bound")
    if not 0 < timeout_seconds <= 3600:
        raise ValueError("invalid inventory time bound")
    started = time.monotonic()
    public, private, visited = [], [], set()
    counts = Counter()
    stop_reason = None

    def walk(directory: Path, depth: int = 0):
        nonlocal stop_reason
        if directory.is_symlink():
            counts["symlinksSkipped"] += 1
            return
        if depth > 64:
            counts["depthLimitReached"] += 1
            return
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if stop_reason:
                        return
                    if counts["entriesVisited"] >= max_entries:
                        stop_reason = "entry-limit"
                        return
                    if time.monotonic() - started >= timeout_seconds:
                        stop_reason = "time-limit"
                        return
                    counts["entriesVisited"] += 1
                    if entry.is_symlink():
                        counts["symlinksSkipped"] += 1
                    elif entry.is_dir(follow_symlinks=False):
                        yield from walk(Path(entry.path), depth + 1)
                    elif entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".wav"):
                        yield Path(entry.path)
        except OSError:
            counts["unreadableDirectories"] += 1

    for root in roots:
        if stop_reason:
            break
        # Refuse symlink ancestors as well as entries, including a linked root.
        absolute = root.absolute()
        if any(part.is_symlink() for part in (absolute, *absolute.parents)):
            counts["symlinksSkipped"] += 1
            counts["unavailableRoots"] += 1
            continue
        for path in walk(absolute):
            if path in visited:
                continue
            if len(public) >= max_files:
                stop_reason = "file-limit"
                break
            visited.add(path)
            item_id = f"clip-{len(public) + 1:06d}"
            row = {"itemID": item_id, "eligibility": "development-only",
                   "label": None, "groupMetadata": "unverified"}
            try:
                row.update(audio_identity(path))
                row["status"] = "READABLE_PCM"
            except ValueError as error:
                row.update(status="UNAVAILABLE", reason=str(error))
            except (OSError, EOFError, wave.Error):
                row.update(status="UNAVAILABLE", reason="unreadable-or-unsupported-WAV")
            public.append(row)
            private.append({"itemID": item_id, "path": str(path)})
    available = [row for row in public if row["status"] == "READABLE_PCM"]
    counts.update({"wavFiles": len(public), "readablePCM": len(available),
                   "unavailable": len(public) - len(available),
                   "uniqueWAV": len({row["audioSHA256"] for row in available}),
                   "uniquePCM": len({row["pcmSHA256"] for row in available})})
    pcm_counts = Counter(row["pcmSHA256"] for row in available)
    for row in available:
        row["duplicatePCMCount"] = pcm_counts[row["pcmSHA256"]]
    report = {"schemaVersion": 1, "kind": "prosody-retained-audio-inventory",
              "status": "PARTIAL" if stop_reason or counts["unreadableDirectories"] or counts["depthLimitReached"] or counts["unavailableRoots"] else "INVENTORIED",
              "stopReason": stop_reason, "promotionAuthority": False,
              "sourceSHA256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "counts": dict(counts), "items": public,
              "limits": {"maxFiles": max_files, "maxEntries": max_entries,
                         "maxWAVBytes": MAX_WAV_BYTES, "readBlockBytes": READ_BYTES,
                         "timeoutSeconds": timeout_seconds},
              "missingEvidence": ["verified-source-speaker-script-translation-groups",
                                  "verified-language", "independent-defect-annotations",
                                  "fresh-predeclared-untouched-holdout"]}
    identity = hashlib.sha256(json.dumps(report, sort_keys=True).encode()).hexdigest()
    report["inventorySHA256"] = identity
    return report, {"schemaVersion": 1, "inventorySHA256": identity, "items": private}
