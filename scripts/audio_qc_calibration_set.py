#!/usr/bin/env python3
"""The AQ-07 injected-defect set over natural takes, and its report-only scorer (M2).

Commands:
  inject  --takes <manifest> --output <dir> [--catalog-seed N] [--classes A,C,F] [--jobs N]
          Apply every applicable T1 injector of the selected classes (by default
          A signal, C boundary and the signal-level F prosody ones) to every
          generated natural take (population N3) of an `audio-qc-calibration-takes`
          manifest, at mild, moderate and severe plus the family's sham. Writes
          <dir>/wav/<clip>.wav and <dir>/injection-set.json.
  verify  --set <injection-set.json> --takes <manifest> [--jobs N]
          Replay every recipe from the source WAVs and require byte-identical
          output digests (and untouched output WAVs).
  score   --takes <manifest> --set <injection-set.json> --output <dir> [--jobs N]
          Run Fast QC v8 (the Python mirror in scripts/lib/audio_qc.py) and the
          Stage 0 observations over every clean take (N3), sham (S) and positive
          (P1); write measurements.json (ids and digests only), report.json and
          report.md.

Recorded takes carry no word intervals (they exist only from the aligner on N1
and N2), no declared pause, no script and no render voice
(`lib/qc_qualification/recordings.py`), so every variant that needs one raises
`InjectorNotApplicable` and is counted with its reason; injectors with a
word-free recording variant (`take-*`) use it instead. Identity swaps from the
manifest's donor pairs are deferred: the donor take is another rendering with
its own timing, so it is not the time-aligned re-render the swap construction
splices, and aligning the two would need word intervals N3 never has.

Report-only. N3 is unlabeled, so a flag rate f bounds the false-alarm rate only
as f / (1 - pi_max), and T1 on N3 qualifies nothing: a fail bound needs N2 and
a pre-registered plan (A2, A5). Everything is written under the caller's output
directory, an untracked build artifact; no model, device or native build runs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
from collections import Counter, OrderedDict
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import numpy as np

import audio_qc_qualification as m1
from lib import audio_qc, audio_qc_observations
from lib.qc_qualification import injectors, policy as policy_module, recordings, resampling
from lib.qc_qualification.pcm import canonical_json, json_digest, pcm_digest
from lib.qc_qualification.stats import DEFAULT_CONFIDENCE, Rate, bonferroni_confidence

TAKES_KIND = "audio-qc-calibration-takes"
SET_KIND = "audio-qc-injection-set"
MEASUREMENTS_KIND = "audio-qc-calibration-measurements"
REPORT_SCHEMA = "vocello.audioqc.calibration-report/1"
GENERATOR = "audio-qc-calibration-set/1"
SEED_SCHEMA = "vocello.audioqc.calibration-seed/1"
SEVERITY_SWEEP = ("sham", "mild", "moderate", "severe")
DEFAULT_CLASSES = ("A", "C", "F")
DEFAULT_CATALOG_SEED = 7
PI_MAX = (0.05, 0.10, 0.20)
TAKE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
SHA256 = re.compile(r"[0-9a-f]{64}")
# The v8 report's numeric fields that measurements.json keeps (no text, no path).
FASTQC_FIELDS = (
    "rmsDBFS", "dcOffset", "peak", "clippedSamples", "hotSamples", "nonFiniteSamples", "clickEvents",
    "longestSilenceMS", "trailingSilenceMS", "stepBurstPeakCount", "stepBurstPeakStartMS", "durationSeconds",
    "expectedPauseCount", "speakingRateTextUnits", "secondsPerTextUnit", "clickEventCount",
    "lowEnergyClickEventCount", "clickEventsPerSecond",
)
OBSERVATION_MEASURES = tuple(source for source, _ in audio_qc.QC_SIGNAL_METRIC_MAP)
DONOR_SWAP_STATUS = {
    "injector": injectors.CATALOG["IDN-SWAP"].key,
    "status": "deferred",
    "reason": "a donor pair's second take is another rendering with its own timing, not the time-aligned "
              "re-render the swap splices; aligning them needs word intervals, which N3 never has",
}


class CalibrationError(ValueError):
    """An input is malformed or does not match what it claims."""


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def file_sha256(path: Path) -> str:
    return recordings.file_sha256(path)


def _plain(value: Any) -> Any:
    """JSON-safe: NumPy scalars to Python, non-finite floats to None."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)):
        return int(value)
    if isinstance(value, (float, np.floating)):
        number = float(value)
        return number if math.isfinite(number) else None
    return value


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #

def _relative_path(base: Path, value: Any, what: str) -> Path:
    if not isinstance(value, str) or not value or value.startswith("/") or ".." in Path(value).parts:
        raise CalibrationError(f"{what} must be a relative path inside its manifest's directory")
    return base / value


def load_takes(path: Path) -> tuple[dict, str]:
    """The takes manifest and the SHA-256 of its bytes, validated."""
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CalibrationError(f"{path.name} is not JSON: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("kind") != TAKES_KIND or manifest.get("schemaVersion") != 1:
        raise CalibrationError(f"{path.name} is not an {TAKES_KIND} schema 1 manifest")
    takes = manifest.get("takes")
    if not isinstance(takes, list):
        raise CalibrationError(f"{path.name} lists no takes")
    seen: set[str] = set()
    for take in takes:
        take_id = take.get("takeID") if isinstance(take, dict) else None
        if not isinstance(take_id, str) or not TAKE_ID.fullmatch(take_id) or take_id in seen:
            raise CalibrationError("every take has a unique takeID of letters, digits, '.', '_' and '-'")
        seen.add(take_id)
        if take.get("status") not in ("generated", "missing"):
            raise CalibrationError(f"{take_id}: status is generated or missing")
        if not isinstance(take.get("family"), str) or not take["family"]:
            raise CalibrationError(f"{take_id}: it names its source family")
        if take["status"] != "generated":
            continue
        if not SHA256.fullmatch(str(take.get("wavSHA256", ""))):
            raise CalibrationError(f"{take_id}: a generated take pins its WAV's SHA-256")
        if not isinstance(take.get("language"), str) or not isinstance(take.get("text"), str):
            raise CalibrationError(f"{take_id}: a generated take names its language and text")
        _relative_path(path.parent, take.get("wavPath"), f"{take_id}: wavPath")
    return manifest, hashlib.sha256(raw).hexdigest()


def generated_takes(manifest: dict) -> list[dict]:
    return [take for take in manifest["takes"] if take["status"] == "generated"]


def take_wav(manifest_path: Path, take: dict) -> Path:
    return _relative_path(manifest_path.parent, take["wavPath"], f"{take['takeID']}: wavPath")


def donor_pairs(manifest: dict) -> int:
    """Scripts rendered by two or more voices: the donor pairs an identity swap would use."""
    voices: dict[str, set[str]] = {}
    for take in generated_takes(manifest):
        voice = take.get("voice") if isinstance(take.get("voice"), dict) else {}
        voices.setdefault(str(take.get("scriptID")), set()).add(f"{voice.get('kind')}:{voice.get('id')}")
    return sum(1 for names in voices.values() if len(names) >= 2)


def derive_seed(source_wav_sha256: str, injector_key: str, catalog_seed: int) -> int:
    """The per-(take, injector) seed: 48 bits of SHA-256 over the source digest, injector and catalog seed.

    The variant is deliberately not an input: `injectors.inject` keys its stream
    by (seed, injector, source), so a sham draws the same positions as its
    positives only when they share the seed.
    """
    material = "|".join((SEED_SCHEMA, source_wav_sha256, injector_key, str(catalog_seed))).encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:6], "big")


def stratum(take: dict) -> str:
    return f"N3/{take.get('language')}/{take.get('mode')}"


def voice_label(take: dict) -> dict:
    """Builtin voices by id; any other voice by a digest of its id (it may be a person's name)."""
    voice = take.get("voice") if isinstance(take.get("voice"), dict) else {}
    kind = str(voice.get("kind"))
    identity = str(voice.get("id"))
    if kind == "builtin":
        return {"kind": kind, "id": identity}
    return {"kind": kind, "idSHA256": hashlib.sha256(identity.encode("utf-8")).hexdigest()}


# --------------------------------------------------------------------------- #
# The plan
# --------------------------------------------------------------------------- #

def build_plan(classes: Iterable[str]) -> list[dict]:
    """Every catalog injector at sham, mild, moderate and severe: scheduled, replaced or out of scope."""
    scope = sorted(set(classes))
    rows = []
    for injector in injectors.CATALOG.values():
        in_scope = bool(set(injector.classes) & set(scope))
        recording = {variant.name: variant for variant in injector.recording_variants}
        for severity in SEVERITY_SWEEP:
            catalog = injector.variant(severity)
            catalog_needs = list(injectors.needs(injector.injector_id, catalog.parameters))
            chosen = recording.get(f"take-{severity}")
            row = {"injector": injector.key, "injectorID": injector.injector_id, "classes": list(injector.classes),
                   "severity": severity, "catalogVariant": catalog.name, "catalogNeeds": catalog_needs}
            if not in_scope:
                row.update(status="out-of-scope", variant=None,
                           reason=f"classes {'/'.join(injector.classes)} are outside this set ({'/'.join(scope)})")
            elif chosen is not None:
                row.update(status="scheduled", variant=chosen.name, parameters=dict(chosen.parameters),
                           replaces=catalog.name if catalog_needs else None)
            else:
                # A catalog variant that needs what no recording has is still attempted on every
                # take, so the refusals it raises are counted with their reason.
                row.update(status="not-applicable" if catalog_needs else "scheduled", variant=catalog.name,
                           parameters=dict(catalog.parameters))
            rows.append(row)
    return rows


def schedule(plan: list[dict]) -> list[tuple[str, str]]:
    return [(row["injectorID"], row["variant"]) for row in plan if row["status"] != "out-of-scope"]


def recording_variants_description() -> list[dict]:
    return [{"injector": injector.key, "variants": [
        {"name": variant.name, "severity": variant.severity, "parameters": dict(variant.parameters)}
        for variant in injector.recording_variants]}
        for injector in injectors.CATALOG.values() if injector.recording_variants]


def _reason(error: Exception, fixture_id: str, key: str, variant: str) -> str:
    """A refusal without the take's id or the variant, so reasons aggregate across takes and variants."""
    return (str(error).replace(f"{fixture_id}: ", "").replace(f"{key} {variant} ", "")
            .replace(fixture_id, "the take"))


# --------------------------------------------------------------------------- #
# Parallel map with progress
# --------------------------------------------------------------------------- #

def parallel(function: Callable[[Any], Any], tasks: list[Any], jobs: int, label: str) -> Iterator[Any]:
    """Results in task order (deterministic for any job count), with progress on stderr."""
    total = len(tasks)
    started = time.monotonic()
    step = max(1, total // 20)

    def progress(done: int) -> None:
        if done % step and done != total:
            return
        elapsed = time.monotonic() - started
        left = elapsed / done * (total - done) if done else 0.0
        log(f"{label}: {done}/{total} ({elapsed:.0f} s elapsed, about {left:.0f} s left)")

    if jobs <= 1 or total <= 1:
        for done, task in enumerate(tasks, 1):
            yield function(task)
            progress(done)
        return
    with get_context().Pool(min(jobs, total)) as pool:
        for done, result in enumerate(pool.imap(function, tasks, chunksize=1), 1):
            yield result
            progress(done)


# --------------------------------------------------------------------------- #
# inject
# --------------------------------------------------------------------------- #

def _entry(take: dict, injection: injectors.Injection, clip_id: str, wav_path: str, wav_sha256: str,
           source_wav_sha256: str, rate: int) -> dict:
    injector = injectors.CATALOG[injection.injector.split("@")[0]]
    entry = {key: value for key, value in take.items() if key != "text"}
    entry.update(
        takeID=clip_id, sourceTakeID=take["takeID"], family=take["family"], status="generated",
        wavPath=wav_path, wavSHA256=wav_sha256, durationSeconds=round(injection.samples.size / rate, 6),
        textSHA256=hashlib.sha256(take["text"].encode("utf-8")).hexdigest(),
    )
    entry["injection"] = {
        "mechanism": injectors.MECHANISM, "catalogVersion": injectors.CATALOG_VERSION,
        "injector": injection.injector, "injectorID": injector.injector_id, "injectorVersion": injector.version,
        "classes": list(injector.classes), "variant": injection.variant, "severity": injection.severity,
        "population": "P1" if injection.positive else "S", "parameters": injection.parameters,
        "seed": injection.seed, "sourceWAVSHA256": source_wav_sha256, "sourcePCMSHA256": injection.source_digest,
        "outputPCMSHA256": injection.digest, "labels": list(injection.labels),
    }
    return _plain(entry)


def _inject_take(task: dict) -> dict:
    take = task["take"]
    fixture, digest = recordings.load_recording(Path(task["wav"]), take_id=take["takeID"], family=take["family"],
                                                stratum=stratum(take), text=take["text"],
                                                expected_sha256=take["wavSHA256"])
    output = Path(task["output"])
    entries, skips = [], []
    written = 0
    for injector_id, variant in task["schedule"]:
        key = injectors.CATALOG[injector_id].key
        seed = derive_seed(digest, key, task["catalogSeed"])
        try:
            injection = injectors.inject(injector_id, variant, fixture, seed)
        except injectors.InjectorNotApplicable as error:
            skips.append([key, variant, _reason(error, fixture.fixture_id, key, variant)])
            continue
        clip_id = f"{take['takeID']}__{injector_id}__{variant}"
        relative = f"wav/{clip_id}.wav"
        wav_sha256 = recordings.write_pcm16_wav(output / relative, injection.samples,
                                                sample_rate=fixture.sample_rate)
        written += (output / relative).stat().st_size
        entries.append(_entry(take, injection, clip_id, relative, wav_sha256, digest, fixture.sample_rate))
    return {"takeID": take["takeID"], "entries": entries, "skips": skips, "bytes": written}


def _write_streamed(path: Path, head: dict, key: str, items: Iterable[dict], tail: Callable[[str], dict]) -> str:
    """Write {head..., key: [items...], tail...} with one item per line; returns the items' json_digest.

    `canonical_json` of a list is "[" + ",".join(item encodings) + "]", so the
    digest is taken while streaming, never holding every item in memory.
    """
    digest = hashlib.sha256(b"[")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        _stream_json(temporary, head, key, items, tail, digest)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)
    return digest.hexdigest()


def _stream_json(temporary: Path, head: dict, key: str, items: Iterable[dict], tail: Callable[[str], dict],
                 digest: Any) -> None:
    with temporary.open("w", encoding="utf-8") as stream:
        stream.write("{\n")
        for name, value in sorted(head.items()):
            stream.write(f"  {json.dumps(name)}: {json.dumps(value, sort_keys=True, allow_nan=False)},\n")
        stream.write(f"  {json.dumps(key)}: [")
        first = True
        for item in items:
            digest.update(b"" if first else b",")
            digest.update(canonical_json(item))
            stream.write(("\n    " if first else ",\n    ") + json.dumps(item, sort_keys=True, allow_nan=False))
            first = False
        stream.write("\n  ],\n" if not first else "],\n")
        digest.update(b"]")
        closing = tail(digest.hexdigest())
        body = [f"  {json.dumps(name)}: {json.dumps(value, sort_keys=True, allow_nan=False)}"
                for name, value in sorted(closing.items())]
        stream.write(",\n".join(body) + "\n}\n")


def run_inject(takes_path: Path, output: Path, *, catalog_seed: int, classes: Iterable[str], jobs: int) -> dict:
    manifest, manifest_sha256 = load_takes(takes_path)
    plan = build_plan(classes)
    scheduled = schedule(plan)
    generated = generated_takes(manifest)
    tasks = [{"take": take, "wav": str(take_wav(takes_path, take)), "output": str(output),
              "schedule": scheduled, "catalogSeed": catalog_seed} for take in generated]
    log(f"inject: {len(generated)} generated takes x {len(scheduled)} scheduled variants, {jobs} jobs")
    skipped: dict[str, dict[str, Counter]] = {}
    counts = Counter()
    written = 0

    def entries() -> Iterator[dict]:
        nonlocal written
        for result in parallel(_inject_take, tasks, jobs, "inject"):
            written += result["bytes"]
            for key, variant, reason in result["skips"]:
                skipped.setdefault(key, {}).setdefault(variant, Counter())[reason] += 1
            for entry in result["entries"]:
                counts[entry["injection"]["population"]] += 1
                yield entry

    head = {
        "schemaVersion": 1, "kind": SET_KIND, "generator": GENERATOR,
        "sourceManifest": {"sha256": manifest_sha256, "runID": manifest.get("runID"),
                           "planDigest": manifest.get("planDigest"), "poolDigest": manifest.get("poolDigest"),
                           "split": manifest.get("split")},
        "catalogVersion": injectors.CATALOG_VERSION, "catalogSeed": catalog_seed,
        "mechanism": injectors.MECHANISM, "classes": sorted(set(classes)),
        "seedDerivation": f"{SEED_SCHEMA}: first 48 bits of SHA-256('{SEED_SCHEMA}|<source WAV SHA-256>|"
                          "<injector@version>|<catalog seed>'), big-endian; the variant is not an input, so a "
                          "sham draws the same positions as its positives",
        "plan": plan, "recordingVariants": recording_variants_description(),
        "identitySwap": {**DONOR_SWAP_STATUS, "donorPairs": donor_pairs(manifest)},
        "textPolicy": "entries carry the source take's fields except its text, bound by textSHA256; the text "
                      "stays in the takes manifest",
    }

    def tail(entries_sha256: str) -> dict:
        not_applicable = {key: {"count": sum(sum(reasons.values()) for reasons in variants.values()),
                                "byVariant": {variant: dict(sorted(reasons.items()))
                                              for variant, reasons in sorted(variants.items())}}
                          for key, variants in sorted(skipped.items())}
        return {"entriesSHA256": entries_sha256, "notApplicable": not_applicable,
                "counts": {"generatedTakes": len(generated),
                           "missingTakes": sum(1 for take in manifest["takes"] if take["status"] != "generated"),
                           "shams": counts["S"], "positives": counts["P1"], "wavBytes": written}}

    path = output / "injection-set.json"
    _write_streamed(path, head, "entries", entries(), tail)
    summary = json.loads(path.read_text(encoding="utf-8"))
    log(f"inject: wrote {summary['counts']['shams']} shams and {summary['counts']['positives']} positives "
        f"({written / 1e6:.1f} MB of WAV) and {path.name}")
    return summary


# --------------------------------------------------------------------------- #
# verify
# --------------------------------------------------------------------------- #

def load_set(path: Path) -> dict:
    injection_set = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(injection_set, dict) or injection_set.get("kind") != SET_KIND \
            or injection_set.get("schemaVersion") != 1 or not isinstance(injection_set.get("entries"), list):
        raise CalibrationError(f"{path.name} is not an {SET_KIND} schema 1 file")
    return injection_set


def _verify_take(task: dict) -> list[list[str]]:
    take = task["take"]
    failures: list[list[str]] = []
    try:
        fixture, digest = recordings.load_recording(Path(task["wav"]), take_id=take["takeID"],
                                                    family=take["family"], stratum=stratum(take),
                                                    text=take["text"], expected_sha256=take["wavSHA256"])
    except recordings.RecordingError as error:
        return [[entry["takeID"], f"source: {error}"] for entry in task["entries"]]
    for entry in task["entries"]:
        clip = entry["takeID"]
        recipe = entry.get("injection") or {}
        try:
            injector = injectors.CATALOG[str(recipe.get("injectorID"))]
            variant = injector.variant(str(recipe.get("variant")))
        except KeyError:
            failures.append([clip, "the catalog has no such injector or variant"])
            continue
        checks = [
            (recipe.get("injector") == injector.key, "injector version differs from the catalog"),
            (recipe.get("catalogVersion") == injectors.CATALOG_VERSION, "catalog version differs"),
            (recipe.get("severity") == variant.severity, "severity differs from the catalog"),
            (recipe.get("parameters") == _plain(dict(variant.parameters)), "parameters differ from the catalog"),
            (recipe.get("sourceWAVSHA256") == digest, "source WAV digest differs"),
            (recipe.get("seed") == derive_seed(digest, injector.key, task["catalogSeed"]),
             "seed differs from its derivation"),
            (entry.get("family") == take["family"], "family differs from the source take's"),
        ]
        problems = [message for ok, message in checks if not ok]
        if problems:
            failures.append([clip, "; ".join(problems)])
            continue
        replay = injectors.inject(injector.injector_id, variant.name, fixture, int(recipe["seed"]))
        if replay.digest != recipe.get("outputPCMSHA256") or _plain(list(replay.labels)) != recipe.get("labels"):
            failures.append([clip, "replay differs from the recorded output digest or labels"])
            continue
        output = Path(task["setDir"]) / entry["wavPath"]
        if not output.is_file() or file_sha256(output) != entry.get("wavSHA256"):
            failures.append([clip, "output WAV is missing or its file digest differs"])
            continue
        if pcm_digest(recordings.read_pcm16_wav(output)) != replay.digest:
            failures.append([clip, "output WAV PCM differs from the replay"])
    return failures


def run_verify(set_path: Path, takes_path: Path, *, jobs: int) -> dict:
    injection_set = load_set(set_path)
    manifest, manifest_sha256 = load_takes(takes_path)
    failures: list[list[str]] = []
    if injection_set.get("sourceManifest", {}).get("sha256") != manifest_sha256:
        failures.append(["<set>", "the set was built from another takes manifest"])
    if json_digest(injection_set["entries"]) != injection_set.get("entriesSHA256"):
        failures.append(["<set>", "entriesSHA256 differs from the entries"])
    takes = {take["takeID"]: take for take in generated_takes(manifest)}
    grouped: "OrderedDict[str, list[dict]]" = OrderedDict()
    for entry in injection_set["entries"]:
        source = entry.get("sourceTakeID")
        if source not in takes:
            failures.append([str(entry.get("takeID")), "its source take is not a generated take of the manifest"])
            continue
        grouped.setdefault(source, []).append(entry)
    tasks = [{"take": takes[source], "wav": str(take_wav(takes_path, takes[source])), "entries": entries,
              "setDir": str(set_path.parent), "catalogSeed": injection_set.get("catalogSeed")}
             for source, entries in grouped.items()]
    for result in parallel(_verify_take, tasks, jobs, "verify"):
        failures.extend(result)
    return {"entries": len(injection_set["entries"]), "sources": len(tasks), "failures": failures,
            "verified": not failures}


# --------------------------------------------------------------------------- #
# score
# --------------------------------------------------------------------------- #

def _score_clip(task: dict) -> dict:
    path = Path(task["wav"])
    if not path.is_file() or file_sha256(path) != task["wavSHA256"]:
        raise CalibrationError(f"{task['clipID']}: its WAV is missing or differs from its digest")
    samples = recordings.read_pcm16_wav(path)
    report = audio_qc.fast_qc_v8(samples, sample_rate=recordings.ENGINE_SAMPLE_RATE, text=task["text"], signal=True)
    fast = {"verdict": report["verdict"], "instabilityVerdict": report["instabilityVerdict"],
            "writtenOutputVerdict": report["writtenOutputVerdict"], "flags": list(report["flags"]),
            "flagLevels": dict(report["flagLevels"])}
    fast.update({field: report.get(field) for field in FASTQC_FIELDS})
    return _plain({**task["meta"], "wavSHA256": task["wavSHA256"], "pcmSHA256": pcm_digest(samples),
                   "fastQC": fast, "observations": report["signal"]})


def _meta(take: dict, clip_id: str, population: str, injection: dict | None) -> dict:
    return {
        "clipID": clip_id, "population": population, "family": take["family"], "sourceTakeID": take["takeID"],
        "scriptID": take.get("scriptID"), "language": take.get("language"), "mode": take.get("mode"),
        "takeVariant": take.get("variant"), "voice": voice_label(take), "seed": take.get("seed"),
        "injection": None if injection is None else {
            "injector": injection["injector"], "injectorID": injection["injectorID"],
            "variant": injection["variant"], "severity": injection["severity"],
            "classes": injection["classes"], "outputPCMSHA256": injection["outputPCMSHA256"]},
    }


def _reduced(measurement: dict) -> dict:
    """What the report reads of one clip: no flags text beyond families, no digests."""
    injection = measurement["injection"] or {}
    return {
        "clipID": measurement["clipID"], "population": measurement["population"],
        "family": measurement["family"], "sourceTakeID": measurement["sourceTakeID"],
        "language": measurement["language"], "injector": injection.get("injector"),
        "injectorID": injection.get("injectorID"), "variant": injection.get("variant"),
        "severity": injection.get("severity"), "verdict": measurement["fastQC"]["verdict"],
        "flagLevels": measurement["fastQC"]["flagLevels"],
        "observations": {name: measurement["observations"].get(name) for name in OBSERVATION_MEASURES},
    }


def _family_rate(units: Iterable[tuple[str, bool]]) -> dict:
    return m1._family_rate(units)


def _family_detection(units: Iterable[tuple[str, bool]]) -> dict:
    """Positives: a family is detected only if every one of its clips is (a miss on any is a miss)."""
    counts = resampling.family_counts(list(units))
    return Rate(sum(1 for events, total in counts.values() if events == total), len(counts)).as_dict()


def _overlap(first: dict, second: dict) -> bool | None:
    if not first["units"] or not second["units"]:
        return None
    return m1._overlap(first, second)


def _at_level(value: str | None, level: str) -> bool:
    return value == "fail" if level == "fail" else value in ("warn", "fail")


def _flag_rates(records: list[dict]) -> dict:
    return {flag: {("fail" if level == "fail" else "warnOrWorse"):
                   _family_rate((record["family"], _at_level(record["flagLevels"].get(flag), level))
                                for record in records)
                   for level in levels}
            for flag, levels in audio_qc.FASTQC_V8_FLAGS.items()}


def _targets(injector_id: str | None) -> tuple[str, ...]:
    return m1.TARGETS.get(injector_id or "", ())


def _hit(record: dict, targets: tuple[str, ...]) -> bool:
    return bool(set(record["flagLevels"]) & set(targets))


def _alarm(record: dict) -> bool:
    return record["verdict"] != "pass"


def _grouped(records: list[dict]) -> "OrderedDict[tuple[str, str], list[dict]]":
    groups: "OrderedDict[tuple[str, str], list[dict]]" = OrderedDict()
    for record in records:
        groups.setdefault((record["injector"], record["variant"]), []).append(record)
    return groups


def _median(values: list[float]) -> float | None:
    return round(float(np.median(values)), 6) if values else None


def build_report(records: list[dict], *, inputs: dict, injection_set: dict) -> dict:
    negatives = [record for record in records if record["population"] == "N3"]
    shams = [record for record in records if record["population"] == "S"]
    positives = [record for record in records if record["population"] == "P1"]
    clean_by_take = {record["sourceTakeID"]: record for record in negatives}
    skipped = injection_set.get("notApplicable", {})

    def skips(key: str, variant: str) -> int:
        return sum((skipped.get(key, {}).get("byVariant", {}).get(variant) or {}).values())

    n3_alarm = _family_rate((record["family"], _alarm(record)) for record in negatives)
    n3 = {
        "clips": len(negatives), "families": len({record["family"] for record in negatives}),
        "alarm": n3_alarm, "fail": _family_rate((record["family"], record["verdict"] == "fail")
                                                for record in negatives),
        "flags": _flag_rates(negatives),
        "unlabeledBound": {
            "note": "N3 carries no labels: FAR <= f / (1 - pi_max), f the flag rate and pi_max the maximum "
                    "defect prevalence; shown for the flag rate's one-sided CP upper bound",
            "flagRateUpper": n3_alarm["upper"],
            "farBoundAtPiMax": {str(pi): (None if n3_alarm["upper"] is None
                                          else round(min(1.0, n3_alarm["upper"] / (1.0 - pi)), 6))
                                for pi in PI_MAX},
        },
    }

    sham_rows = []
    for (key, variant), group in _grouped(shams).items():
        injector_id = group[0]["injectorID"]
        targets = _targets(injector_id)
        families = {record["family"] for record in group}
        same = [record for record in negatives if record["family"] in families]
        alarm = _family_rate((record["family"], _alarm(record)) for record in group)
        clean_alarm = _family_rate((record["family"], _alarm(record)) for record in same)
        row = {"injector": key, "variant": variant, "targets": list(targets), "units": alarm["units"],
               "notApplicable": skips(key, variant), "alarm": alarm, "cleanAlarmSameFamilies": clean_alarm,
               "alarmOverlaps": _overlap(alarm, clean_alarm),
               "flags": dict(sorted(Counter(flag for record in group for flag in record["flagLevels"]).items()))}
        if targets:
            target = _family_rate((record["family"], _hit(record, targets)) for record in group)
            clean_target = _family_rate((record["family"], _hit(record, targets)) for record in same)
            row["a4"] = {"basis": "target-flags", "sham": target, "cleanSameFamilies": clean_target,
                         "overlaps": _overlap(target, clean_target)}
        else:
            row["a4"] = {"basis": "not-applicable", "reason": "v8 has no detector for this family",
                         "overlaps": None}
        sham_rows.append(row)
    sham_pooled = _family_rate((record["family"], _alarm(record)) for record in shams)
    sham_flags = _flag_rates(shams)
    flags = []
    for flag, levels in audio_qc.FASTQC_V8_FLAGS.items():
        level = "warnOrWorse" if "warn" in levels else "fail"
        n3_rate, sham_rate = n3["flags"][flag][level], sham_flags[flag][level]
        flags.append({"flag": flag, "levels": list(levels), "basis": level, "n3": n3["flags"][flag],
                      "shams": sham_flags[flag], "overlaps": _overlap(sham_rate, n3_rate),
                      "targetedBy": sorted(injector for injector, targets in m1.TARGETS.items()
                                           if flag in targets)})

    detection = []
    for (key, variant), group in _grouped(positives).items():
        injector_id = group[0]["injectorID"]
        targets = _targets(injector_id)
        deltas = {}
        for name in OBSERVATION_MEASURES:
            values = []
            for record in group:
                source = clean_by_take.get(record["sourceTakeID"])
                clip, clean = record["observations"].get(name), (source or {}).get("observations", {}).get(name)
                if clip is not None and clean is not None:
                    values.append(clip - clean)
            deltas[name] = _median(values)
        detection.append({
            "injector": key, "variant": variant, "severity": group[0]["severity"],
            "classes": list(injectors.CATALOG[injector_id].classes), "targets": list(targets),
            "units": len({record["family"] for record in group}), "notApplicable": skips(key, variant),
            "target": _family_detection((record["family"], _hit(record, targets)) for record in group)
            if targets else None,
            "alarm": _family_detection((record["family"], _alarm(record)) for record in group),
            "fail": _family_detection((record["family"], record["verdict"] == "fail") for record in group),
            "flags": dict(sorted(Counter(flag for record in group for flag in record["flagLevels"]).items())),
            "observationMedianDelta": deltas,
        })

    languages = sorted({record["language"] for record in records})
    confidence = bonferroni_confidence(DEFAULT_CONFIDENCE, max(1, len(languages)))
    per_language = {}
    for language in languages:
        clean = [record for record in negatives if record["language"] == language]
        units = [(record["family"], _alarm(record)) for record in clean]
        severe: dict[str, list[dict]] = {}
        for record in positives:
            if record["language"] == language and record["severity"] == "severe" and _targets(record["injectorID"]):
                severe.setdefault(record["injector"], []).append(record)
        per_language[language] = {
            "n3Families": len({record["family"] for record in clean}),
            "alarm": _family_rate(units),
            "alarmSimultaneous": Rate(*resampling.family_level_events(units), confidence=confidence).as_dict(),
            "fail": _family_rate((record["family"], record["verdict"] == "fail") for record in clean),
            "shamAlarm": _family_rate((record["family"], _alarm(record)) for record in shams
                                      if record["language"] == language),
            "severeTargetDetection": {key: _family_detection(
                (record["family"], _hit(record, _targets(record["injectorID"]))) for record in group)
                for key, group in sorted(severe.items())},
        }
    judged = [(language, entry) for language, entry in per_language.items() if entry["alarm"]["units"]]
    worst_alarm = max(judged, key=lambda item: (item[1]["alarm"]["upper"], item[0]), default=None)
    # For each injector v8 detects at all when severe, the language where it detects least.
    worst_detection = []
    for row in detection:
        if row["severity"] != "severe" or not row["target"] or not row["target"]["events"]:
            continue
        rates = [(language, entry["severeTargetDetection"][row["injector"]])
                 for language, entry in per_language.items() if row["injector"] in entry["severeTargetDetection"]]
        language, rate = min(rates, key=lambda item: (item[1]["lower"], item[0]))
        worst_detection.append({"injector": row["injector"], "language": language, **rate})

    observations = {}
    for name in OBSERVATION_MEASURES:
        observations[name] = {
            "N3": m1._summary([record["observations"][name] for record in negatives
                               if record["observations"].get(name) is not None]),
            "S": m1._summary([record["observations"][name] for record in shams
                              if record["observations"].get(name) is not None]),
        }

    report = {
        "schema": REPORT_SCHEMA, "generator": GENERATOR, "phase": "M2", "reportOnly": True,
        "subject": {"detector": m1.SUBJECT, "mirror": audio_qc.FASTQC_V8_MIRROR,
                    "observations": audio_qc_observations.OBSERVATIONS_MIRROR, "calibration": "legacy-unqualified"},
        "inputs": inputs,
        "populations": {
            "N3": {"clips": len(negatives), "families": n3["families"]},
            "S": {"clips": len(shams), "families": len({record["family"] for record in shams})},
            "P1": {"clips": len(positives), "families": len({record["family"] for record in positives})},
        },
        "unit": "source family (policy thresholdDerivation.unitOfRates): a negative family errs if any of its "
                "clips alarms; a positive family is detected only if every one of its clips is",
        "n3": n3,
        "flags": flags,
        "shams": sham_rows,
        "shamsPooled": {"alarm": sham_pooled, "n3Alarm": n3_alarm, "overlaps": _overlap(sham_pooled, n3_alarm),
                        "clusterBootstrap": resampling.cluster_bootstrap_rate(
                            [(record["family"], _alarm(record)) for record in shams], label="calibration-shams")},
        "detection": detection,
        "languages": {"rows": per_language, "simultaneousConfidence": round(confidence, 6),
                      "worstN3Alarm": None if worst_alarm is None else
                      {"language": worst_alarm[0], **worst_alarm[1]["alarm"]},
                      "worstSevereDetection": worst_detection},
        "observations": observations,
        "notApplicable": skipped,
        "plan": injection_set.get("plan", []),
        "identitySwap": injection_set.get("identitySwap"),
        "caveats": [
            "N3 is unlabeled: a flag rate f bounds the false-alarm rate only as f / (1 - pi_max), pi_max being "
            "the maximum defect prevalence among natural takes.",
            "Nothing here qualifies anything. T1 on N3 is report-only: a fail bound needs FAR confirmed on N2 "
            "and a plan committed before its confirmation cohort is scored (A2, A5), and TPR on two "
            "mechanisms (A3). Fast QC v8's bounds stay legacy-unqualified (A10).",
            "Recorded takes carry no word intervals, so word-aligned variants are not applicable. The take-* "
            "variants are declared word-free constructions: clicks anywhere, a dropout centred on the take, "
            "noise against the whole take's RMS, a cut at a fraction of the take (which can remove only the "
            "trailing pause) and a run-on of a middle span appended after the take's end.",
            "Per-injection seeds derive from the source WAV digest, the injector and the catalog seed, not "
            "the variant, so a sham draws the same positions as its positives (injectors.inject).",
            "Fast QC runs each clip through the v8 mirror's limiter as if the engine had produced it, as M1 "
            "does; the Stage 0 observations read the PCM16 that limiter writes.",
            "Identity swaps from the donor pairs are deferred (identitySwap).",
        ],
    }
    report["headline"] = headline(report)
    return report


def headline(report: dict) -> list[str]:
    n3 = report["n3"]
    fraction, bound = m1._fraction, m1._bound
    lines = [f"N3 natural takes: v8 alarmed on {fraction(n3['alarm'])} families (flag rate <= "
             f"{bound(n3['alarm'])}, one-sided CP 95%) and failed {fraction(n3['fail'])}; unlabeled, so FAR <= "
             f"{n3['unlabeledBound']['farBoundAtPiMax'].get('0.1')} if at most 10% of takes are defective."]
    frequent = sorted(((row["n3"][row["basis"]]["events"], row["flag"]) for row in report["flags"]
                       if row["n3"][row["basis"]]["events"]), reverse=True)[:3]
    if frequent:
        lines.append("Most frequent N3 flags: " + ", ".join(f"{flag} {events}" for events, flag in frequent) + ".")
    pooled = report["shamsPooled"]
    departing = [row for row in report["shams"] if row["a4"]["overlaps"] is False]
    judged = [row for row in report["shams"] if row["a4"]["overlaps"] is not None]
    lines.append(f"Shams: {fraction(pooled['alarm'])} families alarmed against {fraction(pooled['n3Alarm'])} on "
                 f"N3 (intervals {'overlap' if pooled['overlaps'] else 'do not overlap' if pooled['overlaps'] is False else 'n/a'}); "
                 f"{len(departing)} of {len(judged)} sham rows depart on their target flags (A4)"
                 + (": " + ", ".join(f"{row['injector']} {row['variant']}" for row in departing) if departing else "")
                 + ".")
    severe = [row for row in report["detection"] if row["severity"] == "severe" and row["target"]]
    if severe:
        lines.append("Severe positives, target flags: " + ", ".join(
            f"{row['injector'].split('@')[0]} {fraction(row['target'])} (TPR >= {bound(row['target'], 'lower')})"
            for row in severe) + ".")
    blind = sorted({row["injector"].split("@")[0] for row in report["detection"] if not row["target"]})
    if blind:
        lines.append(f"No v8 detector: {', '.join(blind)} (their alarms are incidental).")
    worst = report["languages"]["worstN3Alarm"]
    if worst:
        lines.append(f"Worst language on N3: {worst['language']} ({worst['events']}/{worst['units']} families, "
                     f"flag rate <= {worst['upper']:.3f}).")
    lines.append("Report-only: T1 on N3 qualifies nothing (A2, A5).")
    return lines


def markdown(report: dict) -> str:
    fraction, bound = m1._fraction, m1._bound
    yes = {True: "yes", False: "NO", None: "n/a"}
    out = [
        "<!-- Generated by scripts/audio_qc_calibration_set.py score. Do not edit. -->",
        "## Audio QC calibration set M2: Fast QC v8 on natural takes, shams and T1 injections",
        "",
        f"Subject `{report['subject']['detector']}` through `{report['subject']['mirror']}` and "
        f"`{report['subject']['observations']}`; calibration `{report['subject']['calibration']}` (A10). "
        "Report-only: nothing here qualifies a bound. Rates are k/n source families with one-sided "
        "Clopper-Pearson 95% bounds.",
        "",
        "### Headline",
        "",
        *[f"- {line}" for line in report["headline"]],
        "",
        "### Populations",
        "",
        "| Population | Clips | Families |", "|---|---|---|",
        *[f"| {name} | {entry['clips']} | {entry['families']} |" for name, entry in report["populations"].items()],
        "",
        "### Flags: N3 rate and shams (A4)",
        "",
        "| Flag | Level | N3 | N3 upper | Shams | Shams upper | Overlap | Targeted by |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in report["flags"]:
        n3, sham = row["n3"][row["basis"]], row["shams"][row["basis"]]
        out.append(f"| {row['flag']} | {row['basis']} | {fraction(n3)} | {bound(n3)} | {fraction(sham)} | "
                   f"{bound(sham)} | {yes[row['overlaps']]} | {', '.join(row['targetedBy']) or 'none'} |")
    bound_row = report["n3"]["unlabeledBound"]
    out += ["", f"Any flag on N3: {fraction(report['n3']['alarm'])} (upper {bound(report['n3']['alarm'])}); "
                f"FAR bound f/(1 - pi_max): " + ", ".join(f"{value} at pi_max {pi}" for pi, value in
                                                        bound_row["farBoundAtPiMax"].items()) + ".",
            "", "### Shams (A4, against N3 on the same families)", "",
            "| Injector | Variant | Families | Not applicable | Alarm | N3 alarm | Overlap | Target flags | "
            "Sham target | N3 target | A4 overlap |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in report["shams"]:
        a4 = row["a4"]
        out.append(f"| {row['injector']} | {row['variant']} | {row['units']} | {row['notApplicable']} | "
                   f"{fraction(row['alarm'])} | {fraction(row['cleanAlarmSameFamilies'])} | "
                   f"{yes[row['alarmOverlaps']]} | {', '.join(row['targets']) or 'none'} | "
                   f"{fraction(a4.get('sham'))} | {fraction(a4.get('cleanSameFamilies'))} | {yes[a4['overlaps']]} |")
    out += ["", "### Detection of T1 injections on natural takes (P1)", "",
            "| Injector | Variant | Severity | Families | Not applicable | Target v8 flags | Detected | TPR lower | "
            "Any alarm | Fail |", "|---|---|---|---|---|---|---|---|---|---|"]
    for row in report["detection"]:
        out.append(f"| {row['injector']} | {row['variant']} | {row['severity']} | {row['units']} | "
                   f"{row['notApplicable']} | {', '.join(row['targets']) or 'none (no v8 detector)'} | "
                   f"{fraction(row['target'])} | {bound(row['target'], 'lower')} | {fraction(row['alarm'])} | "
                   f"{fraction(row['fail'])} |")
    languages = report["languages"]
    out += ["", "### Languages", "",
            f"Simultaneous per-language bounds use Bonferroni confidence {languages['simultaneousConfidence']}.",
            "", "| Language | N3 families | N3 alarm | Upper | Upper (simultaneous) | Fail | Sham alarm | "
                "Severe positives detected by their target flags |", "|---|---|---|---|---|---|---|---|"]
    for language, row in languages["rows"].items():
        severe = ", ".join(f"{key.split('@')[0]} {fraction(rate)}"
                           for key, rate in row["severeTargetDetection"].items()) or "none"
        out.append(f"| {language} | {row['n3Families']} | {fraction(row['alarm'])} | {bound(row['alarm'])} | "
                   f"{bound(row['alarmSimultaneous'])} | {fraction(row['fail'])} | {fraction(row['shamAlarm'])} | "
                   f"{severe} |")
    worst = languages["worstN3Alarm"]
    if worst:
        out += ["", f"Worst stratum on N3: {worst['language']} (alarm {worst['events']}/{worst['units']}, "
                    f"upper {worst['upper']:.3f})."]
    if languages["worstSevereDetection"]:
        out += ["", "Worst stratum per detected severe injector: " + ", ".join(
            f"{entry['injector'].split('@')[0]} {entry['language']} {entry['events']}/{entry['units']} "
            f"(TPR >= {entry['lower']:.3f})" for entry in languages["worstSevereDetection"]) + "."]
    measures = list(OBSERVATION_MEASURES)
    out += ["", "### Stage 0 observations", "", "N3 distribution (median / p90 / max):", "",
            "| Measure | N3 median | N3 p90 | N3 max | Sham median |", "|---|---|---|---|---|"]
    for name in measures:
        entry = report["observations"][name]
        n3, sham = entry["N3"] or {}, entry["S"] or {}
        out.append(f"| {name} | {n3.get('median', 'n/a')} | {n3.get('p90', 'n/a')} | {n3.get('max', 'n/a')} | "
                   f"{sham.get('median', 'n/a')} |")
    out += ["", "Median paired change (positive minus its source take):", "",
            "| Injector | Variant | " + " | ".join(measures) + " |", "|---|---|" + "---|" * len(measures)]
    for row in report["detection"]:
        values = [row["observationMedianDelta"].get(name) for name in measures]
        out.append(f"| {row['injector']} | {row['variant']} | "
                   + " | ".join("n/a" if value is None else f"{value:.3g}" for value in values) + " |")
    out += ["", "### Plan and not-applicable variants", "",
            "| Injector | Severity | Status | Variant | Catalog variant needs | Skips on takes |",
            "|---|---|---|---|---|---|"]
    for row in report["plan"]:
        skipped = (report["notApplicable"].get(row["injector"], {}).get("byVariant", {})
                   .get(row.get("variant") or "", {}))
        reasons = "; ".join(f"{count}: {reason}" for reason, count in skipped.items()) or "none"
        needs = ", ".join(row["catalogNeeds"]) or "nothing"
        out.append(f"| {row['injector']} | {row['severity']} | {row['status']} | {row.get('variant') or 'n/a'} | "
                   f"{needs} | {reasons} |")
    swap = report.get("identitySwap") or {}
    if swap:
        out += ["", f"Identity swap ({swap.get('injector')}): {swap.get('status')}; {swap.get('reason')} "
                    f"({swap.get('donorPairs', 0)} donor pairs in the manifest)."]
    out += ["", "### Caveats", "", *[f"- {caveat}" for caveat in report["caveats"]], "",
            f"Inputs: takes manifest `{report['inputs']['takesManifestSHA256'][:12]}`, injection set entries "
            f"`{report['inputs']['entriesSHA256'][:12]}`, measurements `{report['inputs']['measurementsSHA256'][:12]}`, "
            f"policy `{report['inputs']['policySHA256'][:12]}`, catalog v{report['inputs']['catalogVersion']}, "
            f"NumPy {report['inputs']['numpy']}.", ""]
    return "\n".join(out)


def run_score(takes_path: Path, set_path: Path, output: Path, *, jobs: int) -> dict:
    manifest, manifest_sha256 = load_takes(takes_path)
    injection_set = load_set(set_path)
    if injection_set.get("sourceManifest", {}).get("sha256") != manifest_sha256:
        raise CalibrationError("the injection set was built from another takes manifest")
    if json_digest(injection_set["entries"]) != injection_set.get("entriesSHA256"):
        raise CalibrationError("the injection set's entries differ from its entriesSHA256")
    takes = {take["takeID"]: take for take in generated_takes(manifest)}
    tasks = [{"clipID": take_id, "wav": str(take_wav(takes_path, take)), "wavSHA256": take["wavSHA256"],
              "text": take["text"], "meta": _meta(take, take_id, "N3", None)}
             for take_id, take in takes.items()]
    for entry in injection_set["entries"]:
        take = takes.get(entry.get("sourceTakeID"))
        if take is None:
            raise CalibrationError(f"{entry.get('takeID')}: its source take is not a generated take")
        injection = entry["injection"]
        tasks.append({"clipID": entry["takeID"], "wav": str(_relative_path(set_path.parent, entry["wavPath"],
                                                                           f"{entry['takeID']}: wavPath")),
                      "wavSHA256": entry["wavSHA256"], "text": take["text"],
                      "meta": _meta(take, entry["takeID"], injection["population"], injection)})
    log(f"score: {len(takes)} natural takes and {len(injection_set['entries'])} injected clips, {jobs} jobs")
    records: list[dict] = []

    def measured() -> Iterator[dict]:
        for measurement in parallel(_score_clip, tasks, jobs, "score"):
            records.append(_reduced(measurement))
            yield measurement

    head = {"schemaVersion": 1, "kind": MEASUREMENTS_KIND, "generator": GENERATOR,
            "privacy": "ids and digests only: no text, transcript or path",
            "takesManifestSHA256": manifest_sha256, "entriesSHA256": injection_set["entriesSHA256"],
            "subject": {"detector": m1.SUBJECT, "mirror": audio_qc.FASTQC_V8_MIRROR,
                        "observations": audio_qc_observations.OBSERVATIONS_MIRROR}}
    measurements_sha256 = _write_streamed(output / "measurements.json", head, "clips", measured(),
                                          lambda digest: {"clipsSHA256": digest, "clipCount": len(records)})
    inputs = {"takesManifestSHA256": manifest_sha256, "injectionSetSHA256": file_sha256(set_path),
              "entriesSHA256": injection_set["entriesSHA256"], "measurementsSHA256": measurements_sha256,
              "policySHA256": policy_module.policy_digest(), "catalogVersion": injectors.CATALOG_VERSION,
              "catalogSeed": injection_set.get("catalogSeed"), "numpy": np.__version__}
    report = build_report(records, inputs=inputs, injection_set=injection_set)
    (output / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
                                        encoding="utf-8")
    (output / "report.md").write_text(markdown(report), encoding="utf-8")
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _classes(value: str) -> tuple[str, ...]:
    classes = tuple(sorted({item.strip().upper() for item in value.split(",") if item.strip()}))
    if not classes or not set(classes) <= set("ABCDEFGHIJ"):
        raise argparse.ArgumentTypeError("classes are letters A-J, comma-separated")
    return classes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    inject = commands.add_parser("inject", help="build the injection set from natural takes")
    inject.add_argument("--takes", type=Path, required=True)
    inject.add_argument("--output", type=Path, required=True)
    inject.add_argument("--catalog-seed", type=int, default=DEFAULT_CATALOG_SEED)
    inject.add_argument("--classes", type=_classes, default=DEFAULT_CLASSES,
                        help="defect classes to inject (default A,C,F)")
    verify = commands.add_parser("verify", help="replay every recipe and compare output digests")
    verify.add_argument("--set", type=Path, required=True)
    verify.add_argument("--takes", type=Path, required=True)
    score = commands.add_parser("score", help="run Fast QC v8 and Stage 0 over N3, shams and positives")
    score.add_argument("--takes", type=Path, required=True)
    score.add_argument("--set", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    for command in (inject, verify, score):
        command.add_argument("--jobs", type=int, default=default_jobs(),
                             help="worker processes (default: half the cores)")
    args = parser.parse_args(argv)
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        if args.command == "inject":
            if args.catalog_seed < 0:
                parser.error("--catalog-seed must be non-negative")
            run_inject(args.takes, args.output, catalog_seed=args.catalog_seed, classes=args.classes, jobs=args.jobs)
            return 0
        if args.command == "verify":
            result = run_verify(args.set, args.takes, jobs=args.jobs)
            for clip, reason in result["failures"][:20]:
                print(f"FAIL {clip}: {reason}", file=sys.stderr)
            status = "PASS" if result["verified"] else "FAIL"
            print(f"verify: {status}: {result['entries']} entries from {result['sources']} source takes, "
                  f"{len(result['failures'])} failures")
            return 0 if result["verified"] else 1
        report = run_score(args.takes, args.set, args.output, jobs=args.jobs)
        for line in report["headline"]:
            print(f"- {line}")
        print(f"wrote {m1._display(args.output / 'report.json')} and {m1._display(args.output / 'report.md')}")
        return 0
    except (CalibrationError, recordings.RecordingError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
