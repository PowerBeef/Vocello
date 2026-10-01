#!/usr/bin/env python3
"""Audio QC population N2: N1 recordings resynthesized through the Qwen3-TTS codec.

Population N2 of the audio QC audit (section 5.1) is N1 resynthesized through
the Qwen3-TTS speech tokenizer at full codebooks; a fail bound's false-alarm
rate must be confirmed on it (A2). Every production artifact shares one speech
tokenizer, and only the Base (Voice Cloning) model loads its encoder, so the
round trip runs on the installed Voice Cloning Speed model through the gated
`vocello bench --codec-roundtrip` branch. This module is offline and
model-free; `scripts/macos_test.sh qc-n2` runs the CLI between its steps.

Commands:
  plan               select the eligible recordings of an N1 cohort manifest,
                     resample each to the codec's 24 kHz with the
                     `polyphase-kaiser5-v2` design and write the inputs, the
                     CLI job and an immutable plan
  manifest           bind the CLI's round-trip result to the plan and write the
                     N2 cohort manifest
  validate-manifest  recompute the digests and check the plan binding

Resampling: N1 is 16 kHz read speech; the codec runs at 24 kHz. The design is
the L0 canonicalizer's (`scripts/audio_resampling.py`: Kaiser-5 window, ten
zero crossings at the lower rate, zero-padded, delay-compensated, SciPy's
resample_poly) with only the rate ratio changed (up 3, down 2), quantized
like L0 (round half to even, clip to PCM16). `audio_resampling.py` stays
untouched: its source digest is the L0 cache identity.

Trim: the encoder input carries the clone path's 0.5 s of trailing silence, so
the decode is longer than its input; the facade trims it to the input's sample
count, and an N2 file is exactly as long as its 24 kHz input. Its PCM16 is
written without the production output limiter, as an engine's raw float output
stands before QC's limiter pass.

Speaker labels: a take of a speaker-labelled N1 cohort (`audio_qc_corpora.py
cohort --source speaker`) keeps its `speaker` and `gender`, which the identity
injectors draw donors by, and its `reference` clip, another take of the same
cohort: the N2 take names that take's resynthesis, so a speaker judge scores
codec audio against codec audio (as an impostor is scored against its source).
A FLEURS take names no speaker and keeps neither.

Derived manifests (`derive_manifest`, which `audio_qc_corpora.py
reserve-disjoint` calls): a subset of a validated run's takes, for an N1
manifest derived as a subset of the one the run resynthesized, without a new
round trip. Each kept take is unchanged, its WAV and codes linked into the new
directory under the same paths; `n1ManifestSHA256` names the derived N1
manifest and `derivedFrom` the source run's manifest and the rule.
`validate-manifest --plan` accepts a derived manifest whose takes are items of
the run's plan in plan order.

Everything this module writes (inputs, jobs, plans, manifests) is an untracked
build artifact. Paths are relative to the file that names them.
"""

from __future__ import annotations

import argparse
from collections import OrderedDict
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Iterator, Sequence
import wave

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import numpy as np  # noqa: E402

from audio_resampling import INPUT_BLOCK_FRAMES, RESAMPLER_VERSION, RationalFIR  # noqa: E402
import audio_qc_n1_corpus  # noqa: E402
from lib import jsonio  # noqa: E402
from lib.language_metrics import is_sha256, text_sha256  # noqa: E402

N1_KIND = "audio-qc-n1-cohort"
PLAN_KIND = "audio-qc-n2-plan"
JOB_KIND = "audio-qc-n2-roundtrip-job"
RESULT_KIND = "audio-qc-n2-roundtrip-result"
MANIFEST_KIND = "audio-qc-n2-cohort"
CODEC_RATE = 24_000
CODEBOOKS = 16
# The CLI's bounds (Sources/QwenVoiceCore/CodecRoundTripEvidence.swift).
MAX_ITEMS = 4_096  # CodecRoundTripEvidence.maximumItems: one job, one model load, per cohort
MAX_INPUT_SAMPLES = CODEC_RATE * 60
DECODE_SEMANTICS = "production_nonstreaming_25_frame_schedule"
OUTPUT_FORMAT = "pcm16_mono_24000hz_without_output_limiter"
ENCODER_INPUT = "clone_reference_encoder_input_trailing_silence_500ms"
QUANTIZATION = "rint-clip-pcm16"
JOB_NAME = "n2-job.json"
PLAN_NAME = "n2-plan.json"
INPUT_DIR = "inputs"
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}\Z")
REVISION = re.compile(r"[0-9a-f]{40}\Z")
# The fields an N2 take keeps from its N1 recording, unchanged.
KEPT_FIELDS = ("family", "scriptID", "language", "text")
# The labels a take of a speaker-labelled cohort keeps (its speaker and, where the corpus labels it, gender).
LABEL_FIELDS = ("speaker", "gender")


class N2Error(ValueError):
    """An N1 manifest, plan, round-trip result or N2 manifest is unusable."""


def load_json(path: Path) -> Any:
    return jsonio.load_json(path, error=N2Error, reject_duplicate_keys=True, redact="name")


def self_digest(value: dict[str, Any], field: str) -> str:
    unsigned = dict(value)
    unsigned.pop(field, None)
    return jsonio.sha256_json(unsigned, ascii=False)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _relative(base: Path, value: Any, what: str, *, contained: bool) -> Path:
    """A path named relative to `base`; `contained` also refuses `..`."""
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise N2Error(f"{what} must be a path relative to its manifest")
    if contained and ".." in Path(value).parts:
        raise N2Error(f"{what} must stay under its manifest's directory")
    path = (base / value).resolve()
    if contained and not _inside(path, base.resolve()):
        raise N2Error(f"{what} must stay under its manifest's directory")
    return path


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #

class CodecRateFIR(RationalFIR):
    """The `polyphase-kaiser5-v2` design toward the codec's 24 kHz.

    `RationalFIR` fixes its output at the L0 canonical 16 kHz in `__init__`
    only; the filter prototype, the phase cache and the streaming blocks are
    inherited unchanged. The parameterization below is the parent's with the
    output rate as an argument.
    """

    def __init__(self, source_rate: int, output_rate: int = CODEC_RATE) -> None:  # noqa: D107
        if type(source_rate) is not int or not 8_000 <= source_rate <= 192_000:
            raise ValueError("v2 resampling requires an integer rate in 8000...192000 Hz")
        divisor = math.gcd(source_rate, output_rate)
        self.up, self.down = output_rate // divisor, source_rate // divisor
        self.scale = max(self.up, self.down)
        self.half = 10 * self.scale
        self.taps = (2 * self.half + self.up - 1) // self.up + 1
        self.phases: OrderedDict[int, np.ndarray] = OrderedDict()
        self.normalization = math.fsum(
            float(np.sum(self._prototype(np.arange(start, min(start + INPUT_BLOCK_FRAMES,
                                                            2 * self.half + 1)))))
            for start in range(0, 2 * self.half + 1, INPUT_BLOCK_FRAMES)
        )


def resampler_identity() -> dict[str, Any]:
    return {
        "version": RESAMPLER_VERSION, "outputRate": CODEC_RATE, "quantization": QUANTIZATION,
        "resamplerSourceSHA256": jsonio.sha256_file(SCRIPT_DIR / "audio_resampling.py"),
        "toolSourceSHA256": jsonio.sha256_file(Path(__file__).resolve()),
    }


def _pcm_blocks(reader: wave.Wave_read) -> Iterator[np.ndarray]:
    for raw in iter(lambda: reader.readframes(INPUT_BLOCK_FRAMES), b""):
        yield np.frombuffer(raw, dtype="<i2").astype(np.float64)


def resample_to_codec_rate(source: Path, destination: Path) -> tuple[int, int]:
    """Writes mono PCM16 `source` as 24 kHz mono PCM16; returns the source rate
    and the written frame count. Blocks are PCM units, quantized like L0."""
    try:
        with wave.open(str(source), "rb") as reader:
            if reader.getnchannels() != 1 or reader.getsampwidth() != 2 or reader.getcomptype() != "NONE":
                raise N2Error(f"{source.name} must be mono PCM16")
            rate, frames = reader.getframerate(), reader.getnframes()
            if frames <= 0:
                raise N2Error(f"{source.name} has no audio")
            resampler = CodecRateFIR(rate)
            destination.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with wave.open(str(destination), "wb") as writer:
                writer.setparams((1, 2, CODEC_RATE, 0, "NONE", "not compressed"))
                for block in resampler.blocks(_pcm_blocks(reader), frames):
                    pcm = np.clip(np.rint(block), -32768, 32767).astype("<i2")
                    written += len(pcm)
                    if written > MAX_INPUT_SAMPLES:
                        raise N2Error(f"{source.name} is longer than the codec round trip's 60 s bound")
                    writer.writeframes(pcm.tobytes())
    except (ValueError, EOFError, wave.Error) as error:
        destination.unlink(missing_ok=True)
        if isinstance(error, N2Error):
            raise
        raise N2Error(f"{source.name} is not a readable mono PCM16 WAV at 8-192 kHz") from error
    return rate, written


# --------------------------------------------------------------------------- #
# Plan
# --------------------------------------------------------------------------- #

def eligible_recordings(manifest: Any) -> tuple[list[dict[str, Any]], int]:
    """The N1 cohort's eligible takes, checked, and its take count."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("kind") != N1_KIND:
        raise N2Error(f"the N1 manifest is not {N1_KIND} schema 1")
    # The N1 builder's own integrity check: an edited eligibility mark or text is refused.
    if issues := audio_qc_n1_corpus.manifest_digest_issues(manifest):
        raise N2Error(issues[0])
    takes = manifest.get("takes")
    if not isinstance(takes, list) or not takes:
        raise N2Error("the N1 manifest has no takes")
    seen: set[str] = set()
    eligible = []
    for take in takes:
        take_id = take.get("takeID") if isinstance(take, dict) else None
        if not isinstance(take_id, str) or not take_id:
            raise N2Error("every N1 take names its takeID")
        if take_id in seen:
            raise N2Error(f"{take_id}: the N1 manifest repeats a takeID")
        seen.add(take_id)
        if take.get("population") != "N1":
            raise N2Error(f"{take_id}: an N1 cohort take must be population N1")
        if not isinstance(take.get("eligible"), bool):
            raise N2Error(f"{take_id}: eligible must be true or false")
        if not take["eligible"]:
            continue
        if any(not isinstance(take.get(field), str) or not take[field] for field in KEPT_FIELDS):
            raise N2Error(f"{take_id}: an eligible take names its family, scriptID, language and text")
        if not is_sha256(take.get("wavSHA256")):
            raise N2Error(f"{take_id}: an eligible take names its WAV digest")
        duration = take.get("durationSeconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 60:
            raise N2Error(f"{take_id}: an eligible take lasts more than 0 and at most 60 seconds")
        eligible.append(take)
    if not eligible:
        raise N2Error("the N1 manifest has no eligible take")
    digests = {take["takeID"]: take["wavSHA256"] for take in eligible}
    for take in eligible:
        reference = take.get("reference")
        if reference is None:
            continue
        # A reference clip is another eligible take of the cohort, so the round trip resynthesizes it too.
        if not isinstance(reference, dict) or reference.get("takeID") == take["takeID"] \
                or reference.get("takeID") not in digests or reference.get("wavSHA256") != digests[reference["takeID"]]:
            raise N2Error(f"{take['takeID']}: its reference clip is not another eligible take of the cohort")
    if len(eligible) > MAX_ITEMS:
        raise N2Error(f"the N1 manifest has {len(eligible)} eligible takes; one round trip takes at most {MAX_ITEMS}")
    return eligible, len(takes)


def take_labels(take: dict[str, Any]) -> dict[str, Any]:
    """What a speaker-labelled N1 take carries into its plan item: its labels and its reference clip's N1 take
    id (nothing for a take that names no speaker, such as FLEURS's)."""
    if not isinstance(take.get("speaker"), str) or not take["speaker"]:
        return {}
    labels = {field: take[field] for field in LABEL_FIELDS if isinstance(take.get(field), str) and take[field]}
    if isinstance(take.get("reference"), dict):
        labels["referenceN1TakeID"] = take["reference"]["takeID"]
    return labels


def build_plan(*, n1_manifest: Path, out_dir: Path, run_id: str, label: str | None = None) -> dict[str, Any]:
    if not SAFE_RUN_ID.fullmatch(run_id):
        raise N2Error("the run id must be 1-160 letters, digits, dot, underscore or hyphen")
    manifest = load_json(n1_manifest)
    recordings, n1_count = eligible_recordings(manifest)
    base = n1_manifest.resolve().parent
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        (out_dir / INPUT_DIR).mkdir()
    except FileExistsError:
        raise N2Error("the plan's input directory already exists; plan into a new directory") from None
    items, job_items = [], []
    for index, take in enumerate(recordings, start=1):
        take_id = take["takeID"]
        source = _relative(base, take.get("wavPath"), f"{take_id}: wavPath", contained=False)
        if not source.is_file() or jsonio.sha256_file(source) != take["wavSHA256"]:
            raise N2Error(f"{take_id}: the N1 WAV is missing or does not match its digest")
        item_id = f"n2-{index:05d}"
        input_path = f"{INPUT_DIR}/{item_id}.wav"
        source_rate, count = resample_to_codec_rate(source, out_dir / input_path)
        input_sha256 = jsonio.sha256_file(out_dir / input_path)
        items.append({
            "id": item_id, "n1TakeID": take_id, **{field: take[field] for field in KEPT_FIELDS},
            "textSHA256": text_sha256(take["text"]), "n1WAVSHA256": take["wavSHA256"],
            "n1SampleRate": source_rate, "inputWAVPath": input_path, "inputWAVSHA256": input_sha256,
            "inputSampleCount": count, **take_labels(take),
        })
        job_items.append({"id": item_id, "wavPath": input_path, "wavSHA256": input_sha256})
    job = {"schemaVersion": 1, "kind": JOB_KIND, "sampleRate": CODEC_RATE, "items": job_items}
    job_path = out_dir / JOB_NAME
    jsonio.atomic_json(job_path, job, ascii=False, allow_nan=False)
    plan: dict[str, Any] = {
        "schemaVersion": 1, "kind": PLAN_KIND, "runID": run_id, "label": label,
        "n1Manifest": {"kind": N1_KIND, "sha256": jsonio.sha256_file(n1_manifest),
                       "runID": manifest.get("runID") if isinstance(manifest.get("runID"), str) else None},
        "resampler": resampler_identity(),
        "job": {"path": JOB_NAME, "sha256": jsonio.sha256_file(job_path)},
        "counts": {"n1Takes": n1_count, "planned": len(items)},
        "items": items,
    }
    plan["planDigest"] = self_digest(plan, "planDigest")
    jsonio.atomic_json(out_dir / PLAN_NAME, plan, ascii=False, allow_nan=False)
    return plan


def validate_plan(plan: Any) -> dict[str, Any]:
    if not isinstance(plan, dict) or plan.get("schemaVersion") != 1 or plan.get("kind") != PLAN_KIND:
        raise N2Error(f"the plan is not {PLAN_KIND} schema 1")
    if plan.get("planDigest") != self_digest(plan, "planDigest"):
        raise N2Error("the plan digest does not match its content")
    items = plan.get("items")
    if not isinstance(items, list) or not items or not isinstance(plan.get("job"), dict):
        raise N2Error("the plan has no items or job")
    return plan


# --------------------------------------------------------------------------- #
# Manifest
# --------------------------------------------------------------------------- #

def _checked_result(result: Any, plan: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(result, dict) or result.get("schemaVersion") != 1 or result.get("kind") != RESULT_KIND:
        raise N2Error(f"the round-trip result is not {RESULT_KIND} schema 1")
    if result.get("status") != "complete":
        raise N2Error(f"the round trip did not complete (status {result.get('status')!r})")
    expected = {
        "jobSHA256": plan["job"]["sha256"], "sampleRate": CODEC_RATE, "decodeSemantics": DECODE_SEMANTICS,
        "outputFormat": OUTPUT_FORMAT, "encoderInput": ENCODER_INPUT, "modelLoadCount": 1,
    }
    for key, value in expected.items():
        if result.get(key) != value:
            raise N2Error(f"the round-trip result's {key} is not {value!r}")
    if not is_sha256(result.get("tokenizerSHA256")) or not isinstance(result.get("modelRevision"), str) \
            or not REVISION.fullmatch(result["modelRevision"]) or not isinstance(result.get("modelID"), str):
        raise N2Error("the round-trip result does not bind its tokenizer, model and revision")
    items = result.get("items")
    planned = plan["items"]
    if not isinstance(items, list) or [item.get("id") if isinstance(item, dict) else None for item in items] \
            != [item["id"] for item in planned]:
        raise N2Error("the round-trip result's items are not exactly the plan's items in plan order")
    for item, planned_item in zip(items, planned):
        item_id = planned_item["id"]
        if item.get("status") != "complete":
            raise N2Error(f"{item_id}: the round trip did not complete")
        if item.get("inputSHA256") != planned_item["inputWAVSHA256"] \
                or item.get("outputSampleCount") != planned_item["inputSampleCount"]:
            raise N2Error(f"{item_id}: the round trip's input or length differs from the plan")
        if item.get("codebookCount") != CODEBOOKS or not isinstance(item.get("frameCount"), int) \
                or item["frameCount"] <= 0:
            raise N2Error(f"{item_id}: the round trip did not keep every codebook")
        if item.get("outputPath") != f"{item_id}.wav" or item.get("codesPath") != f"{item_id}.codes.bin" \
                or not is_sha256(item.get("outputSHA256")) or not is_sha256(item.get("codesSHA256")):
            raise N2Error(f"{item_id}: the round trip names no bound output")
    return result


def codec_identity(result: dict[str, Any]) -> dict[str, Any]:
    return {key: result.get(key) for key in (
        "tokenizerSHA256", "modelID", "catalogModelID", "catalogVariantID", "modelRepository", "modelRevision",
        "modelArtifactVersion", "catalogSHA256", "installedManifestSHA256", "modelBinding", "encoderInput",
        "decodeSemantics", "trim", "outputFormat", "codesFormat",
    )}


def build_manifest(*, plan_path: Path, result_path: Path, output: Path) -> dict[str, Any]:
    plan = validate_plan(load_json(plan_path))
    result = _checked_result(load_json(result_path), plan)
    result_dir = result_path.resolve().parent
    manifest_dir = output.resolve().parent
    if not _inside(result_dir, manifest_dir):
        raise N2Error("the round-trip output must lie under the manifest's directory")
    takes = []
    # Each N1 take's resynthesis, which a reference clip names.
    resynthesized = {planned["n1TakeID"]: {"takeID": f"{planned['n1TakeID']}--n2", "n1TakeID": planned["n1TakeID"],
                                           "wavPath": os.path.relpath(result_dir / item["outputPath"], manifest_dir),
                                           "wavSHA256": item["outputSHA256"]}
                     for item, planned in zip(result["items"], plan["items"])}
    for item, planned in zip(result["items"], plan["items"]):
        wav = result_dir / item["outputPath"]
        codes = result_dir / item["codesPath"]
        if not wav.is_file() or jsonio.sha256_file(wav) != item["outputSHA256"]:
            raise N2Error(f"{planned['id']}: the resynthesized WAV is missing or does not match its digest")
        if not codes.is_file() or jsonio.sha256_file(codes) != item["codesSHA256"]:
            raise N2Error(f"{planned['id']}: the codes are missing or do not match their digest")
        labels = {field: planned[field] for field in LABEL_FIELDS if field in planned}
        if "referenceN1TakeID" in planned:
            if planned["referenceN1TakeID"] not in resynthesized:
                raise N2Error(f"{planned['id']}: its reference clip is not an item of the plan")
            labels["reference"] = dict(resynthesized[planned["referenceN1TakeID"]])
        takes.append({
            "takeID": f"{planned['n1TakeID']}--n2", "n1TakeID": planned["n1TakeID"], "population": "N2",
            **{field: planned[field] for field in KEPT_FIELDS}, "textSHA256": planned["textSHA256"], **labels,
            "wavPath": os.path.relpath(wav, manifest_dir), "wavSHA256": item["outputSHA256"],
            "durationSeconds": item["outputSampleCount"] / CODEC_RATE, "eligible": True,
            "clampedSampleCount": item.get("clampedSampleCount"),
            "codec": {
                "tokenizerSHA256": result["tokenizerSHA256"], "modelID": result["modelID"],
                "modelRevision": result["modelRevision"], "codesSHA256": item["codesSHA256"],
                "codesPath": os.path.relpath(codes, manifest_dir), "frameCount": item["frameCount"],
                "codebookCount": item["codebookCount"],
            },
            "source": {"planItemID": planned["id"], "n1WAVSHA256": planned["n1WAVSHA256"],
                       "inputWAVSHA256": planned["inputWAVSHA256"]},
        })
    manifest: dict[str, Any] = {
        "schemaVersion": 1, "kind": MANIFEST_KIND, "runID": plan["runID"], "planDigest": plan["planDigest"],
        "n1ManifestSHA256": plan["n1Manifest"]["sha256"], "resultSHA256": jsonio.sha256_file(result_path),
        "resampler": plan["resampler"], "codec": codec_identity(result),
        "counts": {"takes": len(takes)}, "takes": takes,
    }
    manifest["manifestDigest"] = self_digest(manifest, "manifestDigest")
    jsonio.atomic_json(output, manifest, ascii=False, allow_nan=False)
    return manifest


def manifest_digest_issues(manifest: Any) -> list[str]:
    """The manifest's own kind and self digest, without its plan or audio (what a consumer checks first)."""
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("kind") != MANIFEST_KIND:
        return [f"the manifest is not {MANIFEST_KIND} schema 1"]
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return ["the manifest digest does not match its content"]
    return []


def validate_manifest(manifest: Any, *, manifest_dir: Path, plan: Any = None) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1 or manifest.get("kind") != MANIFEST_KIND:
        return {"status": "FAIL", "errors": [f"the manifest is not {MANIFEST_KIND} schema 1"]}
    if manifest.get("manifestDigest") != self_digest(manifest, "manifestDigest"):
        return {"status": "FAIL", "errors": ["the manifest digest does not match its content"]}
    errors: list[str] = []
    codec = manifest.get("codec")
    if not isinstance(codec, dict) or not is_sha256(codec.get("tokenizerSHA256")) \
            or not isinstance(codec.get("modelRevision"), str) or not REVISION.fullmatch(codec["modelRevision"]):
        return {"status": "FAIL", "errors": ["the manifest does not bind its codec identity"]}
    takes = manifest.get("takes")
    if not isinstance(takes, list) or not takes:
        return {"status": "FAIL", "errors": ["the manifest has no takes"]}
    if plan is not None:
        try:
            plan = validate_plan(plan)
        except N2Error as error:
            return {"status": "FAIL", "errors": [f"plan: {error}"]}
        if manifest.get("planDigest") != plan["planDigest"] or manifest.get("runID") != plan["runID"]:
            errors.append("the manifest does not bind its plan")
        planned = [(item["n1TakeID"], item["id"]) for item in plan["items"]]
        observed = [(take.get("n1TakeID"), _mapping(take.get("source")).get("planItemID"))
                    if isinstance(take, dict) else None for take in takes]
        if manifest.get("derivedFrom") is not None:
            # A derived manifest (`derive_manifest`) keeps a subset of its run's takes, still in plan order.
            remaining = iter(planned)
            if not all(pair in remaining for pair in observed):
                errors.append("the derived manifest's takes are not items of its plan in plan order")
        elif observed != planned:
            errors.append("the manifest's takes are not exactly the plan's items in plan order")
    derived_from = manifest.get("derivedFrom")
    if derived_from is not None and (not isinstance(derived_from, dict) or not all(
            is_sha256(derived_from.get(key)) for key in ("manifestDigest", "manifestSHA256", "n1ManifestSHA256"))):
        errors.append("derivedFrom names the source N2 manifest (digest and file SHA-256) and its N1 manifest")
    root = manifest_dir.resolve()
    take_ids: set[str] = set()
    n1_ids: set[str] = set()
    by_id = {take.get("takeID"): take for take in takes if isinstance(take, dict)}
    for take in takes:
        take_id = take.get("takeID") if isinstance(take, dict) else None
        if not isinstance(take_id, str) or take_id in take_ids:
            errors.append("every take names one unique takeID")
            continue
        take_ids.add(take_id)
        n1_id = take.get("n1TakeID")
        if not isinstance(n1_id, str) or n1_id in n1_ids or take_id != f"{n1_id}--n2":
            errors.append(f"{take_id}: the take names one unique N1 recording")
        n1_ids.add(str(n1_id))
        if take.get("population") != "N2" or take.get("eligible") is not True:
            errors.append(f"{take_id}: an N2 take is eligible population N2")
        if any(not isinstance(take.get(field), str) or not take[field] for field in KEPT_FIELDS) \
                or take.get("textSHA256") != text_sha256(str(take.get("text"))):
            errors.append(f"{take_id}: the take keeps its N1 family, script, language and bound text")
        take_codec = take.get("codec")
        if not isinstance(take_codec, dict) or any(take_codec.get(key) != codec.get(key) for key in (
                "tokenizerSHA256", "modelID", "modelRevision")) or take_codec.get("codebookCount") != CODEBOOKS \
                or not is_sha256(take_codec.get("codesSHA256")):
            errors.append(f"{take_id}: the take does not bind the manifest's codec identity")
            continue
        for path_key, digest_key, owner, what in (("wavPath", "wavSHA256", take, "WAV"),
                                                  ("codesPath", "codesSHA256", take_codec, "codes")):
            try:
                path = _relative(root, owner.get(path_key), f"{take_id}: {path_key}", contained=True)
            except N2Error as error:
                errors.append(str(error))
                continue
            if not path.is_file():
                errors.append(f"{take_id}: the {what} is missing")
            elif jsonio.sha256_file(path) != owner.get(digest_key):
                errors.append(f"{take_id}: the {what} bytes do not match their digest")
        duration = take.get("durationSeconds")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 0 < duration <= 60:
            errors.append(f"{take_id}: invalid duration")
        if any(field in take and (not isinstance(take[field], str) or not take[field]) for field in LABEL_FIELDS):
            errors.append(f"{take_id}: a speaker label is a non-empty string")
        reference = take.get("reference")
        if reference is not None:
            other = by_id.get(reference.get("takeID")) if isinstance(reference, dict) else None
            if other is None or other is take or any(reference.get(key) != other.get(key)
                                                     for key in ("n1TakeID", "wavPath", "wavSHA256")):
                errors.append(f"{take_id}: its reference clip is not another take of the manifest")
    counts = {"takes": len(takes)}
    if manifest.get("counts") != counts:
        errors.append("the manifest's counts do not match its takes")
    return {"status": "PASS" if not errors else "FAIL", "errors": errors, "counts": counts}


def derive_manifest(*, source: Path, n1_manifest: dict[str, Any], n1_manifest_sha256: str, output: Path,
                    derived_from: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    """An N2 cohort over a subset of a qc-n2 run's recordings, without a new round trip.

    `source` is the run's manifest; it must validate (every WAV and codes file
    hashed) and must not itself be derived. `n1_manifest` is the derived N1
    manifest, a subset of the one the run resynthesized: its
    `derivedFrom.manifestSHA256` must be the run's `n1ManifestSHA256`, and
    `n1_manifest_sha256` is the digest of its file. The derived manifest keeps,
    unchanged and in plan order, the source takes whose N1 recording the derived
    N1 manifest keeps eligible, and every such recording must have one. Each
    kept take's WAV and codes are linked beside `output` under the same
    relative paths (a hard link, or a verified copy across volumes). The
    manifest binds `n1ManifestSHA256` to the derived N1 manifest and records
    its source run and rule in `derivedFrom`. The source run is never written.
    `dry_run` returns the manifest without writing or linking anything.
    """
    source = Path(source)
    manifest = load_json(source)
    report = validate_manifest(manifest, manifest_dir=source.parent)
    if report["status"] != "PASS":
        raise N2Error(f"the source N2 manifest does not validate: {report['errors'][0]}")
    if manifest.get("derivedFrom") is not None:
        raise N2Error("the source N2 manifest is itself derived; derive from the qc-n2 run's own manifest")
    if _mapping(n1_manifest.get("derivedFrom")).get("manifestSHA256") != manifest.get("n1ManifestSHA256"):
        raise N2Error("the derived N1 manifest does not derive from the N1 manifest this run resynthesized "
                      "(n1ManifestSHA256)")
    eligible, _count = eligible_recordings(n1_manifest)
    keep = {take["takeID"]: take for take in eligible}
    takes = [take for take in manifest["takes"] if take["n1TakeID"] in keep]
    missing = sorted(set(keep) - {take["n1TakeID"] for take in takes})
    if missing:
        raise N2Error(f"{len(missing)} eligible recordings of the derived N1 manifest have no resynthesis in the "
                      f"run (e.g. {missing[0]})")
    for take in takes:
        recording = keep[take["n1TakeID"]]
        if _mapping(take.get("source")).get("n1WAVSHA256") != recording["wavSHA256"] \
                or any(take[field] != recording[field] for field in KEPT_FIELDS):
            raise N2Error(f"{take['takeID']}: the derived N1 recording differs from the one the run resynthesized")
        reference = take.get("reference")
        if isinstance(reference, dict) and reference.get("n1TakeID") not in keep:
            raise N2Error(f"{take['takeID']}: its reference clip's recording is not kept")
    derived = {key: value for key, value in manifest.items() if key != "manifestDigest"}
    derived.update({
        "n1ManifestSHA256": n1_manifest_sha256,
        "derivedFrom": {**derived_from, "manifestDigest": manifest["manifestDigest"],
                        "manifestSHA256": jsonio.sha256_file(source),
                        "n1ManifestSHA256": manifest["n1ManifestSHA256"], "takes": len(manifest["takes"])},
        "counts": {"takes": len(takes)}, "takes": takes,
    })
    derived["manifestDigest"] = self_digest(derived, "manifestDigest")
    if dry_run:
        return derived
    output = Path(output)
    out_dir = output.resolve().parent
    if _inside(out_dir, source.resolve().parent):
        raise N2Error("the derived manifest goes into a new directory, never into its source run")
    data = jsonio.pretty_bytes(derived, ascii=False, allow_nan=False)
    if output.exists() and output.read_bytes() != data:
        raise N2Error(f"{output.name} already holds another manifest; derive into a new directory")
    for take in takes:
        for relative, digest, what in ((take["wavPath"], take["wavSHA256"], "wavPath"),
                                       (take["codec"]["codesPath"], take["codec"]["codesSHA256"], "codesPath")):
            where = f"{take['takeID']}: {what}"
            try:
                audio_qc_n1_corpus._place(_relative(source.parent, relative, where, contained=True),
                                          _relative(out_dir, relative, where, contained=True), digest)
            except audio_qc_n1_corpus.N1Error as error:
                raise N2Error(str(error)) from None
    jsonio.atomic_write_bytes(output, data)
    report = validate_manifest(derived, manifest_dir=out_dir)
    if report["status"] != "PASS":
        raise N2Error(f"the derived N2 manifest does not validate: {report['errors'][0]}")
    return derived


# --------------------------------------------------------------------------- #
# Command line
# --------------------------------------------------------------------------- #

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="write the 24 kHz inputs, the CLI job and the plan")
    plan.add_argument("--n1-manifest", type=Path, required=True)
    plan.add_argument("--out-dir", type=Path, required=True)
    plan.add_argument("--run-id", required=True)
    plan.add_argument("--label")
    manifest = commands.add_parser("manifest", help="bind the round-trip result to the plan")
    manifest.add_argument("--plan", type=Path, required=True)
    manifest.add_argument("--result", type=Path, required=True, help="the CLI's codec-roundtrip-result.json")
    manifest.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate-manifest", help="recompute digests and check the plan binding")
    validate.add_argument("--manifest", type=Path, required=True)
    validate.add_argument("--plan", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            value = build_plan(n1_manifest=args.n1_manifest, out_dir=args.out_dir, run_id=args.run_id,
                               label=args.label)
            print(json.dumps({"runID": value["runID"], "counts": value["counts"], "planDigest": value["planDigest"],
                              "job": value["job"]}))
            return 0
        if args.command == "manifest":
            value = build_manifest(plan_path=args.plan, result_path=args.result, output=args.output)
            print(json.dumps(value["counts"]))
            return 0
        report = validate_manifest(load_json(args.manifest), manifest_dir=args.manifest.parent,
                                   plan=load_json(args.plan) if args.plan else None)
        print(json.dumps(report, indent=2))
        return 0 if report["status"] == "PASS" else 1
    except (N2Error, OSError) as error:
        print(f"audio-qc-n2-resynthesis: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
