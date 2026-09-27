"""AQ-06 panel qualification: the canary set, run analysis, records and promotion (audit P8, sections 5.8-5.9).

A panel judge moves from `candidate` to `shadow` only on committed evidence
(audit section 5.9): two clean resource runs on the canonical M6, a measured
determinism class and a canary record matching its output identity. This
module is the pure half of `scripts/audio_qc_panel_qualification.py`:

- **The canary set** (`config/audio-qc-canary-set.json`) is procedural and
  committed by golden PCM digest: speech-like sources rendered by
  `lib.qc_qualification.fixtures` (their pseudo-text is the script the aligner
  and the recognizers are scored against), with same-voice and cross-gender
  reference clips for the speaker judges, and silence, noise and a chord for
  every judge's degenerate inputs. No user data and no WAV is committed; the
  lead's latest language-bench takes (generated from the committed corpus)
  join it at run time for the recognizers.
- **Run analysis.** Per judge and run: every launch's measured peaks (sampled
  resident memory, physical footprint, the reaped `ru_maxrss`, the
  child-attributed peak and a native binary's own peak), the ceiling it ran
  under and its failure codes; the run's peak is the largest of them. Also wall
  time, model load and warm-up, threads, and whether the run was clean (every
  envelope qualified on the canonical host, no retry, no unavailable row).
  Determinism compares the two runs' raw outputs (L1) row by row: D0
  bit-exact, D1 equal on every discrete output with the largest numeric
  difference recorded as the measured tolerance, D2 otherwise.
- **Flip analysis.** whisper-small against Whisper large-v3 over the same
  speech takes: which language and accuracy verdicts flip, in each direction.
- **Records.** A privacy-safe canary record per judge (digests and metrics
  only), the session record, the flip analysis and one recovery report per
  run, each validated (`validate_record_file`). Only a complete session is
  published, and only the canary records of judges that passed.
- **Promotion.** `promote` edits `config/audio-qc-judges.json` in place for each
  candidate whose committed record passed: status `shadow`, its determinism
  class, its measured peak and calibrated ceiling (`ceilingBytes`, the larger
  peak of the two runs x 1.2, `ceilingStatus: calibrated`, `ceilingSession`)
  and its canary citation. Nothing else changes, and the registry must still
  validate, or nothing is written.
- **Ceiling recalibration.** A session whose purpose is
  `ceiling-recalibration` runs a full cohort with every judge under the
  measurement ceiling and publishes one ceiling record per judge (`CEILING_SCHEMA`,
  the take rows as a count and a digest). `recalibration_edits` then moves a
  shadow-or-later judge's `canonicalHostPeakBytes`, `ceilingBytes` and
  `ceilingSession` to that record's, appending the replaced ceiling to
  `ceilingHistory`; status, identity and canary never change.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Callable, Iterable, Mapping, Sequence
import wave

REPO = Path(__file__).resolve().parents[3]
CANARY_SET_PATH = REPO / "config/audio-qc-canary-set.json"
CANARY_SET_KIND = "audio-qc-panel-canary-set"
RECORDS_ROOT = REPO / "benchmarks/audio-qc-qualification"
CANARY_SCHEMA = "vocello.audioqc.qc-canary/1"
SESSION_SCHEMA = "vocello.audioqc.qc-panel-session/1"
FLIP_SCHEMA = "vocello.audioqc.qc-flip-analysis/1"
CEILING_SCHEMA = "vocello.audioqc.qc-ceiling/1"
QUALIFICATION_PURPOSE = "qualification"
RECALIBRATION_PURPOSE = "ceiling-recalibration"
PURPOSES = (QUALIFICATION_PURPOSE, RECALIBRATION_PURPOSE)
RECOVERY_REPORT_KIND = "delivery-analyzer-recovery-report"
MAX_RECORD_BYTES = 256 * 1024
REQUIRED_RUNS = 2
CANARY_ROLE = "canary"
CANARY_SAMPLE_RATE = 24_000
BASELINE_RECOGNIZER = "asr.whisper-small@1"
CANDIDATE_RECOGNIZER = "asr.whisper-large-v3@1"
DETERMINISM_CLASSES = ("unmeasured", "D0", "D1", "D2")
QUALIFIED_CLASSES = frozenset({"D0", "D1"})
SESSION_ID = re.compile(r"^[0-9]{8}-[0-9a-f]{8}$")
DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class QualificationError(ValueError):
    """A canary set, a session or a record is unusable."""


def json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_file_name(judge_id: str) -> str:
    """A judge's canary record file name: its id with `@N` spelled `-vN`."""
    name, version = judge_id.rsplit("@", 1)
    return f"{name}-v{version}.json"


# --------------------------------------------------------------------------- #
# The canary set
# --------------------------------------------------------------------------- #

def load_canary_set(path: Path = CANARY_SET_PATH) -> dict[str, Any]:
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QualificationError(f"cannot read the canary set: {error}") from None
    errors = canary_set_errors(spec)
    if errors:
        raise QualificationError("the canary set is invalid: " + "; ".join(errors[:3]))
    return spec


def canary_set_errors(spec: Any) -> list[str]:
    from lib.language_metrics import LANGUAGE_LOCALE_CODES
    from lib.qc_qualification import fixtures

    if not isinstance(spec, dict) or spec.get("kind") != CANARY_SET_KIND or spec.get("schemaVersion") != 1:
        return [f"the canary set is a {CANARY_SET_KIND} schema 1"]
    errors = []
    if spec.get("fixtureVersion") != fixtures.FIXTURE_VERSION or spec.get("sampleRateHz") != CANARY_SAMPLE_RATE:
        errors.append("the canary set names the fixture version and sample rate it was rendered at")
    takes = spec.get("takes")
    if not isinstance(takes, list) or not takes:
        return errors + ["the canary set lists its takes"]
    seen = set()
    for entry in takes:
        identity = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(identity, str) or not re.fullmatch(r"canary-[a-z0-9-]+", identity) or identity in seen:
            errors.append("every canary take has a unique canary-* id")
            continue
        seen.add(identity)
        source = entry.get("source")
        if not isinstance(source, dict) or source.get("kind") not in ("clean", "abstention"):
            errors.append(f"{identity}: its source is a clean or abstention fixture")
        if entry.get("language") not in LANGUAGE_LOCALE_CODES:
            errors.append(f"{identity}: its language is a product language")
        if entry.get("script") not in ("fixture-text", None):
            errors.append(f"{identity}: its script is the fixture's pseudo-text or none")
        if not _SHA256.fullmatch(str(entry.get("pcmSHA256", ""))):
            errors.append(f"{identity}: it pins its PCM digest")
        reference = entry.get("reference")
        if reference is not None and (
            not isinstance(reference, dict) or reference.get("relation") not in ("self", "close", "cross-gender")
            or type(reference.get("renderSeed")) is not int
            or not _SHA256.fullmatch(str(reference.get("pcmSHA256", "")))
        ):
            errors.append(f"{identity}: a reference clip names its voice relation, render seed and PCM digest")
    return errors


def canary_fixture(entry: Mapping[str, Any]) -> Any:
    from lib.qc_qualification import fixtures

    source = entry["source"]
    if source["kind"] == "clean":
        return fixtures.clean_fixture(int(source["index"]), str(source["stratum"]))
    return fixtures.abstention_fixture(str(source["abstention"]))


def canary_reference_samples(entry: Mapping[str, Any], fixture: Any) -> Any:
    from lib.qc_qualification import fixtures

    reference = entry.get("reference")
    if reference is None:
        return None
    voice = fixtures.donor_voice(fixture.voice, str(reference["relation"]))
    return fixtures.rerender(fixture, voice, render_seed=int(reference["renderSeed"]))


def _write_wav(path: Path, samples: Any) -> str:
    from lib.qc_qualification.pcm import to_pcm16

    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(CANARY_SAMPLE_RATE)
        output.writeframes(to_pcm16(samples).tobytes())
    return file_sha256(path)


def materialize_canary_set(spec: Mapping[str, Any], directory: Path) -> list[dict[str, Any]]:
    """Render every canary take (and reference clip) to a WAV, each checked against its golden PCM digest.

    Returns one description per take: its id, WAV path and digest, language,
    script (the fixture's pseudo-text, or None) and reference clip.
    """
    from lib.qc_qualification.pcm import pcm_digest

    takes = []
    for entry in spec["takes"]:
        fixture = canary_fixture(entry)
        if fixture.sample_rate != CANARY_SAMPLE_RATE or fixture.digest != entry["pcmSHA256"]:
            raise QualificationError(f"{entry['id']}: the rendered canary differs from its golden digest")
        audio = directory / f"{entry['id']}.wav"
        take = {"id": entry["id"], "audioPath": str(audio), "audioSHA256": _write_wav(audio, fixture.samples),
                "language": entry["language"], "durationSeconds": fixture.duration_seconds,
                "referenceText": fixture.text if entry.get("script") == "fixture-text" else None}
        samples = canary_reference_samples(entry, fixture)
        if samples is not None:
            if pcm_digest(samples) != entry["reference"]["pcmSHA256"]:
                raise QualificationError(f"{entry['id']}: the rendered reference differs from its golden digest")
            reference = directory / f"{entry['id']}.reference.wav"
            take.update(referenceAudioPath=str(reference), referenceAudioSHA256=_write_wav(reference, samples))
        takes.append(take)
    return takes


def canary_set_identity(spec: Mapping[str, Any]) -> dict[str, Any]:
    return {"sha256": json_digest(spec["takes"]), "takes": len(spec["takes"])}


# --------------------------------------------------------------------------- #
# Run analysis
# --------------------------------------------------------------------------- #

def _positive(value: Any) -> int | None:
    return value if type(value) is int and value > 0 else None


def launch_envelope(launch: Mapping[str, Any]) -> dict[str, Any]:
    """One worker launch's measured peaks, ceiling and failure codes (no text, no path)."""
    envelope = launch.get("resourceEnvelope") or {}
    attribution = envelope.get("recoveryAttribution") if isinstance(envelope.get("recoveryAttribution"), Mapping) \
        else {}
    admission = envelope.get("admission") if isinstance(envelope.get("admission"), Mapping) else {}
    ceiling = _positive(launch.get("ceilingBytes")) or _positive(admission.get("ceilingBytes")) \
        or _positive(envelope.get("maximumAllowedRSSBytes"))
    basis = launch.get("ceilingBasis")
    return {
        "launch": launch.get("launch"),
        "kind": launch.get("kind"),
        "ceilingBytes": ceiling,
        "ceilingBasis": basis if isinstance(basis, str) else None,
        "peakRSSBytes": _positive(envelope.get("peakRSSBytes")),
        "peakPhysicalFootprintBytes": _positive(envelope.get("peakPhysicalFootprintBytes")),
        "waitMaxRSSBytes": _positive(envelope.get("waitMaxRSSBytes")),
        "childPeakBytes": _positive(attribution.get("childPeakBytes")),
        "childPeakBasis": attribution.get("childPeakBasis") if isinstance(attribution.get("childPeakBasis"), str)
        else None,
        "descendantPeakRSSBytes": _positive(launch.get("descendantPeakRSSBytes")),
        "failures": sorted({str(code) for code in envelope.get("qualificationFailures") or []}),
    }


PEAK_FIELDS = ("peakRSSBytes", "peakPhysicalFootprintBytes", "waitMaxRSSBytes", "childPeakBytes",
               "descendantPeakRSSBytes")


def run_resources(worker: Mapping[str, Any] | None, *, canonical_host: str | None) -> dict[str, Any]:
    """One judge's resources in one run, and whether the run was clean, from its worker report.

    The run's peak is the largest measurement of any launch: the sampled
    resident memory and physical footprint, the exact `ru_maxrss` of the reaped
    worker, the child-attributed peak and a native binary's own peak. A spike
    between two samples still reaches the calibrated ceiling.
    """
    launches = list((worker or {}).get("launches") or [])
    envelopes = [launch.get("resourceEnvelope") or {} for launch in launches]
    details = [launch_envelope(launch) for launch in launches]
    failures: set[str] = set()
    if not launches:
        failures.add("not-launched")
    for launch in launches:
        if launch.get("retry"):
            failures.add("retried")
        if not launch.get("completed"):
            failures.add("incomplete")
        if launch.get("protocolError"):
            failures.add("protocol-error")
    for envelope in envelopes:
        failures.update(str(code) for code in envelope.get("qualificationFailures") or [])
        if canonical_host is None or envelope.get("hostProfileID") != canonical_host:
            failures.add("host-not-canonical")
    if (worker or {}).get("rowsUnavailable"):
        failures.add("rows-unavailable")
    if (worker or {}).get("rowsAdopted"):
        failures.add("rows-adopted")
    rss = [item["peakRSSBytes"] for item in details if item["peakRSSBytes"]]
    footprint = [item["peakPhysicalFootprintBytes"] for item in details if item["peakPhysicalFootprintBytes"]]
    peak = max((item[name] for item in details for name in PEAK_FIELDS if item[name]), default=None)
    if launches and peak is None:
        failures.add("peak-unmeasured")
    walls = [float(item["wallSeconds"]) for item in envelopes
             if isinstance(item.get("wallSeconds"), (int, float)) and math.isfinite(item["wallSeconds"])]
    swaps = [item["swapDeltaBytes"] for item in envelopes if type(item.get("swapDeltaBytes")) is int]
    sessions = sorted({str(item["sessionID"]) for item in envelopes if isinstance(item.get("sessionID"), str)})
    return {
        "clean": not failures,
        "failures": sorted(failures),
        "launches": len(launches),
        "rowsAccepted": int((worker or {}).get("rowsAccepted") or 0),
        "rowsUnavailable": len((worker or {}).get("rowsUnavailable") or {}),
        "peakRSSBytes": max(rss, default=None),
        "peakPhysicalFootprintBytes": max(footprint, default=None),
        "peakWaitMaxRSSBytes": max((item["waitMaxRSSBytes"] for item in details if item["waitMaxRSSBytes"]),
                                   default=None),
        "peakChildAttributedBytes": max((item["childPeakBytes"] for item in details if item["childPeakBytes"]),
                                        default=None),
        "peakDescendantRSSBytes": max((item["descendantPeakRSSBytes"] for item in details
                                       if item["descendantPeakRSSBytes"]), default=None),
        "peakBytes": peak,
        "launchEnvelopes": details,
        "wallSeconds": round(sum(walls), 3) if walls else None,
        "modelLoadSeconds": _rounded((worker or {}).get("modelLoadSeconds")),
        "warmupSeconds": _rounded((worker or {}).get("warmupSeconds")),
        "threads": (worker or {}).get("threads") if type((worker or {}).get("threads")) is int else None,
        "swapDeltaBytes": max(swaps, default=None),
        "sessionIDs": sessions,
    }


def _rounded(value: Any, places: int = 3) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(float(value), places)


def compare_payloads(first: Any, second: Any) -> dict[str, Any]:
    """One row's two raw outputs: bit-exact, or discrete mismatches and the largest numeric differences.

    Strings, booleans, nulls, integers, keys and list lengths are discrete; a
    float that differs is a numeric difference (absolute and relative).
    """
    result = {"bitExact": json_digest(first) == json_digest(second), "discreteMismatches": 0,
              "numericDifferences": 0, "maxAbsoluteDifference": 0.0, "maxRelativeDifference": 0.0}

    def walk(a: Any, b: Any) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) != set(b):
                result["discreteMismatches"] += 1
            for key in set(a) & set(b):
                walk(a[key], b[key])
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                result["discreteMismatches"] += 1
            for left, right in zip(a, b):
                walk(left, right)
            return
        floats = (isinstance(a, float) or isinstance(b, float)) and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in (a, b))
        if floats:
            if a != b:
                difference = abs(float(a) - float(b))
                scale = max(abs(float(a)), abs(float(b)), 1e-12)
                result["numericDifferences"] += 1
                result["maxAbsoluteDifference"] = max(result["maxAbsoluteDifference"], difference)
                result["maxRelativeDifference"] = max(result["maxRelativeDifference"], difference / scale)
            return
        if type(a) is not type(b) or a != b:
            result["discreteMismatches"] += 1

    walk(first, second)
    return result


def determinism(pairs: Sequence[tuple[Any, Any]]) -> dict[str, Any]:
    """The determinism class over every row both runs produced (audit sections 3.1 and 5.8)."""
    compared = [compare_payloads(first, second) for first, second in pairs]
    exact = sum(1 for item in compared if item["bitExact"])
    discrete = sum(item["discreteMismatches"] for item in compared)
    if not compared:
        klass = "unmeasured"
    elif exact == len(compared):
        klass = "D0"
    elif discrete == 0:
        klass = "D1"
    else:
        klass = "D2"
    return {
        "class": klass,
        "rowsCompared": len(compared),
        "rowsBitExact": exact,
        "rowsWithDiscreteMismatch": sum(1 for item in compared if item["discreteMismatches"]),
        "discreteMismatches": discrete,
        "numericDifferences": sum(item["numericDifferences"] for item in compared),
        # The measured tolerance of a D1 judge; zero for D0.
        "maxAbsoluteDifference": float(f"{max((item['maxAbsoluteDifference'] for item in compared), default=0.0):.6g}"),
        "maxRelativeDifference": float(f"{max((item['maxRelativeDifference'] for item in compared), default=0.0):.6g}"),
    }


def admission_ceiling(peak: int | None) -> int | None:
    """The registry's ceiling rule: the measured canonical-host peak x 1.2, rounded up."""
    return None if peak is None else -(-peak * 12 // 10)


def _two_runs(runs: Sequence[Mapping[str, Any]], *, budget_bytes: int,
              reservation_bytes: int) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Determinism, resources and the reasons two runs fail on, determinism aside."""
    if len(runs) != REQUIRED_RUNS:
        raise QualificationError(f"a qualification compares exactly {REQUIRED_RUNS} runs")
    first, second = runs
    units = sorted(set(first["raw"]) | set(second["raw"]))
    pairs = [(first["raw"][unit], second["raw"][unit]) for unit in units
             if unit in first["raw"] and unit in second["raw"]]
    measured = determinism(pairs)
    peaks = [run["resources"]["peakBytes"] for run in runs if run["resources"]["peakBytes"] is not None]
    peak = max(peaks) if len(peaks) == REQUIRED_RUNS else None
    ceiling = admission_ceiling(peak)
    fits = ceiling is not None and ceiling + reservation_bytes <= budget_bytes
    reasons = []
    for index, run in enumerate(runs, start=1):
        if not run["resources"]["clean"]:
            reasons.append(f"run-{index}-not-clean")
    if len(pairs) != len(units):
        reasons.append("rows-missing")
    if not fits:
        reasons.append("ceiling-exceeds-budget" if ceiling is not None else "peak-unmeasured")
    resources = {"canonicalHostPeakBytes": peak, "admissionCeilingBytes": ceiling, "fitsBudget": fits,
                 "runPeakBytes": [run["resources"]["peakBytes"] for run in runs]}
    return measured, resources, reasons


def _identity_components(identity: Mapping[str, Any]) -> dict[str, Any]:
    components = dict(identity["components"])
    host = components.pop("hostProfile", None)
    components["hostProfileSHA256"] = json_digest(host)
    return components


def _record_runs(runs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{"run": index, **dict(run["resources"])} for index, run in enumerate(runs, start=1)]


def judge_analysis(judge_id: str, *, runs: Sequence[Mapping[str, Any]], identity: Mapping[str, Any],
                   takes: Sequence[Mapping[str, Any]], session: Mapping[str, Any], canary_set: Mapping[str, Any],
                   registry_sha256: str, budget_bytes: int, reservation_bytes: int) -> dict[str, Any]:
    """One judge's canary record from its two runs (privacy-safe: digests and metrics only).

    `runs[i]` holds the judge's `resources` (from `run_resources`), `raw` (its
    raw output per unit, private and never copied here) and `measurements`
    (the take-evidence measurement per take).
    """
    measured, resources, reasons = _two_runs(runs, budget_bytes=budget_bytes, reservation_bytes=reservation_bytes)
    if measured["class"] not in QUALIFIED_CLASSES:
        reasons.append(f"determinism-{measured['class'].lower()}")
    return {
        "schema": CANARY_SCHEMA,
        "judge": judge_id,
        "session": dict(session),
        "registrySHA256": registry_sha256,
        "outputIdentity": identity["outputIdentity"],
        "identityComponents": _identity_components(identity),
        "canarySet": dict(canary_set),
        "runs": _record_runs(runs),
        "resources": resources,
        "determinism": measured,
        "takes": take_rows(runs, takes),
        "qualification": {"passed": not reasons, "reasons": sorted(reasons)},
    }


def ceiling_analysis(judge_id: str, *, runs: Sequence[Mapping[str, Any]], identity: Mapping[str, Any],
                     takes: Sequence[Mapping[str, Any]], session: Mapping[str, Any], canary_set: Mapping[str, Any],
                     registry_sha256: str, budget_bytes: int, reservation_bytes: int) -> dict[str, Any]:
    """One judge's ceiling record from a full-cohort recalibration session's two runs.

    The canary record's identity, resources and determinism, with the take rows
    kept only as a count and one digest (hundreds of takes would not fit a
    record), and a `recalibration` verdict: two clean runs, no missing row and
    a ceiling the budget holds. Determinism is measured and reported but never
    a reason: the ceiling bounds memory, and the judge keeps the class its
    canary record qualified.
    """
    measured, resources, reasons = _two_runs(runs, budget_bytes=budget_bytes, reservation_bytes=reservation_bytes)
    rows = take_rows(runs, takes)
    return {
        "schema": CEILING_SCHEMA,
        "judge": judge_id,
        "session": dict(session),
        "registrySHA256": registry_sha256,
        "outputIdentity": identity["outputIdentity"],
        "identityComponents": _identity_components(identity),
        "canarySet": dict(canary_set),
        "runs": _record_runs(runs),
        "resources": resources,
        "determinism": measured,
        "takes": {"rows": len(rows), "canaryRows": sum(1 for row in rows if row["role"] == CANARY_ROLE),
                  "rowsSHA256": json_digest(rows)},
        "recalibration": {"passed": not reasons, "reasons": sorted(reasons)},
    }


def take_rows(runs: Sequence[Mapping[str, Any]], takes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Per take: its digests, both runs' raw, metrics and transcript digests, and the first run's flat metrics."""
    rows = []
    for take in takes:
        # A record names a take by its safe id; the raw outputs by the manifest's.
        take_id, unit = take["takeID"], take.get("unit", take["takeID"])
        measurements = [run["measurements"].get(take_id) or {} for run in runs]
        status = measurements[0].get("status") or "none"
        row = {
            "takeID": take_id, "role": take.get("role"), "language": take["language"],
            "audioSHA256": take["audioSHA256"], "canonicalPCMSHA256": take["canonicalPCMSHA256"],
            "status": status,
            "rawSHA256": [json_digest(run["raw"][unit]) if unit in run["raw"] else None for run in runs],
            "metricsSHA256": [item.get("metricsSHA256") for item in measurements],
            "transcriptSHA256": [item.get("transcriptSHA256") for item in measurements],
            "metrics": dict(measurements[0].get("metrics") or {}),
        }
        rows.append(row)
    return rows


# --------------------------------------------------------------------------- #
# Flip analysis
# --------------------------------------------------------------------------- #

def _verdicts(measurement: Mapping[str, Any] | None, language: str) -> dict[str, Any]:
    from lib.language_metrics import MAX_ACCURACY_ERROR_RATE

    metrics = (measurement or {}).get("metrics") or {}
    if (measurement or {}).get("status") != "complete":
        return {}
    output: dict[str, Any] = {}
    rate = metrics.get("errorRate")
    if isinstance(rate, (int, float)) and not isinstance(rate, bool):
        output["accuracy"] = "pass" if rate <= MAX_ACCURACY_ERROR_RATE else "fail"
        output["errorRate"] = rate
    detected = metrics.get("detectedLanguage")
    if isinstance(detected, str):
        output["language"] = "pass" if detected == language else "fail"
        output["detected"] = detected
    return output


def flip_analysis(records: Sequence[Mapping[str, Any]], *, baseline: str = BASELINE_RECOGNIZER,
                  candidate: str = CANDIDATE_RECOGNIZER) -> dict[str, Any]:
    """Which language and accuracy verdicts flip between two recognizers over the same speech takes.

    `records` are one run's take-evidence records; canary (procedural) takes
    are left out, since their scripts are pseudo-text.
    """
    language_rows: list[dict[str, Any]] = []
    accuracy_rows: list[dict[str, Any]] = []
    compared = {"language": 0, "accuracy": 0}
    for record in records:
        take = record["take"]
        if take.get("role") == CANARY_ROLE:
            continue
        measured = {item["judge"]: item for item in record.get("measurements") or []}
        if baseline not in measured or candidate not in measured:
            continue
        first = _verdicts(measured[baseline], take["language"])
        second = _verdicts(measured[candidate], take["language"])
        common = {"takeID": take["takeID"], "language": take["language"],
                  "expectedOutcome": take.get("expectedOutcome")}
        if "language" in first and "language" in second:
            compared["language"] += 1
            if first["language"] != second["language"]:
                language_rows.append({**common, "baseline": first["language"], "candidate": second["language"],
                                      "baselineDetected": first["detected"], "candidateDetected": second["detected"]})
        if "accuracy" in first and "accuracy" in second:
            compared["accuracy"] += 1
            if first["accuracy"] != second["accuracy"]:
                accuracy_rows.append({**common, "baseline": first["accuracy"], "candidate": second["accuracy"],
                                      "baselineErrorRate": first["errorRate"],
                                      "candidateErrorRate": second["errorRate"]})

    def channel(rows: list[dict[str, Any]], total: int) -> dict[str, Any]:
        return {
            "compared": total, "flips": len(rows),
            "fraction": round(len(rows) / total, 6) if total else None,
            "passToFail": sum(1 for row in rows if row["baseline"] == "pass"),
            "failToPass": sum(1 for row in rows if row["baseline"] == "fail"),
            "flipped": sorted(rows, key=lambda row: row["takeID"]),
        }

    return {"schema": FLIP_SCHEMA, "baseline": baseline, "candidate": candidate,
            "language": channel(language_rows, compared["language"]),
            "accuracy": channel(accuracy_rows, compared["accuracy"])}


def flipped_ids(analysis: Mapping[str, Any]) -> dict[str, list[str]]:
    return {channel: [row["takeID"] for row in analysis[channel]["flipped"]] for channel in ("language", "accuracy")}


# --------------------------------------------------------------------------- #
# Record validation
# --------------------------------------------------------------------------- #

def _size_errors(record: Any) -> list[str]:
    size = len(json.dumps(record, sort_keys=True, separators=(",", ":"), allow_nan=True).encode("utf-8"))
    return [] if size <= MAX_RECORD_BYTES else [f"a qualification record is at most {MAX_RECORD_BYTES} bytes"]


def _session_errors(session: Any) -> list[str]:
    if not isinstance(session, Mapping):
        return ["session must be an object"]
    errors = []
    if not SESSION_ID.fullmatch(str(session.get("id", ""))):
        errors.append("session.id is a <yyyymmdd>-<8 hex> session id")
    if not DATE.fullmatch(str(session.get("date", ""))):
        errors.append("session.date is an ISO date")
    if not isinstance(session.get("hostProfileID"), str) or not session["hostProfileID"]:
        errors.append("session.hostProfileID names the hardware profile")
    return errors


_MEASURED_FIELDS = frozenset({"schema", "judge", "session", "registrySHA256", "outputIdentity", "identityComponents",
                              "canarySet", "runs", "resources", "determinism", "takes"})


def _measured_record_errors(record: Mapping[str, Any], verdict: str,
                            ) -> tuple[list[str], list[Any], str | None, Any, Mapping[str, Any]]:
    """What a canary and a ceiling record share: identity, both runs, determinism, resources and the verdict.

    Returns the errors, the runs, the determinism class, the peak and the
    resources, for the caller's own verdict rule.
    """
    errors = []
    if not isinstance(record["judge"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*@[0-9]+", record["judge"]):
        errors.append("judge is a registry judge id")
    errors.extend(_session_errors(record["session"]))
    for field in ("registrySHA256", "outputIdentity"):
        if not _SHA256.fullmatch(str(record.get(field, ""))):
            errors.append(f"{field} is a SHA-256")
    components = record["identityComponents"]
    if not isinstance(components, Mapping) or not _SHA256.fullmatch(str(components.get("registryEntrySHA256", ""))) \
            or not isinstance(components.get("workerSourceSHA256"), Mapping) \
            or type(components.get("threads")) is not int:
        errors.append("identityComponents records the registry entry, worker sources and threads")
    runs = record["runs"]
    if not isinstance(runs, list) or len(runs) != REQUIRED_RUNS or [run.get("run") for run in runs
                                                                    if isinstance(run, Mapping)] != [1, 2]:
        errors.append(f"runs holds runs 1 and {REQUIRED_RUNS}")
        runs = []
    for run in runs:
        if not isinstance(run.get("clean"), bool) or not isinstance(run.get("failures"), list):
            errors.append("each run records whether it was clean and its failures")
        elif run["clean"] == bool(run["failures"]):
            errors.append("a clean run has no failures, and a run with failures is not clean")
    klass = (record["determinism"] or {}).get("class") if isinstance(record["determinism"], Mapping) else None
    if klass not in DETERMINISM_CLASSES:
        errors.append("determinism.class is D0, D1, D2 or unmeasured")
    resources = record["resources"] if isinstance(record["resources"], Mapping) else {}
    peak = resources.get("canonicalHostPeakBytes")
    if peak is not None and type(peak) is not int:
        errors.append("resources.canonicalHostPeakBytes is an integer or null")
    if resources.get("admissionCeilingBytes") != admission_ceiling(peak if type(peak) is int else None):
        errors.append("resources.admissionCeilingBytes is the peak x 1.2, rounded up")
    outcome = record[verdict] if isinstance(record[verdict], Mapping) else {}
    passed = outcome.get("passed")
    if not isinstance(passed, bool) or not isinstance(outcome.get("reasons"), list):
        errors.append(f"{verdict} records passed and its reasons")
    elif passed != (not outcome["reasons"]):
        errors.append(f"a {verdict} passes exactly when it has no reasons")
    elif passed and (any(not run.get("clean") for run in runs) or type(peak) is not int
                     or resources.get("fitsBudget") is not True):
        errors.append(f"a passing {verdict} has two clean runs and a peak that fits the budget")
    return errors, runs, klass, peak, resources


def validate_canary_record(record: Any) -> list[str]:
    """Errors in one judge's canary record; empty when it is complete, consistent and privacy-safe."""
    from lib.qc_pipeline.evidence import privacy_errors

    if not isinstance(record, Mapping) or record.get("schema") != CANARY_SCHEMA:
        return [f"a canary record declares {CANARY_SCHEMA}"]
    expected = _MEASURED_FIELDS | {"qualification"}
    if set(record) != expected:
        return [f"a canary record has exactly {sorted(expected)}"]
    errors, _runs, klass, _peak, _resources = _measured_record_errors(record, "qualification")
    if isinstance(record["qualification"], Mapping) and record["qualification"].get("passed") is True \
            and klass not in QUALIFIED_CLASSES:
        errors.append("a passing qualification has two clean runs, a D0 or D1 class and a peak that fits the budget")
    takes = record["takes"]
    if not isinstance(takes, list) or not takes:
        errors.append("takes lists the canary rows")
    else:
        for index, take in enumerate(takes):
            if not isinstance(take, Mapping) or not isinstance(take.get("metrics"), Mapping) or any(
                    isinstance(value, (Mapping, list)) for value in take["metrics"].values()):
                errors.append(f"takes[{index}] carries flat metrics")
    errors.extend(_size_errors(record))
    errors.extend(privacy_errors(dict(record)))
    return errors


def validate_ceiling_record(record: Any) -> list[str]:
    """Errors in one judge's ceiling record from a recalibration session; empty when it is sound and private."""
    from lib.qc_pipeline.evidence import privacy_errors

    if not isinstance(record, Mapping) or record.get("schema") != CEILING_SCHEMA:
        return [f"a ceiling record declares {CEILING_SCHEMA}"]
    expected = _MEASURED_FIELDS | {"recalibration"}
    if set(record) != expected:
        return [f"a ceiling record has exactly {sorted(expected)}"]
    errors, _runs, _klass, _peak, _resources = _measured_record_errors(record, "recalibration")
    takes = record["takes"]
    if not isinstance(takes, Mapping) or set(takes) != {"rows", "canaryRows", "rowsSHA256"} \
            or type(takes.get("rows")) is not int or takes["rows"] < 1 or type(takes.get("canaryRows")) is not int \
            or not 0 <= takes["canaryRows"] <= takes["rows"] or not _SHA256.fullmatch(str(takes.get("rowsSHA256"))):
        errors.append("takes counts the cohort's rows and its canary rows and digests them")
    errors.extend(_size_errors(record))
    errors.extend(privacy_errors(dict(record)))
    return errors


def validate_flip_record(record: Any) -> list[str]:
    from lib.qc_pipeline.evidence import privacy_errors

    if not isinstance(record, Mapping) or record.get("schema") != FLIP_SCHEMA:
        return [f"a flip analysis declares {FLIP_SCHEMA}"]
    errors = []
    if set(record) != {"schema", "baseline", "candidate", "language", "accuracy", "session", "run2Consistent"}:
        errors.append("a flip analysis has its session, both recognizers, both channels and run2Consistent")
    for channel in ("language", "accuracy"):
        value = record.get(channel)
        if not isinstance(value, Mapping) or type(value.get("compared")) is not int or type(value.get("flips")) is not int \
                or not isinstance(value.get("flipped"), list) or len(value["flipped"]) != value["flips"]:
            errors.append(f"{channel} counts its comparisons and lists every flip")
    if not isinstance(record.get("run2Consistent"), bool):
        errors.append("run2Consistent says whether the second run flipped the same takes")
    errors.extend(_session_errors(record.get("session")))
    errors.extend(_size_errors(record))
    errors.extend(privacy_errors(dict(record)))
    return errors


def validate_session_record(record: Any) -> list[str]:
    from lib.qc_pipeline.evidence import privacy_errors

    if not isinstance(record, Mapping) or record.get("schema") != SESSION_SCHEMA:
        return [f"a session record declares {SESSION_SCHEMA}"]
    errors = _session_errors(record.get("session"))
    purpose = session_purpose(record)
    if purpose not in PURPOSES:
        errors.append(f"purpose is one of {', '.join(PURPOSES)}")
    judges = record.get("judges")
    if not isinstance(judges, Mapping) or not judges:
        errors.append("judges lists every panel judge the session qualified")
        judges = {}
    for judge_id, entry in judges.items():
        if not isinstance(entry, Mapping) or not isinstance(entry.get("passed"), bool):
            errors.append(f"judges.{judge_id} records whether it passed")
        elif purpose == RECALIBRATION_PURPOSE:
            if not isinstance(entry.get("record"), str):
                errors.append(f"judges.{judge_id}: a recalibration session publishes every judge's ceiling record")
        elif entry["passed"] != (entry.get("record") is not None):
            errors.append(f"judges.{judge_id}: exactly the judges that passed publish a canary record")
    runs = record.get("runs")
    if not isinstance(runs, list) or len(runs) != REQUIRED_RUNS:
        errors.append(f"runs lists the session's {REQUIRED_RUNS} runs and their recovery reports")
    errors.extend(_size_errors(record))
    errors.extend(privacy_errors(dict(record)))
    return errors


def validate_recovery_report(record: Any) -> list[str]:
    if not isinstance(record, Mapping) or record.get("kind") != RECOVERY_REPORT_KIND \
            or record.get("schemaVersion") != 1 or record.get("candidateRule") != "attributed-post-exit-recovery-v2":
        return [f"a recovery report is a {RECOVERY_REPORT_KIND} of the candidate rule"]
    counts = ("envelopes", "serialEnvelopes", "unattributed", "overlapPossibleEnvelopes", "envelopesWithoutSession",
              "envelopesWithoutHost", "serialCandidateWouldQualifyBindingFailure")
    return [f"{field} is a count" for field in counts if type(record.get(field)) is not int]


def session_purpose(session: Mapping[str, Any]) -> Any:
    """A session record's purpose; a record from before recalibration existed qualified judges."""
    return session.get("purpose", QUALIFICATION_PURPOSE)


VALIDATORS: dict[str, Callable[[Any], list[str]]] = {
    CANARY_SCHEMA: validate_canary_record,
    CEILING_SCHEMA: validate_ceiling_record,
    SESSION_SCHEMA: validate_session_record,
    FLIP_SCHEMA: validate_flip_record,
}


def validate_record_file(path: Path) -> list[str]:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return [f"{path.name}: unreadable ({type(error).__name__})"]
    if isinstance(record, Mapping) and record.get("kind") == RECOVERY_REPORT_KIND:
        validator = validate_recovery_report
    else:
        validator = VALIDATORS.get(record.get("schema") if isinstance(record, Mapping) else None)
    if validator is None:
        return [f"{path.name}: not a qualification record"]
    return [f"{path.name}: {problem}" for problem in validator(record)]


def validate_session_directory(directory: Path) -> list[str]:
    """Every record of one published session, and the references between them."""
    errors = []
    session_path = directory / "session.json"
    if not session_path.is_file():
        return [f"{directory.name}: session.json is missing"]
    for path in sorted(directory.rglob("*.json")):
        errors.extend(f"{directory.name}/{problem}" for problem in validate_record_file(path))
    if errors:
        return errors
    session = json.loads(session_path.read_text(encoding="utf-8"))
    if session["session"]["id"] != directory.name:
        errors.append(f"{directory.name}: the directory is named for its session id")
    listed = set()
    recalibration = session_purpose(session) == RECALIBRATION_PURPOSE
    for judge_id, entry in session["judges"].items():
        if entry["record"] is None:
            continue
        listed.add(entry["record"])
        path = directory / entry["record"]
        if not path.is_file():
            errors.append(f"{directory.name}: {entry['record']} is missing")
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if recalibration:
            if record.get("schema") != CEILING_SCHEMA or record.get("judge") != judge_id \
                    or record["session"] != session["session"] \
                    or record["recalibration"]["passed"] != entry["passed"]:
                errors.append(f"{directory.name}: {entry['record']} is not {judge_id}'s ceiling record of this session")
        elif record.get("schema") != CANARY_SCHEMA or record.get("judge") != judge_id \
                or record["session"] != session["session"] or not record["qualification"]["passed"]:
            errors.append(f"{directory.name}: {entry['record']} is not {judge_id}'s passing record of this session")
    for path in sorted((directory / "judges").glob("*.json")) if (directory / "judges").is_dir() else []:
        if path.relative_to(directory).as_posix() not in listed:
            errors.append(f"{directory.name}: {path.name} is not listed in session.json")
    for run in session["runs"]:
        if not (directory / str(run.get("recoveryReport"))).is_file():
            errors.append(f"{directory.name}: run {run.get('run')}'s recovery report is missing")
    flip = session.get("flipAnalysis")
    if flip is not None and not (directory / str(flip)).is_file():
        errors.append(f"{directory.name}: {flip} is missing")
    return errors


def validate_records(root: Path = RECORDS_ROOT) -> list[str]:
    if not root.is_dir():
        return []
    errors = []
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        errors.extend(validate_session_directory(directory))
    for path in sorted(root.iterdir()):
        if path.is_file() and path.name != "README.md":
            errors.append(f"{path.name}: records live in one directory per session")
    return errors


# --------------------------------------------------------------------------- #
# Registry integrity (read by `audio_qc_judges`)
# --------------------------------------------------------------------------- #

def identity_freshness_errors(record: Mapping[str, Any], judge_id: str, registry: Mapping[str, Any], *,
                              root: Path = REPO) -> list[str]:
    """A warn or gating judge's canary must match today's worker sources and runtime (audit 5.8)."""
    from lib.qc_pipeline.panel_jobs import runtime_identity, worker_sources

    components = record.get("identityComponents") or {}
    judge = (registry.get("judges") or {}).get(judge_id) or {}
    engine = str((judge.get("execution") or {}).get("engine"))
    errors = []
    try:
        if components.get("workerSourceSHA256") != worker_sources(engine, root=root):
            errors.append("its worker sources changed since its canary record; a judge canary is required")
        if components.get("runtime") != runtime_identity(registry, judge_id):
            errors.append("its runtime changed since its canary record; a judge canary is required")
    except (OSError, ValueError):
        errors.append("its worker sources or runtime cannot be read")
    return errors


# --------------------------------------------------------------------------- #
# Promotion: surgical edits of the registry's JSON text
# --------------------------------------------------------------------------- #

_WHITESPACE = " \t\r\n"
_LITERAL = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][-+]?[0-9]+)?|true|false|null")


def _skip(text: str, index: int) -> int:
    while index < len(text) and text[index] in _WHITESPACE:
        index += 1
    return index


def _scan(text: str, index: int, path: tuple[str, ...], spans: dict[tuple[str, ...], tuple[int, int]],
          wanted: set[tuple[str, ...]]) -> int:
    """Parse one JSON value at `index`; record the span of every wanted key path; return its end."""
    index = _skip(text, index)
    character = text[index]
    if character == "{":
        index = _skip(text, index + 1)
        if text[index] == "}":
            return index + 1
        while True:
            key, index = json.decoder.scanstring(text, _skip(text, index) + 1)
            index = _skip(text, index)
            if text[index] != ":":
                raise QualificationError("the registry is not well-formed JSON")
            start = _skip(text, index + 1)
            end = _scan(text, start, (*path, key), spans, wanted)
            if (*path, key) in wanted:
                spans[(*path, key)] = (start, end)
            index = _skip(text, end)
            if text[index] == ",":
                index += 1
                continue
            if text[index] == "}":
                return index + 1
            raise QualificationError("the registry is not well-formed JSON")
    if character == "[":
        index = _skip(text, index + 1)
        if text[index] == "]":
            return index + 1
        position = 0
        while True:
            index = _skip(text, _scan(text, index, (*path, str(position)), spans, wanted))
            position += 1
            if text[index] == ",":
                index += 1
                continue
            if text[index] == "]":
                return index + 1
            raise QualificationError("the registry is not well-formed JSON")
    if character == '"':
        return json.decoder.scanstring(text, index + 1)[1]
    match = _LITERAL.match(text, index)
    if match is None:
        raise QualificationError("the registry is not well-formed JSON")
    return match.end()


def replace_json_values(text: str, edits: Mapping[tuple[str, ...], Any]) -> str:
    """Replace the values at existing key paths, keeping every other byte of the file.

    Each new value is written on one line, the registry's style for small
    objects. The result must parse to exactly the edited document.
    """
    spans: dict[tuple[str, ...], tuple[int, int]] = {}
    _scan(text, 0, (), spans, set(edits))
    missing = sorted(".".join(path) for path in set(edits) - set(spans))
    if missing:
        raise QualificationError(f"the registry has no {', '.join(missing)} to update")
    output = text
    for path, (start, end) in sorted(spans.items(), key=lambda item: item[1][0], reverse=True):
        output = output[:start] + json.dumps(edits[path], ensure_ascii=False, separators=(", ", ": ")) + output[end:]
    expected = json.loads(text)
    for path, value in edits.items():
        node = expected
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
    if json.loads(output) != expected:
        raise QualificationError("the registry edit changed more than the promoted values")
    return output


def promotion_edits(registry: Mapping[str, Any], session: Mapping[str, Any], records: Mapping[str, Mapping[str, Any]],
                    *, record_paths: Mapping[str, str], record_digests: Mapping[str, str],
                    ) -> tuple[dict[tuple[str, ...], Any], dict[str, str]]:
    """The registry edits that promote each candidate whose committed record passed, and why others are skipped."""
    from audio_qc_judges import acquisition_entry_digest

    edits: dict[tuple[str, ...], Any] = {}
    skipped: dict[str, str] = {}
    judges = registry.get("judges") or {}
    for judge_id, entry in sorted((session.get("judges") or {}).items()):
        judge = judges.get(judge_id)
        record = records.get(judge_id)
        if not entry.get("passed") or record is None:
            skipped[judge_id] = "did-not-pass"
            continue
        if not isinstance(judge, Mapping) or "acquisition" not in judge:
            skipped[judge_id] = "not-a-panel-judge"
            continue
        if judge.get("status") != "candidate":
            skipped[judge_id] = f"status-{judge.get('status')}"
            continue
        if record["identityComponents"].get("registryEntrySHA256") != acquisition_entry_digest(dict(judge)):
            skipped[judge_id] = "registry-entry-changed"
            continue
        resources = dict(judge.get("resources") or {})
        resources["canonicalHostPeakBytes"] = record["resources"]["canonicalHostPeakBytes"]
        resources["ceilingBytes"] = record["resources"]["admissionCeilingBytes"]
        resources["ceilingStatus"] = "calibrated"
        resources["ceilingSession"] = record["session"]["id"]
        base = ("judges", judge_id)
        edits[(*base, "status")] = "shadow"
        edits[(*base, "determinismClass")] = record["determinism"]["class"]
        edits[(*base, "resources")] = resources
        edits[(*base, "canary")] = {"record": record_paths[judge_id], "sha256": record_digests[judge_id],
                                    "outputIdentity": record["outputIdentity"],
                                    "date": record["session"]["date"]}
    return edits, skipped


def candidate_entry(judge: Mapping[str, Any]) -> dict[str, Any]:
    """A promoted judge's entry as it read before `promotion_edits` (for receipts written before P8)."""
    entry = copy.deepcopy(dict(judge))
    if entry.get("status") != "shadow" or not isinstance(entry.get("canary"), Mapping):
        return entry
    entry.update(status="candidate", determinismClass="unmeasured", canary=None)
    resources = dict(entry.get("resources") or {})
    resources.update(canonicalHostPeakBytes=None, ceilingStatus="provisional")
    resources.pop("ceilingBytes", None)
    resources.pop("ceilingSession", None)
    resources.pop("ceilingHistory", None)
    entry["resources"] = resources
    return entry


# --------------------------------------------------------------------------- #
# Ceiling recalibration
# --------------------------------------------------------------------------- #

RECALIBRATION_STATUSES = frozenset({"shadow", "advisory", "warn", "gating"})
CEILING_HISTORY_FIELDS = ("ceilingSession", "date", "canonicalHostPeakBytes", "ceilingBytes")


def session_date(session_id: str) -> str:
    """The ISO date a session id starts with (`<yyyymmdd>-<8 hex>`, the session record's own date)."""
    return f"{session_id[:4]}-{session_id[4:6]}-{session_id[6:8]}"


def _refusal(record: Mapping[str, Any], canonical_host: str | None, session: Mapping[str, Any]) -> str | None:
    """Why a ceiling record cannot move a ceiling: an unclean run, another host, or a failed verdict."""
    if canonical_host is None or session.get("hostProfileID") != canonical_host \
            or record["session"].get("hostProfileID") != canonical_host \
            or any("host-not-canonical" in run.get("failures", []) for run in record["runs"]):
        return "not-canonical-host"
    for run in record["runs"]:
        if not run.get("clean"):
            return f"run-{run.get('run')}-not-clean ({', '.join(run.get('failures') or [])})"
    if not record["recalibration"]["passed"]:
        return ", ".join(record["recalibration"]["reasons"]) or "did-not-pass"
    if type(record["resources"].get("canonicalHostPeakBytes")) is not int:
        return "peak-unmeasured"
    return None


def recalibration_edits(registry: Mapping[str, Any], session: Mapping[str, Any],
                        records: Mapping[str, Mapping[str, Any]], *, canonical_host: str | None,
                        allow_lower: bool = False,
                        ) -> tuple[dict[tuple[str, ...], Any], dict[str, dict[str, Any]], dict[str, str]]:
    """The registry edits that move each shadow-or-later judge to its full-cohort ceiling, and why others refuse.

    Only `resources` changes: `canonicalHostPeakBytes` becomes the larger peak
    of the two clean runs, `ceilingBytes` that peak x 1.2 (`ceilingPolicy`),
    `ceilingSession` this session, and `ceilingHistory` gains the replaced
    ceiling, its session and date. A judge is refused when its runs were not
    clean or not on the canonical host, when its output identity is not the
    one its committed canary record qualified, when it is not yet shadow,
    when the new ceiling (with the orchestrator reservation) does not fit the
    admission budget, or when the new ceiling is lower and `allow_lower` is
    not given.
    """
    from audio_qc_judges import acquisition_entry_digest

    if session_purpose(session) != RECALIBRATION_PURPOSE:
        raise QualificationError(f"only a {RECALIBRATION_PURPOSE} session recalibrates ceilings")
    admission = registry.get("admission") if isinstance(registry.get("admission"), Mapping) else {}
    budget, reservation = admission.get("budgetBytes"), admission.get("orchestratorReservationBytes")
    if type(budget) is not int or type(reservation) is not int or not 0 < reservation < budget:
        raise QualificationError("the registry's admission budget and reservation must be positive bytes")
    session_id = session["session"]["id"]
    edits: dict[tuple[str, ...], Any] = {}
    changed: dict[str, dict[str, Any]] = {}
    refused: dict[str, str] = {}
    judges = registry.get("judges") or {}
    for judge_id, entry in sorted((session.get("judges") or {}).items()):
        judge = judges.get(judge_id)
        record = records.get(judge_id)
        if not isinstance(judge, Mapping) or "acquisition" not in judge:
            refused[judge_id] = "not-a-panel-judge"
            continue
        if judge.get("status") not in RECALIBRATION_STATUSES:
            refused[judge_id] = f"status-{judge.get('status')}"
            continue
        resources = dict(judge.get("resources") or {})
        if resources.get("ceilingStatus") != "calibrated" or type(resources.get("ceilingBytes")) is not int:
            refused[judge_id] = "ceiling-not-calibrated"
            continue
        if record is None or record.get("schema") != CEILING_SCHEMA:
            refused[judge_id] = "no-ceiling-record"
            continue
        reason = _refusal(record, canonical_host, session["session"])
        if reason is not None:
            refused[judge_id] = reason
            continue
        canary = judge.get("canary") if isinstance(judge.get("canary"), Mapping) else {}
        if record["outputIdentity"] != canary.get("outputIdentity") \
                or record["identityComponents"].get("registryEntrySHA256") != acquisition_entry_digest(dict(judge)):
            refused[judge_id] = "identity-mismatch"
            continue
        if resources.get("ceilingSession") == session_id:
            refused[judge_id] = "already-recalibrated"
            continue
        peak = record["resources"]["canonicalHostPeakBytes"]
        ceiling = admission_ceiling(peak)
        if ceiling + reservation > budget:
            refused[judge_id] = "ceiling-exceeds-budget"
            continue
        previous = resources["ceilingBytes"]
        if ceiling < previous and not allow_lower:
            refused[judge_id] = "would-lower-ceiling"
            continue
        old_session = resources.get("ceilingSession")
        history = list(resources.get("ceilingHistory") or [])
        history.append({"ceilingSession": old_session,
                        "date": session_date(old_session) if isinstance(old_session, str) else None,
                        "canonicalHostPeakBytes": resources.get("canonicalHostPeakBytes"),
                        "ceilingBytes": previous})
        resources.update(canonicalHostPeakBytes=peak, ceilingBytes=ceiling, ceilingSession=session_id,
                         ceilingHistory=history)
        edits[("judges", judge_id, "resources")] = resources
        changed[judge_id] = {"fromBytes": previous, "toBytes": ceiling, "peakBytes": peak,
                             "fromSession": old_session, "determinismClass": record["determinism"]["class"],
                             "registryDeterminismClass": judge.get("determinismClass")}
    return edits, changed, refused


def session_records(directory: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    session = json.loads((directory / "session.json").read_text(encoding="utf-8"))
    records = {}
    for judge_id, entry in session["judges"].items():
        if entry.get("record"):
            records[judge_id] = json.loads((directory / entry["record"]).read_text(encoding="utf-8"))
    return session, records


def committed_errors(root: Path, paths: Iterable[str]) -> list[str]:
    """Paths the repository has not committed as they are on disk (the registry's rule)."""
    from audio_qc_judges import _committed_file_errors

    errors = []
    for relative in paths:
        errors.extend(f"{relative} {problem}" for problem in _committed_file_errors(root, relative))
    return errors
