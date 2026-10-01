"""Clone fidelity from a QC v2 run: each take's pitch and identity against its clone reference.

`scripts/clone_fidelity_lane.py` (lane `clone-lane`) and `scripts/voice_identity_language_reliability.py
analyze` (lane `voice-reliability`) score their takes, each with its reference clip, through
`qc.lanes.run` under their lane's roles (speaker, pitchA, pitchB). This module reads that run's
cached results:

- **pitch:** FCPE (pitchA) and SwiftF0 (pitchB) through `qc.pitch.summarize`, on the frames where
  both trackers agree: the take's median against its reference's (the register shift, signed
  semitones), the largest sustained shift, the octave jumps, the longest steady-F0 run and the
  trackers' agreement;
- **identity:** ReDimNet2+ (speaker) cosine similarity of the whole take, and of its least
  similar 4 s window, to the reference clip's embedding.

A take without a reference has no register shift or similarity; a model that did not score a
take leaves that section `available: false`.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from qc import models, pitch, store
from qc.store import Layout

ROLES = ("pitchA", "pitchB", "speaker")


def _identities(layout: Layout, features: dict[str, Any]) -> dict[str, tuple[dict[str, Any], str] | None]:
    """role -> (model, runnerSHA256) for the roles that scored the run, as recorded in its features."""

    registry = {model["id"]: model for model in models.load_registry(layout)}
    out: dict[str, tuple[dict[str, Any], str] | None] = {}
    for role in ROLES:
        identity = (features.get("models") or {}).get(role) or {}
        model = registry.get(identity.get("id"))
        runner_sha = identity.get("runnerSHA256")
        out[role] = (model, runner_sha) if model is not None and runner_sha else None
    return out


def _outputs(layout: Layout, identity: tuple[dict[str, Any], str] | None, audio_sha: str | None,
             variant: str | None) -> dict[str, Any] | None:
    if identity is None or not audio_sha:
        return None
    model, runner_sha = identity
    result = store.read_result(layout, model["id"], audio_sha, variant, runner_sha)
    if not result or not isinstance(result.get("outputs"), dict):
        return None
    return result["outputs"]


def similarity(a: Any, b: Any) -> float | None:
    """Cosine similarity of two embeddings (1 is the same direction)."""

    a, b = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
    if a.size == 0 or a.shape != b.shape:
        return None
    norm = float(np.linalg.norm(a) * np.linalg.norm(b))
    return None if norm == 0 else float(np.dot(a, b)) / norm


def _round(value: Any, digits: int = 4) -> float | None:
    if value is None:
        return None
    value = float(value)
    return round(value, digits) if np.isfinite(value) else None


def pitch_section(take_tracks: tuple[Any, Any] | None, reference_tracks: tuple[Any, Any] | None) -> dict[str, Any]:
    if take_tracks is None or None in take_tracks:
        return {"available": False}
    summary = pitch.summarize(*take_tracks)
    median = summary["takeMedianSt"]
    reference_median = None
    if reference_tracks is not None and None not in reference_tracks:
        reference_median = pitch.summarize(*reference_tracks)["takeMedianSt"]
    shift = summary["sustainedShift"]
    tone = summary["toneRun"]
    return {
        "available": median is not None,
        "takeMedianSemitones": _round(median, 3),
        "referenceMedianSemitones": _round(reference_median, 3),
        "registerShiftSemitones": _round(pitch.register_offset(median, reference_median), 3),
        "sustainedShiftSemitones": _round(shift["shiftSt"], 3),
        "sustainedShiftDetected": bool(shift["detected"]),
        "octaveJumps": len(summary["octaveJumps"]),
        "toneRunSeconds": _round(tone["durationSeconds"], 3),
        "toneLike": bool(tone["toneLike"]),
        "agreeRatio": _round(summary["agreement"]["agreeRatio"]),
        "voicingAgreement": _round(summary["agreement"]["voicingAgreement"]),
    }


def identity_section(speaker: dict[str, Any] | None) -> dict[str, Any]:
    if speaker is None or speaker.get("whole") is None:
        return {"available": False}
    reference = speaker.get("reference")
    if reference is None:
        return {"available": False, "reason": "no-reference"}
    windows = [(similarity(window["embedding"], reference), window)
               for window in speaker.get("windows") or [] if window.get("embedding")]
    windows = [(value, window) for value, window in windows if value is not None]
    worst = min(windows, key=lambda item: item[0]) if windows else None
    return {
        "available": True,
        "similarity": _round(similarity(speaker["whole"], reference)),
        "worstWindowSimilarity": _round(worst[0]) if worst else None,
        "worstWindow": {"start": worst[1].get("start"), "end": worst[1].get("end")} if worst else None,
        "windows": len(windows),
    }


def take_fidelity(layout: Layout, run_id: str) -> list[dict[str, Any]]:
    """Per take of a QC run, in manifest order: its pitch and identity against its reference, and
    its QC v2 flags (detector, class and level)."""

    directory = layout.runs / run_id
    manifest = store.read_json(directory / "takes.json")
    features = store.read_json(directory / "features.json")
    flags = {entry["token"]: entry for entry in store.read_json(directory / "flags.json")["takes"]}
    identities = _identities(layout, features)
    rows = []
    for take in manifest["takes"]:
        tracks = tuple(_outputs(layout, identities[role], take["audioSHA256"], None) for role in ("pitchA", "pitchB"))
        reference_tracks = None
        if take.get("referenceSHA256"):
            reference_tracks = tuple(_outputs(layout, identities[role], take["referenceSHA256"], None)
                                     for role in ("pitchA", "pitchB"))
        speaker_identity = identities["speaker"]
        variant = store.take_variant(speaker_identity[0], take) if speaker_identity else None
        speaker = _outputs(layout, speaker_identity, take["audioSHA256"], variant)
        entry = flags.get(take["token"]) or {}
        rows.append({
            "takeID": take.get("takeID"),
            "control": bool(take.get("control")),
            "pitch": pitch_section(tracks, reference_tracks),
            "identity": identity_section(speaker),
            "flags": [{"detector": flag["detector"], "class": flag["class"], "level": flag["level"]}
                      for flag in entry.get("flags", [])],
        })
    return rows


def distribution(values: list[float]) -> dict[str, float] | None:
    values = [float(value) for value in values if value is not None]
    if not values:
        return None
    array = np.asarray(values)
    return {"count": len(values), "minimum": _round(array.min()), "median": _round(np.median(array)),
            "maximum": _round(array.max()), "mean": _round(array.mean()), "standardDeviation": _round(array.std())}


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distributions of the register shift, sustained shift and similarities, and the flag counts."""

    flag_counts: dict[str, int] = {}
    for row in rows:
        for flag in row["flags"]:
            flag_counts[flag["detector"]] = flag_counts.get(flag["detector"], 0) + 1
    return {
        "count": len(rows),
        "flagged": sum(1 for row in rows if row["flags"]),
        "flagCounts": dict(sorted(flag_counts.items())),
        "registerShiftSemitones": distribution([row["pitch"].get("registerShiftSemitones") for row in rows]),
        "sustainedShiftSemitones": distribution([row["pitch"].get("sustainedShiftSemitones") for row in rows]),
        "octaveJumps": sum(int(row["pitch"].get("octaveJumps") or 0) for row in rows),
        "similarity": distribution([row["identity"].get("similarity") for row in rows]),
        "worstWindowSimilarity": distribution([row["identity"].get("worstWindowSimilarity") for row in rows]),
    }


def run_models(layout: Layout, run_id: str) -> dict[str, Any]:
    """The model id and runner identity each fidelity role scored the run with (report provenance)."""

    features = store.read_json(layout.runs / run_id / "features.json")
    return {role: {key: ((features.get("models") or {}).get(role) or {}).get(key)
                   for key in ("id", "runnerSHA256", "available")}
            for role in ROLES}
