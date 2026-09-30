"""Codec traces and the T2 codec-loop construction (audit 2026-09-25 section 5.2, COD-LOOP, class I).

A codec trace is the talker's generated codec frames, one row of 16 codes per
frame (codebook 0 first), as the engine records it for a take
(`StartupReliabilityDiagnosticEvidence.encode`, "codec-trace v1"):

    b"VQCT" | u32 version (1) | u32 frame count | u32 dropped frames
    then per frame: u16 code count | that many i32 codes (little-endian)

COD-LOOP@1 repeats a span of whole frames right after itself: the talker's
codebook 0 then carries an exact cycle of period `spanFrames` over
`spanFrames * (1 + extraCopies)` frames, which the token-loop detector reads
(`tokenCycleSpanFrames`). Its sham leaves the trace untouched. The catalog
below is the construction's; `vocello bench --codec-loop`
(`CodecLoopMutationEvidence.mutated`) applies the same recipe in Swift, and
the builder requires the two mutated traces to match byte for byte.

Placement. The span starts in the middle 60% of the take, at a seeded
fraction of the room the largest span leaves, so every variant of one take
repeats frames from the same point (a paired design) and no loop sits in the
leading or trailing silence.
"""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any, Mapping, Sequence

MAGIC = b"VQCT"
VERSION = 1
CODEBOOKS = 16
MAXIMUM_FRAMES = 8_192
CODEBOOK_SIZES = (4_096,) + (2_048,) * (CODEBOOKS - 1)
MAXIMUM_TRACE_BYTES = 16 + MAXIMUM_FRAMES * (2 + CODEBOOKS * 4)
# `CodecLoopMutationEvidence` bounds (Swift).
MAXIMUM_SPAN_FRAMES = 64
MAXIMUM_EXTRA_COPIES = 8

CATALOG_VERSION = 1
INJECTOR_ID = "COD-LOOP"
INJECTOR = f"{INJECTOR_ID}@1"
MECHANISM = "T2-codec-construction"
CLASSES = ("I",)
# variant -> (span in codec frames, extra copies): 0.32, 0.96 and 2.56 s repeated once (audit: 4-32 frames).
VARIANTS: dict[str, tuple[int, int]] = {"sham": (0, 0), "mild": (4, 1), "moderate": (12, 1), "severe": (32, 1)}
SEVERITIES = {"sham": "sham", "mild": "mild", "moderate": "moderate", "severe": "severe"}
PLACEMENT_LOW, PLACEMENT_HIGH = 0.2, 0.8
PLACEMENT_SCHEMA = "vocello.audioqc.cod-loop-placement/1"


class TraceError(ValueError):
    """A codec trace or loop recipe the construction refuses."""


def encode(frames: Sequence[Sequence[int]], dropped: int = 0) -> bytes:
    """Frames as the codec-trace v1 binary."""
    if not frames or len(frames) > MAXIMUM_FRAMES:
        raise TraceError("a codec trace holds 1 to 8192 frames")
    out = bytearray(MAGIC)
    out += struct.pack("<III", VERSION, len(frames), dropped)
    for frame in frames:
        if not 1 <= len(frame) <= 64:
            raise TraceError("a codec frame holds 1 to 64 codes")
        out += struct.pack("<H", len(frame))
        out += struct.pack(f"<{len(frame)}i", *frame)
    return bytes(out)


def decode(data: bytes) -> tuple[list[list[int]], int]:
    """(frames, dropped frame count) of a codec-trace v1 binary; refuses anything malformed."""
    if len(data) > MAXIMUM_TRACE_BYTES or len(data) < 16 or data[:4] != MAGIC:
        raise TraceError("not a codec-trace v1 binary")
    version, count, dropped = struct.unpack_from("<III", data, 4)
    if version != VERSION or count > MAXIMUM_FRAMES:
        raise TraceError("unsupported codec-trace version or frame count")
    offset, frames = 16, []
    for _ in range(count):
        if offset + 2 > len(data):
            raise TraceError("the codec trace is truncated")
        (codes,) = struct.unpack_from("<H", data, offset)
        offset += 2
        if not 1 <= codes <= 64 or offset + 4 * codes > len(data):
            raise TraceError("a codec frame is out of bounds")
        frames.append(list(struct.unpack_from(f"<{codes}i", data, offset)))
        offset += 4 * codes
    if offset != len(data):
        raise TraceError("the codec trace has trailing bytes")
    return frames, dropped


def complete_frames(data: bytes) -> list[list[int]]:
    """The frames of a complete trace (no dropped frame) of whole 16-code frames inside each codebook."""
    frames, dropped = decode(data)
    if dropped or not frames:
        raise TraceError("the codec trace is incomplete")
    for frame in frames:
        if len(frame) != CODEBOOKS or any(not 0 <= code < size for code, size in zip(frame, CODEBOOK_SIZES)):
            raise TraceError("a codec frame is not 16 codes inside their codebooks")
    return frames


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def codebook0(frames: Sequence[Sequence[int]]) -> list[int]:
    return [int(frame[0]) for frame in frames]


def recipe(variant: str, start_frame: int) -> dict[str, Any]:
    """The catalog's recipe for one variant at a start frame (the job's and the entry's recipe)."""
    if variant not in VARIANTS:
        raise TraceError(f"COD-LOOP has no variant {variant!r}")
    span, copies = VARIANTS[variant]
    return {"injector": INJECTOR, "variant": variant, "startFrame": int(start_frame), "spanFrames": span,
            "extraCopies": copies}


def recipe_problems(value: Any) -> list[str]:
    """Why a recipe is not this catalog's (`CodecLoopMutationEvidence.Recipe.isWellFormed`, plus the catalog)."""
    if not isinstance(value, Mapping) or set(value) != {"injector", "variant", "startFrame", "spanFrames",
                                                        "extraCopies"}:
        return ["a COD-LOOP recipe names injector, variant, startFrame, spanFrames and extraCopies"]
    problems = []
    if value["injector"] != INJECTOR:
        problems.append(f"a COD-LOOP recipe is {INJECTOR}'s")
    if value["variant"] not in VARIANTS:
        return problems + [f"COD-LOOP has no variant {value['variant']!r}"]
    for key in ("startFrame", "spanFrames", "extraCopies"):
        if isinstance(value[key], bool) or not isinstance(value[key], int) or value[key] < 0:
            problems.append(f"a COD-LOOP recipe's {key} is a non-negative integer")
    if not problems and (value["spanFrames"], value["extraCopies"]) != VARIANTS[value["variant"]]:
        problems.append(f"COD-LOOP {value['variant']} repeats {VARIANTS[value['variant']]} (span, copies)")
    return problems


def apply(frames: Sequence[Sequence[int]], value: Mapping[str, Any]) -> list[list[int]]:
    """The recipe applied: the frames through the span, `extraCopies` more copies of the span, then the rest."""
    if problems := recipe_problems(value):
        raise TraceError(problems[0])
    start, span, copies = value["startFrame"], value["spanFrames"], value["extraCopies"]
    if start + span > len(frames):
        raise TraceError("the COD-LOOP span runs past the trace")
    end = start + span
    output = [list(frame) for frame in frames[:end]]
    for _ in range(copies):
        output.extend(list(frame) for frame in frames[start:end])
    output.extend(list(frame) for frame in frames[end:])
    if len(output) > MAXIMUM_FRAMES:
        raise TraceError("the looped trace exceeds 8192 frames")
    return output


def minimum_frames() -> int:
    """The shortest trace whose middle 60% holds the largest span."""
    largest = max(span for span, _ in VARIANTS.values())
    return math.ceil(largest / (PLACEMENT_HIGH - PLACEMENT_LOW))


def placement(frame_count: int, *, seed: int, take_id: str) -> int | None:
    """The span's start frame for a take (every variant's), or None when the take is too short."""
    largest = max(span for span, _ in VARIANTS.values())
    low = math.ceil(frame_count * PLACEMENT_LOW)
    high = math.floor(frame_count * PLACEMENT_HIGH) - largest
    if high < low:
        return None
    digest = hashlib.sha256("|".join((PLACEMENT_SCHEMA, str(seed), take_id)).encode("utf-8")).digest()
    return low + int.from_bytes(digest[:8], "big") % (high - low + 1)
