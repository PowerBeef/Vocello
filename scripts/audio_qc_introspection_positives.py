#!/usr/bin/env python3
"""Class I positives: the declared T2 and T3 injection sets (audit 2026-09-25 sections 5.1, 5.2; AQ-07).

The class I detectors read the engine's introspection summary (codebook-0
token cycles, the talker's entropy and EOS trajectory), which only a take's
own generation records, so a PCM edit (T1) cannot make their positives. Two
declared constructions do, on the confirmation takes (population N3) they are
confirmed with:

- COD-LOOP@1 (tier T2, population P2): a take's recorded codec trace with a
  span of frames repeated (`lib/qc_qualification/codec_trace.py`), decoded by
  `vocello bench --codec-loop`. Its summary is the Python mirror
  (`audio_qc_observations.introspection_summary`) over the looped codebook 0:
  the cycle fields are exact; entropy and EOS need the talker's logits, so the
  entry carries none and only the token-loop detector reads P2.
- GEN-NOEOS@1 (tier T3, population P3): the take regenerated (same text,
  voice, batch seed and delivery) with the registered internal-diagnostics
  knob QWENVOICE_TALKER_EOS_SUPPRESSION_FRAMES=N, which holds back the
  talker's first sampled EOS for N codec frames. The take's own engine row
  (bound by its WAV digest) gives its summary and records the hold: the frames
  and the frame it opened at. N = 0 is the sham. Only published takes are
  entries, as only published takes are N3 negatives: a take the engine's
  mandatory Fast QC refused is counted, never built.

Each entry is declared with its provenance (`audio_qc_detector_calibration.py`
POSITIVE_PROVENANCE): T2 names its source trace, recipe and decoder digests,
T3 its knob id and recipe digest; both name their construction catalog
version (1). `audio_qc_calibration_set.py score --set` measures the entries
(their own generation's summary, bound to their WAV), and the driver's
`scores --injection-set` reads them as P2, P3 and S.

Commands:
  loop-plan   --takes <manifest> --diagnostics <dir> --traces <dir> --out-dir <new dir>
              [--sample-per-cell N] [--sample-seed S] [--catalog-seed C]
              Bind each confirmation take to its recorded codec trace (engine row
              by WAV digest -> generation id and trace digest -> the lane's copy of
              the trace, whose codebook 0 must reproduce the take's own
              introspection), draw families stratified by language, place each
              take's loop, and write the text-free CLI job and the plan.
  loop-set    --plan <codec-loop-plan.json> --result <codec-loop-result.json>
              --takes <manifest> --output <new dir>
              Replay every recipe on its source trace and require the CLI's
              mutated trace byte for byte, then write the P2/S injection set.
  noeos-plan  --takes <manifest> --out-dir <new dir> [--sample-per-cell N]
              [--sample-seed S] [--catalog-seed C]
              Draw Custom and Voice Design families, and write one line file per
              (source batch, variant) with the rows the lane runs `vocello batch`
              on under the knob, and the plan.
  noeos-set   --plan <noeos-plan.json> --batch-results <dir> --wav-root <dir>
              --diagnostics <dir> --takes <manifest> --output <new dir>
              Bind the batch outputs by item index, require each take's engine
              row to record the planned hold, and write the P3/S injection set.
  verify      --set <injection-set.json> --takes <manifest>
              Recompute every digest a set declares (and replay each T2 recipe).

Everything this module writes is an untracked build artifact: plans, jobs,
line files (the batch texts, like the take plan's), WAV copies and sets (ids
and digests only). Paths are relative to the file that names them.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
from typing import Any, Iterable, Mapping, Sequence

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import audio_qc_calibration_takes as takes_tool  # noqa: E402
from lib import audio_qc_observations, jsonio  # noqa: E402
from lib.language_metrics import is_sha256  # noqa: E402
from lib.qc_qualification import codec_trace, recordings  # noqa: E402
from lib.qc_qualification.pcm import json_digest, pcm_digest  # noqa: E402

GENERATOR = "audio-qc-introspection-positives/1"
SET_KIND = "audio-qc-injection-set"
LOOP_PLAN_KIND = "audio-qc-codec-loop-plan"
LOOP_JOB_KIND = "audio-qc-codec-loop-job"
LOOP_RESULT_KIND = "audio-qc-codec-loop-result"
NOEOS_PLAN_KIND = "audio-qc-noeos-plan"
SAMPLE_SCHEMA = "vocello.audioqc.introspection-sampling/1"
DECODER_SCHEMA = "vocello.audioqc.t2-decoder/1"
TRACE_FILE = "codec-trace-v1.bin"
ENGINE_RATE = 24_000
CODEC_FRAMES_PER_SECOND = 12.5
DEFAULT_SAMPLE_PER_CELL = 150
DEFAULT_SAMPLE_SEED = 1
DEFAULT_CATALOG_SEED = 7
CLASSES = ["I"]
POPULATIONS = {"T2": "P2", "T3": "P3"}

# GEN-NOEOS@1: the codec frames the first sampled EOS is held back for (audit: 6-50 frames; N = 0 is the sham).
NOEOS_CATALOG_VERSION = 1
NOEOS_INJECTOR_ID = "GEN-NOEOS"
NOEOS_INJECTOR = f"{NOEOS_INJECTOR_ID}@1"
NOEOS_MECHANISM = "T3-controlled-generation"
NOEOS_KNOB = "QWENVOICE_TALKER_EOS_SUPPRESSION_FRAMES"
NOEOS_VARIANTS: dict[str, int] = {"sham": 0, "mild": 6, "moderate": 18, "severe": 50}
NOEOS_MODES = ("custom", "design")
# The lane passes --app-delivery to every batch, as qc-takes does (take policy version 2).
NOEOS_DELIVERY = "app-default"
HOLD_FRAMES, HOLD_START = takes_tool.EOS_HOLD_TIMINGS
# The engine summary's integer token fields, which the Python mirror reproduces exactly.
CYCLE_FIELDS = ("codecFrameCount", "longestRepeatedTokenRunFrames", "tokenCyclePeriod", "tokenCycleSpanFrames",
                "tokenCycleRepeats", "tokenCycleStartFrame")
# What an entry copies of its source take (never its WAV, introspection or long-form block).
SOURCE_FIELDS = ("family", "scriptID", "language", "role", "mode", "variant", "variation", "voice", "seed",
                 "batchID", "cell", "voiceLanguage", "textSHA256")
BATCH_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,199}")
FIELD_SEPARATOR = takes_tool.FIELD_SEPARATOR


class PositivesError(ValueError):
    """An input, a binding or a precondition the builder refuses."""


# --------------------------------------------------------------------------- #
# Shared
# --------------------------------------------------------------------------- #

def load_json(path: Path, what: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PositivesError(f"{what} {Path(path).name} is unreadable: {error}") from error


def load_takes(path: Path) -> tuple[dict, str]:
    """The confirmation takes manifest (N3) and the SHA-256 of its bytes, self-digest checked."""
    manifest = load_json(path, "the takes manifest")
    if issues := takes_tool.manifest_digest_issues(manifest):
        raise PositivesError(f"{Path(path).name}: {issues[0]}")
    return manifest, jsonio.sha256_file(Path(path))


def generated(manifest: Mapping[str, Any]) -> list[dict]:
    return [take for take in manifest.get("takes") or () if isinstance(take, dict) and take.get("status") == "generated"]


def long_form(take: Mapping[str, Any]) -> bool:
    return take.get("cell") == takes_tool.LONG_FORM or take.get("longForm") is not None


def self_digest(value: Mapping[str, Any], field: str) -> str:
    return json_digest({key: item for key, item in value.items() if key != field})


def new_directory(path: Path) -> Path:
    try:
        Path(path).mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise PositivesError(f"{Path(path).name} already exists: every output directory is new") from error
    return Path(path)


def inside(base: Path, relative: Any, what: str) -> Path:
    """A path a file names, resolved under its directory; anything else is refused."""
    if not isinstance(relative, str) or not relative or os.path.isabs(relative):
        raise PositivesError(f"{what} is a relative path")
    root = Path(base).resolve()
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise PositivesError(f"{what} leaves its directory") from error
    return resolved


def sample_rank(seed: int, key: str, kind: str, value: str) -> str:
    return hashlib.sha256("|".join((SAMPLE_SCHEMA, str(seed), key, kind, value)).encode("utf-8")).hexdigest()


def stratified_sample(pool: Mapping[str, str], count: int, *, seed: int, key: str) -> list[str]:
    """`count` families of `pool` (family -> language), as even across languages as the pool allows; 0 takes
    every family. Within a language, families go in ascending seeded rank; quotas fill round-robin over the
    languages in their own seeded order. Deterministic in (pool, count, seed, key); the result is sorted."""
    by_language: dict[str, list[str]] = {}
    for family, language in pool.items():
        by_language.setdefault(language, []).append(family)
    if count <= 0:
        return sorted(pool)
    for language, families in by_language.items():
        families.sort(key=lambda family: sample_rank(seed, key, "family", family))
    order = sorted(by_language, key=lambda language: sample_rank(seed, key, "language", language))
    quota = dict.fromkeys(order, 0)
    left = count
    while left > 0:
        progressed = False
        for language in order:
            if left and quota[language] < len(by_language[language]):
                quota[language] += 1
                left -= 1
                progressed = True
        if not progressed:
            break
    return sorted(family for language in order for family in by_language[language][:quota[language]])


def one_take_per_family(takes: Iterable[dict]) -> dict[str, dict]:
    """family -> its eligible take (the lowest take id when a family has several)."""
    chosen: dict[str, dict] = {}
    for take in sorted(takes, key=lambda item: item["takeID"]):
        chosen.setdefault(take["family"], take)
    return chosen


def row_view(record: Mapping[str, Any]) -> dict[str, Any] | None:
    """What the builder reads of an engine telemetry row, raw or reduced by `collect-diagnostics`."""
    generation_id = record.get("generationID")
    notes = record.get("notes") if isinstance(record.get("notes"), dict) else {}
    if not isinstance(generation_id, str) or not takes_tool.GENERATION_ID.fullmatch(generation_id):
        return None
    timings = record.get("timingsMS") if isinstance(record.get("timingsMS"), dict) else {}
    identity = record.get("modelRuntimeIdentity") if isinstance(record.get("modelRuntimeIdentity"), dict) else {}
    tokenizer = record.get("speechTokenizerDigest") or identity.get("speechTokenizerDigest")
    return {
        "generationID": generation_id.upper(),
        "codecTraceSHA256": notes.get("codecTraceSHA256") if is_sha256(notes.get("codecTraceSHA256")) else None,
        "hold": {key: timings[key] for key in takes_tool.EOS_HOLD_TIMINGS if takes_tool._count(timings.get(key))},
        "tokenizer": tokenizer if isinstance(tokenizer, str) and takes_tool.TOKENIZER_DIGEST.fullmatch(tokenizer)
        else None,
    }


def engine_rows(diagnostics: Path, wav_digests: set[str]) -> dict[str, list[dict]]:
    """Each WAV digest's distinct engine row views (the rows whose `samplingWAVDigest` is it)."""
    found: dict[str, list[dict]] = {}
    for record in takes_tool._jsonl(Path(diagnostics) / "engine" / "generations.jsonl"):
        notes = record.get("notes") if isinstance(record.get("notes"), dict) else {}
        digest = notes.get("samplingWAVDigest")
        view = row_view(record) if digest in wav_digests else None
        if view is not None and view not in found.setdefault(digest, []):
            found[digest].append(view)
    return found


def introspection_of(diagnostics: Path, digests: set[str]) -> dict[str, dict]:
    """Each WAV digest's agreed engine introspection summary (bound to that digest)."""
    summaries = takes_tool.engine_introspections(Path(diagnostics), digests)
    return {digest: found[0] for digest, found in summaries.items() if len(found) == 1}


def pcm_of(path: Path) -> tuple[str, float]:
    samples = recordings.read_pcm16_wav(path)
    return pcm_digest(samples), round(samples.size / ENGINE_RATE, 6)


def entry_base(take: Mapping[str, Any], entry_id: str, wav_path: str, wav_sha256: str,
               duration: float) -> dict[str, Any]:
    entry = {key: take[key] for key in SOURCE_FIELDS if key in take}
    entry.update(takeID=entry_id, sourceTakeID=take["takeID"], status="generated", wavPath=wav_path,
                 wavSHA256=wav_sha256, durationSeconds=duration)
    return entry


def not_applicable(injector: str, variants: Iterable[str], reasons: Mapping[str, int]) -> dict[str, Any]:
    """The skipped source takes per variant, in `audio_qc_calibration_set.py`'s report shape."""
    return {injector: {"byVariant": {variant: dict(sorted(reasons.items())) for variant in variants}}}


def write_set(output: Path, head: Mapping[str, Any], entries: list[dict]) -> dict:
    injection_set = {**head, "entries": entries, "entriesSHA256": json_digest(entries)}
    jsonio.atomic_json(output / "injection-set.json", injection_set, ascii=True, allow_nan=False)
    return injection_set


# --------------------------------------------------------------------------- #
# COD-LOOP (T2)
# --------------------------------------------------------------------------- #

def bind_trace(take: Mapping[str, Any], rows: Mapping[str, list[dict]], traces: Path) -> tuple[dict, list | str]:
    """The take's engine row and recorded trace frames, or a not-applicable reason."""
    found = rows.get(take["wavSHA256"]) or []
    if not found:
        return {}, "no-engine-row"
    if len({(row["generationID"], row["codecTraceSHA256"]) for row in found}) != 1:
        return {}, "engine-rows-disagree"
    row = found[0]
    if row["codecTraceSHA256"] is None:
        return row, "no-codec-trace"
    path = Path(traces) / row["generationID"] / TRACE_FILE
    if not path.is_file():
        return row, "trace-file-missing"
    data = path.read_bytes()
    if codec_trace.sha256(data) != row["codecTraceSHA256"]:
        raise PositivesError(f"{take['takeID']}: its trace file is not the trace its engine row recorded")
    try:
        frames = codec_trace.complete_frames(data)
    except codec_trace.TraceError:
        return row, "trace-incomplete"
    summary = take.get("engineIntrospection")
    if isinstance(summary, dict):
        # The trace's codebook 0 is the token sequence the engine summarized: its cycles must be the take's.
        mirror = audio_qc_observations.introspection_summary(codec_trace.codebook0(frames))
        if any(mirror[key] != summary.get(key) for key in CYCLE_FIELDS):
            raise PositivesError(f"{take['takeID']}: its codec trace does not reproduce the take's own introspection "
                                 "(another generation's trace)")
    return row, frames


def loop_plan(*, takes_path: Path, diagnostics: Path, traces: Path, out_dir: Path, per_cell: int,
              sample_seed: int, catalog_seed: int) -> dict:
    manifest, manifest_sha256 = load_takes(takes_path)
    candidates = [take for take in generated(manifest) if not long_form(take)]
    rows = engine_rows(diagnostics, {take["wavSHA256"] for take in candidates})
    reasons: Counter = Counter()
    long_takes = sum(1 for take in generated(manifest) if long_form(take))
    if long_takes:
        reasons["long-form"] = long_takes
    eligible: list[dict] = []
    bound: dict[str, tuple[dict, list]] = {}
    for take in candidates:
        row, frames = bind_trace(take, rows, traces)
        if isinstance(frames, str):
            reasons[frames] += 1
            continue
        start = codec_trace.placement(len(frames), seed=catalog_seed, take_id=take["takeID"])
        if start is None:
            reasons["trace-too-short"] += 1
            continue
        eligible.append(take)
        bound[take["takeID"]] = (row, frames)
    by_family = one_take_per_family(eligible)
    families = stratified_sample({family: take["language"] for family, take in by_family.items()}, per_cell,
                                 seed=sample_seed, key=codec_trace.INJECTOR_ID)
    selected = sorted((by_family[family] for family in families), key=lambda take: take["takeID"])
    if not selected:
        raise PositivesError("no confirmation take has a bound, complete codec trace long enough for COD-LOOP")
    out = new_directory(out_dir)
    (out / "traces").mkdir()
    tokenizers = {bound[take["takeID"]][0]["tokenizer"] for take in selected}
    tokenizer = next(iter(tokenizers)) if len(tokenizers) == 1 else None
    tokenizer = tokenizer.removeprefix("sha256:") if isinstance(tokenizer, str) else None
    items, entries = [], []
    for take in selected:
        row, frames = bound[take["takeID"]]
        trace_path = f"traces/{row['codecTraceSHA256']}.bin"
        shutil.copyfile(Path(traces) / row["generationID"] / TRACE_FILE, out / trace_path)
        start = codec_trace.placement(len(frames), seed=catalog_seed, take_id=take["takeID"])
        for variant in codec_trace.VARIANTS:
            entry_id = f"{take['takeID']}__{codec_trace.INJECTOR_ID}__{variant}"
            item_id = f"cl-{hashlib.sha256(entry_id.encode('utf-8')).hexdigest()[:24]}"
            recipe = codec_trace.recipe(variant, start)
            items.append({"id": item_id, "tracePath": trace_path, "traceSHA256": row["codecTraceSHA256"],
                          "recipe": recipe})
            entries.append({"entryID": entry_id, "itemID": item_id, "sourceTakeID": take["takeID"],
                            "family": take["family"], "language": take["language"], "variant": variant,
                            "severity": codec_trace.SEVERITIES[variant],
                            "population": "S" if variant == "sham" else POPULATIONS["T2"],
                            "recipe": recipe, "recipeSHA256": json_digest(recipe),
                            "traceSHA256": row["codecTraceSHA256"], "sourceFrameCount": len(frames),
                            "generationID": row["generationID"]})
    job = {"schemaVersion": 1, "kind": LOOP_JOB_KIND, "sampleRate": ENGINE_RATE, "tokenizerSHA256": tokenizer,
           "items": items}
    jsonio.atomic_json(out / "codec-loop-job.json", job, ascii=True, allow_nan=False)
    plan = {
        "schemaVersion": 1, "kind": LOOP_PLAN_KIND, "generator": GENERATOR,
        "privacy": "ids and digests only: no text, transcript or path",
        "takesManifest": {"fileSHA256": manifest_sha256, "manifestDigest": manifest["manifestDigest"],
                          "runID": manifest.get("runID"), "split": manifest.get("split")},
        "catalog": {"injector": codec_trace.INJECTOR, "version": codec_trace.CATALOG_VERSION, "seed": catalog_seed,
                    "variants": {name: list(value) for name, value in codec_trace.VARIANTS.items()},
                    "placement": [codec_trace.PLACEMENT_LOW, codec_trace.PLACEMENT_HIGH]},
        "sampling": {"schema": SAMPLE_SCHEMA, "perCell": per_cell, "seed": sample_seed},
        "job": {"path": "codec-loop-job.json", "sha256": jsonio.sha256_file(out / "codec-loop-job.json"),
                "tokenizerSHA256": tokenizer},
        "notApplicable": dict(sorted(reasons.items())),
        "counts": {"candidates": len(candidates), "eligible": len(eligible), "eligibleFamilies": len(by_family),
                   "selected": len(selected), "items": len(items)},
        "entries": entries,
    }
    plan["planDigest"] = self_digest(plan, "planDigest")
    jsonio.atomic_json(out / "codec-loop-plan.json", plan, ascii=True, allow_nan=False)
    return plan


def load_plan(path: Path, kind: str) -> dict:
    plan = load_json(path, "the plan")
    if not isinstance(plan, dict) or plan.get("kind") != kind or plan.get("schemaVersion") != 1:
        raise PositivesError(f"{Path(path).name} is not an {kind} schema 1 file")
    if plan.get("planDigest") != self_digest(plan, "planDigest"):
        raise PositivesError(f"{Path(path).name} does not match its planDigest (edited after it was written)")
    return plan


def decoder_identity(result: Mapping[str, Any]) -> dict[str, Any]:
    """What decoded a T2 construction: the speech tokenizer's weights, the schedule, window and output stage."""
    keys = ("tokenizerSHA256", "modelRepository", "modelRevision", "modelArtifactVersion", "decodeSemantics",
            "sampleWindow", "outputStage", "markingEnabled", "sampleRate")
    identity = {"schema": DECODER_SCHEMA, **{key: result.get(key) for key in keys}}
    if not is_sha256(identity["tokenizerSHA256"]) or result.get("modelBinding") != \
            "all_installed_file_bytes_match_pinned_catalog" or identity["sampleRate"] != ENGINE_RATE:
        raise PositivesError("the codec-loop result names no catalog-bound tokenizer at 24 kHz")
    return identity


def loop_introspection(frames: Sequence[Sequence[int]], wav_sha256: str) -> dict[str, Any]:
    summary = audio_qc_observations.introspection_summary(codec_trace.codebook0(frames))
    summary["wavSHA256"] = wav_sha256
    if issues := takes_tool.introspection_issues(summary):
        raise PositivesError(f"the mirror summary is malformed: {issues[0]}")
    return summary


def loop_set(*, plan_path: Path, result_path: Path, takes_path: Path, output: Path) -> dict:
    plan = load_plan(plan_path, LOOP_PLAN_KIND)
    manifest, manifest_sha256 = load_takes(takes_path)
    if manifest_sha256 != plan["takesManifest"]["fileSHA256"]:
        raise PositivesError("the takes manifest is not the one the plan was drawn from")
    plan_dir, result_dir = Path(plan_path).parent, Path(result_path).parent
    job_path = inside(plan_dir, plan["job"]["path"], "the plan's job")
    result = load_json(result_path, "the codec-loop result")
    if not isinstance(result, dict) or result.get("kind") != LOOP_RESULT_KIND or result.get("schemaVersion") != 1:
        raise PositivesError(f"{Path(result_path).name} is not an {LOOP_RESULT_KIND} schema 1 file")
    if result.get("status") != "complete":
        raise PositivesError(f"the codec-loop replay did not complete ({result.get('status')!r})")
    if result.get("jobSHA256") != plan["job"]["sha256"] or jsonio.sha256_file(job_path) != plan["job"]["sha256"]:
        raise PositivesError("the codec-loop result ran another job than the plan's")
    decoder = decoder_identity(result)
    decoder_sha256 = json_digest(decoder)
    items = {item.get("id"): item for item in result.get("items") or () if isinstance(item, dict)}
    takes = {take["takeID"]: take for take in generated(manifest)}
    out = new_directory(output)
    (out / "wav").mkdir()
    (out / "traces").mkdir()
    source_pcm: dict[str, str] = {}
    entries = []
    for planned in plan["entries"]:
        item = items.get(planned["itemID"])
        where = planned["entryID"]
        if not item or item.get("status") != "complete" or item.get("recipe") != planned["recipe"] \
                or item.get("traceSHA256") != planned["traceSHA256"]:
            raise PositivesError(f"{where}: the replay did not complete the planned recipe on the planned trace")
        take = takes.get(planned["sourceTakeID"])
        if take is None or take["wavSHA256"] is None:
            raise PositivesError(f"{where}: its source take is not a generated take of the manifest")
        source = (plan_dir / "traces" / f"{planned['traceSHA256']}.bin").read_bytes()
        if codec_trace.sha256(source) != planned["traceSHA256"]:
            raise PositivesError(f"{where}: the plan's copy of its source trace changed")
        mutated = codec_trace.apply(codec_trace.complete_frames(source), planned["recipe"])
        mutated_bytes = codec_trace.encode(mutated)
        mutated_sha256 = codec_trace.sha256(mutated_bytes)
        codes = inside(result_dir, item.get("codesPath"), f"{where}: codesPath")
        if item.get("codesSHA256") != mutated_sha256 or codec_trace.sha256(codes.read_bytes()) != mutated_sha256 \
                or item.get("mutatedFrameCount") != len(mutated):
            raise PositivesError(f"{where}: the replay decoded another trace than its recipe makes")
        wav = inside(result_dir, item.get("wavPath"), f"{where}: wavPath")
        if not wav.is_file() or jsonio.sha256_file(wav) != item.get("wavSHA256"):
            raise PositivesError(f"{where}: its WAV is missing or differs from the replay's digest")
        destination = out / "wav" / f"{where}.wav"
        shutil.copyfile(wav, destination)
        for digest, data in ((planned["traceSHA256"], source), (mutated_sha256, mutated_bytes)):
            (out / "traces" / f"{digest}.bin").write_bytes(data)
        if take["takeID"] not in source_pcm:
            source_pcm[take["takeID"]] = pcm_of(inside(Path(takes_path).parent, take["wavPath"], "a take's WAV"))[0]
        output_pcm, duration = pcm_of(destination)
        entry = entry_base(take, where, f"wav/{where}.wav", item["wavSHA256"], duration)
        entry["engineIntrospection"] = loop_introspection(mutated, item["wavSHA256"])
        recipe = planned["recipe"]
        entry["injection"] = {
            "mechanism": codec_trace.MECHANISM, "catalogVersion": codec_trace.CATALOG_VERSION,
            "injector": codec_trace.INJECTOR, "injectorID": codec_trace.INJECTOR_ID, "injectorVersion": 1,
            "classes": list(codec_trace.CLASSES), "variant": planned["variant"], "severity": planned["severity"],
            "population": planned["population"],
            "parameters": {key: recipe[key] for key in ("startFrame", "spanFrames", "extraCopies")},
            "recipe": recipe, "sourceWAVSHA256": take["wavSHA256"], "sourcePCMSHA256": source_pcm[take["takeID"]],
            "outputPCMSHA256": output_pcm, "sourceFrameCount": planned["sourceFrameCount"],
            "mutatedTraceSHA256": mutated_sha256, "marked": item.get("marked"),
            "provenance": {"tier": "T2", "traceSHA256": planned["traceSHA256"],
                           "recipeSHA256": json_digest(recipe), "decoderSHA256": decoder_sha256},
        }
        entries.append(entry)
    head = {
        "schemaVersion": 1, "kind": SET_KIND, "generator": GENERATOR, "tier": "T2",
        "privacy": "ids and digests only: no text, transcript or path",
        "sourceManifest": {"sha256": manifest_sha256, "manifestDigest": manifest["manifestDigest"]},
        "catalogVersion": codec_trace.CATALOG_VERSION, "catalogSeed": plan["catalog"]["seed"], "classes": CLASSES,
        "sampling": {"schema": SAMPLE_SCHEMA, "perCell": plan["sampling"]["perCell"],
                     "seed": plan["sampling"]["seed"]},
        "decoder": decoder, "decoderSHA256": decoder_sha256,
        "constructionPlan": {"sha256": jsonio.sha256_file(Path(plan_path)), "planDigest": plan["planDigest"]},
        "codecLoopResult": {"sha256": jsonio.sha256_file(Path(result_path)), "runID": result.get("runID")},
        "notApplicable": not_applicable(codec_trace.INJECTOR, codec_trace.VARIANTS, plan["notApplicable"]),
        "counts": dict(Counter(entry["injection"]["population"] for entry in entries)),
    }
    return write_set(out, head, entries)


# --------------------------------------------------------------------------- #
# GEN-NOEOS (T3)
# --------------------------------------------------------------------------- #

def noeos_recipe(take: Mapping[str, Any], variant: str, catalog_seed: int) -> dict[str, Any]:
    """What one knob take is: the source take regenerated with the hold, bound by the source's identity."""
    voice = take.get("voice") or {}
    return {"injector": NOEOS_INJECTOR, "variant": variant, "knob": NOEOS_KNOB,
            "suppressionFrames": NOEOS_VARIANTS[variant], "catalogSeed": catalog_seed,
            "sourceTakeID": take["takeID"], "sourceWAVSHA256": take["wavSHA256"], "textSHA256": take["textSHA256"],
            "mode": take["mode"], "takeVariant": take["variant"], "variation": take["variation"],
            "seed": take["seed"], "voiceKey": takes_tool.voice_key(dict(voice)), "delivery": NOEOS_DELIVERY}


def noeos_reason(take: Mapping[str, Any]) -> str | None:
    """Why a take cannot be regenerated under the knob by the lane, or None."""
    if long_form(take):
        return "long-form"
    if take.get("mode") not in NOEOS_MODES:
        return "clone-regeneration"
    voice = take.get("voice") if isinstance(take.get("voice"), dict) else {}
    if (take["mode"] == "custom" and not voice.get("id")) or (take["mode"] == "design" and not voice.get("brief")):
        return "voice-unrecorded"
    if not takes_tool._count(take.get("seed")) or not isinstance(take.get("text"), str) \
            or not is_sha256(take.get("textSHA256")) or not take.get("batchID"):
        return "request-unrecorded"
    return None


def noeos_plan(*, takes_path: Path, out_dir: Path, per_cell: int, sample_seed: int, catalog_seed: int) -> dict:
    manifest, manifest_sha256 = load_takes(takes_path)
    reasons: Counter = Counter()
    eligible = []
    for take in generated(manifest):
        reason = noeos_reason(take)
        if reason:
            reasons[reason] += 1
        else:
            eligible.append(take)
    by_family = one_take_per_family(eligible)
    families = stratified_sample({family: take["language"] for family, take in by_family.items()}, per_cell,
                                 seed=sample_seed, key=NOEOS_INJECTOR_ID)
    selected = [by_family[family] for family in families]
    if not selected:
        raise PositivesError("no confirmation take can be regenerated under the knob (Custom or Voice Design)")
    by_batch: dict[str, list[dict]] = {}
    for take in sorted(selected, key=lambda item: item["takeID"]):
        by_batch.setdefault(take["batchID"], []).append(take)
    out = new_directory(out_dir)
    (out / "batches").mkdir()
    batches, entries, rows = [], [], []
    for variant, frames in NOEOS_VARIANTS.items():
        for source_batch, members in sorted(by_batch.items()):
            first = members[0]
            if any((take["mode"], take["variant"], take["variation"], take["seed"], json.dumps(take["voice"],
                   sort_keys=True)) != (first["mode"], first["variant"], first["variation"], first["seed"],
                                        json.dumps(first["voice"], sort_keys=True)) for take in members):
                raise PositivesError(f"{source_batch}: its takes disagree on the batch's request")
            batch_id = f"{source_batch}__{NOEOS_INJECTOR_ID}__{variant}"
            if not BATCH_ID.fullmatch(batch_id):
                raise PositivesError(f"{batch_id}: not a safe batch id")
            path = out / "batches" / f"{batch_id}.txt"
            path.write_text("\n".join(take["text"] for take in members) + "\n", encoding="utf-8")
            entry_ids = []
            for index, take in enumerate(members):
                entry_id = f"{take['takeID']}__{NOEOS_INJECTOR_ID}__{variant}"
                recipe = noeos_recipe(take, variant, catalog_seed)
                entry_ids.append(entry_id)
                entries.append({"entryID": entry_id, "batchID": batch_id, "index": index,
                                "sourceTakeID": take["takeID"], "family": take["family"],
                                "language": take["language"], "variant": variant, "severity": variant,
                                "population": "S" if variant == "sham" else POPULATIONS["T3"],
                                "suppressionFrames": frames, "recipe": recipe, "recipeSHA256": json_digest(recipe)})
            voice = first["voice"]
            batches.append({"batchID": batch_id, "sourceBatchID": source_batch, "variant": variant,
                            "suppressionFrames": frames, "mode": first["mode"], "takeVariant": first["variant"],
                            "variation": first["variation"], "seed": first["seed"], "entryIDs": entry_ids,
                            "file": f"batches/{batch_id}.txt"})
            fields = [batch_id, first["mode"], first["variant"], first["variation"], str(first["seed"]),
                      voice.get("id", "") if first["mode"] == "custom" else "",
                      voice.get("brief", "") if first["mode"] == "design" else "",
                      str(len(members)), str(path.resolve()), str(frames)]
            if any(FIELD_SEPARATOR in field or "\n" in field for field in fields):
                raise PositivesError(f"{batch_id}: a batch field contains a separator")
            rows.append(FIELD_SEPARATOR.join(fields))
    (out / "noeos-batches.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    plan = {
        "schemaVersion": 1, "kind": NOEOS_PLAN_KIND, "generator": GENERATOR,
        "privacy": "ids and digests only (the line files beside it carry the batch texts)",
        "takesManifest": {"fileSHA256": manifest_sha256, "manifestDigest": manifest["manifestDigest"],
                          "runID": manifest.get("runID"), "split": manifest.get("split")},
        "catalog": {"injector": NOEOS_INJECTOR, "version": NOEOS_CATALOG_VERSION, "seed": catalog_seed,
                    "knob": NOEOS_KNOB, "variants": dict(NOEOS_VARIANTS), "delivery": NOEOS_DELIVERY},
        "sampling": {"schema": SAMPLE_SCHEMA, "perCell": per_cell, "seed": sample_seed},
        "notApplicable": dict(sorted(reasons.items())),
        "counts": {"eligible": len(eligible), "eligibleFamilies": len(by_family), "selected": len(selected),
                   "batches": len(batches), "entries": len(entries)},
        "batches": batches,
        "entries": entries,
    }
    plan["planDigest"] = self_digest(plan, "planDigest")
    jsonio.atomic_json(out / "noeos-plan.json", plan, ascii=True, allow_nan=False)
    return plan


def noeos_set(*, plan_path: Path, batch_results: Path, wav_root: Path, diagnostics: Path, takes_path: Path,
              output: Path) -> dict:
    plan = load_plan(plan_path, NOEOS_PLAN_KIND)
    manifest, manifest_sha256 = load_takes(takes_path)
    if manifest_sha256 != plan["takesManifest"]["fileSHA256"]:
        raise PositivesError("the takes manifest is not the one the plan was drawn from")
    takes = {take["takeID"]: take for take in generated(manifest)}
    planned_entries = {entry["entryID"]: entry for entry in plan["entries"]}
    wav_root = Path(wav_root).resolve()
    out = new_directory(output)
    (out / "wav").mkdir()
    outcomes: list[tuple[dict, dict]] = []
    for batch in plan["batches"]:
        planned = [{"takeID": entry_id, "text": takes[planned_entries[entry_id]["sourceTakeID"]]["text"]}
                   for entry_id in batch["entryIDs"]]
        shape = {"batchID": batch["batchID"], "mode": batch["mode"], "variant": batch["takeVariant"],
                 "takeIDs": batch["entryIDs"]}
        try:
            found = takes_tool.segmented_outcomes(Path(batch_results), shape, planned)
        except takes_tool.TakeError as error:
            raise PositivesError(str(error)) from error
        outcomes.extend((planned_entries[entry_id], outcome) for entry_id, outcome in zip(batch["entryIDs"], found))
    failures = takes_tool.engine_failures(Path(diagnostics), {outcome["generationID"] for _, outcome in outcomes
                                                             if "generationID" in outcome})
    published: list[tuple[dict, Path, str, float]] = []
    # Why a planned take is no entry: the batch did not publish it, or its hold never acted.
    unpublished: dict[str, Counter] = {variant: Counter() for variant in NOEOS_VARIANTS}
    rejected_flags: Counter = Counter()
    for entry, outcome in outcomes:
        if outcome["status"] == "generated":
            source = Path(outcome["audioPath"])
            source = (source if source.is_absolute() else wav_root / source).resolve()
            try:
                source.relative_to(wav_root)
            except ValueError as error:
                raise PositivesError(f"{entry['entryID']}: the batch wrote its audio outside the WAV root") from error
            if not source.is_file():
                unpublished[entry["variant"]]["output-file-missing"] += 1
                continue
            destination = out / "wav" / f"{entry['entryID']}.wav"
            shutil.copyfile(source, destination)
            published.append((entry, destination, jsonio.sha256_file(destination), outcome["durationSeconds"]))
            continue
        failure = failures.get(outcome.get("generationID")) or {}
        if str(failure.get("errorCode", "")).startswith(takes_tool.QC_REJECTION_CODE):
            unpublished[entry["variant"]]["fast-qc-rejected"] += 1
            rejected_flags.update(flag.split(":", 1)[0] for flag in failure.get("audioQCFlags", ()))
        elif failure.get("errorCode"):
            unpublished[entry["variant"]][f"failed:{failure['errorCode']}"] += 1
        else:
            unpublished[entry["variant"]][outcome.get("missingReason") or "missing"] += 1
    digests = {digest for _, _, digest, _ in published}
    rows = engine_rows(Path(diagnostics), digests)
    summaries = introspection_of(Path(diagnostics), digests)
    source_summaries = {take["takeID"]: take.get("engineIntrospection") for take in takes.values()}
    source_pcm: dict[str, str] = {}
    entries = []
    determinism = Counter()
    for entry, destination, digest, duration in published:
        where, frames = entry["entryID"], entry["suppressionFrames"]
        found = rows.get(digest) or []
        if len(found) != 1:
            raise PositivesError(f"{where}: its WAV binds {len(found)} engine rows (collect the lane's diagnostics)")
        hold = found[0]["hold"]
        if hold.get(HOLD_FRAMES) != frames:
            raise PositivesError(f"{where}: its engine row records a hold of {hold.get(HOLD_FRAMES)!r} frames, the "
                                 f"plan {frames} ({NOEOS_KNOB} was not applied: an internal-diagnostics build with "
                                 "QWENVOICE_DEBUG=1 runs the knob)")
        if frames and HOLD_START not in hold:
            # The take reached the token cap before the talker sampled EOS: the hold never acted.
            unpublished[entry["variant"]]["hold-never-opened"] += 1
            continue
        summary = summaries.get(digest)
        if summary is None:
            raise PositivesError(f"{where}: its engine row carries no introspection summary")
        take = takes[entry["sourceTakeID"]]
        if take["takeID"] not in source_pcm:
            source_pcm[take["takeID"]] = pcm_of(inside(Path(takes_path).parent, take["wavPath"], "a take's WAV"))[0]
        output_pcm, _ = pcm_of(destination)
        natural = (source_summaries.get(take["takeID"]) or {}).get("codecFrameCount")
        if frames == 0:
            determinism["shamPCMEqualsSource"] += output_pcm == source_pcm[take["takeID"]]
            determinism["shams"] += 1
        elif natural is not None:
            determinism["holdOpenedAtSourceStop"] += hold.get(HOLD_START) == natural
            determinism["positivesWithSourceSummary"] += 1
        result = entry_base(take, where, f"wav/{where}.wav", digest, duration)
        result["engineIntrospection"] = summary
        result["injection"] = {
            "mechanism": NOEOS_MECHANISM, "catalogVersion": NOEOS_CATALOG_VERSION, "injector": NOEOS_INJECTOR,
            "injectorID": NOEOS_INJECTOR_ID, "injectorVersion": 1, "classes": list(CLASSES),
            "variant": entry["variant"], "severity": entry["severity"], "population": entry["population"],
            "parameters": {"suppressionFrames": frames}, "knob": NOEOS_KNOB, "recipe": entry["recipe"],
            "sourceWAVSHA256": take["wavSHA256"], "sourcePCMSHA256": source_pcm[take["takeID"]],
            "outputPCMSHA256": output_pcm, "generationID": found[0]["generationID"],
            "hold": {"frames": hold[HOLD_FRAMES], "startFrame": hold.get(HOLD_START),
                     "sourceCodecFrameCount": natural},
            "provenance": {"tier": "T3", "knob": NOEOS_KNOB, "recipeSHA256": json_digest(entry["recipe"])},
        }
        entries.append(result)
    reasons = {variant: dict(sorted(counts.items())) for variant, counts in unpublished.items()}
    head = {
        "schemaVersion": 1, "kind": SET_KIND, "generator": GENERATOR, "tier": "T3",
        "privacy": "ids and digests only: no text, transcript or path",
        "sourceManifest": {"sha256": manifest_sha256, "manifestDigest": manifest["manifestDigest"]},
        "catalogVersion": NOEOS_CATALOG_VERSION, "catalogSeed": plan["catalog"]["seed"], "classes": CLASSES,
        "sampling": {"schema": SAMPLE_SCHEMA, "perCell": plan["sampling"]["perCell"],
                     "seed": plan["sampling"]["seed"]},
        "knob": NOEOS_KNOB,
        "constructionPlan": {"sha256": jsonio.sha256_file(Path(plan_path)), "planDigest": plan["planDigest"]},
        "notApplicable": {NOEOS_INJECTOR: {"byVariant": {
            variant: dict(sorted({**plan["notApplicable"], **reasons[variant]}.items()))
            for variant in NOEOS_VARIANTS}}},
        "unpublished": reasons, "rejectedFlagFamilies": dict(sorted(rejected_flags.items())),
        "determinism": dict(sorted(determinism.items())),
        "counts": dict(Counter(entry["injection"]["population"] for entry in entries)),
    }
    return write_set(out, head, entries)


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #

def verify_set(set_path: Path, takes_path: Path) -> dict:
    """Recompute what a built set declares: its entries digest, every WAV and provenance digest, and each T2
    recipe's mutated trace and mirror summary."""
    data = load_json(set_path, "the injection set")
    if not isinstance(data, dict) or data.get("kind") != SET_KIND or data.get("generator") != GENERATOR:
        raise PositivesError(f"{Path(set_path).name} is not a set this builder wrote")
    manifest, manifest_sha256 = load_takes(takes_path)
    failures: list[str] = []
    if data.get("entriesSHA256") != json_digest(data.get("entries")):
        failures.append("the entries differ from entriesSHA256")
    if (data.get("sourceManifest") or {}).get("sha256") != manifest_sha256:
        failures.append("the set was built on another takes manifest")
    takes = {take["takeID"]: take for take in generated(manifest)}
    set_dir = Path(set_path).parent
    tier = data.get("tier")
    decoder_sha256 = json_digest(data["decoder"]) if tier == "T2" and isinstance(data.get("decoder"), dict) else None
    if tier == "T2" and decoder_sha256 != data.get("decoderSHA256"):
        failures.append("the decoder identity differs from decoderSHA256")
    for entry in data.get("entries") or ():
        where = entry.get("takeID")
        injection = entry.get("injection") or {}
        provenance = injection.get("provenance") or {}
        take = takes.get(entry.get("sourceTakeID"))
        if take is None or injection.get("sourceWAVSHA256") != take.get("wavSHA256"):
            failures.append(f"{where}: its source take is not the manifest's")
        try:
            wav = inside(set_dir, entry.get("wavPath"), f"{where}: wavPath")
            if jsonio.sha256_file(wav) != entry.get("wavSHA256"):
                failures.append(f"{where}: its WAV differs from its digest")
        except (PositivesError, OSError) as error:
            failures.append(f"{where}: {error}")
        recipe = injection.get("recipe")
        if provenance.get("recipeSHA256") != json_digest(recipe):
            failures.append(f"{where}: its recipe differs from recipeSHA256")
        if (entry.get("engineIntrospection") or {}).get("wavSHA256") != entry.get("wavSHA256"):
            failures.append(f"{where}: its introspection summary describes other audio")
        if tier == "T2":
            if provenance.get("decoderSHA256") != decoder_sha256:
                failures.append(f"{where}: it names another decoder")
            try:
                source = (set_dir / "traces" / f"{provenance.get('traceSHA256')}.bin").read_bytes()
                if codec_trace.sha256(source) != provenance.get("traceSHA256"):
                    raise PositivesError("its source trace copy changed")
                mutated = codec_trace.apply(codec_trace.complete_frames(source), recipe)
                if codec_trace.sha256(codec_trace.encode(mutated)) != injection.get("mutatedTraceSHA256"):
                    raise PositivesError("its recipe no longer makes its mutated trace")
                if loop_introspection(mutated, entry.get("wavSHA256")) != entry.get("engineIntrospection"):
                    raise PositivesError("its summary is not the mirror's over its looped codebook 0")
            except (PositivesError, codec_trace.TraceError, OSError) as error:
                failures.append(f"{where}: {error}")
        elif tier == "T3":
            hold = injection.get("hold") or {}
            if provenance.get("knob") != NOEOS_KNOB or hold.get("frames") != (recipe or {}).get("suppressionFrames"):
                failures.append(f"{where}: its engine-recorded hold is not its recipe's")
        else:
            failures.append(f"{where}: the set names no construction tier")
    return {"entries": len(data.get("entries") or ()), "failures": failures, "verified": not failures}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("loop-plan", "noeos-plan"):
        command = commands.add_parser(name)
        command.add_argument("--takes", type=Path, required=True, help="the confirmation takes manifest (N3)")
        command.add_argument("--out-dir", type=Path, required=True, help="a new directory")
        command.add_argument("--sample-per-cell", type=int, default=DEFAULT_SAMPLE_PER_CELL,
                             help=f"families per variant, stratified by language; 0 is every family "
                                  f"(default {DEFAULT_SAMPLE_PER_CELL})")
        command.add_argument("--sample-seed", type=int, default=DEFAULT_SAMPLE_SEED)
        command.add_argument("--catalog-seed", type=int, default=DEFAULT_CATALOG_SEED)
        if name == "loop-plan":
            command.add_argument("--diagnostics", type=Path, required=True,
                                 help="the qc-takes run's collected engine rows (its diagnostics/)")
            command.add_argument("--traces", type=Path, required=True,
                                 help="the qc-takes run's codec traces (<generation id>/codec-trace-v1.bin)")
    loop = commands.add_parser("loop-set")
    loop.add_argument("--plan", type=Path, required=True)
    loop.add_argument("--result", type=Path, required=True, help="the CLI's codec-loop-result.json")
    loop.add_argument("--takes", type=Path, required=True)
    loop.add_argument("--output", type=Path, required=True, help="a new directory")
    noeos = commands.add_parser("noeos-set")
    noeos.add_argument("--plan", type=Path, required=True)
    noeos.add_argument("--batch-results", type=Path, required=True)
    noeos.add_argument("--wav-root", type=Path, required=True)
    noeos.add_argument("--diagnostics", type=Path, required=True)
    noeos.add_argument("--takes", type=Path, required=True)
    noeos.add_argument("--output", type=Path, required=True, help="a new directory")
    verify = commands.add_parser("verify")
    verify.add_argument("--set", type=Path, required=True)
    verify.add_argument("--takes", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if getattr(args, "sample_per_cell", 0) < 0:
            raise PositivesError("--sample-per-cell is 0 or more")
        if args.command == "loop-plan":
            value = loop_plan(takes_path=args.takes, diagnostics=args.diagnostics, traces=args.traces,
                              out_dir=args.out_dir, per_cell=args.sample_per_cell, sample_seed=args.sample_seed,
                              catalog_seed=args.catalog_seed)
            print(json.dumps({"counts": value["counts"], "notApplicable": value["notApplicable"],
                              "planDigest": value["planDigest"]}, sort_keys=True))
            return 0
        if args.command == "noeos-plan":
            value = noeos_plan(takes_path=args.takes, out_dir=args.out_dir, per_cell=args.sample_per_cell,
                               sample_seed=args.sample_seed, catalog_seed=args.catalog_seed)
            print(json.dumps({"counts": value["counts"], "notApplicable": value["notApplicable"],
                              "planDigest": value["planDigest"]}, sort_keys=True))
            return 0
        if args.command == "loop-set":
            value = loop_set(plan_path=args.plan, result_path=args.result, takes_path=args.takes, output=args.output)
        elif args.command == "noeos-set":
            value = noeos_set(plan_path=args.plan, batch_results=args.batch_results, wav_root=args.wav_root,
                              diagnostics=args.diagnostics, takes_path=args.takes, output=args.output)
        else:
            report = verify_set(args.set, args.takes)
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0 if report["verified"] else 1
        print(json.dumps({key: value.get(key) for key in ("tier", "counts", "unpublished", "determinism",
                                                          "entriesSHA256") if key in value}, sort_keys=True))
        return 0
    except (PositivesError, codec_trace.TraceError, recordings.RecordingError, OSError) as error:
        print(f"audio-qc-introspection-positives: FAIL\n{error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
