"""The language lanes on QC v2: their takes manifest and the recognition evidence they publish.

`scripts/macos_test.sh lang-bench` and `scripts/ios_device.sh lang-bench` run, once every
generation has finished:

1. `qc.py language-bench takes`: the run's planned takes as a QC v2 takes manifest. Each take's
   WAV is bound to the digest the engine published (macOS engine row) or the sentinel bound
   (iPhone `output.wav`); its text is the corpus script and its language the language the cell
   expects. A negative control (an expected failure, or a script in another language than the
   one expected) is marked `control`: it is scored and flagged, never gated.
2. `qc.py run --takes <manifest> --lane language-bench` (or `ios-language-bench`): the lane's
   QC v2 models and detectors.
3. `qc.py language-bench evidence --run <qc run>`: the two ASR families' recognitions of every
   take, read from that run's cached results (Qwen3-ASR as asrA, Whisper large-v3 as asrB), in
   the form `publish_benchmark_history.py language --recognitions` re-scores, with each take's
   two-family verdict (`lib.language_metrics.qc_take_verdict`).

Both recognizers decode the whole take with neither its script nor its language, and identify
the language from the audio. The negative control is therefore a language control: both
families must identify a language other than the pinned one.

The evidence holds transcripts of tracked corpus scripts, digests and model identities; it
stays in the lane's untracked artifacts directory, beside the WAVs it describes.
"""

from __future__ import annotations

import re
import sys
import wave
from pathlib import Path
from typing import Any

from qc import models, runtime, store
from qc.store import Layout

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from lib.language_metrics import (  # noqa: E402
    LANGUAGE_LOCALE_CODES,
    QC_ASR_ALGORITHM,
    QC_RECOGNITION_FAMILIES,
    QC_RECOGNITION_SCHEMA,
    is_sha256,
    qc_take_verdict,
    text_sha256,
)

TAKES_KIND = "language-bench"
EVIDENCE_SCHEMA = "vocello.qc.language-evidence/1"
EVIDENCE_KIND = "qc-language-evidence"
PLATFORMS = ("macos", "ios")
# The lane each platform's takes run under (`lanes` in config/qc/detectors.json).
LANES = {"macos": "language-bench", "ios": "ios-language-bench"}
# The detectors.json role each recognizer family reads.
FAMILY_ROLES = {"qwen3-asr": "asrA", "whisper": "asrB"}
LANGUAGE_NAME = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
EXIT_PASS, EXIT_FAIL, EXIT_ERROR = 0, 1, 2


class LanguageBenchError(ValueError):
    """The lane's artifacts, plan or QC run cannot produce the takes or the evidence."""


# --- the takes manifest ---------------------------------------------------------------

def wav_duration_seconds(path: Path) -> float:
    try:
        with wave.open(str(path), "rb") as stream:
            rate, frames = stream.getframerate(), stream.getnframes()
    except (OSError, EOFError, wave.Error) as error:
        raise LanguageBenchError(f"{path.name} is not a readable WAV: {error}") from error
    if rate <= 0 or frames <= 0:
        raise LanguageBenchError(f"{path.name} has no audio")
    return frames / rate


def _voice(planned: dict[str, Any]) -> str:
    if planned.get("mode") == "design":
        return f"design-{str(planned.get('designInstructionDigest') or 'brief')[:12]}"
    return str(planned.get("customSpeakerID") or planned.get("mode") or "unknown")


def _qc_take(*, run_id: str, planned: dict[str, Any], audio: Path, digest: str, generation_id: str,
             script: str) -> dict[str, Any]:
    child = str(planned["childRunID"])
    expected = str(planned.get("expectedHint"))
    if expected not in LANGUAGE_LOCALE_CODES:
        raise LanguageBenchError(f"{child}: unsupported expected language {expected!r}")
    outcome = "fail" if planned.get("expectedOutcome") == "fail" else "pass"
    script_language = str(planned.get("scriptLang"))
    return {
        "takeID": child,
        "token": store.take_token(run_id, child),
        "audio": str(audio),
        "audioSHA256": digest,
        "language": expected,
        "text": script,
        "mode": planned.get("mode"),
        "voice": _voice(planned),
        "cell": "standard",
        "reference": None,
        "referenceSHA256": None,
        "referenceText": None,
        "finishReason": None,
        "seed": planned.get("seed"),
        "family": script_language,
        "control": outcome == "fail" or script_language != expected,
        "languageBench": {
            "cellID": str(planned["cellID"]),
            "childRunID": child,
            "generationID": generation_id,
            "expectedOutcome": outcome,
            "scriptLanguage": script_language,
            "scriptSHA256": text_sha256(script),
            "durationSeconds": wav_duration_seconds(audio),
        },
    }


def build_takes(*, platform: str, run_id: str, plan: Path, corpus: Path, diagnostics: Path,
                wav_dir: Path | None = None) -> dict[str, Any]:
    """The lane's output-verified planned takes, each bound to the digest its generation published."""

    from check_language_hints import corpus_scripts, read_engine_rows
    from language_bench_evidence import EvidenceError, exact_sentinels, load_json, validate_plan

    if platform not in PLATFORMS:
        raise LanguageBenchError(f"unknown platform {platform!r}")
    try:
        plan_payload = load_json(plan)
        planned_takes = validate_plan(plan_payload)
    except EvidenceError as error:
        raise LanguageBenchError(str(error)) from error
    if plan_payload.get("runID") != run_id:
        raise LanguageBenchError("the run plan belongs to another run ID")
    scripts = corpus_scripts(store.read_json(corpus))
    takes: list[dict[str, Any]] = []
    if platform == "macos":
        if wav_dir is None:
            raise LanguageBenchError("a macOS run needs --wav-dir")
        try:
            rows = read_engine_rows(str(diagnostics), run_id)
        except FileNotFoundError as error:
            raise LanguageBenchError(f"engine telemetry is missing: {Path(str(error)).name}") from error
        by_cell: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            cell_id = (row.get("notes") or {}).get("benchCell")
            if isinstance(cell_id, str):
                by_cell.setdefault(cell_id, []).append(row)
        sentinels: dict[str, Any] = {}
    else:
        try:
            sentinels = exact_sentinels(diagnostics, plan_payload)
        except EvidenceError as error:
            raise LanguageBenchError(str(error)) from error
        by_cell = {}
    for planned in planned_takes:
        if planned.get("skipOutputVerification"):
            continue
        cell_id, child = str(planned["cellID"]), str(planned["childRunID"])
        script = scripts.get(str(planned.get("scriptLang")))
        if not isinstance(script, str) or not script.strip():
            raise LanguageBenchError(f"{child}: the corpus lacks scriptLang {planned.get('scriptLang')!r}")
        if platform == "macos":
            matches = by_cell.get(cell_id, [])
            if len(matches) != 1:
                raise LanguageBenchError(f"{cell_id}: expected one engine row, found {len(matches)}")
            digest = (matches[0].get("notes") or {}).get("samplingWAVDigest")
            generation_id = str(matches[0].get("generationID"))
            audio = Path(wav_dir) / f"{cell_id}.wav"
            what = "the engine's published digest"
        else:
            sentinel_path, record = sentinels[child]
            if record.get("status") != "ok":
                raise LanguageBenchError(f"{child}: diagnostics did not complete")
            evidence = record.get("outputEvidence")
            digest = evidence.get("sha256") if isinstance(evidence, dict) else None
            generation_id = str(record.get("generationID"))
            audio = Path(sentinel_path).parent / "output.wav"
            what = "the sentinel's digest"
        if not is_sha256(digest):
            raise LanguageBenchError(f"{child}: no published WAV digest to bind the take to")
        if not audio.is_file() or store.sha256_file(audio) != digest:
            raise LanguageBenchError(f"{child}: the output WAV is missing or differs from {what}")
        takes.append(_qc_take(run_id=run_id, planned=planned, audio=audio, digest=digest,
                              generation_id=generation_id, script=script))
    if not takes:
        raise LanguageBenchError("the run has no output-verified take")
    return {"schema": store.TAKES_SCHEMA, "kind": TAKES_KIND, "source": run_id, "platform": platform,
            "generationProcessExited": True, "planDigest": plan_payload.get("planDigest"), "takes": takes}


# --- the recognition evidence ----------------------------------------------------------

def language_name(value: Any) -> str | None:
    """`French`, `fr` or `<|fr|>` as `french`; another language as its lowercase name."""

    if not isinstance(value, str):
        return None
    cleaned = value.strip().strip("<|>").strip().lower()
    try:
        return store.normalize_language(cleaned)
    except ValueError:
        return cleaned if LANGUAGE_NAME.fullmatch(cleaned) else None


def language_probabilities(value: Any) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(value, dict):
        for key, probability in value.items():
            name = language_name(key)
            if name and isinstance(probability, (int, float)) and not isinstance(probability, bool):
                out[name] = out.get(name, 0.0) + float(probability)
    return out


def recognizer_identity(layout: Layout, model: dict[str, Any], runner_sha256: str, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "modelID": model["id"],
        "runtimeSHA256": runner_sha256,
        "modelIdentitySHA256": store.sha256_text(store.canonical_json(
            {"id": model["id"], "pins": models.pins_digest(model)})),
        "configSHA256": store.sha256_text(store.canonical_json(
            {"options": model.get("options") or {}, "version": model["version"]})),
    }


def recognition(take: dict[str, Any], result: dict[str, Any], family: str,
                recognizer: dict[str, Any]) -> dict[str, Any]:
    """One family's recognition of one take, in the shape `qc_take_verdict` and the publisher score."""

    outputs = result.get("outputs") if isinstance(result.get("outputs"), dict) else {}
    transcript = str(outputs.get("text") or "").strip()
    probabilities = language_probabilities(outputs.get("languageProbs"))
    detected = language_name(outputs.get("language"))
    duration = result.get("durationSeconds")
    windows = [
        {"start": window.get("start"), "end": window.get("end"), "language": language_name(window.get("language"))}
        for window in outputs.get("languageWindows") or [] if isinstance(window, dict)
    ]
    return {
        "schemaVersion": QC_RECOGNITION_SCHEMA,
        "algorithmVersion": QC_ASR_ALGORITHM,
        "modelFamily": family,
        "modelID": recognizer["modelID"],
        "audioSHA256": take["audioSHA256"],
        "inputTextSHA256": text_sha256(take["text"]),
        "status": "failed" if "error" in result else ("complete" if transcript else "empty"),
        "outputLanguage": take["language"],
        "detectedLanguage": detected,
        "languageMatchScore": probabilities.get(take["language"]) if probabilities else None,
        "detectedLanguageProbability": probabilities.get(detected) if probabilities and detected else None,
        # The runner decoded the whole file unless its token budget ran out (Qwen3-ASR).
        "fullFileProcessed": "error" not in result and not outputs.get("truncated", False),
        "processedDurationSeconds": duration,
        "languageWindows": windows or None,
        "transcript": transcript,
        "provenance": {key: recognizer[key] for key in ("runtimeSHA256", "modelIdentitySHA256", "configSHA256")},
    }


def build_evidence(layout: Layout, run_id: str) -> dict[str, Any]:
    """The QC run's two-family recognitions of every take, with each take's verdict and the run's status:
    `pass` when every take met its declared outcome, `fail` when one did not, `error` when a family's
    result is missing from the cache (the model did not score that take)."""

    if not RUN_ID.fullmatch(run_id) or not (layout.runs / run_id / "takes.json").is_file():
        raise LanguageBenchError(f"no QC run {run_id!r}")
    directory = layout.runs / run_id
    manifest = store.read_json(directory / "takes.json")
    features = store.read_json(directory / "features.json")
    if manifest.get("kind") != TAKES_KIND or manifest.get("platform") not in PLATFORMS:
        raise LanguageBenchError(f"QC run {run_id} did not score a language-bench takes manifest")
    registry = models.load_registry(layout)
    recognizers: dict[str, dict[str, Any]] = {}
    for family in QC_RECOGNITION_FAMILIES:
        role = FAMILY_ROLES[family]
        identity = (features.get("models") or {}).get(role) or {}
        runner_sha = identity.get("runnerSHA256")
        if not identity.get("id") or not runner_sha:
            raise LanguageBenchError(f"{role} is not registered or did not score QC run {run_id}")
        try:
            model = models.find_model(registry, identity["id"])
        except KeyError as error:
            raise LanguageBenchError(f"{role}: {error.args[0]}") from error
        if runtime.runner_identity(layout, model) != runner_sha:
            raise LanguageBenchError(f"{role} ({model['id']}) changed since QC run {run_id}; run it again")
        recognizers[family] = recognizer_identity(layout, model, runner_sha, role)
    cells: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for take in manifest["takes"]:
        bench = take.get("languageBench") or {}
        recognitions = []
        for family, recognizer in recognizers.items():
            result = store.read_result(layout, recognizer["modelID"], take["audioSHA256"], None,
                                       recognizer["runtimeSHA256"])
            if result is None:
                missing.append(f"{take['takeID']}:{family}")
                continue
            recognitions.append(recognition(take, result, family, recognizer))
        expect_failure = bench.get("expectedOutcome") == "fail"
        verdict = qc_take_verdict(
            recognitions, audio_sha256=take["audioSHA256"], script=take["text"], language=take["language"],
            duration_seconds=float(bench.get("durationSeconds") or 0.0), expect_failure=expect_failure,
        )
        cells[take["takeID"]] = {
            "cellID": bench.get("cellID"),
            "generationID": bench.get("generationID"),
            "audioSHA256": take["audioSHA256"],
            "expectedLanguage": take["language"],
            "expectedOutcome": "fail" if expect_failure else "pass",
            "durationSeconds": bench.get("durationSeconds"),
            "recognitions": recognitions,
            "verdict": {
                "status": verdict["status"],
                "issues": verdict["issues"],
                "channels": (verdict["consensus"] or {}).get("statuses"),
                "families": {
                    family: {"detectedLanguage": recognition_.get("detectedLanguage"),
                             "languagePass": bool(verdict["verdicts"][family]["languagePass"]),
                             "accuracyPass": bool(verdict["verdicts"][family]["accuracyPass"]),
                             "accuracyMetric": verdict["verdicts"][family]["accuracyMetric"],
                             "errorRate": round(float(verdict["verdicts"][family]["errorRate"]), 4)}
                    for family, recognition_ in ((item["modelFamily"], item) for item in recognitions)
                    if family in verdict["verdicts"]
                },
            },
        }
    statuses = {cell["verdict"]["status"] for cell in cells.values()}
    status = "error" if missing else ("pass" if statuses == {"pass"} else "fail")
    return {
        "schema": EVIDENCE_SCHEMA,
        "kind": EVIDENCE_KIND,
        "runID": manifest.get("source"),
        "platform": manifest["platform"],
        "qcRun": run_id,
        "lane": features.get("lane"),
        "generationProcessExited": manifest.get("generationProcessExited") is True,
        "recognitionAlgorithm": QC_ASR_ALGORITHM,
        "families": list(QC_RECOGNITION_FAMILIES),
        "recognizers": recognizers,
        "status": status,
        "missing": sorted(missing),
        "cells": cells,
    }


def summary_lines(evidence: dict[str, Any]) -> list[str]:
    """Privacy-safe lines: statuses, detected languages and error rates, never transcripts."""

    lines = []
    for take_id, cell in sorted(evidence["cells"].items()):
        verdict = cell["verdict"]
        families = " ".join(
            f"{family}={item['detectedLanguage']}/{item['accuracyMetric'][:1]}ER{item['errorRate']:.3f}"
            for family, item in sorted(verdict["families"].items())
        )
        issues = "; ".join(f"{family}: {','.join(found)}" for family, found in sorted(verdict["issues"].items()))
        lines.append(f"  {take_id:<52} {verdict['status']:<12} expected={cell['expectedLanguage']}"
                     f"/{cell['expectedOutcome']} {families}{(' issues ' + issues) if issues else ''}")
    for item in evidence.get("missing") or []:
        lines.append(f"  missing recognition: {item}")
    lines.append(f"spoken content: {evidence['status']} · {len(evidence['cells'])} takes · families "
                 f"{','.join(evidence['families'])} · QC run {evidence['qcRun']}")
    return lines


def exit_code(evidence: dict[str, Any]) -> int:
    return {"pass": EXIT_PASS, "fail": EXIT_FAIL}.get(evidence["status"], EXIT_ERROR)
