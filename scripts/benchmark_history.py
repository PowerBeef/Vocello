#!/usr/bin/env python3
"""Create and validate privacy-safe, repository-tracked benchmark records.

The benchmark runner owns raw evidence.  This module accepts only the compact,
allowlisted ``historyRecord`` embedded in ``benchmark-evidence.json`` (or a
manifest that is itself that record), verifies the successful-run contract,
adds reproducible repository provenance, and writes one immutable JSON record.

Raw telemetry, WAVs, screenshots, result bundles, and Instruments traces must
never be copied into the repository by this tool.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
import plistlib
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

# Some deterministic tests load this module through importlib without adding the
# scripts directory to sys.path. Make the repository-local policy helper
# importable in that supported context as well as during normal CLI execution.
SCRIPT_DIRECTORY = Path(__file__).resolve().parent
if str(SCRIPT_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIRECTORY))
from build_output_policy import load_policy


REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_OUTPUT_POLICY = load_policy(REPO_ROOT)
MACOS_DERIVED_DATA = (
    REPO_ROOT / BUILD_OUTPUT_POLICY.entries_by_id["xcode-macos-derived-data"]["path"]
)
IOS_DERIVED_DATA = (
    REPO_ROOT / BUILD_OUTPUT_POLICY.entries_by_id["xcode-ios-device-derived-data"]["path"]
)
BENCHMARK_ROOT = REPO_ROOT / "benchmarks"
RUNS_ROOT = BENCHMARK_ROOT / "runs"
HARDWARE_PROFILES_PATH = BENCHMARK_ROOT / "hardware-profiles.json"
SCHEMA_PATHS = {
    1: BENCHMARK_ROOT / "schema-v1.json",
    2: BENCHMARK_ROOT / "schema-v2.json",
    3: BENCHMARK_ROOT / "schema-v3.json",
}
# Compatibility alias retained for schema-v1 fixture callers. New publication
# uses SCHEMA_PATHS[2]; historical v1 tests may safely patch this read-only path.
SCHEMA_PATH = SCHEMA_PATHS[1]
HISTORY_PATH = BENCHMARK_ROOT / "HISTORY.md"
MAX_RECORD_BYTES = 256 * 1024
SCHEMA_VERSION = 2
SUPPORTED_SCHEMA_VERSIONS = frozenset(SCHEMA_PATHS)

KINDS = {
    "ui-generation",
    "engine-generation",
    "language",
    "telemetry-overhead",
    "instrument-profile",
    "prosody-calibration",
}
V1_KINDS = set(KINDS)
# ui-perf (UI-7, 2026-08): the macOS SwiftUI frame-health lane. v2-only like
# memory-qualification — no historical v1 records can carry it.
V2_KINDS = (KINDS - {"telemetry-overhead"}) | {"memory-qualification", "ui-perf"}
ALL_KINDS = V1_KINDS | V2_KINDS
MEMORY_QUALIFIED_KINDS = {
    "ui-generation", "engine-generation", "language", "instrument-profile",
    "memory-qualification",
}
PLATFORMS = {"macos", "ios"}
SUCCESS_STATUSES = {"passed", "passedWithWarnings"}
CLASSIFICATIONS = {"canonical", "focused", "exploratory", "instrumented", "partial"}
MATRIX_SCOPES = {"canonical", "focused", "partial", "instrumented"}
LISTENING_STATUSES = {"pass", "fail", "not-performed"}
QC_VERDICTS = {"pass", "warn"}

TOP_LEVEL_KEYS = {
    "schemaVersion", "run", "hardware", "source", "toolchain", "inputs",
    "models", "evidence", "takes", "cells", "comparison", "listening", "digest",
}
SECTION_KEYS = {
    "run": {
        "id", "kind", "platform", "label", "startedAt", "finishedAt",
        "durationSeconds", "status", "matrixScope", "classification", "warnings",
    },
    "hardware": {
        "profileID", "modelIdentifier", "marketingName", "chip", "memoryBytes",
        "cpuCores", "performanceCores", "efficiencyCores", "osName", "osVersion",
        "osBuild", "thermalState", "lowPowerMode", "transport", "loadAverage1M",
        "freeStorageBytes", "uptimeSeconds",
    },
    "source": {
        "commit", "dirty", "changedPaths", "workspaceFingerprint", "preFingerprint",
        "postFingerprint", "fingerprintsMatch",
    },
    "toolchain": {
        "xcodeVersion", "xcodeBuild", "swiftVersion", "sdkName", "sdkVersion",
        "optimization", "appVersion", "appBuild", "executableUUIDs", "executableHashes",
    },
    "inputs": {
        "contractHash", "dependencyLockHash", "projectInputHash", "harnessHash",
        "matrixHash", "corpusHash", "analysisProfileHash",
    },
    "evidence": {
        "manifestDigest", "validatorSchemaVersion", "telemetrySchemaVersion",
        "qcAlgorithmVersion", "validatorPassed", "crashDeltaPassed", "crashCount",
        "expectedTakeCount", "actualTakeCount", "resultBundleDigest",
        "rawTelemetryDigest", "selectedEvidenceDigest", "screenshotDigests", "trace",
        "languageVerification",
        "memoryContractVersion", "memoryQualified", "sampleSidecarCount",
        "sampleSidecarsDigest", "memoryPolicyID", "retentionMetric",
        "retentionThresholdFraction", "maximumRetainedGrowthMB",
        "maximumRetainedGrowthFraction", "retentionPassed",
        "streamingTelemetryV9SidecarCount", "streamingTelemetryV9SidecarsDigest",
        "streamingTelemetryV9PublicationReadyCount",
    },
    "comparison": {"key", "comparable", "baselineRunID", "deltas"},
    "listening": {"status", "note", "annotatedAt"},
}
MODEL_KEYS = {
    "mode", "modelID", "variant", "quantization", "revision", "artifactVersion",
    "integrityDigest", "runtimeProfileSignature", "fixtureDigest",
}
TAKE_KEYS = {
    "takeIndex", "generationID", "cell", "mode", "modelID", "variant", "warmState",
    "length", "finishReason", "status", "layerCompleteness", "layers",
    "durationSeconds", "metrics", "output", "audioQC", "thermalState", "warnings",
    "runtimeProfileSignature", "fixtureDigest", "modelIntegrityDigest", "modelRepository",
    "modelRevision", "modelArtifactVersion", "modelQuantization", "seed",
    "accuracyMetric", "accuracyThreshold", "playbackStartSource",
    "memoryStatus", "sampleSidecarDigest",
    "streamingTelemetryV9SidecarDigest", "samplingPromotionPackaged", "samplingWAVDigest",
    "samplingSeedAgreement",
    "qualityRegistryOutcome", "qualityRegistryRequiredGates", "qualityRegistryIssues",
}
OUTPUT_KEYS = {
    "readableWAV", "atomicPublish", "durationSeconds", "sampleRate", "channels",
    "frames", "fileDigest",
}
AUDIO_QC_KEYS = {
    "algorithmVersion", "verdict", "instabilityVerdict", "writtenOutputVerdict",
    "warningCodes", "metrics",
}
CELL_KEYS = {
    "key", "mode", "modelID", "variant", "warmState", "length", "count", "status",
    "statistics", "worstQCVerdict", "worstThermalState", "maximumTrimLevel", "warningCount",
}
TRACE_RETENTION_KEYS = {
    "originalEphemeralPath", "summaryArtifact", "rawTraceRetained",
    "retentionPolicy", "captureSettings", "captureSettingsDigest",
}
TRACE_KEYS = {
    "digest", "template", "durationSeconds", "validated", "summary",
} | TRACE_RETENTION_KEYS
TRACE_CAPTURE_SETTINGS_KEYS = {
    "profileKind", "template", "requestedDurationSeconds", "targetProcess", "exactPID",
}
TRACE_SUMMARY_ARTIFACT_KEYS = {"path", "digest"}
LEGACY_MEMORY_TRACE_SUMMARY_KEYS = {
    "allocationTargetDataBytes", "allocationTrackVerified",
    "vmTrackerRegionMapVerified", "vmTrackerTrackVerified",
}
MEMORY_TRACE_V2_SUMMARY_KEYS = {
    "memoryTraceEvidenceVersion",
    "allocationTargetDataBytes", "allocationTrackPresent", "allocationListPresent",
    "allocationDataExportStatus", "allocationTargetRowCount",
    "vmTrackerTrackPresent", "vmTrackerRegionMapPresent",
    "vmTrackerDataExportStatus", "vmTrackerTargetRowCount",
}
TRACE_SUMMARY_KEYS = {
    "artifact", "capturedDataRowCount", "capturedRowsBySchema",
    "correlatedSignpostEventCount", "correlationFieldsVerified",
    "cpuCycleWeight", "cpuSampleCount", "cpuSampleSpanMS", "cpuSampleWeightMS",
    "processCount", "schemaCount", "signpostEventCount", "signpostSchemaCount",
    "tableCount", "targetPIDVerified", "targetProcess", "tocDigest",
} | LEGACY_MEMORY_TRACE_SUMMARY_KEYS | MEMORY_TRACE_V2_SUMMARY_KEYS
LANGUAGE_VERIFICATION_KEYS = {
    "outputSchemaVersion", "outputAlgorithm", "recognitionSchemaVersion",
    "recognitionAlgorithm", "accuracyMetricVersion", "requiredPassCount",
}
LANGUAGE_ACCURACY_METRIC_KEYS = {
    "wordErrorRate", "characterErrorRate", "primaryAccuracyScore", "accuracyThreshold",
    "languageMatchScore", "outputLanguagePass", "outputAccuracyPass",
    "referenceTokenCount", "hypothesisTokenCount", "referenceCharacterCount",
    "hypothesisCharacterCount", "substitutions", "insertions", "deletions",
    "characterSubstitutions", "characterInsertions", "characterDeletions",
    "recognitionPassCount", "recognitionDurationSeconds",
}
STATISTIC_KEYS = {"count", "median", "iqr", "min", "max"}

SCHEMA_PROPERTY_KEYS = {
    **SECTION_KEYS,
    "model": MODEL_KEYS,
    "take": TAKE_KEYS,
    "cell": CELL_KEYS,
    "output": OUTPUT_KEYS,
    "audioQC": AUDIO_QC_KEYS,
    "trace": TRACE_KEYS,
    "traceSummary": TRACE_SUMMARY_KEYS,
}
SCHEMA_REQUIRED_KEYS = {
    "run": SECTION_KEYS["run"],
    "hardware": SECTION_KEYS["hardware"],
    "source": SECTION_KEYS["source"],
    "toolchain": SECTION_KEYS["toolchain"],
    "inputs": SECTION_KEYS["inputs"],
    "evidence": SECTION_KEYS["evidence"] - {
        "trace", "languageVerification", "memoryContractVersion", "memoryQualified",
        "sampleSidecarCount", "sampleSidecarsDigest",
        "memoryPolicyID", "retentionMetric", "retentionThresholdFraction",
        "maximumRetainedGrowthMB", "maximumRetainedGrowthFraction", "retentionPassed",
        "streamingTelemetryV9SidecarCount", "streamingTelemetryV9SidecarsDigest",
        "streamingTelemetryV9PublicationReadyCount",
    },
    "comparison": SECTION_KEYS["comparison"],
    "listening": SECTION_KEYS["listening"],
    "model": MODEL_KEYS,
    "take": {"takeIndex", "generationID", "cell", "status", "metrics", "warnings"},
    "cell": CELL_KEYS,
    "output": {"readableWAV", "atomicPublish"},
    "audioQC": {
        "algorithmVersion", "verdict", "instabilityVerdict", "writtenOutputVerdict",
        "warningCodes", "metrics",
    },
    # Trace-retention metadata is optional only to preserve read-only
    # compatibility with records published before the summary-only policy.
    # When any retention field is present, the executable validator requires
    # the complete set and enforces its internal consistency.
    "trace": TRACE_KEYS - TRACE_RETENTION_KEYS,
    "traceSummary": {
        "artifact", "capturedDataRowCount", "capturedRowsBySchema",
        "correlatedSignpostEventCount", "correlationFieldsVerified", "cpuSampleCount",
        "cpuSampleSpanMS", "processCount", "schemaCount", "signpostEventCount",
        "signpostSchemaCount", "tableCount", "targetPIDVerified", "targetProcess", "tocDigest",
    },
    "traceCaptureSettings": TRACE_CAPTURE_SETTINGS_KEYS,
    "traceSummaryArtifact": TRACE_SUMMARY_ARTIFACT_KEYS,
}
V2_ONLY_EVIDENCE_KEYS = {
    "memoryContractVersion", "memoryQualified", "sampleSidecarCount", "sampleSidecarsDigest",
    "memoryPolicyID", "retentionMetric", "retentionThresholdFraction",
    "maximumRetainedGrowthMB", "maximumRetainedGrowthFraction", "retentionPassed",
    "streamingTelemetryV9SidecarCount", "streamingTelemetryV9SidecarsDigest",
    "streamingTelemetryV9PublicationReadyCount",
}
V2_ONLY_TAKE_KEYS = {
    "memoryStatus", "sampleSidecarDigest",
    "streamingTelemetryV9SidecarDigest", "samplingPromotionPackaged", "samplingWAVDigest",
    "samplingSeedAgreement",
}
# Phase 13: the typed quality-registry identity is a v3 addition; v1/v2
# records must reject it as unknown so historical documents stay immutable.
V3_ONLY_TAKE_KEYS = {
    "qualityRegistryOutcome", "qualityRegistryRequiredGates", "qualityRegistryIssues",
}
V2_ONLY_TRACE_SUMMARY_KEYS = {
    *LEGACY_MEMORY_TRACE_SUMMARY_KEYS,
    *MEMORY_TRACE_V2_SUMMARY_KEYS,
}
V2_ONLY_TRACE_KEYS = set(TRACE_RETENTION_KEYS)


def schema_property_keys(version: int) -> dict[str, set[str]]:
    properties = {name: set(keys) for name, keys in SCHEMA_PROPERTY_KEYS.items()}
    if version == 1:
        properties["evidence"] -= V2_ONLY_EVIDENCE_KEYS
        properties["take"] -= V2_ONLY_TAKE_KEYS | V3_ONLY_TAKE_KEYS
        properties["trace"] -= V2_ONLY_TRACE_KEYS
        properties["traceSummary"] -= V2_ONLY_TRACE_SUMMARY_KEYS
    else:
        if version == 2:
            properties["take"] -= V3_ONLY_TAKE_KEYS
        properties["traceCaptureSettings"] = set(TRACE_CAPTURE_SETTINGS_KEYS)
        properties["traceSummaryArtifact"] = set(TRACE_SUMMARY_ARTIFACT_KEYS)
    return properties

SAFE_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,95}$")
SAFE_WARNING_RE = re.compile(
    r"^[a-z0-9][a-z0-9_.:-]{0,79}(?:\([0-9]+/[0-9]+(?:-[0-9]+)?\))?$"
)
SAFE_CELL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/#:-]{0,159}$")
SAFE_GENERATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,159}$")
SAFE_SCREENSHOT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

RAW_BENCHMARK_FILE_SUFFIXES = {
    ".jsonl", ".ndjson", ".jsonlines", ".log", ".ips", ".tracev3",
    ".wav", ".wave", ".aif", ".aiff", ".caf", ".flac", ".mp3", ".m4a",
    ".ogg", ".opus",
    ".png", ".jpg", ".jpeg", ".gif", ".heic", ".heif", ".tif", ".tiff",
    ".webp", ".bmp",
}
RAW_BENCHMARK_BUNDLE_SUFFIXES = {".xcresult", ".trace", ".xcarchive", ".dsym"}

# This is intentionally finite.  New telemetry must be deliberately promoted
# into the tracked schema rather than leaking arbitrary diagnostics into Git.
METRIC_KEYS = {
    "rtf", "tokensPerSecond", "ttfcMS", "submitToFirstChunkMS", "submitToCompletedMS",
    "playbackScheduledMS", "firstChunkToPlaybackScheduledMS", "requestToFirstChunkMS",
    "decodeWallSeconds", "audioSeconds", "generatedTokens", "backendWallMS",
    "modelLoadMS", "prewarmMS", "finalizationMS", "postprocessMS",
    "peakPhysicalFootprintMB", "peakResidentMB", "peakCompressedMB",
    "peakGPUAllocatedMB", "minimumHeadroomMB", "memoryTrimCount", "maximumTrimLevel",
    "uiMaximumDelayedHeartbeatMS", "delayedHeartbeatCount", "heartbeatCoverage",
    "cpuUserSeconds", "cpuSystemSeconds", "pageFaults", "contextSwitches",
    "blockIOOperations", "samplerTargetIntervalMS", "samplerEffectiveMedianIntervalMS",
    "samplerMaximumLatenessMS", "samplerBoundarySampleCount", "samplerCaptureFailureCount",
    "samplerMaximumDriftMS",
    "residentStartMB", "residentEndMB", "residentDeltaMB",
    "physicalFootprintStartMB", "physicalFootprintEndMB", "physicalFootprintDeltaMB",
    "gpuRecommendedWorkingSetMB", "gpuWorkingSetUsageRatioPeak", "memoryTimeToPeakMS",
    "samplerSampleCount", "samplerPeriodicSampleCount", "samplerMissedDeadlineCount",
    "samplerCoverage", "memoryPressureEventCount", "maximumPressureLevel",
    "memoryWarningCount", "memoryExitCount", "headroomStartMB", "headroomEndMB",
    "peakProcessBudgetUtilization", "alignedProcessSampleCount",
    "alignedProcessSampleCoverage", "alignedEngineSampleCoverage",
    "alignedAppSampleCoverage", "mlxActivePeakMB", "mlxCachePeakMB", "mlxPeakMB",
    "impliedProcessLimitMB", "totalDeviceRAMMB",
    "loadAverage1M", "freeStorageBytes", "uptimeSeconds", "lowPowerMode",
    "chunksReceived", "continuityFailures", "underruns", "startBufferDepth",
    "chunksForwarded", "transportChunkGaps", "transportDuplicateChunks", "transportOutOfOrderChunks",
    "minimumQueueDurationMS", "hintCellsPassed", "hintCellsExpected",
    "outputCellsPassed", "outputCellsExpected", "medianRTF", "medianTTFCMS",
    "wordErrorRate", "characterErrorRate", "languageMatchScore",
    "outputLanguagePass", "outputAccuracyPass",
    "referenceTokenCount", "hypothesisTokenCount", "referenceCharacterCount",
    "hypothesisCharacterCount", "substitutions", "insertions", "deletions",
    "characterSubstitutions", "characterInsertions", "characterDeletions",
    "recognitionPassCount", "recognitionDurationSeconds",
    "primaryAccuracyScore", "accuracyThreshold",
    "rtfRegressionPercent", "ttfcRegressionPercent", "f0MeanHz", "f0StdHz",
    "f0TurningPointsPerSecond", "syllableRateHz", "localRateCV", "maximumPauseSeconds",
    "pauseSpeechRatio", "energyEnvelopeRoughness", "discontinuityCount", "clipCount",
    "nonFiniteCount", "dcOffset", "longestSilenceMS",
    "goodClipCount", "badClipCount", "targetFalsePositiveRate",
    "observedFalsePositiveRate", "observedTruePositiveRate", "goodFlagRate", "badFlagRate",
    "monotoneF0StdThresholdHz", "monotoneTurningPointsThresholdPerSecond",
    "rushedSyllableRateThresholdHz", "rushedMaximumPauseRatio",
    "flatEnvelopeRoughnessThreshold", "flatRateCVThreshold",
    "maximumPauseThresholdSeconds", "maximumPauseRatioThreshold",
    "deliveryDF0StdHz", "deliveryDRateCV", "deliveryDPauseRatio",
    "deliveryDRoughness", "deliveryProsodyEffect",
    "deliveryPitchShiftSemitones", "deliveryArousalScore",
    # ui-perf (UI-7): per-scenario SwiftUI frame-health evidence from the
    # in-app display-link probe, joined by scripts/check_macos_ui_perf.py.
    "uiHitchTimeMSPerS", "uiMaxGapMS", "uiP95GapMSApprox", "uiFramesDelivered",
    "uiExpectedFrames", "uiProbeCoverage", "uiRefreshIntervalMS",
    "uiWindowDurationMS", "uiActionCount",
}
UI_PERF_REQUIRED_METRICS = {
    "uiHitchTimeMSPerS", "uiMaxGapMS", "uiFramesDelivered", "uiExpectedFrames",
    "uiProbeCoverage", "uiRefreshIntervalMS", "uiWindowDurationMS", "uiActionCount",
    "cpuUserSeconds", "cpuSystemSeconds",
}
# One ui-perf kind, platform-aware (IUI-6): the metric allowlist is shared;
# only the probe scenario set differs per platform.
UI_PERF_SCENARIOS_BY_PLATFORM = {
    "macos": {
        "idle-baseline", "sidebar-navigation", "history-scroll", "history-filter",
        "delivery-menu", "settings-scroll", "composer-typing", "window-resize",
        "generation-active",
    },
    "ios": {
        "ios-idle-baseline", "ios-tab-navigation", "ios-history-scroll",
        "ios-voices-scroll", "ios-settings-scroll", "ios-composer-typing",
        "ios-sheet-present-dismiss", "ios-player-scrub", "ios-generation-active",
    },
}
MEMORY_REQUIRED_METRICS = {
    "residentStartMB", "residentEndMB", "residentDeltaMB", "peakResidentMB",
    "physicalFootprintStartMB", "physicalFootprintEndMB", "physicalFootprintDeltaMB",
    "peakPhysicalFootprintMB", "peakCompressedMB", "peakGPUAllocatedMB",
    "gpuRecommendedWorkingSetMB", "gpuWorkingSetUsageRatioPeak",
    "memoryTimeToPeakMS", "samplerSampleCount", "samplerPeriodicSampleCount",
    "samplerBoundarySampleCount", "samplerCaptureFailureCount",
    "samplerMissedDeadlineCount", "samplerCoverage", "memoryPressureEventCount",
    "maximumPressureLevel", "memoryTrimCount", "maximumTrimLevel",
    "memoryWarningCount", "memoryExitCount",
    "mlxActivePeakMB", "mlxCachePeakMB", "mlxPeakMB",
}
IOS_MEMORY_REQUIRED_METRICS = {
    "headroomStartMB", "headroomEndMB", "minimumHeadroomMB",
    "peakProcessBudgetUtilization",
    "impliedProcessLimitMB", "totalDeviceRAMMB",
}
MACOS_UI_MEMORY_REQUIRED_METRICS = {
    "alignedProcessSampleCount", "alignedProcessSampleCoverage",
    "alignedEngineSampleCoverage", "alignedAppSampleCoverage",
}

SENSITIVE_KEY_PARTS = {
    "serial", "udid", "ecid", "hostname", "devicename", "username", "userhome",
    "prompt", "transcript", "voicedescription", "rawerror", "absolutePath".lower(),
    "email", "url", "uri",
}
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")
EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
URL_RE = re.compile(r"\b(?:https?|file)://", re.IGNORECASE)
WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
SECRET_RE = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{12,}|gh[pousr]_[A-Za-z0-9]{12,}|"
    r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----|bearer\s+[A-Za-z0-9._~-]{12,})",
    re.IGNORECASE,
)


class HistoryError(RuntimeError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")


def stored_json_bytes(value: Any) -> bytes:
    """Return the deterministic, size-bounded representation used on disk.

    Benchmark records intentionally retain both exact per-take evidence and
    per-cell aggregates.  Pretty-print whitespace made the canonical 29-take
    UI matrix exceed the 256 KiB registry contract even though its allowlisted
    content fit.  Reuse the canonical JSON representation used for record
    digests so the cap measures evidence rather than presentation overhead.
    """
    return canonical_bytes(value) + b"\n"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record_digest(record: dict[str, Any]) -> str:
    unsigned = copy.deepcopy(record)
    unsigned.pop("digest", None)
    return sha256_bytes(canonical_bytes(unsigned))


def run_command(arguments: list[str], *, check: bool = True) -> str:
    result = subprocess.run(
        arguments, cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if check and result.returncode != 0:
        raise HistoryError(f"command failed: {arguments[0]} ({result.stderr.strip()})")
    return result.stdout.strip()


def reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, child in pairs:
        if key in value:
            raise HistoryError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_json_keys
        )
    except (OSError, json.JSONDecodeError) as error:
        raise HistoryError(f"cannot read JSON {path}: {error}") from error


def atomic_json_write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = stored_json_bytes(value)
    if len(encoded) > MAX_RECORD_BYTES:
        raise HistoryError(f"record exceeds {MAX_RECORD_BYTES} bytes ({len(encoded)} bytes)")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_text_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_profiles() -> dict[str, dict[str, Any]]:
    payload = load_json(HARDWARE_PROFILES_PATH)
    if payload.get("schemaVersion") != 1 or not isinstance(payload.get("profiles"), list):
        raise HistoryError("hardware-profiles.json has an unsupported schema")
    profiles: dict[str, dict[str, Any]] = {}
    for profile in payload["profiles"]:
        identifier = profile.get("id")
        if not isinstance(identifier, str) or identifier in profiles:
            raise HistoryError("hardware profiles must have unique string IDs")
        profiles[identifier] = profile
    return profiles


def require_schema_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HistoryError(f"benchmark schema {location} must be an object")
    return value


def load_schema_contract(version: int | None = None) -> dict[str, Any]:
    """Parse one history schema and prove it matches the executable allowlist.

    The repository intentionally has no runtime dependency on ``jsonschema``.
    This contract check covers the closed record shape and the enums that must
    stay in lockstep with the executable validator; ``validate_schema_value``
    then evaluates the schema subset used by schema-v1 for every record.
    """
    if version is None:
        version = 1 if SCHEMA_PATH != SCHEMA_PATHS[1] else SCHEMA_VERSION
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise HistoryError(f"unsupported benchmark history schema: {version!r}")
    schema_path = SCHEMA_PATH if version == 1 else SCHEMA_PATHS[version]
    schema = require_schema_object(load_json(schema_path), "root")
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise HistoryError("benchmark schema must declare JSON Schema draft 2020-12")
    if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
        raise HistoryError("benchmark schema root must be a closed object")
    properties = require_schema_object(schema.get("properties"), "properties")
    if set(properties) != TOP_LEVEL_KEYS:
        raise HistoryError("benchmark schema top-level properties drifted from the executable allowlist")
    if set(schema.get("required", [])) != TOP_LEVEL_KEYS:
        raise HistoryError("benchmark schema top-level required fields drifted from the executable validator")
    if properties.get("schemaVersion", {}).get("const") != version:
        raise HistoryError("benchmark schema version drifted from the executable validator")

    definitions = require_schema_object(schema.get("$defs"), "$defs")
    for name, expected_properties in schema_property_keys(version).items():
        definition = require_schema_object(definitions.get(name), f"$defs.{name}")
        if definition.get("type") != "object" or definition.get("additionalProperties") is not False:
            raise HistoryError(f"benchmark schema $defs.{name} must be a closed object")
        actual_properties = require_schema_object(
            definition.get("properties"), f"$defs.{name}.properties"
        )
        if set(actual_properties) != expected_properties:
            raise HistoryError(
                f"benchmark schema $defs.{name} properties drifted from the executable allowlist"
            )
        if set(definition.get("required", [])) != SCHEMA_REQUIRED_KEYS[name]:
            raise HistoryError(
                f"benchmark schema $defs.{name} required fields drifted from the executable validator"
            )

    run_properties = definitions["run"]["properties"]
    enum_contracts = {
        "kind": V2_KINDS if version >= 2 else V1_KINDS,
        "platform": PLATFORMS,
        "status": SUCCESS_STATUSES,
        "matrixScope": MATRIX_SCOPES,
        "classification": CLASSIFICATIONS,
    }
    for field, expected in enum_contracts.items():
        if set(run_properties.get(field, {}).get("enum", [])) != expected:
            raise HistoryError(f"benchmark schema run.{field} enum drifted from the executable validator")
    if set(definitions["listening"]["properties"]["status"].get("enum", [])) != LISTENING_STATUSES:
        raise HistoryError("benchmark schema listening statuses drifted from the executable validator")
    if set(definitions["audioQC"]["properties"]["verdict"].get("enum", [])) != QC_VERDICTS:
        raise HistoryError("benchmark schema audio-QC verdicts drifted from the executable validator")
    profile_ids = set(load_profiles())
    if set(definitions["hardware"]["properties"]["profileID"].get("enum", [])) != profile_ids:
        raise HistoryError("benchmark schema hardware profiles drifted from hardware-profiles.json")
    return schema


def resolve_schema_reference(reference: str, root: dict[str, Any]) -> dict[str, Any]:
    prefix = "#/$defs/"
    if not reference.startswith(prefix) or "/" in reference[len(prefix):]:
        raise HistoryError(f"benchmark schema contains unsupported reference: {reference}")
    return require_schema_object(root.get("$defs", {}).get(reference[len(prefix):]), reference)


def schema_type_matches(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))
    if expected == "string":
        return isinstance(value, str)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    raise HistoryError(f"benchmark schema contains unsupported type: {expected}")


def validate_schema_value(value: Any, node: dict[str, Any], root: dict[str, Any], location: str) -> None:
    if "$ref" in node:
        validate_schema_value(value, resolve_schema_reference(node["$ref"], root), root, location)
        return
    if "const" in node and value != node["const"]:
        raise HistoryError(f"{location} does not match the benchmark schema constant")
    if "enum" in node and value not in node["enum"]:
        raise HistoryError(f"{location} is outside the benchmark schema enum")
    expected_types = node.get("type")
    if expected_types is not None:
        choices = [expected_types] if isinstance(expected_types, str) else expected_types
        if not isinstance(choices, list) or not all(isinstance(item, str) for item in choices):
            raise HistoryError(f"benchmark schema {location} has an invalid type declaration")
        if not any(schema_type_matches(value, item) for item in choices):
            raise HistoryError(f"{location} has the wrong type for benchmark history schema")

    if isinstance(value, dict):
        properties = node.get("properties", {})
        if not isinstance(properties, dict):
            raise HistoryError(f"benchmark schema {location}.properties must be an object")
        required = node.get("required", [])
        if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
            raise HistoryError(f"benchmark schema {location}.required must be a string list")
        missing = sorted(set(required) - set(value))
        if missing:
            raise HistoryError(f"{location} is missing schema fields: {', '.join(missing)}")
        if node.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise HistoryError(f"{location} has schema-disallowed fields: {', '.join(unknown)}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, dict):
                validate_schema_value(child, child_schema, root, f"{location}.{key}")
    elif isinstance(value, list):
        item_schema = node.get("items")
        if isinstance(item_schema, dict):
            for index, child in enumerate(value):
                validate_schema_value(child, item_schema, root, f"{location}[{index}]")
    elif isinstance(value, str):
        pattern = node.get("pattern")
        if pattern is not None and (not isinstance(pattern, str) or re.fullmatch(pattern, value) is None):
            raise HistoryError(f"{location} does not match the benchmark schema pattern")
        maximum = node.get("maxLength")
        if isinstance(maximum, int) and len(value) > maximum:
            raise HistoryError(f"{location} exceeds the benchmark schema length limit")
        if node.get("format") == "date-time":
            iso_timestamp(value, location)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        minimum = node.get("minimum")
        if isinstance(minimum, (int, float)) and value < minimum:
            raise HistoryError(f"{location} is below the benchmark schema minimum")


def validate_record_against_schema(record: dict[str, Any], schema: dict[str, Any]) -> None:
    validate_schema_value(record, schema, schema, "record")


def validate_benchmark_storage_tree() -> None:
    """Reject raw evidence anywhere below benchmarks/, including bundle directories."""
    if not BENCHMARK_ROOT.exists():
        return
    if not BENCHMARK_ROOT.is_dir() or BENCHMARK_ROOT.is_symlink():
        raise HistoryError("benchmarks must be a real directory")
    for path in BENCHMARK_ROOT.rglob("*"):
        suffix = path.suffix.lower()
        if path.is_dir() and suffix in RAW_BENCHMARK_BUNDLE_SUFFIXES:
            raise HistoryError(f"raw benchmark bundle is prohibited: {path.relative_to(BENCHMARK_ROOT)}")
        if path.is_file() and suffix in RAW_BENCHMARK_FILE_SUFFIXES | RAW_BENCHMARK_BUNDLE_SUFFIXES:
            raise HistoryError(f"raw benchmark artifact is prohibited: {path.relative_to(BENCHMARK_ROOT)}")


def validate_registry_tree() -> list[Path]:
    """Return records only when benchmarks/runs has the exact closed layout."""
    if not RUNS_ROOT.exists():
        return []
    if not RUNS_ROOT.is_dir() or RUNS_ROOT.is_symlink():
        raise HistoryError("benchmarks/runs must be a real directory")
    records: list[Path] = []
    for kind_path in sorted(RUNS_ROOT.iterdir()):
        if kind_path.is_symlink() or not kind_path.is_dir() or kind_path.name not in ALL_KINDS:
            raise HistoryError(f"unexpected benchmark run-kind entry: {kind_path.name}")
        for path in sorted(kind_path.iterdir()):
            if path.is_symlink() or not path.is_file():
                raise HistoryError(f"unexpected non-record entry under benchmarks/runs: {path.relative_to(RUNS_ROOT)}")
            if path.suffix != ".json" or not RUN_ID_RE.fullmatch(path.stem):
                raise HistoryError(f"unexpected benchmark run file: {path.relative_to(RUNS_ROOT)}")
            records.append(path)
    return records


def is_registry_output(path: str) -> bool:
    return path == "benchmarks/HISTORY.md" or path.startswith("benchmarks/runs/")


def parse_git_status_paths(raw: str) -> list[str]:
    """Return exact repository-relative paths from porcelain-v1 ``-z`` output.

    The leading space in an unstaged status record is structural.  Callers must
    pass the untrimmed Git output or a first pathname such as ``.agents/...``
    can lose its leading dot when the status prefix is sliced off.
    """
    entries = [entry for entry in raw.split("\0") if entry]
    paths: list[str] = []
    index = 0
    while index < len(entries):
        entry = entries[index]
        status = entry[:2] if len(entry) >= 3 else "??"
        path = entry[3:] if len(entry) >= 4 else entry
        if not is_registry_output(path):
            paths.append(path)
        # In porcelain-v1 -z output a rename/copy has a second NUL-delimited
        # pathname rather than the human-readable "old -> new" form. Preserve
        # both sides in changedPaths and never misparse the second path as a
        # fresh status record.
        if "R" in status or "C" in status:
            index += 1
            if index >= len(entries):
                raise HistoryError("git status returned an incomplete rename record")
            related = entries[index]
            if not is_registry_output(related):
                paths.append(related)
        index += 1
    return sorted(set(paths))


def git_status_porcelain() -> str:
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        raise HistoryError(f"git status failed: {detail}")
    return result.stdout.decode("utf-8", "surrogateescape")


def git_state() -> dict[str, Any]:
    commit = run_command(["git", "rev-parse", "HEAD"])
    paths = parse_git_status_paths(git_status_porcelain())

    digest = hashlib.sha256()
    digest.update(commit.encode("ascii"))
    digest.update(b"\0")
    diff = subprocess.run(
        [
            "git", "diff", "--binary", "HEAD", "--", ".",
            ":(exclude)benchmarks/HISTORY.md", ":(exclude)benchmarks/runs/**",
        ],
        cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if diff.returncode != 0:
        raise HistoryError(f"git diff failed: {diff.stderr.decode('utf-8', 'replace').strip()}")
    digest.update(diff.stdout)
    for relative in paths:
        candidate = REPO_ROOT / relative
        if candidate.is_file() and run_command(["git", "ls-files", "--error-unmatch", "--", relative], check=False) == "":
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(file_digest(candidate).encode("ascii"))

    fingerprint = digest.hexdigest()
    return {
        "commit": commit,
        "dirty": bool(paths),
        "changedPaths": paths,
        "workspaceFingerprint": fingerprint,
        "preFingerprint": fingerprint,
        "postFingerprint": fingerprint,
        "fingerprintsMatch": True,
    }


def source_state_for_artifact(artifact_dir: Path) -> dict[str, Any]:
    """Resolve pre/post provenance when the runner captured a pre-run snapshot."""
    snapshot_path = artifact_dir / "benchmark-source.json"
    if not snapshot_path.is_file():
        return git_state()
    snapshot = load_json(snapshot_path)
    before = snapshot.get("source") if isinstance(snapshot, dict) else None
    if snapshot.get("schemaVersion") != 1 or not isinstance(before, dict):
        raise HistoryError("benchmark-source.json has an unsupported schema")
    after = git_state()
    fingerprints_match = (
        before.get("commit") == after.get("commit")
        and before.get("workspaceFingerprint") == after.get("workspaceFingerprint")
    )
    return {
        "commit": before.get("commit"),
        "dirty": bool(before.get("dirty") or after.get("dirty") or not fingerprints_match),
        "changedPaths": sorted(set(before.get("changedPaths", [])) | set(after.get("changedPaths", []))),
        "workspaceFingerprint": before.get("workspaceFingerprint"),
        "preFingerprint": before.get("workspaceFingerprint"),
        "postFingerprint": after.get("workspaceFingerprint"),
        "fingerprintsMatch": fingerprints_match,
    }


def hash_existing_files(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    found = False
    for path in sorted(paths, key=lambda item: item.as_posix()):
        if not path.is_file():
            continue
        found = True
        digest.update(path.relative_to(REPO_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest(path).encode("ascii"))
    return digest.hexdigest() if found else "not-applicable"


def default_inputs(record: dict[str, Any]) -> dict[str, Any]:
    run = record["run"]
    matrix_payload = {
        "kind": run["kind"], "scope": run["matrixScope"],
        "cells": [take.get("cell") for take in record.get("takes", [])],
    }
    package_locks = [
        REPO_ROOT / "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
        REPO_ROOT / "Packages/VocelloQwen3Core/Package.resolved",
    ]
    harness_paths = [
        REPO_ROOT / "scripts" / "ui_test.sh",
        REPO_ROOT / "scripts" / "check_test_workflows.sh",
        REPO_ROOT / "scripts" / "check_macos_xpc_bench.py",
        REPO_ROOT / "scripts" / "check_ios_ui_benchmark.py",
        REPO_ROOT / "scripts" / "summarize_generation_telemetry.py",
        REPO_ROOT / "scripts" / "benchmark_memory.py",
        REPO_ROOT / "scripts" / "benchmark_history.py",
        REPO_ROOT / "scripts" / "publish_benchmark_history.py",
        REPO_ROOT / "scripts" / "ios_memory_field_report.py",
        REPO_ROOT / "scripts" / "macos_test.sh",
        REPO_ROOT / "scripts" / "ios_device.sh",
        REPO_ROOT / "scripts" / "telemetry_overhead.py",
        REPO_ROOT / "scripts" / "prosody_calibration.py",
        REPO_ROOT / "scripts" / "analyze_prosody.py",
        REPO_ROOT / "scripts" / "bench_delivery_prosody.py",
        REPO_ROOT / "scripts" / "prosody_profile.py",
        REPO_ROOT / "scripts" / "prosody_quality_gate.py",
        # The delivery verdict and its inputs shape published take metrics just
        # as much as the prosody gate does; before this they could change
        # without invalidating inputs.analysisProfileHash.
        REPO_ROOT / "scripts" / "delivery_quality_gate.py",
        REPO_ROOT / "scripts" / "delivery_separability.py",
        REPO_ROOT / "scripts" / "clone_prosody_fidelity.py",
        REPO_ROOT / "scripts" / "check_language_hints.py",
        REPO_ROOT / "scripts" / "check_language_output.py",
        REPO_ROOT / "Tests" / "UIAutomationSupport" / "VocelloUIAutomationSupport.swift",
        REPO_ROOT / "Tests" / "VocelloMacUITests" / "VocelloMacBenchmarkUITests.swift",
        REPO_ROOT / "Tests" / "VocelloMacUITests" / "VocelloMacPerfUITests.swift",
        REPO_ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSBenchmarkUITests.swift",
        # ui-perf (UI-7 macOS, IUI-6 iOS): the frame probes, history seeders,
        # gate checkers, perf test classes, and per-platform threshold
        # contracts shape published frame-health evidence.
        REPO_ROOT / "scripts" / "check_macos_ui_perf.py",
        REPO_ROOT / "Sources" / "Services" / "UIPerfFrameProbe.swift",
        REPO_ROOT / "Sources" / "Services" / "UIPerfHistorySeeder.swift",
        REPO_ROOT / "config" / "ui-perf-thresholds.json",
        REPO_ROOT / "scripts" / "check_ios_ui_perf.py",
        REPO_ROOT / "Sources" / "iOSSupport" / "Services" / "IOSUIPerfFrameProbe.swift",
        REPO_ROOT / "Sources" / "iOSSupport" / "Services" / "IOSUIPerfHistorySeeder.swift",
        REPO_ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSPerfUITests.swift",
        REPO_ROOT / "config" / "ui-perf-thresholds-ios.json",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "BenchMatrixSpec.swift",
        REPO_ROOT / "Sources" / "VocelloCLI" / "BenchCommand.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "GenerationTelemetryRecord.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "NativeTelemetrySampler.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "GenerationOutputAdapter.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "NativeEngineRuntime.swift",
        REPO_ROOT / "Sources" / "SharedSupport" / "Telemetry" / "AppGenerationTimeline.swift",
        REPO_ROOT / "Sources" / "SharedSupport" / "Telemetry" / "MainThreadStallWatchdog.swift",
        REPO_ROOT / "Sources" / "QwenVoiceEngineSupport" / "EngineServiceTransportAccumulator.swift",
        REPO_ROOT / "benchmarks" / "schema-v2.json",
        REPO_ROOT / "config" / "memory-qualification-policy.json",
    ]
    corpus_paths = [
        REPO_ROOT / "Tests" / "UIAutomationSupport" / "VocelloUIAutomationSupport.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "BenchMatrixSpec.swift",
        REPO_ROOT / "Sources" / "VocelloCLI" / "BenchCommand.swift",
    ]
    return {
        "contractHash": hash_existing_files([REPO_ROOT / "Sources/Resources/qwenvoice_contract.json"]),
        "dependencyLockHash": hash_existing_files(package_locks),
        "projectInputHash": hash_existing_files([
            REPO_ROOT / "project.yml",
            REPO_ROOT / "benchmarks" / "schema-v2.json",
            REPO_ROOT / "config" / "memory-qualification-policy.json",
        ]),
        "harnessHash": hash_existing_files(harness_paths),
        "matrixHash": sha256_bytes(canonical_bytes(matrix_payload)),
        "corpusHash": hash_existing_files(corpus_paths),
        "analysisProfileHash": "not-applicable",
    }


def mac_runtime_hardware() -> dict[str, Any]:
    thermal_names = {"0": "nominal", "1": "fair", "2": "serious", "3": "critical"}
    swift_probe = run_command([
        "swift", "-e",
        "import Foundation; print(ProcessInfo.processInfo.thermalState.rawValue); "
        "print(ProcessInfo.processInfo.isLowPowerModeEnabled ? 1 : 0)",
    ], check=False).splitlines()
    return {
        "osName": run_command(["sw_vers", "-productName"]),
        "osVersion": run_command(["sw_vers", "-productVersion"]),
        "osBuild": run_command(["sw_vers", "-buildVersion"]),
        "thermalState": thermal_names.get(swift_probe[0], "unknown") if swift_probe else "unknown",
        "lowPowerMode": len(swift_probe) > 1 and swift_probe[1] == "1",
        "transport": "local",
        "loadAverage1M": os.getloadavg()[0],
        "freeStorageBytes": shutil.disk_usage(REPO_ROOT).free,
        "uptimeSeconds": time.monotonic(),
    }


def ios_runtime_hardware(profile: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "osName": "iOS", "thermalState": "unknown", "lowPowerMode": None,
        "transport": "physical-device",
    }
    descriptor, temporary = tempfile.mkstemp(prefix="vocello-devices-", suffix=".json")
    os.close(descriptor)
    try:
        command = subprocess.run(
            [
                "xcrun", "devicectl", "list", "devices", "--quiet", "--timeout", "5",
                "--filter", f"hardwareProperties.productType == '{profile['modelIdentifier']}'",
                "--json-output", temporary,
            ],
            cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if command.returncode == 0:
            payload = load_json(Path(temporary))
            devices = payload.get("result", {}).get("devices", [])
            if len(devices) == 1:
                device = devices[0]
                properties = device.get("deviceProperties", {})
                connection = device.get("connectionProperties", {})
                result["osVersion"] = properties.get("osVersionNumber")
                result["osBuild"] = properties.get("osBuildUpdate")
                transport = connection.get("transportType")
                if transport:
                    result["transport"] = {
                        "localNetwork": "local-network", "wired": "wired",
                    }.get(transport, "physical-device")
    finally:
        Path(temporary).unlink(missing_ok=True)
    return result


def xcresult_runtime_hardware(artifact_dir: Path, platform: str) -> dict[str, Any]:
    """Read immutable OS identity from a retained XCTest result summary.

    Device discovery is useful during a live run, but delayed benchmark
    publication must not depend on the phone still being connected.  The UI
    runner stores the compact xcresult summary beside the run artifacts; only
    its non-identifying OS fields enter tracked history.
    """
    summary_path = artifact_dir / "xcresult-test-summary.json"
    if not summary_path.is_file():
        return {}
    summary = load_json(summary_path)
    devices = summary.get("devicesAndConfigurations")
    if not isinstance(devices, list):
        return {}
    expected_platform = "iOS" if platform == "ios" else "macOS"
    identities: set[tuple[str, str]] = set()
    for row in devices:
        device = row.get("device") if isinstance(row, dict) else None
        if not isinstance(device, dict) or device.get("platform") != expected_platform:
            continue
        version = device.get("osVersion")
        build = device.get("osBuildNumber")
        if isinstance(version, str) and version and isinstance(build, str) and build:
            identities.add((version, build))
    if len(identities) != 1:
        return {}
    version, build = identities.pop()
    return {"osName": expected_platform, "osVersion": version, "osBuild": build}


def default_runtime_hardware(platform: str, profile: dict[str, Any]) -> dict[str, Any]:
    return mac_runtime_hardware() if platform == "macos" else ios_runtime_hardware(profile)


def parse_project_versions() -> tuple[str, str]:
    text = (REPO_ROOT / "project.yml").read_text(encoding="utf-8")
    version = re.search(r'MARKETING_VERSION:\s*["\']?([^"\'\s]+)', text)
    build = re.search(r'CURRENT_PROJECT_VERSION:\s*["\']?([^"\'\s]+)', text)
    return (version.group(1) if version else "unknown", build.group(1) if build else "unknown")


def app_identity(platform: str, outer: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    supplied = outer.get("executableRelativePaths")
    has_explicit_executables = isinstance(supplied, dict)
    bundle_value = outer.get("appBundleRelativePath")
    if isinstance(bundle_value, str):
        bundle = (REPO_ROOT / bundle_value).resolve()
        if REPO_ROOT not in bundle.parents:
            raise HistoryError("appBundleRelativePath must remain inside the repository")
    elif not has_explicit_executables:
        bundle = (
            MACOS_DERIVED_DATA / "Build/Products/Release/Vocello.app" if platform == "macos"
            else IOS_DERIVED_DATA / "Build/Products/Release-iphoneos/Vocello.app"
        )
    else:
        bundle = Path("/__vocello_no_default_bundle__")
    executable_paths: dict[str, Path] = {}
    if bundle.is_dir():
        info_path = bundle / ("Contents/Info.plist" if platform == "macos" else "Info.plist")
        if info_path.is_file():
            with info_path.open("rb") as handle:
                plist = plistlib.load(handle)
            executable_name = plist.get("CFBundleExecutable", "Vocello")
            executable = bundle / (f"Contents/MacOS/{executable_name}" if platform == "macos" else executable_name)
            if executable.is_file():
                executable_paths["Vocello"] = executable
            if platform == "macos":
                service = bundle / "Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/MacOS/QwenVoiceEngineService"
                if service.is_file():
                    executable_paths["QwenVoiceEngineService"] = service
            app_version = str(plist.get("CFBundleShortVersionString", "unknown"))
            app_build = str(plist.get("CFBundleVersion", "unknown"))
        else:
            app_version, app_build = parse_project_versions()
    else:
        app_version, app_build = parse_project_versions()

    if isinstance(supplied, dict):
        for label, relative in supplied.items():
            if not isinstance(label, str) or not isinstance(relative, str):
                raise HistoryError("executableRelativePaths must map labels to relative paths")
            candidate = (REPO_ROOT / relative).resolve()
            if REPO_ROOT not in candidate.parents or not candidate.is_file():
                raise HistoryError(f"invalid executableRelativePaths entry: {label}")
            executable_paths[label] = candidate

    hashes: dict[str, str] = {}
    uuids: dict[str, str] = {}
    for label, executable in sorted(executable_paths.items()):
        hashes[label] = file_digest(executable)
        output = run_command(["dwarfdump", "--uuid", str(executable)], check=False)
        matches = re.findall(r"UUID: ([0-9A-Fa-f-]+) \(([^)]+)\)", output)
        for uuid, architecture in matches:
            uuids[f"{label}[{architecture}]"] = uuid.upper()
    return {
        "appVersion": app_version, "appBuild": app_build,
        "executableUUIDs": uuids, "executableHashes": hashes,
    }


def default_toolchain(platform: str, outer: dict[str, Any], artifact_dir: Path) -> dict[str, Any]:
    xcode_lines = run_command(["xcodebuild", "-version"]).splitlines()
    swift_line = run_command(["swiftc", "--version"]).splitlines()[0]
    sdk = "macosx" if platform == "macos" else "iphoneos"
    result = {
        "xcodeVersion": xcode_lines[0].removeprefix("Xcode ") if xcode_lines else "unknown",
        "xcodeBuild": xcode_lines[1].removeprefix("Build version ") if len(xcode_lines) > 1 else "unknown",
        "swiftVersion": swift_line,
        "sdkName": sdk,
        "sdkVersion": run_command(["xcrun", "--sdk", sdk, "--show-sdk-version"]),
        "optimization": str(outer.get("optimization") or "unknown"),
    }
    result.update(app_identity(platform, outer, artifact_dir))
    return result


def digest_xcresult_summary(artifact_dir: Path) -> str:
    bundles = sorted(path for path in artifact_dir.glob("*.xcresult") if path.is_dir())
    if not bundles:
        return "not-applicable"
    if len(bundles) != 1:
        raise HistoryError("artifact directory must contain at most one xcresult bundle")
    output = run_command([
        "xcrun", "xcresulttool", "get", "test-results", "summary",
        "--path", str(bundles[0]), "--format", "json",
    ])
    try:
        summary = json.loads(output)
    except json.JSONDecodeError as error:
        raise HistoryError("xcresulttool returned invalid summary JSON") from error
    return sha256_bytes(canonical_bytes(summary))


def screenshot_digests(artifact_dir: Path) -> list[dict[str, str]]:
    screenshots: dict[str, str] = {}
    for suffix in ("*.png", "*.jpg", "*.jpeg"):
        for path in (artifact_dir / "attachments").rglob(suffix):
            digest = file_digest(path)
            previous = screenshots.get(path.name)
            if previous is not None and previous != digest:
                raise HistoryError(f"duplicate screenshot basename with different content: {path.name}")
            screenshots[path.name] = digest
    return [{"name": name, "digest": digest} for name, digest in sorted(screenshots.items())]


QUALITY_FAST_GATES = {
    "terminal", "token_cap", "codec_behavior", "persisted_wav", "streaming_continuity",
}
QUALITY_GATE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
QUALITY_ISSUE_RE = re.compile(r"^[a-z][a-z0-9_.]*$")


def validate_take_quality_identity(
    take: dict[str, Any], position: int, *, generation_kind: bool
) -> None:
    """Phase 13 (schema v3): every generation take carries the fail-closed
    quality-registry verdict it published with. A failing verdict is never
    publishable (PASS-only history), the covered gate set must include the
    five fast gates, and issue codes stay machine-readable."""
    label = f"takes[{position - 1}]"
    outcome = take.get("qualityRegistryOutcome")
    gates = take.get("qualityRegistryRequiredGates")
    if not generation_kind:
        if any(key in take for key in V3_ONLY_TAKE_KEYS):
            raise HistoryError(f"{label} quality identity applies only to generation takes")
        return
    if outcome not in {"pass", "warning"}:
        raise HistoryError(f"{label} requires a publishable qualityRegistryOutcome")
    if (
        not isinstance(gates, list) or not gates
        or any(not isinstance(gate, str) or not QUALITY_GATE_RE.fullmatch(gate) for gate in gates)
        or len(set(gates)) != len(gates)
        or gates != sorted(gates)
    ):
        raise HistoryError(f"{label} qualityRegistryRequiredGates must be sorted unique gate ids")
    if not QUALITY_FAST_GATES.issubset(gates):
        raise HistoryError(f"{label} quality identity must cover the five fast gates")
    issues = take.get("qualityRegistryIssues")
    if issues is not None:
        if (
            not isinstance(issues, list)
            or any(not isinstance(issue, str) or not QUALITY_ISSUE_RE.fullmatch(issue) for issue in issues)
        ):
            raise HistoryError(f"{label} qualityRegistryIssues must be machine-readable codes")
        if outcome == "pass" and issues:
            raise HistoryError(f"{label} a pass verdict cannot carry registry issues")
    if outcome == "warning" and not issues:
        raise HistoryError(f"{label} a warning verdict must record its registry issues")


def artifact_version_key(value: str) -> tuple[int, ...]:
    try:
        return tuple(int(part) for part in value.split("."))
    except ValueError as error:
        raise HistoryError(f"artifactVersion is not a dotted numeric version: {value!r}") from error


def default_models(record: dict[str, Any], *, allow_superseded: bool = False) -> list[dict[str, Any]]:
    contract_path = REPO_ROOT / "Sources/Resources/qwenvoice_contract.json"
    contract = load_json(contract_path)
    definitions = {model["id"]: model for model in contract.get("models", [])}
    platform = record["run"]["platform"]
    requested: dict[tuple[str, str], dict[str, str]] = {}
    for take in record.get("takes", []):
        model_id = take.get("modelID")
        mode = take.get("mode")
        if not isinstance(model_id, str) or not isinstance(mode, str) or model_id == "not-applicable":
            continue
        base_id, variant = model_id, take.get("variant")
        for suffix in ("speed", "quality"):
            marker = f"_{suffix}"
            if base_id.endswith(marker):
                base_id, variant = base_id[: -len(marker)], suffix
                break
        if not isinstance(variant, str):
            variant = "speed" if platform == "ios" else "quality"
        value = {
            "mode": mode,
            "internalModelID": model_id,
            "runtimeProfileSignature": str(take.get("runtimeProfileSignature", "")),
            "fixtureDigest": str(take.get("fixtureDigest", "not-applicable")),
            "integrityDigest": str(take.get("modelIntegrityDigest", "not-applicable")),
            "repository": str(take.get("modelRepository", "")),
            "revision": str(take.get("modelRevision", "")),
            "artifactVersion": str(take.get("modelArtifactVersion", "")),
            "quantization": str(take.get("modelQuantization", "")),
        }
        previous = requested.get((base_id, variant))
        if previous is not None and previous != value:
            raise HistoryError(f"inconsistent typed model identity for {base_id}/{variant}")
        requested[(base_id, variant)] = value

    models: list[dict[str, Any]] = []
    for (base_id, variant), observed in sorted(requested.items()):
        definition = definitions.get(base_id)
        if not definition:
            raise HistoryError(f"telemetry model ID is absent from qwenvoice_contract.json: {base_id}")
        selected = definition
        for candidate in definition.get("variants", []):
            if candidate.get("id") == variant:
                selected = candidate
                break
        folder = str(selected.get("folder", definition.get("folder", "")))
        quantization_match = re.search(r"-(\d+)bit$", folder, re.IGNORECASE)
        expected_quantization = f"{quantization_match.group(1)}-bit" if quantization_match else "unquantized"
        expected_repository = str(selected.get("huggingFaceRepo", definition.get("huggingFaceRepo", "")))
        expected_revision = str(selected.get("huggingFaceRevision", definition.get("huggingFaceRevision", "")))
        expected_artifact = str(selected.get("artifactVersion", definition.get("artifactVersion", "")))
        expected = {
            "repository": expected_repository,
            "revision": expected_revision,
            "artifactVersion": expected_artifact,
            "quantization": expected_quantization,
        }
        for field, expected_value in expected.items():
            if observed[field] != expected_value:
                # Published records are immutable point-in-time evidence. After an
                # artifact re-pin, existing records keep the identity they measured;
                # they stay valid only when their pin is strictly older than the
                # contract's current pin. New publications still fail closed.
                if allow_superseded and artifact_version_key(observed["artifactVersion"]) < artifact_version_key(
                    expected["artifactVersion"]
                ):
                    break
                raise HistoryError(
                    f"typed {field} for {base_id}/{variant} does not match qwenvoice_contract.json"
                )
        if not observed["runtimeProfileSignature"]:
            raise HistoryError(f"typed runtime profile is missing for {base_id}/{variant}")
        require_digest(observed["integrityDigest"], f"typed integrity for {base_id}/{variant}", allow_na=False)
        if observed["mode"] in {"design", "clone"}:
            require_digest(observed["fixtureDigest"], f"typed fixture for {base_id}/{variant}", allow_na=False)
        elif observed["fixtureDigest"] != "not-applicable":
            require_digest(observed["fixtureDigest"], f"typed fixture for {base_id}/{variant}")
        models.append({
            "mode": observed["mode"],
            "modelID": observed["repository"],
            "variant": variant,
            "quantization": observed["quantization"],
            "revision": observed["revision"],
            "artifactVersion": observed["artifactVersion"],
            "integrityDigest": observed["integrityDigest"],
            "runtimeProfileSignature": observed["runtimeProfileSignature"],
            "fixtureDigest": observed["fixtureDigest"],
        })
    return models


def merge_missing(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        target.setdefault(key, value)


def normalize_status(value: Any) -> str:
    normalized = value.lower() if isinstance(value, str) else value
    aliases = {"pass": "passed", "passed": "passed", "passed-with-warnings": "passedWithWarnings", "passedwithwarnings": "passedWithWarnings"}
    if normalized not in aliases:
        raise HistoryError(f"benchmark status is not successful: {value!r}")
    return aliases[normalized]


def iso_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise HistoryError(f"{field} must be an ISO-8601 string")
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(candidate)
    except ValueError as error:
        raise HistoryError(f"{field} is not valid ISO-8601") from error
    if parsed.tzinfo is None:
        raise HistoryError(f"{field} must include a timezone")
    return parsed.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def metric_summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    if len(ordered) >= 2:
        quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
        iqr = quartiles[2] - quartiles[0]
    else:
        iqr = 0.0
    return {
        "count": len(ordered), "median": statistics.median(ordered), "iqr": iqr,
        "min": ordered[0], "max": ordered[-1],
    }


def aggregate_cells(takes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for take in takes:
        # The ordered take identity retains #repetition, but statistics describe
        # the comparable benchmark cell. Otherwise a 29-take matrix degenerates
        # into 29 n=1 summaries with meaningless zero IQRs.
        cell = re.sub(r"#\d+$", "", take["cell"])
        grouped.setdefault(cell, []).append(take)
    cells: list[dict[str, Any]] = []
    qc_rank = {"pass": 0, "warn": 1}
    for key, group in grouped.items():
        metrics: dict[str, list[float]] = {}
        for take in group:
            for metric, value in take.get("metrics", {}).items():
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    metrics.setdefault(metric, []).append(float(value))
        first = group[0]
        verdicts = [take.get("audioQC", {}).get("verdict", "pass") for take in group]
        warnings = sum(
            len(set(take.get("warnings", [])) | set(take.get("audioQC", {}).get("warningCodes", [])))
            for take in group
        )
        trim_values = [int(take.get("metrics", {}).get("maximumTrimLevel", 0)) for take in group]
        thermal = [take.get("thermalState", "nominal") for take in group]
        thermal_rank = {"nominal": 0, "fair": 1, "serious": 2, "critical": 3, "unknown": 4}
        cells.append({
            "key": key,
            "mode": first.get("mode", "not-applicable"),
            "modelID": first.get("modelID", "not-applicable"),
            "variant": first.get("variant", "not-applicable"),
            "warmState": first.get("warmState", "not-applicable"),
            "length": first.get("length", "not-applicable"),
            "count": len(group),
            "status": "passedWithWarnings" if warnings or "warn" in verdicts else "passed",
            "statistics": {name: metric_summary(values) for name, values in sorted(metrics.items())},
            "worstQCVerdict": max(verdicts, key=lambda item: qc_rank.get(item, 99)),
            "worstThermalState": max(thermal, key=lambda item: thermal_rank.get(item, 99)),
            "maximumTrimLevel": max(trim_values, default=0),
            "warningCount": warnings,
        })
    return cells


def selected_evidence_digest(record: dict[str, Any]) -> str:
    evidence = record["evidence"]
    payload = {
        "kind": record.get("run", {}).get("kind"),
        "platform": record.get("run", {}).get("platform"),
        "rawTelemetryDigest": evidence.get("rawTelemetryDigest"),
        "resultBundleDigest": evidence.get("resultBundleDigest"),
        "screenshotDigests": evidence.get("screenshotDigests", []),
        "traceDigest": (evidence.get("trace") or {}).get("digest"),
        "crashDeltaPassed": evidence.get("crashDeltaPassed"),
        "crashCount": evidence.get("crashCount"),
        "takes": record.get("takes", []),
    }
    if evidence.get("languageVerification") is not None:
        payload["languageVerification"] = evidence["languageVerification"]
    if record.get("schemaVersion", 0) >= 2:
        for key in (
            "sampleSidecarsDigest", "memoryPolicyID", "retentionMetric",
            "retentionThresholdFraction", "maximumRetainedGrowthMB",
            "maximumRetainedGrowthFraction", "retentionPassed",
        ):
            if key in evidence:
                payload[key] = evidence[key]
    return sha256_bytes(canonical_bytes(payload))


def comparison_key(record: dict[str, Any]) -> str:
    comparable_identity = {
        "kind": record["run"]["kind"],
        "platform": record["run"]["platform"],
        "matrixScope": record["run"]["matrixScope"],
        "hardware": record["hardware"]["profileID"],
        "os": [record["hardware"].get("osVersion"), record["hardware"].get("osBuild")],
        "toolchain": [
            record["toolchain"].get("xcodeBuild"), record["toolchain"].get("sdkVersion"),
            record["toolchain"].get("optimization"), record["toolchain"].get("appVersion"),
            record["toolchain"].get("appBuild"),
        ],
        "matrixHash": record["inputs"]["matrixHash"],
        "inputIdentity": [
            record["inputs"].get("contractHash"),
            record["inputs"].get("dependencyLockHash"),
            record["inputs"].get("projectInputHash"),
            record["inputs"].get("harnessHash"),
            record["inputs"].get("corpusHash"),
            record["inputs"].get("analysisProfileHash"),
        ],
        "models": [
            [
                model.get("mode"), model.get("modelID"), model.get("variant"),
                model.get("quantization"), model.get("revision"), model.get("artifactVersion"),
                model.get("integrityDigest"), model.get("runtimeProfileSignature"),
                model.get("fixtureDigest"),
            ]
            for model in record.get("models", [])
        ],
        "evidenceContract": [
            record.get("schemaVersion"), record["evidence"].get("validatorSchemaVersion"),
            record["evidence"].get("telemetrySchemaVersion"),
            record["evidence"].get("qcAlgorithmVersion"),
        ],
    }
    return sha256_bytes(canonical_bytes(comparable_identity))


def apply_comparison_baseline(
    record: dict[str, Any],
    existing: list[tuple[Path, dict[str, Any]]],
) -> None:
    """Attach deterministic deltas to the nearest earlier compatible clean run."""
    record["comparison"] = expected_comparison_metadata(record, existing)
    record["digest"] = record_digest(record)


def record_is_comparable(record: dict[str, Any]) -> bool:
    return (
        record.get("source", {}).get("dirty") is False
        and record.get("source", {}).get("fingerprintsMatch") is True
        and record.get("run", {}).get("classification")
        not in {"exploratory", "instrumented", "partial"}
    )


def comparison_deltas(
    record: dict[str, Any], baseline: dict[str, Any],
) -> dict[str, dict[str, dict[str, float]]]:
    baseline_cells = {cell["key"]: cell for cell in baseline.get("cells", [])}
    deltas: dict[str, dict[str, dict[str, float]]] = {}
    for cell in record.get("cells", []):
        prior = baseline_cells.get(cell["key"])
        if not prior:
            continue
        metric_deltas: dict[str, dict[str, float]] = {}
        for metric, current_summary in cell.get("statistics", {}).items():
            prior_summary = prior.get("statistics", {}).get(metric)
            current_value = current_summary.get("median") if isinstance(current_summary, dict) else None
            prior_value = prior_summary.get("median") if isinstance(prior_summary, dict) else None
            if not isinstance(current_value, (int, float)) or not isinstance(prior_value, (int, float)):
                continue
            delta = float(current_value) - float(prior_value)
            metric_deltas[metric] = {
                "baseline": float(prior_value),
                "current": float(current_value),
                "absolute": delta,
                "percent": (delta / abs(float(prior_value)) * 100.0) if prior_value else 0.0,
            }
        if metric_deltas:
            deltas[cell["key"]] = metric_deltas
    return deltas


def expected_comparison_metadata(
    record: dict[str, Any], existing: list[tuple[Path, dict[str, Any]]],
) -> dict[str, Any]:
    """Derive comparison metadata from record content, independent of arrival order."""
    key = comparison_key(record)
    expected: dict[str, Any] = {
        "key": key,
        "comparable": record_is_comparable(record),
        "baselineRunID": None,
        "deltas": {},
    }
    if not expected["comparable"]:
        return expected
    current_order = (record["run"]["finishedAt"], record["run"]["id"])
    candidates = [
        candidate for _, candidate in existing
        if candidate.get("run", {}).get("id") != record["run"]["id"]
        and record_is_comparable(candidate)
        and comparison_key(candidate) == key
        and (candidate["run"]["finishedAt"], candidate["run"]["id"]) < current_order
    ]
    if not candidates:
        return expected
    baseline = max(candidates, key=lambda item: (item["run"]["finishedAt"], item["run"]["id"]))
    expected["baselineRunID"] = baseline["run"]["id"]
    expected["deltas"] = comparison_deltas(record, baseline)
    return expected


def build_record(manifest_path: Path) -> dict[str, Any]:
    outer = load_json(manifest_path)
    if not isinstance(outer, dict):
        raise HistoryError("benchmark-evidence.json must be an object")
    candidate = outer.get("historyRecord", outer)
    if not isinstance(candidate, dict):
        raise HistoryError("historyRecord must be an object")
    record = copy.deepcopy(candidate)
    record.setdefault("schemaVersion", SCHEMA_VERSION)

    # Accept the validator's compact top-level identity as defaults while the
    # nested historyRecord remains the tracked-record contract.
    artifact_dir = manifest_path.parent
    run = record.setdefault("run", {})
    run.setdefault("id", outer.get("runID"))
    run.setdefault("kind", outer.get("benchmarkKind"))
    run.setdefault("platform", outer.get("platform"))
    run.setdefault("status", outer.get("status"))
    run.setdefault("label", outer.get("label", run.get("id")))
    run.setdefault("matrixScope", outer.get("matrixScope", "focused"))
    run_metadata_path = artifact_dir / "run.json"
    if run_metadata_path.is_file():
        run_metadata = load_json(run_metadata_path)
        if run_metadata.get("runID") != run.get("id") or run_metadata.get("platform") != run.get("platform"):
            raise HistoryError("run.json identity does not match benchmark evidence")
        expected_lane = "perf" if run.get("kind") == "ui-perf" else "benchmark"
        if run_metadata.get("lane") != expected_lane or run_metadata.get("status") not in {"pass", "passed"}:
            raise HistoryError(f"run.json does not describe a successful {expected_lane} lane")
        if run_metadata.get("startedAt"):
            run["startedAt"] = run_metadata["startedAt"]
        if run_metadata.get("finishedAt"):
            run["finishedAt"] = run_metadata["finishedAt"]
    run["status"] = normalize_status(run.get("status"))
    run["startedAt"] = iso_timestamp(run.get("startedAt"), "run.startedAt")
    run["finishedAt"] = iso_timestamp(run.get("finishedAt"), "run.finishedAt")
    started = dt.datetime.fromisoformat(run["startedAt"].replace("Z", "+00:00"))
    finished = dt.datetime.fromisoformat(run["finishedAt"].replace("Z", "+00:00"))
    if finished < started:
        raise HistoryError("run.finishedAt precedes run.startedAt")
    run.setdefault("durationSeconds", round((finished - started).total_seconds(), 6))
    run.setdefault("warnings", [])

    source = record.setdefault("source", {})
    source_keys = {"commit", "dirty", "changedPaths", "workspaceFingerprint", "preFingerprint", "postFingerprint", "fingerprintsMatch"}
    if not source_keys.issubset(source):
        merge_missing(source, source_state_for_artifact(artifact_dir))
    if source.get("dirty"):
        run["classification"] = "exploratory"
    elif run.get("kind") == "instrument-profile":
        run["classification"] = "instrumented"
    else:
        run.setdefault("classification", run.get("matrixScope", "focused"))

    profile_id = record.setdefault("hardware", {}).get("profileID")
    profiles = load_profiles()
    if profile_id not in profiles:
        raise HistoryError(f"unknown hardware profile: {profile_id!r}")
    profile = profiles[profile_id]
    hardware_defaults = {
        key: value for key, value in profile.items()
        if key in SECTION_KEYS["hardware"] and key not in {"osVersion", "osBuild", "thermalState", "lowPowerMode", "transport"}
    }
    merge_missing(record["hardware"], hardware_defaults)
    if isinstance(outer.get("hardware"), dict):
        merge_missing(record["hardware"], outer["hardware"])
    merge_missing(record["hardware"], xcresult_runtime_hardware(artifact_dir, run["platform"]))
    merge_missing(record["hardware"], default_runtime_hardware(run["platform"], profile))

    record.setdefault("toolchain", {})
    if isinstance(outer.get("toolchain"), dict):
        merge_missing(record["toolchain"], outer["toolchain"])
    if not {"xcodeVersion", "xcodeBuild", "swiftVersion", "sdkName", "sdkVersion", "optimization", "appVersion", "appBuild", "executableUUIDs", "executableHashes"}.issubset(record["toolchain"]):
        merge_missing(record["toolchain"], default_toolchain(run["platform"], outer, artifact_dir))
    record.setdefault("takes", outer.get("takes", []))
    record.setdefault("models", [])
    if not record["models"]:
        record["models"] = default_models(record)
    record.setdefault("inputs", {})
    if not SECTION_KEYS["inputs"].issubset(record["inputs"]):
        merge_missing(record["inputs"], default_inputs(record))

    evidence = record.setdefault("evidence", {})
    outer_status = str(outer.get("status", "")).lower()
    evidence.setdefault("manifestDigest", file_digest(manifest_path))
    evidence.setdefault("validatorSchemaVersion", outer.get("schemaVersion", 1))
    evidence.setdefault("telemetrySchemaVersion", outer.get("telemetrySchemaVersion", "not-applicable"))
    evidence.setdefault("qcAlgorithmVersion", outer.get("qcAlgorithmVersion", "not-applicable"))
    evidence.setdefault("validatorPassed", outer_status in {"pass", "passed", "passedwithwarnings", "passed-with-warnings"})
    evidence.setdefault("crashDeltaPassed", outer.get("crashDeltaPassed", False))
    evidence.setdefault("crashCount", outer.get("crashCount", 0))
    evidence.setdefault("expectedTakeCount", outer.get("expectedTakeCount", len(record["takes"])))
    evidence.setdefault("actualTakeCount", outer.get("actualTakeCount", len(record["takes"])))
    if "resultBundleDigest" not in evidence:
        evidence["resultBundleDigest"] = outer.get("resultBundleDigest") or digest_xcresult_summary(artifact_dir)
    evidence.setdefault("rawTelemetryDigest", outer.get("rawTelemetryDigest", "not-applicable"))
    for key in (
        "memoryContractVersion", "memoryQualified", "sampleSidecarCount", "sampleSidecarsDigest",
        "memoryPolicyID", "retentionMetric", "retentionThresholdFraction",
        "maximumRetainedGrowthMB", "maximumRetainedGrowthFraction", "retentionPassed",
    ):
        if key not in evidence and key in outer:
            evidence[key] = outer[key]
    if "screenshotDigests" not in evidence:
        evidence["screenshotDigests"] = outer.get("screenshotDigests") or screenshot_digests(artifact_dir)
    evidence["selectedEvidenceDigest"] = selected_evidence_digest(record)

    if not record.get("cells"):
        record["cells"] = aggregate_cells(record["takes"])
    has_warning = bool(run["warnings"]) or any(
        take.get("warnings") or take.get("audioQC", {}).get("verdict") == "warn"
        or take.get("audioQC", {}).get("warningCodes")
        for take in record["takes"]
    )
    if has_warning:
        run["status"] = "passedWithWarnings"
    comparison = record.setdefault("comparison", {})
    comparison["key"] = comparison_key(record)
    comparison["comparable"] = (
        not source.get("dirty") and source.get("fingerprintsMatch") is True
        and run["classification"] not in {"exploratory", "instrumented", "partial"}
    )
    comparison.setdefault("baselineRunID", None)
    comparison.setdefault("deltas", {})
    record.setdefault("listening", {"status": "not-performed", "note": "", "annotatedAt": None})
    record["digest"] = record_digest(record)
    return record


def reject_unknown_keys(value: dict[str, Any], allowed: set[str], location: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise HistoryError(f"{location} contains non-allowlisted fields: {', '.join(unknown)}")


def validate_safe_scalar(value: Any, location: str) -> None:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise HistoryError(f"{location} contains a non-finite number")
        return
    if not isinstance(value, str):
        raise HistoryError(f"{location} contains an unsupported value type")
    if "\n" in value or "\r" in value:
        raise HistoryError(f"{location} contains a newline")
    if EMAIL_RE.search(value) or URL_RE.search(value):
        raise HistoryError(f"{location} contains an email address or URL")
    if SECRET_RE.search(value):
        raise HistoryError(f"{location} contains a secret-like token")
    if "../" in value or "..\\" in value:
        raise HistoryError(f"{location} contains path traversal")
    if value.startswith(("/", "~/", "\\\\")) or WINDOWS_PATH_RE.match(value):
        raise HistoryError(f"{location} contains an absolute path")
    if "/Users/" in value or "/var/folders/" in value or "/private/" in value:
        raise HistoryError(f"{location} contains a local path")


def privacy_scan(value: Any, location: str = "record") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                raise HistoryError(f"{location}.{key} is a prohibited privacy field")
            privacy_scan(child, f"{location}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            privacy_scan(child, f"{location}[{index}]")
    else:
        validate_safe_scalar(value, location)


def require_digest(value: Any, location: str, *, allow_na: bool = True) -> None:
    if allow_na and value == "not-applicable":
        return
    if not isinstance(value, str) or not HEX_64.fullmatch(value):
        raise HistoryError(f"{location} must be a SHA-256 digest")


def validate_machine_codes(values: Any, location: str) -> None:
    if not isinstance(values, list) or not all(
        isinstance(value, str) and SAFE_WARNING_RE.fullmatch(value) for value in values
    ):
        raise HistoryError(f"{location} must contain privacy-safe machine warning codes")
    if len(values) != len(set(values)):
        raise HistoryError(f"{location} contains duplicate warning codes")


def validate_model_identity_for_take(
    take: dict[str, Any], model_lookup: dict[tuple[str, str], dict[str, Any]],
) -> None:
    identity_fields = {
        "mode", "variant", "modelRepository", "modelRevision", "modelArtifactVersion",
        "modelQuantization", "modelIntegrityDigest", "runtimeProfileSignature", "fixtureDigest",
    }
    if missing := sorted(identity_fields - set(take)):
        raise HistoryError(f"generation take is missing typed model identity: {', '.join(missing)}")
    model = model_lookup.get((take["mode"], take["variant"]))
    if model is None:
        raise HistoryError("generation take has no matching model record")
    expected_identity = {
        "modelRepository": model["modelID"],
        "modelRevision": model["revision"],
        "modelArtifactVersion": str(model["artifactVersion"]),
        "modelQuantization": model["quantization"],
        "modelIntegrityDigest": model["integrityDigest"],
        "runtimeProfileSignature": model["runtimeProfileSignature"],
        "fixtureDigest": model["fixtureDigest"],
    }
    for field, expected in expected_identity.items():
        if str(take.get(field)) != str(expected):
            raise HistoryError(f"generation take {field} does not match its model record")


def validate_telemetry_overhead_semantics(
    record: dict[str, Any], model_lookup: dict[tuple[str, str], dict[str, Any]],
) -> None:
    run = record["run"]
    takes = record["takes"]
    evidence = record["evidence"]
    if run["platform"] != "macos" or run["matrixScope"] != "focused":
        raise HistoryError("telemetry-overhead must be a focused macOS benchmark")
    expected_schema = 7 if record.get("schemaVersion") == 1 else 8
    if evidence.get("telemetrySchemaVersion") != expected_schema or evidence.get("qcAlgorithmVersion") != "not-applicable":
        raise HistoryError(
            f"telemetry-overhead requires schema-v{expected_schema} telemetry and no audio-QC version"
        )
    if len(record["models"]) != 1:
        raise HistoryError("telemetry-overhead requires one exact Custom Speed model")
    model = record["models"][0]
    if model.get("mode") != "custom" or model.get("variant") != "speed":
        raise HistoryError("telemetry-overhead model must be Custom Speed")
    rotations = (
        ("off", "lightweight", "verbose"),
        ("lightweight", "verbose", "off"),
        ("verbose", "off", "lightweight"),
    )
    expected_cells = [
        f"rotation-{rotation}/order-{order}/{mode}/take-{measured}"
        for rotation, modes in enumerate(rotations, start=1)
        for order, mode in enumerate(modes, start=1)
        for measured in range(1, 3)
    ]
    if len(takes) != 18 or [take.get("cell") for take in takes] != expected_cells:
        raise HistoryError("telemetry-overhead requires the exact ordered 18-take rotation matrix")
    required_metrics = {
        "rtf", "ttfcMS", "audioSeconds", "loadAverage1M", "freeStorageBytes",
        "uptimeSeconds", "lowPowerMode",
    }
    metrics_by_mode: dict[str, dict[str, list[float]]] = {
        mode: {"rtf": [], "ttfcMS": []} for mode in ("off", "lightweight", "verbose")
    }
    pcm_by_mode: dict[str, dict[tuple[int, int], str]] = {
        mode: {} for mode in metrics_by_mode
    }
    for take, cell in zip(takes, expected_cells):
        validate_model_identity_for_take(take, model_lookup)
        if (
            take.get("mode") != "custom" or take.get("modelID") != "pro_custom_speed"
            or take.get("variant") != "speed" or take.get("warmState") != "warm"
            or take.get("length") != "medium" or take.get("finishReason") != "completed"
        ):
            raise HistoryError("telemetry-overhead take identity is not exact")
        if not required_metrics.issubset(take["metrics"]):
            raise HistoryError("telemetry-overhead take lacks timing or machine context")
        if (
            take["metrics"]["rtf"] <= 0 or take["metrics"]["ttfcMS"] < 0
            or take["metrics"]["audioSeconds"] <= 0
        ):
            raise HistoryError("telemetry-overhead take contains invalid timing")
        if take.get("thermalState") not in {"nominal", "fair", "serious", "critical", "unknown"}:
            raise HistoryError("telemetry-overhead take lacks bounded thermal context")
        parts = cell.split("/")
        rotation = int(parts[0].removeprefix("rotation-"))
        telemetry_mode = parts[2]
        measured = int(parts[3].removeprefix("take-"))
        metrics_by_mode[telemetry_mode]["rtf"].append(float(take["metrics"]["rtf"]))
        metrics_by_mode[telemetry_mode]["ttfcMS"].append(float(take["metrics"]["ttfcMS"]))
        output = take.get("output")
        if not isinstance(output, dict) or output.get("readableWAV") is not True or output.get("atomicPublish") is not True:
            raise HistoryError("telemetry-overhead take lacks readable atomic PCM evidence")
        require_digest(output.get("fileDigest"), "telemetry-overhead output.fileDigest", allow_na=False)
        if output.get("durationSeconds") != take["metrics"]["audioSeconds"]:
            raise HistoryError("telemetry-overhead output duration does not match measured audio")
        pcm_by_mode[telemetry_mode][(rotation, measured)] = output["fileDigest"]
    if any(pcm_by_mode[mode] != pcm_by_mode["off"] for mode in ("lightweight", "verbose")):
        raise HistoryError("telemetry-overhead PCM parity does not match across modes")
    baseline_rtf = statistics.median(metrics_by_mode["off"]["rtf"])
    baseline_ttfc = statistics.median(metrics_by_mode["off"]["ttfcMS"])
    for mode, limit in (("lightweight", 5.0), ("verbose", 10.0)):
        candidate_rtf = statistics.median(metrics_by_mode[mode]["rtf"])
        candidate_ttfc = statistics.median(metrics_by_mode[mode]["ttfcMS"])
        rtf_regression = 0.0 if baseline_rtf <= 0 else (1.0 - candidate_rtf / baseline_rtf) * 100.0
        ttfc_regression = 0.0 if baseline_ttfc <= 0 else (candidate_ttfc / baseline_ttfc - 1.0) * 100.0
        if rtf_regression > limit or ttfc_regression > limit:
            raise HistoryError(f"telemetry-overhead {mode} exceeds its tracked overhead threshold")


def validate_prosody_semantics(record: dict[str, Any]) -> None:
    run = record["run"]
    if run["platform"] != "macos" or run["matrixScope"] != "focused":
        raise HistoryError("prosody calibration must be a focused macOS benchmark")
    if record["models"]:
        raise HistoryError("prosody calibration must not claim a generation model")
    if (
        record["evidence"].get("telemetrySchemaVersion") != "not-applicable"
        or record["evidence"].get("qcAlgorithmVersion") != "not-applicable"
    ):
        raise HistoryError("prosody calibration must not claim generation telemetry or audio-QC")
    if len(record["takes"]) != 1:
        raise HistoryError("prosody calibration requires one aggregate analysis take")
    take = record["takes"][0]
    expected_identity = {
        "cell": "prosody-calibration/corpus",
        "generationID": f"{run['id']}-analysis",
        "mode": "not-applicable", "modelID": "not-applicable",
        "variant": "not-applicable", "warmState": "not-applicable",
        "length": "not-applicable", "finishReason": "completed",
    }
    if any(take.get(key) != value for key, value in expected_identity.items()):
        raise HistoryError("prosody calibration take identity is not exact")
    required_metrics = {
        "goodClipCount", "badClipCount", "targetFalsePositiveRate",
        "observedFalsePositiveRate", "observedTruePositiveRate", "goodFlagRate", "badFlagRate",
        "monotoneF0StdThresholdHz", "monotoneTurningPointsThresholdPerSecond",
        "rushedSyllableRateThresholdHz", "rushedMaximumPauseRatio",
        "flatEnvelopeRoughnessThreshold", "flatRateCVThreshold",
        "maximumPauseThresholdSeconds", "maximumPauseRatioThreshold",
    }
    if set(take["metrics"]) != required_metrics:
        raise HistoryError("prosody calibration aggregate metrics are incomplete")
    for name in ("goodClipCount", "badClipCount"):
        value = take["metrics"][name]
        if value < 2 or float(value).is_integer() is False:
            raise HistoryError("prosody calibration requires at least two clips per class")
    for name in (
        "targetFalsePositiveRate", "observedFalsePositiveRate", "observedTruePositiveRate",
        "goodFlagRate", "badFlagRate", "rushedMaximumPauseRatio", "maximumPauseRatioThreshold",
    ):
        if not 0 <= take["metrics"][name] <= 1:
            raise HistoryError(f"prosody calibration metric {name} is outside [0, 1]")
    require_digest(record["inputs"].get("corpusHash"), "inputs.corpusHash", allow_na=False)
    require_digest(record["inputs"].get("analysisProfileHash"), "inputs.analysisProfileHash", allow_na=False)


def validate_ui_perf_semantics(record: dict[str, Any]) -> None:
    """ui-perf (UI-7 macOS, IUI-6 platform-aware): one frame-health take per
    scenario, no model, engine-telemetry, or audio-QC claims — the probe
    measures main-run-loop cadence, not generation. Threshold breaches are
    warn-only and surface as take/run warnings, never as a failed status."""
    run = record["run"]
    expected_scenarios = UI_PERF_SCENARIOS_BY_PLATFORM.get(run.get("platform"))
    if expected_scenarios is None or run.get("matrixScope") != "canonical":
        raise HistoryError("ui-perf must be a canonical-matrix macOS or iOS benchmark")
    if record.get("models"):
        raise HistoryError("ui-perf must not claim a generation model")
    if (
        record["evidence"].get("telemetrySchemaVersion") != "not-applicable"
        or record["evidence"].get("qcAlgorithmVersion") != "not-applicable"
    ):
        raise HistoryError("ui-perf must not claim generation telemetry or audio-QC")
    takes = record["takes"]
    scenarios = [str(take.get("cell", "")).removeprefix("ui-perf/") for take in takes]
    if len(takes) != len(expected_scenarios) or set(scenarios) != expected_scenarios:
        raise HistoryError("ui-perf requires exactly one take per probe scenario")
    for take, scenario in zip(takes, scenarios):
        expected_identity = {
            "cell": f"ui-perf/{scenario}",
            "generationID": f"{run['id']}-{scenario}",
            "mode": "not-applicable", "modelID": "not-applicable",
            "variant": "not-applicable", "warmState": "not-applicable",
            "length": "not-applicable", "finishReason": "completed",
        }
        if any(take.get(key) != value for key, value in expected_identity.items()):
            raise HistoryError(f"ui-perf take identity is not exact for {scenario}")
        metrics = take["metrics"]
        if missing := sorted(UI_PERF_REQUIRED_METRICS - set(metrics)):
            raise HistoryError(f"ui-perf {scenario} metrics are incomplete: {', '.join(missing)}")
        if not 0.9 <= metrics["uiProbeCoverage"] <= 1.0:
            raise HistoryError(f"ui-perf {scenario} probe coverage is outside [0.9, 1.0]")
        if not 1000.0 / 140.0 <= metrics["uiRefreshIntervalMS"] <= 1000.0 / 30.0:
            raise HistoryError(f"ui-perf {scenario} refresh interval is outside the 30-140 Hz band")
        if metrics["uiHitchTimeMSPerS"] < 0 or metrics["uiMaxGapMS"] < 0:
            raise HistoryError(f"ui-perf {scenario} frame-health metrics are negative")


def _safe_build_artifact_path(value: Any, *, suffix: str, location: str) -> PurePosixPath:
    path = PurePosixPath(value) if isinstance(value, str) else None
    if (
        path is None or path.is_absolute() or ".." in path.parts
        or not path.parts or path.parts[0] != "build" or path.suffix != suffix
    ):
        raise HistoryError(f"{location} must be a safe build-relative {suffix} path")
    return path


def validate_trace_retention(record: dict[str, Any], trace: dict[str, Any]) -> None:
    """Validate the summary-only retention contract for newly published traces.

    Older v1/v2 records predate this metadata and remain read-only compatible.
    Schema v3 adds quality identity and preserves the v2 retention contract.
    Once a record carries any retention field, however, all fields are required
    so a raw trace path can never be mistaken for proof that the trace remains.
    """

    present = TRACE_RETENTION_KEYS.intersection(trace)
    if not present:
        return
    if record.get("schemaVersion") not in {2, 3}:
        raise HistoryError("trace-retention metadata requires benchmark history schema v2 or v3")
    if missing := sorted(TRACE_RETENTION_KEYS - set(trace)):
        raise HistoryError("trace-retention metadata is incomplete: " + ", ".join(missing))

    original = _safe_build_artifact_path(
        trace["originalEphemeralPath"], suffix=".trace",
        location="evidence.trace.originalEphemeralPath",
    )
    summary = trace.get("summary")
    if not isinstance(summary, dict) or summary.get("artifact") != original.as_posix():
        raise HistoryError("trace summary artifact must match the original ephemeral trace path")

    retention_policy = trace["retentionPolicy"]
    expected_raw_retained = {
        "summaryOnly": False,
        "keptExplicitly": True,
    }.get(retention_policy)
    if expected_raw_retained is None:
        raise HistoryError("trace retentionPolicy is unsupported")
    if trace["rawTraceRetained"] is not expected_raw_retained:
        raise HistoryError("trace rawTraceRetained conflicts with its retentionPolicy")

    summary_artifact = trace["summaryArtifact"]
    if not isinstance(summary_artifact, dict):
        raise HistoryError("trace summaryArtifact must be an object")
    reject_unknown_keys(
        summary_artifact, TRACE_SUMMARY_ARTIFACT_KEYS, "evidence.trace.summaryArtifact"
    )
    if missing := sorted(TRACE_SUMMARY_ARTIFACT_KEYS - set(summary_artifact)):
        raise HistoryError("trace summaryArtifact is missing: " + ", ".join(missing))
    summary_path = _safe_build_artifact_path(
        summary_artifact["path"], suffix=".json",
        location="evidence.trace.summaryArtifact.path",
    )
    if original == summary_path or original in summary_path.parents:
        raise HistoryError("trace summaryArtifact must live outside the ephemeral trace bundle")
    require_digest(
        summary_artifact["digest"], "evidence.trace.summaryArtifact.digest", allow_na=False
    )

    capture_settings = trace["captureSettings"]
    if not isinstance(capture_settings, dict):
        raise HistoryError("trace captureSettings must be an object")
    reject_unknown_keys(
        capture_settings, TRACE_CAPTURE_SETTINGS_KEYS, "evidence.trace.captureSettings"
    )
    if missing := sorted(TRACE_CAPTURE_SETTINGS_KEYS - set(capture_settings)):
        raise HistoryError("trace captureSettings is missing: " + ", ".join(missing))
    if capture_settings["profileKind"] not in {"cpu", "memory"}:
        raise HistoryError("trace captureSettings.profileKind is unsupported")
    if capture_settings["template"] != trace.get("template"):
        raise HistoryError("trace captureSettings.template does not match trace.template")
    if capture_settings["targetProcess"] != summary.get("targetProcess"):
        raise HistoryError("trace captureSettings.targetProcess does not match trace summary")
    if capture_settings["exactPID"] is not True:
        raise HistoryError("trace captureSettings must identify exact-PID attachment")
    requested_duration = capture_settings["requestedDurationSeconds"]
    if (
        isinstance(requested_duration, bool)
        or not isinstance(requested_duration, (int, float))
        or not math.isfinite(float(requested_duration))
        or requested_duration <= 0
        or float(requested_duration) != float(trace.get("durationSeconds", -1))
    ):
        raise HistoryError("trace capture duration does not match validated trace evidence")
    memory_profile = "allocations" in str(trace.get("template", "")).lower()
    expected_kind = "memory" if memory_profile else "cpu"
    if capture_settings["profileKind"] != expected_kind:
        raise HistoryError("trace captureSettings.profileKind conflicts with its template")
    require_digest(
        trace["captureSettingsDigest"], "evidence.trace.captureSettingsDigest", allow_na=False
    )
    if trace["captureSettingsDigest"] != sha256_bytes(canonical_bytes(capture_settings)):
        raise HistoryError("trace captureSettingsDigest does not match captureSettings")


def validate_trace_summary(record: dict[str, Any]) -> None:
    trace = record["evidence"].get("trace")
    if not isinstance(trace, dict):
        raise HistoryError("instrument-profile evidence requires a validated trace")
    validate_trace_retention(record, trace)
    summary = trace.get("summary")
    if not isinstance(summary, dict):
        raise HistoryError("instrument-profile requires a structured trace summary")
    reject_unknown_keys(summary, TRACE_SUMMARY_KEYS, "evidence.trace.summary")
    required = SCHEMA_REQUIRED_KEYS["traceSummary"]
    if missing := sorted(required - set(summary)):
        raise HistoryError(f"trace summary is missing: {', '.join(missing)}")
    artifact = summary["artifact"]
    artifact_path = PurePosixPath(artifact) if isinstance(artifact, str) else None
    if (
        artifact_path is None or artifact_path.is_absolute() or ".." in artifact_path.parts
        or not artifact.startswith("build/") or not artifact.endswith(".trace")
    ):
        raise HistoryError("trace summary artifact must be a safe build-relative trace path")
    count_fields = {
        "capturedDataRowCount", "cpuSampleCount", "processCount", "schemaCount",
        "signpostEventCount", "signpostSchemaCount", "tableCount",
    }
    if any(
        not isinstance(summary[name], int) or isinstance(summary[name], bool) or summary[name] <= 0
        for name in count_fields
    ):
        raise HistoryError("trace summary contains an empty count")
    if summary["correlatedSignpostEventCount"] < len(record["takes"]):
        raise HistoryError("trace summary lacks one correlated signpost per take")
    if summary["correlationFieldsVerified"] is not True or summary["targetPIDVerified"] is not True:
        raise HistoryError("trace summary did not verify correlation fields and target PID")
    rows = summary["capturedRowsBySchema"]
    if not isinstance(rows, dict) or not rows:
        raise HistoryError("trace summary lacks captured schema rows")
    if any(
        not isinstance(name, str) or not SAFE_LABEL_RE.fullmatch(name)
        or not isinstance(value, int) or isinstance(value, bool) or value < 0
        for name, value in rows.items()
    ):
        raise HistoryError("trace summary schema-row counts are invalid")
    if not any(rows.values()):
        raise HistoryError("trace summary contains no target-process schema rows")
    memory_profile = (
        record.get("schemaVersion", 0) >= 2
        and "allocations" in str(trace.get("template", "")).lower()
    )
    if memory_profile:
        evidence_version = summary.get("memoryTraceEvidenceVersion")
        if evidence_version == 2:
            if missing := sorted(MEMORY_TRACE_V2_SUMMARY_KEYS - set(summary)):
                raise HistoryError(
                    "memory trace summary is missing v2 track evidence: " + ", ".join(missing)
                )
            legacy_only = LEGACY_MEMORY_TRACE_SUMMARY_KEYS - {"allocationTargetDataBytes"}
            if legacy_only.intersection(summary):
                raise HistoryError("memory trace summary mixes legacy verified flags with v2 evidence")
            presence_fields = {
                "allocationTrackPresent", "allocationListPresent",
                "vmTrackerTrackPresent", "vmTrackerRegionMapPresent",
            }
            if any(summary[name] is not True for name in presence_fields):
                raise HistoryError("memory trace summary is missing configured memory tracks")
            allocation_schemas = {
                name: count for name, count in rows.items()
                if "allocation" in name.lower()
            }
            vm_schemas = {
                name: count for name, count in rows.items()
                if (
                    name.lower().startswith("vm")
                    or "vm-tracker" in name.lower()
                    or "vm_tracker" in name.lower()
                    or "virtual-memory" in name.lower()
                    or "virtual_memory" in name.lower()
                )
            }

            def validate_export(
                *, label: str, status_key: str, count_key: str,
                schema_rows: dict[str, int],
            ) -> None:
                status = summary[status_key]
                count = summary[count_key]
                if (
                    status not in {"targetRows", "notExportable"}
                    or not isinstance(count, int) or isinstance(count, bool) or count < 0
                ):
                    raise HistoryError(f"memory trace summary has invalid {label} export evidence")
                exported_count = sum(schema_rows.values())
                if status == "targetRows":
                    if not schema_rows or count <= 0 or count != exported_count:
                        raise HistoryError(
                            f"memory trace summary lacks exact-PID {label} exported rows"
                        )
                elif schema_rows or count != 0:
                    raise HistoryError(
                        f"memory trace summary misclassifies exportable {label} data"
                    )

            validate_export(
                label="Allocations", status_key="allocationDataExportStatus",
                count_key="allocationTargetRowCount", schema_rows=allocation_schemas,
            )
            validate_export(
                label="VM Tracker", status_key="vmTrackerDataExportStatus",
                count_key="vmTrackerTargetRowCount", schema_rows=vm_schemas,
            )
        else:
            # Read-only compatibility for v2 records published before explicit
            # export-status evidence replaced the ambiguous `Verified` flags.
            v2_only_fields = MEMORY_TRACE_V2_SUMMARY_KEYS - {"allocationTargetDataBytes"}
            if v2_only_fields.intersection(summary):
                raise HistoryError("memory trace summary has v2 fields without evidence version 2")
            if missing := sorted(LEGACY_MEMORY_TRACE_SUMMARY_KEYS - set(summary)):
                raise HistoryError(
                    "memory trace summary is missing legacy track evidence: " + ", ".join(missing)
                )
            legacy_flags = LEGACY_MEMORY_TRACE_SUMMARY_KEYS - {"allocationTargetDataBytes"}
            if any(summary[name] is not True for name in legacy_flags):
                raise HistoryError("legacy memory trace summary did not verify both memory tracks")
        allocation_bytes = summary["allocationTargetDataBytes"]
        if (
            isinstance(allocation_bytes, bool)
            or not isinstance(allocation_bytes, int)
            or allocation_bytes <= 0
        ):
            raise HistoryError("memory trace summary contains no exact-PID allocation data")
    elif (LEGACY_MEMORY_TRACE_SUMMARY_KEYS | MEMORY_TRACE_V2_SUMMARY_KEYS).intersection(summary):
        raise HistoryError("CPU-only trace summary contains memory-profile evidence")
    if not isinstance(summary["targetProcess"], str) or not SAFE_LABEL_RE.fullmatch(summary["targetProcess"]):
        raise HistoryError("trace summary target process is not a safe identifier")
    require_digest(summary["tocDigest"], "evidence.trace.summary.tocDigest", allow_na=False)
    cpu_rows = sum(rows.get(name, 0) for name in ("cpu-profile", "time-profile"))
    signpost_rows = sum(value for name, value in rows.items() if "signpost" in name)
    if cpu_rows != summary["cpuSampleCount"] or signpost_rows != summary["signpostEventCount"]:
        raise HistoryError("trace summary row counts do not match CPU/signpost totals")
    if sum(rows.values()) != summary["capturedDataRowCount"]:
        raise HistoryError("trace summary captured-row total is inconsistent")
    if not isinstance(summary["cpuSampleSpanMS"], (int, float)) or summary["cpuSampleSpanMS"] <= 0:
        raise HistoryError("trace summary CPU sample span is empty")
    weight = summary.get("cpuCycleWeight", summary.get("cpuSampleWeightMS"))
    if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
        raise HistoryError("trace summary lacks positive CPU sample weight")


def validate_record(
    record: dict[str, Any], *, expected_path: Path | None = None,
    schema: dict[str, Any] | None = None,
) -> None:
    if not isinstance(record, dict):
        raise HistoryError("record must be a JSON object")
    version = record.get("schemaVersion")
    if version not in SUPPORTED_SCHEMA_VERSIONS:
        raise HistoryError(f"unsupported benchmark history schema: {version!r}")
    selected_schema = schema
    if (
        selected_schema is None
        or selected_schema.get("properties", {}).get("schemaVersion", {}).get("const") != version
    ):
        selected_schema = load_schema_contract(version)
    validate_record_against_schema(record, selected_schema)
    reject_unknown_keys(record, TOP_LEVEL_KEYS, "record")
    privacy_scan(record)

    for section in ("run", "hardware", "source", "toolchain", "inputs", "evidence", "comparison", "listening"):
        payload = record.get(section)
        if not isinstance(payload, dict):
            raise HistoryError(f"{section} must be an object")
        allowed = SECTION_KEYS[section]
        if version == 1 and section == "evidence":
            allowed = allowed - V2_ONLY_EVIDENCE_KEYS
        reject_unknown_keys(payload, allowed, section)

    run = record["run"]
    required_run = {"id", "kind", "platform", "label", "startedAt", "finishedAt", "durationSeconds", "status", "matrixScope", "classification", "warnings"}
    if missing := sorted(required_run - set(run)):
        raise HistoryError(f"run is missing: {', '.join(missing)}")
    if not isinstance(run["id"], str) or not RUN_ID_RE.fullmatch(run["id"]):
        raise HistoryError("run.id is not filesystem-safe")
    if not isinstance(run["label"], str) or not SAFE_LABEL_RE.fullmatch(run["label"]):
        raise HistoryError("run.label must be a privacy-safe opaque identifier")
    allowed_kinds = V2_KINDS if version >= 2 else V1_KINDS
    if run["kind"] not in allowed_kinds or run["platform"] not in PLATFORMS:
        raise HistoryError("run kind or platform is unsupported")
    if run["status"] not in SUCCESS_STATUSES:
        raise HistoryError("only successful benchmark runs may be tracked")
    if run["matrixScope"] not in MATRIX_SCOPES or run["classification"] not in CLASSIFICATIONS:
        raise HistoryError("run scope or classification is unsupported")
    iso_timestamp(run["startedAt"], "run.startedAt")
    iso_timestamp(run["finishedAt"], "run.finishedAt")
    if not isinstance(run["durationSeconds"], (int, float)) or run["durationSeconds"] < 0:
        raise HistoryError("run.durationSeconds must be non-negative")
    validate_machine_codes(run["warnings"], "run.warnings")

    profiles = load_profiles()
    hardware = record["hardware"]
    profile = profiles.get(hardware.get("profileID"))
    if not profile or profile["platform"] != run["platform"]:
        raise HistoryError("hardware profile is missing or belongs to another platform")
    for key in ("modelIdentifier", "marketingName", "chip", "memoryBytes"):
        if hardware.get(key) != profile.get(key):
            raise HistoryError(f"hardware.{key} does not match the canonical profile")
    for key in SECTION_KEYS["hardware"]:
        if key not in hardware:
            raise HistoryError(f"hardware is missing: {key}")

    source = record["source"]
    for key in ("commit", "dirty", "changedPaths", "workspaceFingerprint", "preFingerprint", "postFingerprint", "fingerprintsMatch"):
        if key not in source:
            raise HistoryError(f"source is missing: {key}")
    if not re.fullmatch(r"[0-9a-f]{40}", str(source["commit"])):
        raise HistoryError("source.commit must be a full Git SHA")
    for key in ("workspaceFingerprint", "preFingerprint", "postFingerprint"):
        require_digest(source[key], f"source.{key}", allow_na=False)
    if not isinstance(source["changedPaths"], list):
        raise HistoryError("source.changedPaths must be a list")
    for changed in source["changedPaths"]:
        if not isinstance(changed, str) or PurePosixPath(changed).is_absolute() or ".." in PurePosixPath(changed).parts:
            raise HistoryError("source.changedPaths must contain safe repository-relative paths")
    if source["dirty"] and run["classification"] != "exploratory":
        raise HistoryError("dirty-source records must be exploratory")
    if not source["fingerprintsMatch"] and record["comparison"].get("comparable"):
        raise HistoryError("a source-changing run cannot be comparable")

    required_toolchain = {"xcodeVersion", "xcodeBuild", "swiftVersion", "sdkName", "sdkVersion", "optimization", "appVersion", "appBuild", "executableUUIDs", "executableHashes"}
    if missing := sorted(required_toolchain - set(record["toolchain"])):
        raise HistoryError(f"toolchain is missing: {', '.join(missing)}")
    if not isinstance(record["toolchain"]["executableUUIDs"], dict) or not isinstance(record["toolchain"]["executableHashes"], dict):
        raise HistoryError("executable identities must be objects")
    for key, digest in record["toolchain"]["executableHashes"].items():
        validate_safe_scalar(key, "toolchain.executableHashes key")
        require_digest(digest, f"toolchain.executableHashes.{key}")

    for key in SECTION_KEYS["inputs"]:
        if key not in record["inputs"]:
            raise HistoryError(f"inputs is missing: {key}")
        require_digest(record["inputs"][key], f"inputs.{key}")

    models = record.get("models")
    if not isinstance(models, list):
        raise HistoryError("models must be a list")
    for index, model in enumerate(models):
        if not isinstance(model, dict):
            raise HistoryError(f"models[{index}] must be an object")
        reject_unknown_keys(model, MODEL_KEYS, f"models[{index}]")
        required = {"mode", "modelID", "variant", "quantization", "revision", "artifactVersion", "integrityDigest", "runtimeProfileSignature", "fixtureDigest"}
        if missing := sorted(required - set(model)):
            raise HistoryError(f"models[{index}] is missing: {', '.join(missing)}")
        require_digest(model["integrityDigest"], f"models[{index}].integrityDigest")
        require_digest(model["fixtureDigest"], f"models[{index}].fixtureDigest")
    model_lookup = {
        (model["mode"], model["variant"]): model
        for model in models
    }

    takes = record.get("takes")
    if not isinstance(takes, list):
        raise HistoryError("takes must be a list")
    generation_kind = run["kind"] in {
        "ui-generation", "engine-generation", "instrument-profile", "language",
        "memory-qualification",
    }
    if generation_kind and not takes:
        raise HistoryError("generation benchmarks require at least one take")
    seen_generations: set[str] = set()
    for position, take in enumerate(takes, start=1):
        if not isinstance(take, dict):
            raise HistoryError(f"takes[{position - 1}] must be an object")
        allowed_take_keys = set(TAKE_KEYS)
        if version < 2:
            allowed_take_keys -= V2_ONLY_TAKE_KEYS
        if version < 3:
            allowed_take_keys -= V3_ONLY_TAKE_KEYS
        reject_unknown_keys(take, allowed_take_keys, f"takes[{position - 1}]")
        required = {"takeIndex", "generationID", "cell", "status", "metrics", "warnings"}
        if missing := sorted(required - set(take)):
            raise HistoryError(f"takes[{position - 1}] is missing: {', '.join(missing)}")
        if take["takeIndex"] != position:
            raise HistoryError("take indices must be contiguous and one-based")
        if "seed" in take and (
            isinstance(take["seed"], bool)
            or not isinstance(take["seed"], int)
            or not 0 <= take["seed"] <= (1 << 64) - 1
        ):
            raise HistoryError("take.seed must be an unsigned 64-bit integer")
        if "accuracyMetric" in take or "accuracyThreshold" in take:
            if (
                take.get("accuracyMetric") not in {"wordErrorRate", "characterErrorRate"}
                or not isinstance(take.get("accuracyThreshold"), (int, float))
                or isinstance(take.get("accuracyThreshold"), bool)
                or not math.isfinite(float(take["accuracyThreshold"]))
                or not 0 <= float(take["accuracyThreshold"]) <= 1
            ):
                raise HistoryError("take accuracy gate is invalid")
        generation_id = take["generationID"]
        if (
            not isinstance(generation_id, str) or not SAFE_GENERATION_RE.fullmatch(generation_id)
            or generation_id in seen_generations
        ):
            raise HistoryError("generation IDs must be privacy-safe and unique")
        seen_generations.add(generation_id)
        if not isinstance(take["cell"], str) or not SAFE_CELL_RE.fullmatch(take["cell"]):
            raise HistoryError("take cell must be a privacy-safe machine identifier")
        if take["status"] not in SUCCESS_STATUSES:
            raise HistoryError("tracked takes must be successful")
        if version >= 3:
            validate_take_quality_identity(take, position, generation_kind=generation_kind)
        playback_source = take.get("playbackStartSource")
        if playback_source is not None and playback_source not in {"liveStream", "finalFile"}:
            raise HistoryError("take playbackStartSource is invalid")
        if version >= 2 and run["kind"] == "ui-generation" and playback_source is None:
            raise HistoryError("schema-v2 UI take has no typed playback start source")
        if version >= 2 and run["kind"] in MEMORY_QUALIFIED_KINDS:
            if take.get("memoryStatus") not in {"qualified", "qualifiedWithWarnings"}:
                raise HistoryError("memory-qualified take has no qualification status")
            require_digest(
                take.get("sampleSidecarDigest"), "take.sampleSidecarDigest", allow_na=False
            )
        if not isinstance(take["metrics"], dict):
            raise HistoryError("take.metrics must be an object")
        reject_unknown_keys(take["metrics"], METRIC_KEYS, "take.metrics")
        for metric, value in take["metrics"].items():
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
                raise HistoryError(f"take metric {metric} must be finite numeric data")
        if version >= 2 and run["kind"] in MEMORY_QUALIFIED_KINDS:
            required_memory = set(MEMORY_REQUIRED_METRICS)
            if run["platform"] == "ios":
                required_memory |= IOS_MEMORY_REQUIRED_METRICS
            if run["kind"] == "ui-generation" and run["platform"] == "macos":
                required_memory |= MACOS_UI_MEMORY_REQUIRED_METRICS
            if missing := sorted(required_memory - set(take["metrics"])):
                raise HistoryError(
                    "memory-qualified take metrics are incomplete: " + ", ".join(missing)
                )
            metrics = take["metrics"]
            if not 0.95 <= float(metrics["samplerCoverage"]) <= 1:
                raise HistoryError("memory sampler coverage is outside [0.95, 1]")
            for coverage_key in (
                "alignedProcessSampleCoverage",
                "alignedEngineSampleCoverage",
                "alignedAppSampleCoverage",
            ):
                if coverage_key in metrics and not 0.95 <= float(metrics[coverage_key]) <= 1:
                    raise HistoryError(
                        f"{coverage_key} is outside the qualified range [0.95, 1]"
                    )
            if any(metrics[key] != 0 for key in (
                "samplerCaptureFailureCount", "memoryWarningCount", "memoryExitCount",
            )):
                raise HistoryError("memory-qualified take contains a capture failure or memory exit")
            if metrics["maximumPressureLevel"] > 1 or metrics["maximumTrimLevel"] > 1:
                raise HistoryError("memory-qualified take reached a hard memory-pressure action")
            has_memory_warning = any(
                warning.startswith("memory.") for warning in take.get("warnings", [])
            )
            expected_memory_status = "qualifiedWithWarnings" if has_memory_warning else "qualified"
            if take["memoryStatus"] != expected_memory_status:
                raise HistoryError("take memory status does not match its memory warnings")
        if "accuracyMetric" in take:
            metrics = take["metrics"]
            if missing := sorted(LANGUAGE_ACCURACY_METRIC_KEYS - set(metrics)):
                raise HistoryError(
                    "language accuracy metrics are incomplete: " + ", ".join(missing)
                )
            selected_score = metrics[take["accuracyMetric"]]
            if (
                not math.isclose(float(take["accuracyThreshold"]), 0.15, rel_tol=0, abs_tol=1e-12)
                or not math.isclose(
                    float(metrics["accuracyThreshold"]), float(take["accuracyThreshold"]),
                    rel_tol=0, abs_tol=1e-12,
                )
                or not math.isclose(
                    float(metrics["primaryAccuracyScore"]), float(selected_score),
                    rel_tol=1e-9, abs_tol=1e-12,
                )
                or float(selected_score) > float(take["accuracyThreshold"])
                or metrics["outputLanguagePass"] != 1.0
                or metrics["outputAccuracyPass"] != 1.0
                or not 0.5 <= metrics["languageMatchScore"] <= 1.0
                or metrics["recognitionPassCount"] != 3.0
                or metrics["recognitionDurationSeconds"] <= 0
            ):
                raise HistoryError("language accuracy gate metrics are inconsistent")
            count_keys = {
                "referenceTokenCount", "hypothesisTokenCount", "referenceCharacterCount",
                "hypothesisCharacterCount", "substitutions", "insertions", "deletions",
                "characterSubstitutions", "characterInsertions", "characterDeletions",
            }
            if any(
                float(metrics[key]).is_integer() is False or metrics[key] < 0
                for key in count_keys
            ) or metrics["referenceTokenCount"] <= 0 or metrics["referenceCharacterCount"] <= 0:
                raise HistoryError("language accuracy counts are invalid")
            word_edits = sum(metrics[key] for key in ("substitutions", "insertions", "deletions"))
            character_edits = sum(metrics[key] for key in (
                "characterSubstitutions", "characterInsertions", "characterDeletions",
            ))
            if not math.isclose(
                float(metrics["wordErrorRate"]),
                float(word_edits) / float(metrics["referenceTokenCount"]),
                rel_tol=1e-9, abs_tol=1e-12,
            ) or not math.isclose(
                float(metrics["characterErrorRate"]),
                float(character_edits) / float(metrics["referenceCharacterCount"]),
                rel_tol=1e-9, abs_tol=1e-12,
            ):
                raise HistoryError("language edit rates do not match tracked counts")
        validate_machine_codes(take["warnings"], "take.warnings")
        if generation_kind:
            validate_model_identity_for_take(take, model_lookup)
            if take.get("finishReason") not in {"completed", "success"}:
                raise HistoryError("generation take did not complete")
            if take.get("layerCompleteness") != "complete":
                raise HistoryError("generation take has incomplete telemetry layers")
            output = take.get("output")
            audio_qc = take.get("audioQC")
            if not isinstance(output, dict) or not isinstance(audio_qc, dict):
                raise HistoryError("generation take requires output and audioQC evidence")
            reject_unknown_keys(output, OUTPUT_KEYS, "take.output")
            reject_unknown_keys(audio_qc, AUDIO_QC_KEYS, "take.audioQC")
            if output.get("readableWAV") is not True or output.get("atomicPublish") is not True:
                raise HistoryError("generation output is not readable and atomically published")
            if audio_qc.get("verdict") not in QC_VERDICTS:
                raise HistoryError("generation audio QC did not pass")
            if audio_qc.get("instabilityVerdict") not in QC_VERDICTS:
                raise HistoryError("generation instability QC did not pass")
            if audio_qc.get("writtenOutputVerdict") not in QC_VERDICTS:
                raise HistoryError("generation written-output QC did not pass")
            if audio_qc.get("algorithmVersion") != record["evidence"].get("qcAlgorithmVersion"):
                raise HistoryError("take audio-QC version does not match the evidence contract")
            validate_machine_codes(audio_qc.get("warningCodes"), "audioQC.warningCodes")
            if "metrics" in audio_qc:
                if not isinstance(audio_qc["metrics"], dict):
                    raise HistoryError("audioQC.metrics must be an object")
                reject_unknown_keys(audio_qc["metrics"], METRIC_KEYS, "take.audioQC.metrics")

    language_verification = record["evidence"].get("languageVerification")
    accuracy_evidence_required = any("accuracyMetric" in take for take in takes)
    if language_verification is not None:
        if not isinstance(language_verification, dict):
            raise HistoryError("evidence.languageVerification must be an object")
        reject_unknown_keys(
            language_verification, LANGUAGE_VERIFICATION_KEYS,
            "evidence.languageVerification",
        )
    expected_language_verification = {
        "outputSchemaVersion": 3,
        "outputAlgorithm": "language-output-verifier-v3",
        "recognitionSchemaVersion": 2,
        "recognitionAlgorithm": "apple-speech-file-consensus-v2",
        "accuracyMetricVersion": "normalized-edit-rate-v1",
        "requiredPassCount": 3,
    }
    if accuracy_evidence_required and (
        run["kind"] != "language" or language_verification != expected_language_verification
    ):
        raise HistoryError("language accuracy takes require exact verifier provenance")
    if language_verification is not None and run["kind"] != "language":
        raise HistoryError("language verifier provenance belongs only to language records")

    cells = record.get("cells")
    if not isinstance(cells, list):
        raise HistoryError("cells must be a list")
    for index, cell in enumerate(cells):
        if not isinstance(cell, dict):
            raise HistoryError(f"cells[{index}] must be an object")
        reject_unknown_keys(cell, CELL_KEYS, f"cells[{index}]")
        if missing := sorted(CELL_KEYS - set(cell)):
            raise HistoryError(f"cells[{index}] is missing: {', '.join(missing)}")
        if not isinstance(cell.get("statistics"), dict):
            raise HistoryError("cell.statistics must be an object")
        for metric, summary in cell["statistics"].items():
            if metric not in METRIC_KEYS or not isinstance(summary, dict):
                raise HistoryError("cell statistics contain unsupported metrics")
            reject_unknown_keys(summary, STATISTIC_KEYS, f"cell.statistics.{metric}")
            if set(summary) != STATISTIC_KEYS:
                raise HistoryError("cell statistic is missing count/median/IQR/min/max")
    if cells != aggregate_cells(takes):
        raise HistoryError("cell aggregates do not match the exact ordered takes")

    evidence = record["evidence"]
    if evidence.get("validatorPassed") is not True or evidence.get("crashDeltaPassed") is not True:
        raise HistoryError("validator and crash-delta gates must pass")
    if evidence.get("crashCount") != 0:
        raise HistoryError("successful evidence cannot contain a crash delta")
    if evidence.get("expectedTakeCount") != evidence.get("actualTakeCount") or evidence.get("actualTakeCount") != len(takes):
        raise HistoryError("take counts do not match the selected evidence")
    for key in ("manifestDigest", "resultBundleDigest", "rawTelemetryDigest"):
        require_digest(evidence.get(key), f"evidence.{key}")
    screenshots = evidence.get("screenshotDigests")
    if not isinstance(screenshots, list):
        raise HistoryError("evidence.screenshotDigests must be a list")
    for screenshot in screenshots:
        if not isinstance(screenshot, dict) or set(screenshot) != {"name", "digest"}:
            raise HistoryError("each screenshot digest requires only name and digest")
        if (
            Path(screenshot["name"]).name != screenshot["name"]
            or not SAFE_SCREENSHOT_RE.fullmatch(screenshot["name"])
        ):
            raise HistoryError("screenshot names must be privacy-safe basenames")
        require_digest(screenshot["digest"], "screenshot digest")

    kind = run["kind"]
    memory_contract_applies = version >= 2 and kind in MEMORY_QUALIFIED_KINDS
    if memory_contract_applies:
        if evidence.get("memoryContractVersion") != 1 or evidence.get("memoryQualified") is not True:
            raise HistoryError("record lacks the benchmark memory qualification contract")
        require_digest(
            evidence.get("sampleSidecarsDigest"), "evidence.sampleSidecarsDigest", allow_na=False
        )
        expected_sidecars = len(takes)
        if kind == "ui-generation" and run["platform"] == "macos":
            expected_sidecars *= 2
        if evidence.get("sampleSidecarCount") != expected_sidecars:
            raise HistoryError("selected memory-sidecar count does not match the benchmark takes")
        qualified_with_warnings = any(
            take.get("memoryStatus") == "qualifiedWithWarnings" for take in takes
        )
        if qualified_with_warnings and run["status"] != "passedWithWarnings":
            raise HistoryError("memory warnings must promote the run status to passedWithWarnings")
    if kind == "memory-qualification":
        if evidence.get("memoryPolicyID") != "retained-memory-v1":
            raise HistoryError("memory qualification has an unknown policy ID")
        if evidence.get("retentionMetric") != "withinModeRetainedPhysicalFootprintGrowth":
            raise HistoryError("memory qualification has an unknown retention metric")
        threshold = evidence.get("retentionThresholdFraction")
        observed = evidence.get("maximumRetainedGrowthFraction")
        growth_mb = evidence.get("maximumRetainedGrowthMB")
        if (
            not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
            or not math.isclose(float(threshold), 0.05, rel_tol=0, abs_tol=1e-12)
            or not isinstance(observed, (int, float)) or isinstance(observed, bool)
            or not math.isfinite(float(observed)) or float(observed) < 0
            or not isinstance(growth_mb, (int, float)) or isinstance(growth_mb, bool)
            or not math.isfinite(float(growth_mb)) or float(growth_mb) < 0
            or float(observed) > float(threshold)
            or evidence.get("retentionPassed") is not True
        ):
            raise HistoryError("memory qualification retention gate did not pass")
        expected_fraction = float(growth_mb) / (float(record["hardware"]["memoryBytes"]) / 1_048_576)
        if not math.isclose(float(observed), expected_fraction, rel_tol=1e-6, abs_tol=1e-9):
            raise HistoryError("memory qualification growth fraction does not match hardware RAM")
    if evidence.get("rawTelemetryDigest") == "not-applicable":
        raise HistoryError(f"{kind} requires a selected-evidence digest")
    require_digest(evidence.get("selectedEvidenceDigest"), "evidence.selectedEvidenceDigest", allow_na=False)
    if evidence.get("selectedEvidenceDigest") != selected_evidence_digest(record):
        raise HistoryError("selected evidence digest does not match the distilled evidence")
    if kind == "ui-generation":
        require_digest(evidence.get("resultBundleDigest"), "evidence.resultBundleDigest", allow_na=False)
        require_digest(evidence.get("rawTelemetryDigest"), "evidence.rawTelemetryDigest", allow_na=False)
        if not screenshots:
            raise HistoryError("UI generation evidence requires at least one named screenshot")
    generation_evidence_kind = kind in {
        "ui-generation", "engine-generation", "language", "instrument-profile",
        "memory-qualification",
    }
    executable_evidence_kind = generation_evidence_kind or kind == "telemetry-overhead"
    if executable_evidence_kind:
        if record["toolchain"].get("optimization") in {None, "", "unknown", "not-applicable"}:
            raise HistoryError(f"{kind} requires an exact optimization setting")
        if not record["toolchain"].get("executableHashes"):
            raise HistoryError(f"{kind} requires an exact executable hash")
        if not record["toolchain"].get("executableUUIDs"):
            raise HistoryError(f"{kind} requires a Mach-O UUID")
    if generation_evidence_kind:
        telemetry_version = evidence.get("telemetrySchemaVersion")
        qc_version = evidence.get("qcAlgorithmVersion")
        minimum_telemetry_schema = 8 if memory_contract_applies else 7
        if not isinstance(telemetry_version, int) or telemetry_version < minimum_telemetry_schema:
            raise HistoryError(
                f"{kind} requires generation telemetry schema v{minimum_telemetry_schema} or newer"
            )
        if not isinstance(qc_version, int) or qc_version < 2:
            raise HistoryError(f"{kind} requires audio-QC algorithm v2 or newer")
        if not models:
            raise HistoryError(f"{kind} requires exact model identity")
        for index, model in enumerate(models):
            require_digest(model.get("integrityDigest"), f"models[{index}].integrityDigest", allow_na=False)
            if model.get("mode") in {"design", "clone"}:
                require_digest(model.get("fixtureDigest"), f"models[{index}].fixtureDigest", allow_na=False)
    if generation_evidence_kind or kind == "telemetry-overhead":
        if models != default_models(record, allow_superseded=True):
            raise HistoryError("tracked model identity does not match the pinned model contract")
    if kind == "prosody-calibration":
        validate_prosody_semantics(record)
    if kind == "ui-perf":
        validate_ui_perf_semantics(record)
    if kind == "telemetry-overhead":
        validate_telemetry_overhead_semantics(record, model_lookup)
    if "trace" in evidence:
        trace = evidence["trace"]
        if not isinstance(trace, dict):
            raise HistoryError("evidence.trace must be an object")
        reject_unknown_keys(trace, TRACE_KEYS, "evidence.trace")
        if trace.get("validated") is not True:
            raise HistoryError("tracked Instruments evidence must be validated")
        require_digest(trace.get("digest"), "evidence.trace.digest")
    if kind == "instrument-profile":
        validate_trace_summary(record)

    comparison = record["comparison"]
    require_digest(comparison.get("key"), "comparison.key", allow_na=False)
    if comparison.get("key") != comparison_key(record):
        raise HistoryError("comparison key does not match the record identity")
    if comparison.get("comparable") is not record_is_comparable(record):
        raise HistoryError("comparison eligibility does not match source/classification")
    if source["dirty"] and comparison.get("comparable"):
        raise HistoryError("dirty-source records cannot be comparable")
    if comparison.get("baselineRunID") is not None and not isinstance(comparison["baselineRunID"], str):
        raise HistoryError("comparison.baselineRunID must be a run ID or null")
    if not isinstance(comparison.get("deltas"), dict):
        raise HistoryError("comparison.deltas must be an object")
    listening = record["listening"]
    if listening.get("status") not in LISTENING_STATUSES:
        raise HistoryError("listening.status is invalid")

    expected_digest = record_digest(record)
    if record.get("digest") != expected_digest:
        raise HistoryError("record digest does not match its canonical content")
    encoded = stored_json_bytes(record)
    if len(encoded) > MAX_RECORD_BYTES:
        raise HistoryError("record exceeds the per-file size limit")
    if expected_path is not None:
        expected_parent = RUNS_ROOT / run["kind"]
        if expected_path.parent != expected_parent or expected_path.name != f"{run['id']}.json":
            raise HistoryError("record path does not match its kind and run ID")


def record_path(record: dict[str, Any]) -> Path:
    return RUNS_ROOT / record["run"]["kind"] / f"{record['run']['id']}.json"


def all_record_paths() -> list[Path]:
    return validate_registry_tree()


def read_all_records() -> list[tuple[Path, dict[str, Any]]]:
    validate_benchmark_storage_tree()
    return [(path, load_json(path)) for path in all_record_paths()]


def comparison_reconciliation_updates(
    records: list[tuple[Path, dict[str, Any]]],
) -> list[tuple[Path, dict[str, Any]]]:
    updates: list[tuple[Path, dict[str, Any]]] = []
    for path, record in records:
        expected = expected_comparison_metadata(record, records)
        if record.get("comparison") == expected:
            continue
        replacement = copy.deepcopy(record)
        replacement["comparison"] = expected
        replacement["digest"] = record_digest(replacement)
        updates.append((path, replacement))
    return updates


def validate_all(
    records: list[tuple[Path, dict[str, Any]]] | None = None, *,
    validate_comparisons: bool = True,
) -> None:
    records = records if records is not None else read_all_records()
    schema = load_schema_contract()
    run_ids: dict[str, Path] = {}
    evidence_digests: dict[str, Path] = {}
    for path, record in records:
        validate_record(record, expected_path=path, schema=schema)
        run_id = record["run"]["id"]
        evidence_digest = record["evidence"]["selectedEvidenceDigest"]
        if run_id in run_ids:
            raise HistoryError(f"duplicate run ID in {run_ids[run_id]} and {path}")
        if evidence_digest in evidence_digests:
            raise HistoryError(f"duplicate evidence digest in {evidence_digests[evidence_digest]} and {path}")
        run_ids[run_id] = path
        evidence_digests[evidence_digest] = path
    if validate_comparisons:
        updates = comparison_reconciliation_updates(records)
        if updates:
            relative = updates[0][0].relative_to(RUNS_ROOT)
            raise HistoryError(
                f"comparison metadata is stale for {relative}; run rebuild-index"
            )


def markdown_escape(value: Any) -> str:
    return str(value).replace("|", "\\|")


def memory_contract_status(record: dict[str, Any]) -> str:
    if record.get("schemaVersion") == 1:
        return "memory-contract-incomplete"
    if record.get("run", {}).get("kind") not in MEMORY_QUALIFIED_KINDS:
        return "not-applicable"
    return (
        "qualified-with-warnings"
        if any(take.get("memoryStatus") == "qualifiedWithWarnings" for take in record.get("takes", []))
        else "qualified"
    )


def trend_summary(record: dict[str, Any]) -> str:
    comparison = record["comparison"]
    baseline = comparison.get("baselineRunID")
    if not baseline:
        return "baseline"
    collected: dict[str, list[float]] = {"rtf": [], "ttfcMS": []}
    if record.get("schemaVersion", 0) >= 2 and memory_contract_status(record).startswith("qualified"):
        collected["peakPhysicalFootprintMB"] = []
    for metrics in comparison.get("deltas", {}).values():
        if not isinstance(metrics, dict):
            continue
        for name in collected:
            value = metrics.get(name)
            if isinstance(value, dict) and isinstance(value.get("percent"), (int, float)):
                collected[name].append(float(value["percent"]))
    parts = []
    labels = {"rtf": "RTF", "ttfcMS": "TTFC", "peakPhysicalFootprintMB": "RAM"}
    for name, values in collected.items():
        if values:
            parts.append(f"{labels[name]} {statistics.median(values):+.1f}%")
    suffix = ", ".join(parts) if parts else "compatible"
    return f"vs {baseline}: {suffix}"


def render_history(records: list[tuple[Path, dict[str, Any]]]) -> str:
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
    for _, record in records:
        key = (
            record["run"]["kind"], record["run"]["platform"],
            record["hardware"]["profileID"], record["comparison"]["key"],
        )
        grouped.setdefault(key, []).append(record)
    lines = [
        "<!-- Generated by scripts/benchmark_history.py rebuild-index. Do not edit by hand. -->",
        "# Benchmark history",
        "",
        "Only validated, successful benchmark records are indexed here. Raw telemetry, audio, screenshots,",
        "result bundles, and traces remain untracked. Earlier manual results are preserved in",
        "[`LEGACY_HISTORY.md`](LEGACY_HISTORY.md) and are not treated as structured evidence.",
        "Schema-v1 records remain readable but are marked memory-contract-incomplete and are excluded",
        "from schema-v2 memory trends.",
        "RTF here is audio seconds ÷ wall-clock seconds (`audioSecondsPerWallSecond`): higher is",
        "faster, 1.1 ≈ 1.1× realtime, and a positive RTF trend is an improvement. Much of the TTS",
        "ecosystem defines RTF as the inverse (wall-clock ÷ audio, lower is better); convert before",
        "cross-project comparisons.",
        "",
    ]
    if not grouped:
        lines.extend(["_No structured benchmark runs have been recorded yet._", ""])
        return "\n".join(lines)
    for kind, platform, profile, configuration in sorted(grouped):
        lines.extend([
            f"## {kind} / {platform} / {profile} / config `{configuration[:12]}`", "",
            "| completed (UTC) | run | scope | classification | status | memory | takes | source | comparison | trend | label |",
            "|---|---|---|---|---|---|---:|---|---|---|---|",
        ])
        ordered = sorted(
            grouped[(kind, platform, profile, configuration)],
            key=lambda item: (item["run"]["finishedAt"], item["run"]["id"]),
        )
        for record in ordered:
            run = record["run"]
            source = record["source"]
            comparison = record["comparison"]
            relative = f"runs/{kind}/{run['id']}.json"
            comparable = comparison["key"][:12] if comparison.get("comparable") else "excluded"
            lines.append(
                "| {date} | [`{run_id}`]({relative}) | {scope} | {classification} | {status} | {memory} | {takes} | `{sha}`{dirty} | `{comparison}` | {trend} | {label} |".format(
                    date=run["finishedAt"].split("T", 1)[0], run_id=markdown_escape(run["id"]),
                    relative=relative, scope=run["matrixScope"], classification=run["classification"],
                    status=run["status"], takes=len(record["takes"]), sha=source["commit"][:12],
                    memory=memory_contract_status(record),
                    dirty=" dirty" if source["dirty"] else "", comparison=comparable,
                    trend=markdown_escape(trend_summary(record)),
                    label=markdown_escape(run["label"]),
                )
            )
        lines.append("")
    return "\n".join(lines)


def rebuild_index(*, check: bool = False) -> None:
    records = read_all_records()
    validate_all(records, validate_comparisons=False)
    updates = comparison_reconciliation_updates(records)
    update_by_path = {path: replacement for path, replacement in updates}
    reconciled = [
        (path, update_by_path.get(path, record)) for path, record in records
    ]
    validate_all(reconciled)
    if updates and check:
        relative = updates[0][0].relative_to(RUNS_ROOT)
        raise HistoryError(f"comparison metadata is stale for {relative}; run rebuild-index")
    rendered = render_history(reconciled)
    if check:
        existing = HISTORY_PATH.read_text(encoding="utf-8") if HISTORY_PATH.exists() else ""
        if existing != rendered:
            raise HistoryError("benchmarks/HISTORY.md is not reproducible; run rebuild-index")
    else:
        originals = {path: record for path, record in records if path in update_by_path}
        history_existed = HISTORY_PATH.exists()
        previous_history = HISTORY_PATH.read_text(encoding="utf-8") if history_existed else ""
        try:
            for path, replacement in updates:
                atomic_json_write(path, replacement)
            atomic_text_write(HISTORY_PATH, rendered)
        except Exception:
            # Reconciliation can touch older records when an earlier compatible
            # run arrives later. Restore every changed file so a publication
            # failure never leaves references to a record that the caller rolls
            # back; the printed repair command remains idempotent.
            for path, original in originals.items():
                atomic_json_write(path, original)
            if history_existed:
                atomic_text_write(HISTORY_PATH, previous_history)
            else:
                HISTORY_PATH.unlink(missing_ok=True)
            raise


def record_manifest(artifact_dir: Path) -> Path:
    manifest_path = artifact_dir / "benchmark-evidence.json"
    if not manifest_path.is_file():
        raise HistoryError(f"missing benchmark evidence manifest: {manifest_path}")
    existing_records = read_all_records()
    # Freeze publication-time enrichment beside the raw artifacts. This makes a
    # delayed/idempotent repair use the run's original hardware, toolchain,
    # binary, model and input identities instead of whatever happens to be
    # installed when the repair is attempted later.
    resolved_path = artifact_dir / "benchmark-history-record.json"
    if resolved_path.is_file():
        record = load_json(resolved_path)
        if record.get("evidence", {}).get("manifestDigest") != file_digest(manifest_path):
            raise HistoryError("resolved benchmark record does not match benchmark-evidence.json")
        validate_record(record)
    else:
        record = build_record(manifest_path)
        apply_comparison_baseline(record, existing_records)
        validate_record(record)
        atomic_json_write(resolved_path, record)
    destination = record_path(record)
    if destination.exists():
        existing = load_json(destination)
        # Runtime enrichment (for example free storage or load average) may
        # legitimately differ when the operator retries publication after an
        # interrupted index write.  The immutable evidence digest is the
        # idempotency identity; never replace an already validated record.
        if (
            existing.get("run", {}).get("id") == record["run"]["id"]
            and existing.get("evidence", {}).get("manifestDigest")
            == record["evidence"]["manifestDigest"]
        ):
            validate_record(existing, expected_path=destination)
            rebuild_index()
            return destination
        raise HistoryError(f"run ID already exists with different evidence: {record['run']['id']}")
    for path, existing in existing_records:
        if existing.get("run", {}).get("id") == record["run"]["id"]:
            raise HistoryError(f"run ID already exists: {path}")
        if existing.get("evidence", {}).get("selectedEvidenceDigest") == record["evidence"]["selectedEvidenceDigest"]:
            raise HistoryError(f"evidence is already registered by {path}")
    atomic_json_write(destination, record)
    try:
        rebuild_index()
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def find_record(run_id: str) -> tuple[Path, dict[str, Any]]:
    matches = [(path, record) for path, record in read_all_records() if record.get("run", {}).get("id") == run_id]
    if len(matches) != 1:
        raise HistoryError(f"expected one record for {run_id!r}, found {len(matches)}")
    return matches[0]


def annotate(run_id: str, status: str, note: str) -> Path:
    path, record = find_record(run_id)
    validate_safe_scalar(note, "listening.note")
    if len(note) > 500:
        raise HistoryError("listening note exceeds 500 characters")
    current = record["listening"]
    if current.get("status") == status and current.get("note") == note:
        return path
    record["listening"] = {
        "status": status,
        "note": note,
        "annotatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    record["digest"] = record_digest(record)
    validate_record(record, expected_path=path)
    atomic_json_write(path, record)
    rebuild_index()
    return path


def parse_arguments(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record_parser = subparsers.add_parser("record", help="publish one successful evidence manifest")
    record_parser.add_argument("--artifact-dir", type=Path, required=True)

    validate_parser = subparsers.add_parser("validate", help="validate one record or the full registry")
    validate_group = validate_parser.add_mutually_exclusive_group(required=True)
    validate_group.add_argument("record", nargs="?", type=Path)
    validate_group.add_argument("--all", action="store_true")

    rebuild_parser = subparsers.add_parser("rebuild-index", help="rebuild the generated Markdown index")
    rebuild_parser.add_argument("--check", action="store_true")

    annotate_parser = subparsers.add_parser("annotate", help="attach a listening verdict")
    annotate_parser.add_argument("--run-id", required=True)
    annotate_parser.add_argument("--listening", choices=sorted(LISTENING_STATUSES), required=True)
    annotate_parser.add_argument("--note", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv if argv is not None else sys.argv[1:])
    try:
        if args.command == "record":
            print(record_manifest(args.artifact_dir.resolve()).relative_to(REPO_ROOT))
        elif args.command == "validate":
            if args.all:
                validate_all()
                print(f"benchmark history: PASS ({len(all_record_paths())} records)")
            else:
                path = args.record.resolve()
                validate_record(load_json(path), expected_path=path if RUNS_ROOT in path.parents else None)
                print(f"benchmark history: PASS ({path})")
        elif args.command == "rebuild-index":
            rebuild_index(check=args.check)
            print("benchmark history index: PASS" if args.check else "benchmark history index rebuilt")
        elif args.command == "annotate":
            print(annotate(args.run_id, args.listening, args.note).relative_to(REPO_ROOT))
        return 0
    except (HistoryError, OSError, ValueError) as error:
        print(f"benchmark history: FAIL: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
