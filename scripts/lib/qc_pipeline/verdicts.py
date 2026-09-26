"""Stage 3 over L2 metrics (audit section 3.3). Pure and never cached.

Two outputs per take:

- **The current verdicts, replayed.** The language lane's witness verdict
  (`independent_asr.witness_verdict`) and the delivery cascade's automated
  review and route (`run_local_delivery_cascade`) run unchanged, except that a
  recognition's score comes from its L2 metrics through `asr_verdict` instead
  of being recomputed from the transcript. `asr_verdict` rebuilds exactly what
  `score_recognition` returns: L2 holds its measurements, never its verdicts or
  thresholds, which are applied here from today's constants.
- **Composer verdicts.** One detector verdict per channel (content accuracy,
  class B; language identity, class D; Fast QC, class A, stage 0; canonical
  integrity, class A, stage 1), each naming its judges and its calibration
  record, composed per lane by `lib.qc_qualification.composer`. No language or
  content detector has a qualified record yet, so they compose as
  `uncalibrated` (the M0 state the audit prescribes); Fast QC v8 cites its
  legacy-unqualified Stage 0 record (A10).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from lib.language_metrics import (
    ACCURACY_METRIC_VERSION,
    DELETION_RUN_WARNING_LENGTH,
    LANGUAGE_CHECK_KINDS,
    MAX_ACCURACY_ERROR_RATE,
    MIN_LANGUAGE_MATCH_SCORE,
    score_recognition,
)
from lib.qc_qualification.composer import compose

REPO = Path(__file__).resolve().parents[3]
LANGUAGE_METRICS_SOURCE = REPO / "scripts/lib/language_metrics.py"
STAGE0_CALIBRATION = REPO / "config/audio-qc-stage0-calibration.json"
ASR_METRIC_DEFINITION = ACCURACY_METRIC_VERSION
# `score_recognition` fields that are verdicts or thresholds; Stage 3 applies them.
ASR_VERDICT_FIELDS = ("modelFamily", "accuracyThreshold", "languagePass", "accuracyPass", "passed", "deletionRunWarning")
# Recognizer families and the registry judges they come from.
FAMILY_JUDGES = {
    "whisper": "asr.whisper-small@1",
    "apple-speech": "asr.apple-speech-consensus@2",
    "sensevoice": "compact.sensevoice-small-q8@1",
}
CONTENT_DETECTOR = "content.accuracy@1"
LANGUAGE_DETECTOR = "language.identity@1"
INTEGRITY_DETECTOR = "signal.canonical-integrity@1"
LANE_REQUIRED = {
    "language-bench": (CONTENT_DETECTOR, LANGUAGE_DETECTOR),
    "delivery-bench": (),
}
QC_VERDICTS = ("pass", "warn", "fail")


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def asr_metrics(recognition: Mapping[str, Any], *, script: str, language: str) -> dict[str, Any]:
    """L2 of one recognition: `score_recognition`'s measurements, no verdict or threshold."""
    scored = score_recognition(dict(recognition), script=script, language=language)
    metrics = {key: value for key, value in scored.items() if key not in ASR_VERDICT_FIELDS}
    metrics["detectedLanguage"] = recognition.get("detectedLanguage")
    return metrics


def asr_verdict(metrics: Mapping[str, Any], *, family: Any, language: str) -> dict[str, Any]:
    """`score_recognition`'s result rebuilt from L2 metrics and today's thresholds."""
    rebuilt = {key: value for key, value in metrics.items() if key != "detectedLanguage"}
    language_pass = metrics.get("detectedLanguage") == language
    accuracy_pass = metrics["errorRate"] <= MAX_ACCURACY_ERROR_RATE
    rebuilt.update({
        "modelFamily": family,
        "accuracyThreshold": MAX_ACCURACY_ERROR_RATE,
        "languagePass": language_pass,
        "accuracyPass": accuracy_pass,
        "passed": language_pass and accuracy_pass,
        "deletionRunWarning": metrics["longestDeletionRun"] >= DELETION_RUN_WARNING_LENGTH,
    })
    return rebuilt


def family_channels(family: str, metrics: Mapping[str, Any], *, expected_language: str) -> dict[str, bool]:
    """One family's language and accuracy channels from its metrics (audit #42).

    Audio-LID families (whisper, SenseVoice) pass the language channel when the
    detected language is the expected one; Apple Speech's channel is its
    transcript-language consistency score against the Swift verifier's 0.5.
    """
    accuracy = metrics["errorRate"] <= MAX_ACCURACY_ERROR_RATE
    if LANGUAGE_CHECK_KINDS.get(family) == "transcript-language-consistency":
        language = metrics["languageMatchScore"] >= MIN_LANGUAGE_MATCH_SCORE
    else:
        language = metrics.get("detectedLanguage") == expected_language
    return {"language": bool(language), "accuracy": bool(accuracy)}


class L2Scorer:
    """The scorer the replayed verdict functions call: metrics from L2, verdicts here."""

    def __init__(self) -> None:
        self._metrics: dict[tuple[Any, ...], dict[str, Any]] = {}
        self.cached = 0
        self.computed = 0

    @staticmethod
    def key(recognition: Mapping[str, Any], script: str, language: str) -> tuple[Any, ...]:
        transcript = str(recognition.get("transcript", ""))
        return (
            recognition.get("modelFamily"), recognition.get("audioSHA256"),
            hashlib.sha256(transcript.encode("utf-8")).hexdigest(),
            hashlib.sha256(script.encode("utf-8")).hexdigest(), language,
            recognition.get("detectedLanguage"),
        )

    def add(self, recognition: Mapping[str, Any], *, script: str, language: str, metrics: Mapping[str, Any]) -> None:
        self._metrics[self.key(recognition, script, language)] = dict(metrics)

    def metrics(self, recognition: Mapping[str, Any], *, script: str, language: str) -> dict[str, Any]:
        key = self.key(recognition, script, language)
        if key in self._metrics:
            self.cached += 1
            return self._metrics[key]
        # A supplied recognition (not produced by this run's judges) is scored
        # from its transcript through the same L2 definition.
        self.computed += 1
        metrics = asr_metrics(recognition, script=script, language=language)
        self._metrics[key] = metrics
        return metrics

    def __call__(self, recognition: Mapping[str, Any], *, script: str, language: str) -> dict[str, Any]:
        return asr_verdict(self.metrics(recognition, script=script, language=language),
                           family=recognition.get("modelFamily"), language=language)


# --------------------------------------------------------------------------- #
# Composer detector verdicts
# --------------------------------------------------------------------------- #

def _detector(detector: str, klass: str, stage: int, judges: list[str], status: str,
              reasons: list[str], calibration: dict[str, Any] | None) -> dict[str, Any]:
    return {"detector": detector, "class": klass, "stage": stage, "judges": sorted(set(judges)),
            "status": status, "reasons": sorted(set(reasons)), "calibration": calibration}


def stage0_detector(receipt: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Fast QC's worst verdict; v8 cites its legacy-unqualified Stage 0 record (A10)."""
    if not isinstance(receipt, Mapping):
        return None
    version = receipt.get("algorithmVersion")
    if type(version) is not int or version <= 0:
        return None
    verdicts = [receipt.get(key) for key in ("verdict", "instabilityVerdict", "writtenOutputVerdict")]
    present = [value for value in verdicts if value is not None]
    judge = f"fastqc@{version}"
    detector = f"signal.fastqc@{version}"
    if not present or any(value not in QC_VERDICTS for value in present):
        return _detector(detector, "A", 0, [judge], "unavailable", ["analysis-failed"], None)
    worst = "fail" if "fail" in present else "warn" if "warn" in present else "pass"
    calibration = None
    if version == 8 and STAGE0_CALIBRATION.is_file():
        calibration = {"recordSHA256": file_sha256(STAGE0_CALIBRATION), "level": "legacy-unqualified",
                       "inScope": True}
    return _detector(detector, "A", 0, [judge], worst, [], calibration)


def integrity_detector(integrity: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(integrity, Mapping):
        return None
    status = "pass" if integrity.get("status") == "complete" else "fail"
    return _detector(INTEGRITY_DETECTOR, "A", 1, ["integrity.canonical-pcm@1"], status, [], None)


def channel_detectors(families: Mapping[str, list[dict[str, bool]]], *, unqualified: list[str],
                      unavailable: Mapping[str, str], out_of_scope: list[str] = ()) -> list[dict[str, Any]]:
    """Content (B) and language (D) detector verdicts from each family's channels.

    `families` maps a family to its qualified witnesses' channels (repetitions
    of one family are one witness). Two agreeing families decide; families that
    disagree abstain; one family is its own verdict, uncalibrated like every
    verdict here until a qualified record exists. A judge this run launched and
    lost makes the detector `unavailable` even beside other witnesses (fails
    closed: a partial panel never decides). With no qualified witness, an
    unqualified recognition (`low-confidence`) or a language the judge cannot
    lock (`out-of-scope`) abstains.
    """
    judges = sorted({FAMILY_JUDGES.get(family, "asr.unknown@0") for family in families}
                    | {FAMILY_JUDGES.get(family, "asr.unknown@0") for family in unqualified}
                    | set(unavailable) | set(out_of_scope))
    output = []
    for detector, klass, channel in ((CONTENT_DETECTOR, "B", "accuracy"), (LANGUAGE_DETECTOR, "D", "language")):
        votes = {family: [witness[channel] for witness in witnesses] for family, witnesses in families.items() if witnesses}
        if unavailable:
            status, reasons = "unavailable", sorted(set(unavailable.values()))
        elif not votes:
            if unqualified:
                status, reasons = "abstain", ["low-confidence"]
            elif out_of_scope:
                status, reasons = "abstain", ["out-of-scope"]
            else:
                status, reasons = "unavailable", ["missing-verdict"]
        elif any(len(set(values)) != 1 for values in votes.values()):
            status, reasons = "abstain", ["repeatability-disagreement"]
        else:
            outcomes = {values[0] for values in votes.values()}
            if len(outcomes) != 1:
                status, reasons = "abstain", ["families-disagree"]
            else:
                status, reasons = ("pass" if outcomes.pop() else "fail"), []
        output.append(_detector(detector, klass, 2, judges or ["asr.unknown@0"], status, reasons, None))
    return output


def compose_take(lane: str, detectors: list[dict[str, Any] | None]) -> dict[str, Any]:
    return compose([item for item in detectors if item is not None], lane, required=LANE_REQUIRED.get(lane, ()))


# --------------------------------------------------------------------------- #
# Replay of committed language records
# --------------------------------------------------------------------------- #

def committed_take_metrics(take: Mapping[str, Any]) -> tuple[str, dict[str, Any], dict[str, bool]] | None:
    """The L2 metrics and recorded channels a committed language take carries, by family.

    Mac records carry the whisper family (`independent*` metrics, and since
    2026-09-26 its detected language); iPhone records carry Apple Speech
    (`primaryAccuracyScore`, `languageMatchScore`, `output*Pass`). Records
    publish no transcript, so the metrics are the replay's L2 input.
    """
    metrics = take.get("metrics") if isinstance(take.get("metrics"), Mapping) else {}
    if "independentPrimaryAccuracyScore" in metrics:
        detected = (take.get("detectedLanguages") or {}).get("whisper")
        return "whisper", {
            "errorRate": metrics["independentPrimaryAccuracyScore"],
            "detectedLanguage": detected,
            "languageMatchScore": metrics.get("independentLanguageMatchScore"),
        }, {"language": metrics.get("independentLanguagePass") == 1.0,
            "accuracy": metrics.get("independentAccuracyPass") == 1.0}
    if "primaryAccuracyScore" in metrics and "outputAccuracyPass" in metrics:
        return "apple-speech", {
            "errorRate": metrics["primaryAccuracyScore"],
            "languageMatchScore": metrics.get("languageMatchScore"),
        }, {"language": metrics.get("outputLanguagePass") == 1.0,
            "accuracy": metrics.get("outputAccuracyPass") == 1.0}
    return None


def replay_committed_language_record(record: Mapping[str, Any], cells: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Stage 3 over a committed language record's metrics, against its recorded verdicts.

    `cells` maps a matrix cell id to its entry (`expectedHint`, `expectedOutcome`).
    Accuracy is recomputed from every take's primary score; the language
    channel from Apple Speech's match score, or from whisper's detected
    language where the record carries it (older whisper records do not, so
    their recorded channel is used and counted apart). Each take's expectation
    (the negative control must fail on accuracy) and the run's counts are then
    recomputed and compared.
    """
    from lib.language_metrics import single_family_meets_expectation

    takes = [take for take in record.get("takes") or [] if isinstance(take, Mapping)]
    mismatches: list[dict[str, Any]] = []
    counts = {"takesWithMetrics": 0, "accuracyReplayed": 0, "languageReplayed": 0, "languageFromRecord": 0,
              "expectationsMet": 0, "negativeControlsConfirmed": 0}
    families: set[str] = set()
    for take in takes:
        found = committed_take_metrics(take)
        if found is None:
            continue
        family, metrics, recorded = found
        families.add(family)
        counts["takesWithMetrics"] += 1
        cell = cells.get(str(take.get("cell"))) or {}
        expected_language = cell.get("expectedHint")
        expect_failure = take.get("expectedOutcome") == "fail" or cell.get("expectedOutcome") == "fail"
        accuracy = metrics["errorRate"] <= MAX_ACCURACY_ERROR_RATE
        threshold = take.get("accuracyThreshold")
        if isinstance(threshold, (int, float)) and threshold != MAX_ACCURACY_ERROR_RATE:
            mismatches.append({"cell": take.get("cell"), "field": "accuracyThreshold"})
        counts["accuracyReplayed"] += 1
        if accuracy != recorded["accuracy"]:
            mismatches.append({"cell": take.get("cell"), "field": "accuracy"})
        if family == "apple-speech" and isinstance(metrics.get("languageMatchScore"), (int, float)):
            language = family_channels(family, metrics, expected_language=str(expected_language))["language"]
            counts["languageReplayed"] += 1
        elif family == "whisper" and metrics.get("detectedLanguage") is not None and expected_language:
            language = family_channels(family, metrics, expected_language=str(expected_language))["language"]
            counts["languageReplayed"] += 1
        else:
            language = recorded["language"]
            counts["languageFromRecord"] += 1
        if language != recorded["language"]:
            mismatches.append({"cell": take.get("cell"), "field": "language"})
        met = single_family_meets_expectation(language, accuracy, expect_failure=expect_failure)
        counts["expectationsMet"] += met
        counts["negativeControlsConfirmed"] += bool(met and expect_failure)
    summary = (record.get("evidence") or {}).get("languageVerification") or {}
    recorded_counts = {key: summary.get(key) for key in ("outputCellsPassed", "negativeControlsConfirmed")
                       if key in summary}
    if "outputCellsPassed" in recorded_counts and recorded_counts["outputCellsPassed"] != counts["expectationsMet"]:
        mismatches.append({"field": "outputCellsPassed"})
    if ("negativeControlsConfirmed" in recorded_counts
            and recorded_counts["negativeControlsConfirmed"] != counts["negativeControlsConfirmed"]):
        mismatches.append({"field": "negativeControlsConfirmed"})
    return {"families": sorted(families), **counts, "recordedCounts": recorded_counts,
            "identical": not mismatches, "mismatches": mismatches}
