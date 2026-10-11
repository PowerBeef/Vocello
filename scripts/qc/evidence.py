"""Bounded, report-only perceptual evidence from existing WAVs and cached runners.

These measurements expose blind spots; they do not establish native accent,
whisper, emotional intent or clone acceptance. No inference or downloads occur.
"""
from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path

import numpy as np

from qc import acoustics, boundary, fidelity, pronunciation, store

SCHEMA = "vocello.qc.perceptual-evidence/1"
EVENTS_SCHEMA = "vocello.qc.events/1"
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_ARCHIVE_BYTES = 128 * 1024**2
MAX_EXPANDED_BYTES = 256 * 1024**2


def load_posteriors(layout, model_id, audio_sha, output):
    """Read only the exact audio/model cache member; never unpickle NPZ data.

    Older runner JSON does not bind the NPZ digest. Record the bytes actually
    read, and disclose that provenance limit instead of claiming attestation.
    """
    unavailable = {"inputStatus": "unavailable", "reason": "missing-posteriors"}
    if not isinstance(output, dict) or not output.get("posteriors"):
        return None, unavailable
    if not isinstance(model_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", model_id) or model_id in (".", ".."):
        return None, dict(unavailable, reason="invalid-model-identity")
    if not isinstance(audio_sha, str) or not SHA256.fullmatch(audio_sha):
        return None, dict(unavailable, reason="invalid-audio-identity")
    path = store.result_npz_path(layout, model_id, audio_sha)
    if output["posteriors"] != path.name:
        return None, dict(unavailable, reason="posterior-cache-name-mismatch")
    try:
        # Reject symlinks in the cache path, including model directories.
        if any(part.is_symlink() for part in (path, *path.parents) if part.is_relative_to(layout.root) and part != layout.root):
            raise ValueError("symlinked-posterior-cache")
        if path.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ValueError("posterior-archive-too-large")
        with zipfile.ZipFile(path) as archive:
            if sum(item.file_size for item in archive.infolist()) > MAX_EXPANDED_BYTES:
                raise ValueError("posterior-expanded-size-too-large")
            if sorted(archive.namelist()) != ["frameSeconds.npy", "logprobs.npy", "vocab.npy"]:
                raise ValueError("unexpected-posterior-members")
            for member in archive.infolist():
                with archive.open(member) as stream:
                    version = np.lib.format.read_magic(stream)
                    if version == (1, 0):
                        shape, _, dtype = np.lib.format.read_array_header_1_0(stream)
                    elif version == (2, 0):
                        shape, _, dtype = np.lib.format.read_array_header_2_0(stream)
                    else:
                        raise ValueError("unsupported-posterior-array-format")
                    if dtype.hasobject or math.prod(shape) * dtype.itemsize > member.file_size - stream.tell():
                        raise ValueError("invalid-posterior-array-size")
                    if member.filename == "logprobs.npy" and math.prod(shape) > pronunciation.DEFAULT_LIMITS["cells"]:
                        raise ValueError("posterior-cell-budget-exceeded")
        digest = store.sha256_file(path)
        with np.load(path, allow_pickle=False) as values:
            raw = values["logprobs"]
            vocab = values["vocab"]
            frame = values["frameSeconds"]
            if raw.dtype.kind != "f" or raw.ndim != 2 or not raw.size or raw.shape[0] > 20000 or raw.shape[1] > 4096:
                raise ValueError("invalid-posterior-shape")
            if vocab.ndim != 1 or vocab.dtype.kind not in "US" or len(vocab) != raw.shape[1]:
                raise ValueError("invalid-posterior-vocabulary")
            if frame.shape not in ((), (1,)) or frame.dtype.kind not in "fi":
                raise ValueError("invalid-posterior-frame-clock")
            seconds = float(frame.reshape(-1)[0])
            if not math.isfinite(seconds) or not 0 < seconds <= 1 or np.isnan(raw).any() or np.isposinf(raw).any():
                raise ValueError("invalid-posterior-values")
            if store.sha256_file(path) != digest:
                raise ValueError("posterior-changed-during-read")
            return {"logprobs": raw, "vocab": vocab.astype(str).tolist(), "frameSeconds": seconds}, {
                "inputStatus": "complete", "sha256": digest,
                "binding": "observed-cache-bytes-not-runner-attested", "frames": raw.shape[0],
                "vocabularySize": raw.shape[1], "frameSeconds": seconds}
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, EOFError):
        return None, dict(unavailable, reason="invalid-or-unreadable-posteriors")


def analyze(take, results, context, *, layout, model_ids, expected, words, audio):
    outputs = {role: value.get("outputs") if isinstance(value, dict) and not value.get("error")
               and isinstance(value.get("outputs"), dict) else None
               for role, value in results.items()}
    result = {"schema": SCHEMA, "qualification": "uncalibrated", "decision": "not-assessed",
              "audioSHA256": take.get("audioSHA256"), "posteriorArtifacts": {},
              "audioDurationSeconds": len(audio[0]) / audio[1] if audio is not None and audio[1] > 0 else None,
              "nativeAccent": {"decision": "not-assessed", "reason": "no-qualified-accent-detector"},
              "emotionalIntent": {"decision": "not-assessed", "reason": "no-qualified-intent-detector"}}
    expected_windows = []
    if take.get("language") == "french":
        posteriors = {}
        for role in ("phones", "phonesB"):
            values, provenance = load_posteriors(layout, model_ids.get(role), take.get("audioSHA256"), outputs.get(role))
            result["posteriorArtifacts"][role] = provenance
            if values is not None:
                posteriors[role] = values
        diagnostic = pronunciation.analyze(expected, words, outputs, posteriors=posteriors,
                                           alternatives=take.get("pronunciationAlternatives"))
        result["pronunciation"] = diagnostic
        result["boundaryPronunciation"] = boundary.analyze(expected, words, diagnostic,
            reviewed_boundaries=take.get("boundaryPronunciationHypotheses"),
            duration_seconds=result["audioDurationSeconds"])
        for role, entry in diagnostic.get("roles", {}).items():
            for window in (entry.get("posterior") or {}).get("expectedWindows", []):
                expected_windows.append(dict(window, source=role))
    recognized = []
    for role in ("phones", "phonesB"):
        tokens = (outputs.get(role) or {}).get("phones")
        if not isinstance(tokens, (list, tuple)):
            continue
        for token in tokens[:acoustics.MAX_WINDOWS + 1]:
            if isinstance(token, dict):
                recognized.append(dict(token, source=role))
                if len(recognized) > acoustics.MAX_WINDOWS:
                    break
        if len(recognized) > acoustics.MAX_WINDOWS:
            break
    result["localAcoustics"] = acoustics.analyze(*audio, expected_windows=expected_windows,
        recognized_windows=recognized, reference=context.get("referenceAcoustics", {}).get(take.get("referenceSHA256"))) \
        if audio is not None else {"inputStatus": "unavailable", "decision": "not-assessed", "reason": "unreadable-audio"}
    reference = context.get("referenceResults", {}).get(take.get("referenceSHA256"), {})
    reference_outputs = {role: value["outputs"] for role, value in reference.items()
                         if isinstance(value, dict) and not value.get("error") and isinstance(value.get("outputs"), dict)}
    try:
        result["clonePitch"] = fidelity.pitch_section(tuple(outputs.get(role) for role in ("pitchA", "pitchB")),
                                                     tuple(reference_outputs.get(role) for role in ("pitchA", "pitchB")))
    except (TypeError, ValueError, KeyError, AttributeError):
        result["clonePitch"] = {"available": False, "reason": "invalid-pitch-tracks", "decision": "not-assessed"}
    try:
        result["cloneIdentity"] = fidelity.identity_section(outputs.get("speaker"))
    except (TypeError, ValueError, KeyError, AttributeError):
        result["cloneIdentity"] = {"available": False, "reason": "invalid-speaker-embeddings", "decision": "not-assessed"}
    return result


def events_document(run_id, scoring_sha, models, takes, rows):
    """Export bounded timed observations as candidates, never defect verdicts."""
    entries = []
    for take, row in zip(takes, rows, strict=True):
        evidence = row.get("perceptualEvidence") or {}
        events = []
        duration = evidence.get("audioDurationSeconds")
        if duration is None:
            duration = (evidence.get("localAcoustics") or {}).get("durationSeconds")
        if type(duration) not in (int, float) or not math.isfinite(duration) or duration <= 0:
            duration = None
        # Preserve single-witness disagreements separately from consensus. Missing
        # timing stays in pronunciation evidence; it cannot be localized here.
        for role, diagnostic in (evidence.get("pronunciation") or {}).get("roles", {}).items():
            for candidate in diagnostic.get("localizedCandidates", []):
                start, end = candidate.get("start"), candidate.get("end")
                if not all(type(x) in (int, float) and math.isfinite(x) for x in (start, end)):
                    continue
                if start < 0 or end <= start or duration is None or end > duration:
                    continue
                events.append({"id": f"{role}-{len(events)}", "class": "pronunciation",
                    "start": start, "end": end, "source": role, "status": "candidate",
                    "candidateType": candidate.get("type")})
        pronunciation_status = (evidence.get("pronunciation") or {}).get("inputStatus", "unavailable")
        dimensions = {"pronunciation": {"inputStatus": pronunciation_status, "decision": "not-assessed"},
            "nativeAccent": {"inputStatus": "unsupported", "decision": "not-assessed"},
            "emotionalIntent": {"inputStatus": "unsupported", "decision": "not-assessed"}}
        producers = (evidence.get("localAcoustics") or {}).get("candidateProducers") or {}
        producers = {**producers, "boundary-pronunciation": evidence.get("boundaryPronunciation") or {}}
        for name, limit in (("phonation-anomaly", 128), ("short-fragment", 128), ("boundary-pronunciation", 256)):
            producer = producers.get(name) or {}
            dimensions[name] = {"inputStatus": producer.get("inputStatus", "unavailable"),
                "decision": "not-assessed", "qualification": "uncalibrated",
                "coverage": producer.get("coverage", {})}
            if producer.get("reason"):
                dimensions[name]["reason"] = producer["reason"]
            observations = producer.get("candidates") or []
            if not isinstance(observations, (list, tuple)):
                dimensions[name].update(inputStatus="partial", export={"reason": "invalid-candidate-collection"})
                continue
            rejected, truncated = 0, max(0, len(observations) - limit)
            for candidate in observations[:limit]:
                if not isinstance(candidate, dict) or candidate.get("class") != name or candidate.get("status") != "candidate":
                    rejected += 1
                    continue
                start, end = candidate.get("start"), candidate.get("end")
                if not all(type(x) in (int, float) and math.isfinite(x) for x in (start, end)):
                    rejected += 1
                    continue
                if duration is None or not 0 <= start < end <= duration:
                    rejected += 1
                    continue
                events.append(dict(candidate, id=f"{name}-{len(events)}"))
            if rejected or truncated:
                dimensions[name].update(inputStatus="partial", export={"reason": "candidate-export-loss",
                    "rejected": rejected, "truncated": truncated})
        entries.append({"token": take["token"], "audioSHA256": take["audioSHA256"],
                        "durationSeconds": duration, "inputStatus": pronunciation_status,
                        "durationSource": "decoded-pcm", "manifestDurationMismatch":
                            take.get("durationSeconds") is not None and take["durationSeconds"] != duration,
                        "events": events, "dimensions": dimensions})
    return {"schema": EVENTS_SCHEMA, "run": run_id, "scoringSHA256": scoring_sha,
            "models": models, "qualification": "uncalibrated", "decision": "not-assessed", "takes": entries}
