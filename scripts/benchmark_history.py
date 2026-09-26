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
from benchmark_memory import (  # noqa: E402
    KERNEL_LEDGER_TOLERANCE_MB,
)
from lib import rtf as rtf_semantics
from lib import jsonio  # noqa: E402
from lib import lineage_identity  # noqa: E402
from lib import bench_seed  # noqa: E402
from lib import trace_cpu  # noqa: E402
from lib import trace_intervals  # noqa: E402
from lib.language_metrics import (  # noqa: E402
    ACCURACY_METRIC_NORMALIZATIONS,
    ACCURACY_METRIC_VERSIONS,
    CHANNEL_CONSENSUS_ALGORITHM,
    CHANNEL_STATUSES,
    LANGUAGE_CHANNELS,
    LANGUAGE_CHECK_KINDS,
    NEGATIVE_CONTROL_KIND,
    SEGMENTATION_AWARE_METRIC_VERSIONS,
    TEXT_NORMALIZATION_V2,
    channel_consensus,
    run_channel_verdicts,
)
from lib.build_provenance import ProvenanceError, load_build_provenance  # noqa: E402


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
# Kinds whose takes carry a real-time factor and therefore declare which one:
# ui-perf measures frame health and prosody-calibration scores prosody, neither
# publishes an RTF.
RTF_BEARING_KINDS = ALL_KINDS - {"ui-perf", "prosody-calibration"}
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

# The per-kind lineage identity (lib/lineage_identity.py, audit #22): optional
# inputs, schema v2 and later, all four or none. When present the comparison
# key reads them instead of the whole-tree projectInputHash/harnessHash.
LINEAGE_INPUT_KEYS = {
    "lineageContractVersion", "lineageMeasurementVersion", "lineageHarnessHash",
    "lineageProjectHash",
}

TOP_LEVEL_KEYS = {
    "schemaVersion", "run", "hardware", "source", "toolchain", "inputs",
    "models", "evidence", "takes", "cells", "comparison", "listening", "digest",
}
SECTION_KEYS = {
    "run": {
        "id", "kind", "platform", "label", "startedAt", "finishedAt",
        "durationSeconds", "status", "matrixScope", "classification", "warnings",
        # "wall/audio" on every record published since 2026-09-12; absent on
        # legacy records whose `rtf` is the inverted decode-loop speedup.
        "rtfDefinition",
        # What `ttfcMS` measures (lib/rtf.py TTFC_DEFINITIONS); schema v2+
        # records since 2026-09-25 that carry a ttfcMS. Absent on older records.
        "ttfcDefinition",
        # Memory-tier provenance (audit #19): optional, schema v2 and later.
        # Lineage contract 2 keys a forced or emulated tier apart (audit #11).
        "runtimePolicy",
        # How every take chose its sampling seed (lib/bench_seed.py, audit #29):
        # optional, schema v2 and later; lineage contract 2 keys it.
        "seedPolicy",
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
        *LINEAGE_INPUT_KEYS,
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
        "maximumRetainedGrowthFraction", "retentionPassed", "retainedMemoryV2",
        "streamingTelemetryV9SidecarCount", "streamingTelemetryV9SidecarsDigest",
        "streamingTelemetryV9PublicationReadyCount",
        # How the cells summarize the takes (audit #30); absent means 1.
        "cellAggregateVersion",
    },
    "comparison": {"key", "comparable", "baselineRunID", "deltas", "deltaMetrics"},
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
    "accuracyMetric", "accuracyThreshold", "expectedOutcome", "playbackStartSource",
    "playbackCaptureStatus", "playbackCaptureDigest",
    "memoryStatus", "sampleSidecarDigest",
    "streamingTelemetryV9SidecarDigest", "samplingPromotionPackaged", "samplingWAVDigest",
    "samplingSeedAgreement",
    "qualityRegistryOutcome", "qualityRegistryRequiredGates", "qualityRegistryIssues",
    "detectedLanguages", "channelConsensus",
    # The first take after a cold take (audit #30); cell aggregate 2 leaves it
    # out of its cell's statistics.
    "followsColdTake",
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
# The versioned signpost block (records from BT-06 on, 2026-09-25, audit #12/#96):
# begin/end/point/interval counts, orphans, the recorded duration and per-take
# decode-loop interval statistics (scripts/lib/trace_intervals.py).
SIGNPOST_TRACE_SUMMARY_KEYS = set(trace_intervals.SUMMARY_KEYS)
# Per-take cycles per rusage CPU-second and the CPU rows the sums lost (records
# since 2026-09-25, audit #97; scripts/lib/trace_cpu.py).
CPU_PLAUSIBILITY_TRACE_SUMMARY_KEYS = {"cpuPlausibility"}
TRACE_SUMMARY_KEYS = {
    "artifact", "capturedDataRowCount", "capturedRowsBySchema",
    "correlatedSignpostEventCount", "correlationFieldsVerified",
    "cpuCycleWeight", "cpuSampleCount", "cpuSampleSpanMS", "cpuSampleWeightMS", "cpuPlausibility",
    "processCount", "schemaCount", "signpostEventCount", "signpostSchemaCount",
    "tableCount", "targetPIDVerified", "targetProcess", "tocDigest",
} | LEGACY_MEMORY_TRACE_SUMMARY_KEYS | MEMORY_TRACE_V2_SUMMARY_KEYS | SIGNPOST_TRACE_SUMMARY_KEYS
LANGUAGE_VERIFICATION_KEYS = {
    "outputSchemaVersion", "outputAlgorithm", "recognitionSchemaVersion",
    "recognitionAlgorithm", "accuracyMetricVersion", "requiredPassCount",
    # Run-level counts (records since 2026-09-12); older records carried these
    # as identical constants on every take's metrics.
    "hintCellsPassed", "hintCellsExpected", "outputCellsPassed", "outputCellsExpected",
    "negativeControlsConfirmed", "families",
    # Independent (whisper-family) recognizer identity, records since 2026-09-12.
    "independentRecognitionAlgorithm", "independentModelIdentitySHA256",
    # What each cited family's language check observes (records since
    # 2026-09-25, audit #42): lib.language_metrics.LANGUAGE_CHECK_KINDS.
    "languageCheckKinds",
    # Per-channel consensus and the accuracy control (records since
    # 2026-09-25, audit #42): lib.language_metrics.channel_consensus.
    "negativeControlKind", "channelConsensusAlgorithm", "channelVerdicts",
}
# The per-family take metrics each verdict channel reads (audit #42).
FAMILY_CHANNEL_METRICS = {
    "apple-speech": {"language": "outputLanguagePass", "accuracy": "outputAccuracyPass"},
    "whisper": {"language": "independentLanguagePass", "accuracy": "independentAccuracyPass"},
}
RECOGNITION_FAMILIES = ("apple-speech", "whisper", "sensevoice")
# Records before 2026-09-12 carry no `families`; every one of them was verified
# by the in-app Apple Speech consensus.
LEGACY_LANGUAGE_FAMILIES = ["apple-speech"]
APPLE_SPEECH_VERIFICATION_IDENTITY = {
    "outputSchemaVersion": 3,
    "outputAlgorithm": "language-output-verifier-v3",
    "recognitionSchemaVersion": 2,
    "recognitionAlgorithm": "apple-speech-file-consensus-v2",
    "accuracyMetricVersion": "normalized-edit-rate-v1",
    "requiredPassCount": 3,
}
INDEPENDENT_VERIFICATION_IDENTITY = {
    "outputSchemaVersion": 1,
    "outputAlgorithm": "independent-asr-output-v1",
    "recognitionSchemaVersion": 1,
    "recognitionAlgorithm": "mlx-whisper-locked-decode-v1",
    "accuracyMetricVersion": "normalized-edit-rate-v1",
    "requiredPassCount": 1,
}
INDEPENDENT_ACCURACY_METRIC_KEYS = {
    "independentWordErrorRate", "independentCharacterErrorRate", "independentPrimaryAccuracyScore",
    "independentLanguageMatchScore", "independentLanguagePass", "independentAccuracyPass",
    "independentRecognitionDurationSeconds",
}
LANGUAGE_VERIFICATION_IDENTITY_KEYS = {
    "outputSchemaVersion", "outputAlgorithm", "recognitionSchemaVersion",
    "recognitionAlgorithm", "accuracyMetricVersion", "requiredPassCount",
}
DELETION_RUN_METRIC_KEYS = ("longestDeletionRun", "independentLongestDeletionRun")
# Fillers each family's transcript holds beyond the script's (records scored
# under text normalization v2, accuracy metric v3, AQ-02): counted, never
# erased and never gated.
FILLER_COUNT_METRIC_KEYS = ("excessFillerCount", "independentExcessFillerCount")
# WER v2 (records since 2026-09-25, audit #43): each family's segmentation-aware
# word rate and the word-boundary edits it credited; v2 records gate on it.
SEGMENTATION_AWARE_METRIC_KEYS = {
    "apple-speech": ("segmentationAwareWordErrorRate", "wordBoundaryOnlyEdits"),
    "whisper": ("independentSegmentationAwareWordErrorRate", "independentWordBoundaryOnlyEdits"),
}
INDEPENDENT_CONFIDENCE_METRIC_KEYS = (
    "independentMaximumNoSpeechProbability", "independentMeanAverageLogProbability",
)
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
    "run": SECTION_KEYS["run"] - {"rtfDefinition", "ttfcDefinition", "runtimePolicy", "seedPolicy"},
    "hardware": SECTION_KEYS["hardware"],
    "source": SECTION_KEYS["source"],
    "toolchain": SECTION_KEYS["toolchain"],
    "inputs": SECTION_KEYS["inputs"] - LINEAGE_INPUT_KEYS,
    "evidence": SECTION_KEYS["evidence"] - {
        "trace", "languageVerification", "memoryContractVersion", "memoryQualified",
        "sampleSidecarCount", "sampleSidecarsDigest",
        "memoryPolicyID", "retentionMetric", "retentionThresholdFraction",
        "maximumRetainedGrowthMB", "maximumRetainedGrowthFraction", "retentionPassed",
        "retainedMemoryV2",
        "streamingTelemetryV9SidecarCount", "streamingTelemetryV9SidecarsDigest",
        "streamingTelemetryV9PublicationReadyCount", "cellAggregateVersion",
    },
    # deltaMetrics is declared only by records published from 2026-09-14 on;
    # older records keep their full delta blocks and never claim it.
    "comparison": SECTION_KEYS["comparison"] - {"deltaMetrics"},
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
    "retainedMemoryV2",
    "streamingTelemetryV9SidecarCount", "streamingTelemetryV9SidecarsDigest",
    "streamingTelemetryV9PublicationReadyCount", "cellAggregateVersion",
}
# schema-v1 is frozen history; the first-chunk definition arrived after it.
V2_ONLY_RUN_KEYS = {"ttfcDefinition", "runtimePolicy", "seedPolicy"}
V2_ONLY_TAKE_KEYS = {
    "memoryStatus", "sampleSidecarDigest",
    "streamingTelemetryV9SidecarDigest", "samplingPromotionPackaged", "samplingWAVDigest",
    "samplingSeedAgreement",
    # The language each recognizer family detected for a language take (records
    # since 2026-09-25, audit #42), so a misattributed verdict is visible.
    "detectedLanguages",
    "followsColdTake",
    # Each verdict channel's two-family consensus (records since 2026-09-25, audit #42).
    "channelConsensus",
}
# Phase 13: the typed quality-registry identity is a v3 addition; v1/v2
# records must reject it as unknown so historical documents stay immutable.
V3_ONLY_TAKE_KEYS = {
    "qualityRegistryOutcome", "qualityRegistryRequiredGates", "qualityRegistryIssues",
    # A language negative control (expected verification failure) is stamped on
    # the take since 2026-09-12; older records never carried one with metrics.
    "expectedOutcome",
    # Played-audio capture evidence (PC-01, 2026-09) on macOS UI benchmark takes.
    "playbackCaptureStatus", "playbackCaptureDigest",
}
PLAYBACK_CAPTURE_STATUSES = {"captured", "silent", "unavailable", "referenceUnresolved", "aborted"}
V2_ONLY_TRACE_SUMMARY_KEYS = {
    *LEGACY_MEMORY_TRACE_SUMMARY_KEYS,
    *MEMORY_TRACE_V2_SUMMARY_KEYS,
    *SIGNPOST_TRACE_SUMMARY_KEYS,
    *CPU_PLAUSIBILITY_TRACE_SUMMARY_KEYS,
}
V2_ONLY_TRACE_KEYS = set(TRACE_RETENTION_KEYS)
# Profile kinds a trace's capture settings may name. The witness (audit #50,
# 2026-09-25) records os_signpost alone: no CPU sampler, so its summary carries
# no CPU fields. From schema v2 on the schema therefore leaves the CPU summary
# fields optional and the executable validator requires them of every other
# profile kind; frozen schema-v1 keeps them required.
TRACE_PROFILE_KINDS = {"cpu", "memory", "witness"}
WITNESS_TRACE_TEMPLATE = "os_signpost"
CPU_TRACE_SUMMARY_KEYS = frozenset({"cpuSampleCount", "cpuSampleSpanMS"})
CPU_SAMPLER_TRACE_SUMMARY_KEYS = CPU_TRACE_SUMMARY_KEYS | {
    "cpuCycleWeight", "cpuSampleWeightMS", "cpuPlausibility",
}
# The CPU sampler table each capture instrument exports: CPU Profiler's
# hardware-counter cycles (cpu-profile) or Time Profiler's timer samples with a
# sampled-time weight (time-profile). A macOS profile samples with Time
# Profiler from instrument-profile measurement version 4 (2026-09-26: kpc needs
# root on macOS 27) and with CPU Profiler before it.
TRACE_CPU_SAMPLER_SCHEMAS = {"cpu-profile": "CPU Profiler", "time-profile": "Time Profiler"}
MACOS_TIME_PROFILER_MEASUREMENT_VERSION = 4


def schema_required_keys(version: int) -> dict[str, set[str]]:
    required = {name: set(keys) for name, keys in SCHEMA_REQUIRED_KEYS.items()}
    if version >= 2:
        required["traceSummary"] -= CPU_TRACE_SUMMARY_KEYS
    return required


def schema_property_keys(version: int) -> dict[str, set[str]]:
    properties = {name: set(keys) for name, keys in SCHEMA_PROPERTY_KEYS.items()}
    if version == 1:
        properties["run"] -= V2_ONLY_RUN_KEYS
        properties["inputs"] -= LINEAGE_INPUT_KEYS
        properties["evidence"] -= V2_ONLY_EVIDENCE_KEYS
        properties["comparison"] -= {"deltaMetrics"}   # legacy records never declare it
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
    "rtf", "requestWallSeconds", "decodeSpeedupX", "rtfAppEndToEnd",
    # The startup windows the standard RTF excludes from requestWallSeconds
    # (records since 2026-09-25); `prewarmMS` keeps timing the explicit prewarm.
    "excludedStartupMS", "modelLoadWindowMS", "prewarmWindowMS",
    "tokensPerSecond", "ttfcMS", "submitToFirstChunkMS", "submitToCompletedMS",
    # The CLI first-chunk observer's lag behind the engine's first-chunk
    # hand-off, part of ttfcMS (records since 2026-09-25, audit #48); signed.
    "ttfcObserverLagMS",
    "playbackScheduledMS", "firstChunkToPlaybackScheduledMS", "requestToFirstChunkMS",
    "decodeWallSeconds", "audioSeconds", "generatedTokens", "backendWallMS",
    "modelLoadMS", "prewarmMS", "finalizationMS", "postprocessMS",
    "peakPhysicalFootprintMB", "peakResidentMB", "peakCompressedMB",
    "peakGPUAllocatedMB", "minimumHeadroomMB", "memoryTrimCount", "maximumTrimLevel",
    "uiMaximumDelayedHeartbeatMS", "delayedHeartbeatCount", "heartbeatCoverage",
    # Heartbeats still queued at the end of a take, counted by their lower
    # bound (records since 2026-09-25, audit #18). Its presence marks that
    # uiMaximumDelayedHeartbeatMS and delayedHeartbeatCount include them;
    # records without it counted completed heartbeats only.
    "censoredHeartbeatCount",
    "cpuUserSeconds", "cpuSystemSeconds", "pageFaults", "contextSwitches",
    "blockIOOperations", "samplerTargetIntervalMS", "samplerEffectiveMedianIntervalMS",
    "samplerMaximumLatenessMS", "samplerBoundarySampleCount", "samplerCaptureFailureCount",
    "samplerMaximumDriftMS",
    # The summed cost of a take's boundary memory captures, which the
    # generation path awaits inline (records since 2026-09-25, audit #65).
    "samplerBoundaryCaptureTotalMS",
    # The largest same-sample gap between the kernel's limit_bytes_remaining
    # and os_proc_available_memory on an iPhone take (records since
    # 2026-09-25, audit #68).
    "processLimitRemainingDriftMB",
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
    # The routine per-tier post-generation MLX cache clear, counted apart from
    # memory pressure (records since 2026-09-25; older records fold it into
    # the pressure level and the soft-trim warning).
    "policyCacheClearCount",
    # retained-memory-v2 (records since 2026-09-25): MLX active and cache memory
    # at the end of the take (after the routine post-generation cache clear,
    # else after the stream).
    "mlxEndActiveMB", "mlxEndCacheMB",
    # Memory contract v2 (records since 2026-09-25): the longest unobserved gap
    # in the process's one memory series and the policy bound it met
    # (max(multiple x cadence, floor) at publication), the sampled Metal peak's shortfall
    # against the exact MLX peak, and the kernel ledgers when the sampler read
    # them (a process-lifetime footprint high-water mark, 1 when it rose inside
    # the take so it is the take's exact peak, the sampled footprint's shortfall
    # against it, and the graphics-tagged footprint at the take's end).
    "samplerMaximumUnobservedGapMS", "samplerUnobservedGapLimitMS", "gpuPeakCaptureMissMB",
    "kernelPhysFootprintPeakMB", "kernelPhysFootprintPeakExact",
    "footprintPeakCaptureMissMB", "graphicsFootprintEndMB",
    "loadAverage1M", "freeStorageBytes", "uptimeSeconds", "lowPowerMode",
    "chunksReceived", "continuityFailures", "underruns", "startBufferDepth",
    # Independent (whisper-family) recognition of language takes, since 2026-09-12.
    "independentWordErrorRate", "independentCharacterErrorRate", "independentPrimaryAccuracyScore",
    "independentLanguageMatchScore", "independentLanguagePass", "independentAccuracyPass",
    "independentRecognitionDurationSeconds",
    # Whisper's own confidence per take (records since 2026-09-25, audit #89):
    # the worst segment's no-speech probability and the mean segment log
    # probability. Descriptive only; no gate reads them.
    *INDEPENDENT_CONFIDENCE_METRIC_KEYS,
    # The longest run of consecutive reference units each family's recognizer
    # deleted, on the primary metric's units (records since 2026-09-25, audit
    # #84). Warn-only: a run of two or more on a take that must pass carries
    # language.deletion_run:<family>.
    *DELETION_RUN_METRIC_KEYS,
    # WER v2 per family (records since 2026-09-25, audit #43).
    *(key for keys in SEGMENTATION_AWARE_METRIC_KEYS.values() for key in keys),
    # Excess fillers per family (text normalization v2, AQ-02).
    *FILLER_COUNT_METRIC_KEYS,
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
    "nonFiniteCount", "dcOffset", "longestSilenceMS", "stepBurstPeakCount", "stepBurstPeakStartMS",
    # Audio QC v8 speaking rate: seconds per letter or digit of the spoken text.
    "secondsPerTextUnit",
    # Clustered click events (audit #85, additive on audio QC v8): the count, the low-energy
    # subcount and events per second of audio. Observational.
    "clickEventCount", "lowEnergyClickEventCount", "clickEventsPerSecond",
    # Stage 0 observational signal measures (AQ-04, additive on audio QC v8):
    # BS.1770 loudness and true peak, the pause-percentile noise floor, WADA-SNR,
    # effective bandwidth, spectral-flux events per second, the 12.5 Hz
    # codec-frame modulation index, the largest seam z-score and the longest
    # repetition stripe. Observational.
    "integratedLoudnessLUFS", "shortTermLoudnessMaxLUFS", "loudnessRangeLU", "truePeakDBTP",
    "noiseFloorDBFS", "wadaSNRDB", "effectiveBandwidthHz", "spectralFluxEventsPerSecond",
    "codecFrameModulationIndex", "seamDiscontinuityMaxZ", "repetitionStripeLongestMS",
    # Played-audio capture (PC-01, 2026-09): the app's rendered output compared with the take.
    "playbackCaptureAlignmentMS", "playbackCaptureResidualDBFS", "playbackCaptureDropoutCount",
    "playbackCaptureMaxGapMS", "playbackCaptureFirstAudibleMS", "playbackCaptureCoverage",
    "playbackCaptureStepBurstPeakCount",
    "goodClipCount", "badClipCount", "targetFalsePositiveRate",
    "observedFalsePositiveRate", "observedTruePositiveRate", "goodFlagRate", "badFlagRate",
    "monotoneF0StdThresholdHz", "monotoneTurningPointsThresholdPerSecond",
    "rushedSyllableRateThresholdHz", "rushedMaximumPauseRatio",
    "flatEnvelopeRoughnessThreshold", "flatRateCVThreshold",
    "maximumPauseThresholdSeconds", "maximumPauseRatioThreshold",
    # The prosody analyzer version a calibration ran (publisher since 2026-07-17);
    # optional so the one earlier calibration record stays valid.
    "analyzerAlgorithmVersion",
    "deliveryDF0StdHz", "deliveryDRateCV", "deliveryDPauseRatio",
    # deliveryProsodyEffect is the instructed take's ABSOLUTE expressiveness on
    # every record that carries it (its name notwithstanding); the paired
    # instructed-minus-neutral effect is deliveryPairedProsodyEffect, published
    # beside it since 2026-09-25 (audit #9).
    "deliveryDRoughness", "deliveryProsodyEffect", "deliveryPairedProsodyEffect",
    "deliveryPitchShiftSemitones", "deliveryArousalScore",
    # Records since 2026-09-25 (audit #39): the remaining expectation-bound
    # paired features, so a campaign re-judges its cells from records, and the
    # count of the take's own adherence flags, which are diagnostics (the cell
    # verdict warns as `delivery_cell:<flag>`).
    "deliveryVoiceTensionScore", "deliveryVoiceBreathinessScore",
    "deliveryVoicedFractionDelta", "deliveryTurningPointsDeltaPerSecond",
    "deliveryTakeFlagCount",
    # ui-perf (UI-7): per-scenario SwiftUI frame-health evidence from the
    # in-app display-link probe, joined by scripts/check_macos_ui_perf.py.
    "uiHitchTimeMSPerS", "uiMaxGapMS", "uiP95GapMSApprox", "uiFramesDelivered",
    "uiExpectedFrames", "uiProbeCoverage", "uiRefreshIntervalMS",
    "uiWindowDurationMS", "uiActionCount",
    # In-window excess frame time per scripted action (records since
    # 2026-09-25, audit #79; never backfilled).
    "uiHitchMSPerAction",
    # From the probe's per-block samples (records since 2026-09-25, audit #80,
    # #81): the p95 of the frame gaps that end in the window and how many it
    # read (its presence also marks uiMaxGapMS as clipped to the window), and
    # the window's own heartbeats: completed, delayed past 50 and 250 ms, and
    # the largest delay past 50 ms (0 when none).
    "uiP95GapMS", "uiGapSampleCount",
    "uiWindowHeartbeatCount", "uiWindowDelayedHeartbeatCount50",
    "uiWindowDelayedHeartbeatCount250", "uiWindowMaximumDelayedHeartbeatMS",
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
        # Since 2026-09-25: the harness-only control (audit #32) and navigation
        # with the product's warms on (audit #33), both exploratory.
        "harness-control", "sidebar-navigation-warms",
    },
    "ios": {
        "ios-idle-baseline", "ios-tab-navigation", "ios-history-scroll",
        "ios-voices-scroll", "ios-settings-scroll", "ios-composer-typing",
        "ios-sheet-present-dismiss", "ios-player-scrub", "ios-generation-active",
    },
}
# Scenarios a platform's earlier records measured without: a record carries
# either the full current set or the full set without these, never a mix.
UI_PERF_SCENARIOS_ADDED = {
    "macos": {"harness-control", "sidebar-navigation-warms"},
    "ios": set(),
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
# Memory contract v1 records keep their meaning (95% coverage; macOS UI totals
# from uptime-paired app and engine samples). Contract v2 gives one process one
# series: it gates on the longest unobserved gap and publishes each take's
# sampled-peak shortfall against the exact high-water marks, and it never
# carries the v1 pairing metrics.
MEMORY_CONTRACT_VERSIONS = frozenset({1, 2})
MEMORY_V2_REQUIRED_METRICS = {
    "samplerTargetIntervalMS", "samplerMaximumUnobservedGapMS", "samplerUnobservedGapLimitMS",
    "gpuPeakCaptureMissMB",
}
KERNEL_LEDGER_METRICS = {
    "kernelPhysFootprintPeakMB", "kernelPhysFootprintPeakExact", "footprintPeakCaptureMissMB",
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


canonical_bytes = jsonio.canonical_bytes


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


file_digest = jsonio.sha256_file


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


def load_json(path: Path) -> Any:
    return jsonio.load_json(path, error=HistoryError, require_object=False, reject_duplicate_keys=True)


def atomic_json_write(path: Path, value: Any) -> None:
    encoded = stored_json_bytes(value)
    if len(encoded) > MAX_RECORD_BYTES:
        raise HistoryError(f"record exceeds {MAX_RECORD_BYTES} bytes ({len(encoded)} bytes)")
    jsonio.atomic_write_bytes(path, encoded)


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


# `NativeDeviceMemoryClass` raw values (Sources/QwenVoiceCore/SemanticTypes.swift).
RUNTIME_DEVICE_CLASSES = {"floor_8gb_mac", "mid_16gb_mac", "high_memory_mac", "iphone_pro"}
RUNTIME_POLICY_KEYS = {"deviceClass", "deviceClassForced"}
# A Mac emulating a smaller one (audit #11 option b) names the emulated RAM.
RUNTIME_POLICY_OPTIONAL_KEYS = {"simulatedPhysicalMemoryMB"}


def validate_runtime_policy(run: dict[str, Any]) -> None:
    """Check run.runtimePolicy, the memory-tier provenance (audit #19).

    A native tier must match the platform; a forced tier is exploratory
    evidence and can never join a comparison lineage. An emulated smaller Mac
    (`simulatedPhysicalMemoryMB`, audit #11) is a forced tier on macOS."""
    policy = run["runtimePolicy"]
    if (
        not isinstance(policy, dict)
        or not RUNTIME_POLICY_KEYS <= set(policy)
        or set(policy) - RUNTIME_POLICY_KEYS - RUNTIME_POLICY_OPTIONAL_KEYS
    ):
        raise HistoryError(
            "run.runtimePolicy must name deviceClass and deviceClassForced "
            "and at most simulatedPhysicalMemoryMB"
        )
    device_class = policy["deviceClass"]
    forced = policy["deviceClassForced"]
    if device_class not in RUNTIME_DEVICE_CLASSES or not isinstance(forced, bool):
        raise HistoryError("run.runtimePolicy has an unsupported device class")
    if "simulatedPhysicalMemoryMB" in policy:
        simulated = policy["simulatedPhysicalMemoryMB"]
        if isinstance(simulated, bool) or not isinstance(simulated, int) or simulated <= 0:
            raise HistoryError("run.runtimePolicy.simulatedPhysicalMemoryMB must be a positive integer")
        if not forced or run.get("platform") != "macos":
            raise HistoryError("an emulated physical memory is a forced tier on macOS")
    if forced:
        if run.get("classification") not in {"exploratory", "instrumented", "partial"}:
            raise HistoryError("a forced memory class can only publish non-comparable evidence")
    elif (device_class == "iphone_pro") != (run.get("platform") == "ios"):
        raise HistoryError("run.runtimePolicy device class does not match the platform")


def validate_cold_take_flags(takes: list[dict[str, Any]], aggregate_version: int) -> None:
    """`followsColdTake` marks exactly the take after a cold take (audit #30).

    It is true when present and only on a take whose predecessor is cold; a
    record aggregated under version 2 must flag every such take, since its
    cell statistics leave the flagged takes out."""
    for position, take in enumerate(takes):
        follows = position > 0 and takes[position - 1].get("warmState") == "cold"
        flag = take.get("followsColdTake")
        if flag is not None and (flag is not True or not follows):
            raise HistoryError(f"take {take.get('cell')} carries followsColdTake but does not follow a cold take")
        if aggregate_version >= 2 and follows and flag is not True:
            raise HistoryError(
                f"take {take.get('cell')} follows a cold take; cell aggregate 2 needs followsColdTake"
            )


def validate_seed_policy(record: dict[str, Any]) -> None:
    """Check run.seedPolicy against the takes' published seeds (audit #29).

    cell-hash-v1 publishes every take's seed and each must be its cell's
    (lib/bench_seed.py, the Swift policy's hash); generated publishes none;
    requested publishes every take's."""
    policy = record["run"]["seedPolicy"]
    if policy not in bench_seed.SEED_POLICIES:
        raise HistoryError(f"run.seedPolicy is unsupported: {policy!r}")
    takes = record.get("takes", [])
    if policy == bench_seed.GENERATED:
        if any("seed" in take for take in takes):
            raise HistoryError("run.seedPolicy generated cannot publish a take seed")
        return
    if any("seed" not in take for take in takes):
        raise HistoryError(f"run.seedPolicy {policy} needs every take's seed")
    if policy == bench_seed.CELL_HASH_V1:
        for take in takes:
            if take["seed"] != bench_seed.cell_seed(take["cell"]):
                raise HistoryError(
                    f"take {take['cell']} seed {take['seed']} is not its {policy} seed"
                )


def validate_lineage_inputs(record: dict[str, Any]) -> None:
    """Check the optional lineage identity: schema v2+, all four fields, known versions."""
    inputs = record["inputs"]
    present = LINEAGE_INPUT_KEYS & set(inputs)
    if not present:
        return
    if present != LINEAGE_INPUT_KEYS:
        raise HistoryError(
            "inputs lineage identity must name lineageContractVersion, lineageMeasurementVersion, "
            "lineageHarnessHash and lineageProjectHash together"
        )
    if record.get("schemaVersion", 1) < 2:
        raise HistoryError("schema-v1 records cannot carry a lineage identity")
    version = inputs["lineageContractVersion"]
    if (
        not isinstance(version, int) or isinstance(version, bool)
        or version not in lineage_identity.SUPPORTED_LINEAGE_CONTRACT_VERSIONS
    ):
        raise HistoryError(f"inputs.lineageContractVersion is unsupported: {version!r}")
    # Contract 1 predates the seed policy and cell aggregate 2 and its key
    # ignores them, while a contract-2 record at the defaults keeps the
    # contract-1 key: a contract-1 record carrying either would share a lineage
    # with records measured differently.
    if version == 1 and (
        "seedPolicy" in record["run"]
        or (record.get("evidence") or {}).get("cellAggregateVersion", 1) != 1
    ):
        raise HistoryError(
            "a lineage contract 1 record cannot carry run.seedPolicy or a cell aggregate version above 1"
        )
    if not lineage_identity.has_lineage(record["run"]["kind"], record["run"]["platform"]):
        raise HistoryError("this record kind and platform define no lineage identity")
    measurement = inputs["lineageMeasurementVersion"]
    if not isinstance(measurement, int) or isinstance(measurement, bool) or measurement < 1:
        raise HistoryError("inputs.lineageMeasurementVersion must be a positive integer")
    # Versions only rise, so every published record names one that exists.
    current = lineage_identity.LINEAGE_MEASUREMENT_VERSIONS[(record["run"]["kind"], record["run"]["platform"])]
    if measurement > current:
        raise HistoryError(
            f"inputs.lineageMeasurementVersion {measurement} is newer than this kind's reviewed version {current}"
        )
    require_digest(inputs["lineageHarnessHash"], "inputs.lineageHarnessHash", allow_na=False)
    require_digest(inputs["lineageProjectHash"], "inputs.lineageProjectHash")


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
        if set(definition.get("required", [])) != schema_required_keys(version)[name]:
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
    if version >= 2:
        policy_properties = run_properties.get("runtimePolicy", {}).get("properties", {})
        if set(policy_properties.get("deviceClass", {}).get("enum", [])) != RUNTIME_DEVICE_CLASSES:
            raise HistoryError(
                "benchmark schema run.runtimePolicy.deviceClass enum drifted from the executable validator"
            )
        lineage_versions = definitions["inputs"]["properties"]["lineageContractVersion"].get("enum", [])
        if set(lineage_versions) != lineage_identity.SUPPORTED_LINEAGE_CONTRACT_VERSIONS:
            raise HistoryError(
                "benchmark schema inputs.lineageContractVersion enum drifted from the executable validator"
            )
    if set(definitions["listening"]["properties"]["status"].get("enum", [])) != LISTENING_STATUSES:
        raise HistoryError("benchmark schema listening statuses drifted from the executable validator")
    if set(definitions["audioQC"]["properties"]["verdict"].get("enum", [])) != QC_VERDICTS:
        raise HistoryError("benchmark schema audio-QC verdicts drifted from the executable validator")
    profile_ids = set(load_profiles())
    schema_profile_ids = set(definitions["hardware"]["properties"]["profileID"].get("enum", []))
    # schema-v1 is frozen history: it predates hosts added later (the Mac mini M6
    # became the canonical macOS host on 2026-09-22), so its enum only has to
    # name registered profiles. Live schemas must list the registry exactly.
    if version == 1:
        profiles_match = bool(schema_profile_ids) and schema_profile_ids <= profile_ids
    else:
        profiles_match = schema_profile_ids == profile_ids
    if not profiles_match:
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
    pass the untrimmed Git output or a first pathname such as ``.claude/...``
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
        REPO_ROOT / "scripts" / "repo_invariants.sh",
        REPO_ROOT / "scripts" / "check_macos_ui_bench.py",
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
        # The base test cases whose navigation and launch code runs inside the
        # measured takes and windows (audit V-3).
        REPO_ROOT / "Tests" / "VocelloMacUITests" / "VocelloMacUITestCase.swift",
        REPO_ROOT / "Tests" / "VocelloiOSUITests" / "VocelloiOSUITestCase.swift",
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
        # Ceiling calibration and derivation shared by both perf checkers (audit #34, #77).
        REPO_ROOT / "scripts" / "lib" / "ui_perf_thresholds.py",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "BenchMatrixSpec.swift",
        REPO_ROOT / "Sources" / "VocelloCLI" / "BenchCommand.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "GenerationTelemetryRecord.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "NativeTelemetrySampler.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "GenerationOutputAdapter.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "NativeEngineRuntime.swift",
        REPO_ROOT / "Sources" / "SharedSupport" / "Telemetry" / "AppGenerationTimeline.swift",
        REPO_ROOT / "Sources" / "SharedSupport" / "Telemetry" / "MainThreadStallWatchdog.swift",
        REPO_ROOT / "benchmarks" / "schema-v2.json",
        REPO_ROOT / "config" / "memory-qualification-policy.json",
        # The iPhone memory bands benchmark_memory.py gates published evidence on.
        REPO_ROOT / "config" / "ios-memory-budget-policy.json",
        # The macOS UI benchmark's stall gate statistic and limit (audit #6).
        REPO_ROOT / "config" / "macos-ui-stall-gate.json",
    ]
    corpus_paths = [
        REPO_ROOT / "Tests" / "UIAutomationSupport" / "VocelloUIAutomationSupport.swift",
        REPO_ROOT / "Sources" / "QwenVoiceCore" / "BenchMatrixSpec.swift",
        REPO_ROOT / "Sources" / "VocelloCLI" / "BenchCommand.swift",
    ]
    inputs: dict[str, Any] = {
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
    # projectInputHash and harnessHash stay recorded as provenance; new schema-v2+
    # records are keyed on the narrower per-kind lineage identity instead (audit #22).
    if int(record.get("schemaVersion", SCHEMA_VERSION)) >= 2:
        lineage = lineage_identity.lineage_inputs(run["kind"], run["platform"], read_repository_file)
        if lineage is not None:
            inputs.update(lineage)
    return inputs


def read_repository_file(relative: str) -> bytes | None:
    """A tracked input's bytes from the working tree, or None when it does not exist."""
    path = REPO_ROOT / relative
    return path.read_bytes() if path.is_file() else None


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
    if platform == "macos" and outer.get("benchmarkKind") == "ui-perf":
        # UI acceptance runs the optimized cache, not the development cache.
        # Bind publication to the run-owned receipt rather than guessing a bundle.
        try:
            receipt = load_build_provenance(
                artifact_dir / "last-build.json", platform="macos", root=REPO_ROOT,
                producer_prefix="scripts/ui_test.sh macos perf",
            )
        except ProvenanceError as error:
            raise HistoryError(f"macOS ui-perf app identity is unproven: {error}") from error
        executable = Path(receipt["executableRelativePath"])
        outer = {
            **outer,
            "optimization": receipt["optimization"],
            "appBundleRelativePath": str(executable.parents[2]),
            "executableRelativePaths": {"Vocello": str(executable)},
        }
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


# How a record's `cells` summarize its takes (`evidence.cellAggregateVersion`;
# absent means 1, so every stored record keeps its aggregates).
# 1: every take of a cell; an IQR from two or more takes (0 for one).
# 2 (2026-09-25, audit #30): a take flagged `followsColdTake` (the first warm
#    take after a cold take, which pays a settling cost) stays in the record
#    but out of its cell's statistics, and an IQR is published only from at
#    least four takes (None below).
CELL_AGGREGATE_VERSIONS = frozenset({1, 2})
CURRENT_CELL_AGGREGATE_VERSION = 2
IQR_MINIMUM_COUNT = 4


def cell_aggregate_version(record: dict[str, Any]) -> int:
    version = (record.get("evidence") or {}).get("cellAggregateVersion", 1)
    if isinstance(version, bool) or version not in CELL_AGGREGATE_VERSIONS:
        raise HistoryError(f"evidence.cellAggregateVersion is unsupported: {version!r}")
    return int(version)


def metric_summary(values: list[float], version: int = 1) -> dict[str, float | int | None]:
    ordered = sorted(values)
    iqr: float | None
    if version >= 2 and len(ordered) < IQR_MINIMUM_COUNT:
        iqr = None
    elif len(ordered) >= 2:
        quartiles = statistics.quantiles(ordered, n=4, method="inclusive")
        iqr = quartiles[2] - quartiles[0]
    else:
        iqr = 0.0
    return {
        "count": len(ordered), "median": statistics.median(ordered), "iqr": iqr,
        "min": ordered[0], "max": ordered[-1],
    }


def aggregate_cells(takes: list[dict[str, Any]], version: int = 1) -> list[dict[str, Any]]:
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
            if version >= 2 and take.get("followsColdTake") is True:
                continue
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
            "statistics": {name: metric_summary(values, version) for name, values in sorted(metrics.items())},
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
            "maximumRetainedGrowthFraction", "retentionPassed", "retainedMemoryV2",
        ):
            if key in evidence:
                payload[key] = evidence[key]
    return sha256_bytes(canonical_bytes(payload))


def comparison_key(record: dict[str, Any]) -> str:
    """The comparison lineage key: the legacy key, or the frozen composition of the
    record's lineage contract version (lib/lineage_identity.py, audit #22).

    A published version's composition never changes: a new identity field or a
    changed meaning bumps LINEAGE_CONTRACT_VERSION and adds a branch to
    lineage_comparison_identity."""
    version = record["inputs"].get("lineageContractVersion")
    if version is None:
        return legacy_comparison_key(record)
    return sha256_bytes(canonical_bytes(lineage_comparison_identity(record)))


def lineage_comparison_identity(record: dict[str, Any]) -> dict[str, Any]:
    """The frozen identity of a lineage-stamped record's contract version."""
    version = record["inputs"].get("lineageContractVersion")
    if version == 1:
        return lineage_v1_identity(record)
    if version == 2:
        return lineage_v2_identity(record)
    raise HistoryError(f"inputs.lineageContractVersion is unsupported: {version!r}")


def lineage_v1_comparison_key(record: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(lineage_v1_identity(record)))


def lineage_v2_comparison_key(record: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes(lineage_v2_identity(record)))


def lineage_v2_identity(record: dict[str, Any]) -> dict[str, Any]:
    """Lineage contract v2: contract v1 plus the forced or emulated memory tier,
    the run's seed policy and the cell aggregate version (audit #11 option b,
    #29, #30).

    A forced class or an emulated smaller Mac keys apart from the host it ran
    on (a native tier adds None, so native records key alike with or without
    run.runtimePolicy), a seeded matrix (run.seedPolicy) never shares a
    lineage with random per-take seeds, and cells that leave the take after a
    cold take out of their medians never compare with cells that kept it.
    Contract-1 records keep their keys.

    A record at all three defaults (a native tier, no seed policy, aggregate 1)
    measures what contract 1 measured, so it keeps the contract-1 identity and
    continues that lineage: the next engine gate record takes its baseline from
    the contract-1 gate records. Only the non-default values key apart: a
    forced tier never publishes comparably (validate_runtime_policy), and a
    contract-1 record cannot carry a seed policy or aggregate 2
    (validate_lineage_inputs)."""
    identity = lineage_v1_identity(record)
    runtime_policy = lineage_identity.runtime_policy_identity(record["run"])
    seed_policy = record["run"].get("seedPolicy")
    # How the cells summarize the takes (audit #30): the medians differ.
    aggregate_version = record["evidence"].get("cellAggregateVersion", 1)
    if runtime_policy is None and seed_policy is None and aggregate_version == 1:
        return identity
    identity["lineageContractVersion"] = 2
    identity["runtimePolicy"] = runtime_policy
    identity["seedPolicy"] = seed_policy
    identity["cellAggregateVersion"] = aggregate_version
    return identity


def lineage_v1_identity(record: dict[str, Any]) -> dict[str, Any]:
    """Lineage contract v1: what the record kind measures, not the whole tree.

    Against the legacy key it drops what does not change a measurement: the app
    version labels, the product contract (the models are keyed exactly below),
    the dependency lock and the whole-tree projectInputHash/harnessHash (engine
    and harness churn). It adds the kind's reviewed measurement version, the
    build-settings subset of project.yml its lane builds, the topology (the
    take layer set) and the memory contract version, which the legacy key read
    only through the whole-tree hashes. lineageHarnessHash is provenance only
    (HISTORY marks it)."""
    inputs = record["inputs"]
    return {
        "lineageContractVersion": 1,
        "lineageMeasurementVersion": inputs["lineageMeasurementVersion"],
        "kind": record["run"]["kind"],
        "platform": record["run"]["platform"],
        "matrixScope": record["run"]["matrixScope"],
        "hardware": record["hardware"]["profileID"],
        "os": [record["hardware"].get("osVersion"), record["hardware"].get("osBuild")],
        "toolchain": [
            record["toolchain"].get("xcodeBuild"), record["toolchain"].get("sdkVersion"),
            record["toolchain"].get("optimization"),
        ],
        "matrixHash": inputs["matrixHash"],
        "inputIdentity": [
            inputs.get("lineageProjectHash"),
            None if record["run"]["kind"] in lineage_identity.CORPUS_FREE_KINDS
            else inputs.get("corpusHash"),
            inputs.get("analysisProfileHash"),
        ],
        "topology": lineage_identity.topology(record.get("takes", [])),
        "models": [
            [
                model.get("mode"), model.get("modelID"), model.get("variant"),
                model.get("quantization"), model.get("revision"), model.get("artifactVersion"),
                model.get("integrityDigest"), model.get("runtimeProfileSignature"),
                model.get("fixtureDigest"),
            ]
            for model in record.get("models", [])
        ],
        # The memory contract names the memory aggregation (audit #1): a change of
        # it never shares a lineage, whatever the kind's measurement version says.
        "evidenceContract": [
            record.get("schemaVersion"), record["evidence"].get("validatorSchemaVersion"),
            record["evidence"].get("telemetrySchemaVersion"),
            record["evidence"].get("qcAlgorithmVersion"),
            record["evidence"].get("memoryContractVersion"),
        ],
        "rtfDefinition": record["run"].get("rtfDefinition"),
        "ttfcDefinition": record["run"].get("ttfcDefinition"),
    }


def legacy_comparison_key(record: dict[str, Any]) -> str:
    """The key of every record without a lineage contract version; frozen byte for byte."""
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
    # A standard-RTF record never shares a comparison lineage with a legacy
    # speedup record. Legacy keys stay byte-identical (no key when absent).
    definition = record["run"].get("rtfDefinition")
    if definition:
        comparable_identity["rtfDefinition"] = definition
    # Likewise the two first-chunk definitions never share a lineage (audit #59).
    ttfc_definition = record["run"].get("ttfcDefinition")
    if ttfc_definition:
        comparable_identity["ttfcDefinition"] = ttfc_definition
    # The memory aggregation marker: a contract-v2 series (one per process)
    # never shares a lineage with a v1 aggregate (macOS UI v1 summed two
    # samplers of one process), whatever the harness paths hash. Contract v1
    # records keep their keys byte-identical (no key).
    memory_contract = record["evidence"].get("memoryContractVersion")
    if isinstance(memory_contract, int) and not isinstance(memory_contract, bool) and memory_contract >= 2:
        comparable_identity["memoryContractVersion"] = memory_contract
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


# `comparison.deltaMetrics: "trend-v1"` restricts a record's stored deltas to the
# metrics something actually reads (the index trend line, the RTF and memory
# gates, first-chunk and playback latency, the played-audio comparison). A
# full 11-cell record carried 75 metrics × 4 floats of deltas (about 90 KB)
# and overflowed the 256 KiB record contract on the second canonical
# captured run; records without the declaration keep their full blocks.
COMPARISON_DELTA_METRICS = {
    "trend-v1": frozenset({
        "rtf", "decodeSpeedupX", "ttfcMS", "peakPhysicalFootprintMB", "physicalFootprintEndMB",
        "submitToFirstChunkMS", "playbackScheduledMS", "submitToCompletedMS",
        "stepBurstPeakCount", "playbackCaptureFirstAudibleMS", "playbackCaptureAlignmentMS",
        "playbackCaptureResidualDBFS", "playbackCaptureDropoutCount", "playbackCaptureMaxGapMS",
        "playbackCaptureCoverage", "playbackCaptureStepBurstPeakCount",
    }),
}
DEFAULT_COMPARISON_DELTA_METRICS = "trend-v1"


def allowed_delta_metrics(record: dict[str, Any]) -> frozenset[str] | None:
    """The metric allowlist a record declares for its stored deltas; None means every metric."""
    declared = (record.get("comparison") or {}).get("deltaMetrics")
    if declared is None:
        return None
    if declared not in COMPARISON_DELTA_METRICS:
        raise HistoryError(f"comparison.deltaMetrics is unknown: {declared!r}")
    return COMPARISON_DELTA_METRICS[declared]


def comparison_deltas(
    record: dict[str, Any], baseline: dict[str, Any],
) -> dict[str, dict[str, dict[str, float]]]:
    baseline_cells = {cell["key"]: cell for cell in baseline.get("cells", [])}
    allowed = allowed_delta_metrics(record)
    deltas: dict[str, dict[str, dict[str, float]]] = {}
    for cell in record.get("cells", []):
        prior = baseline_cells.get(cell["key"])
        if not prior:
            continue
        metric_deltas: dict[str, dict[str, float]] = {}
        for metric, current_summary in cell.get("statistics", {}).items():
            if allowed is not None and metric not in allowed:
                continue
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
    *, keys: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Derive comparison metadata from record content, independent of arrival order.

    `keys` maps `id(record)` to its precomputed comparison key, so reconciling
    the registry computes each key once instead of once per pair of records."""
    def key_of(candidate: dict[str, Any]) -> str:
        cached = keys.get(id(candidate)) if keys is not None else None
        return cached if cached is not None else comparison_key(candidate)

    key = key_of(record)
    expected: dict[str, Any] = {
        "key": key,
        "comparable": record_is_comparable(record),
        "baselineRunID": None,
        "deltas": {},
    }
    declared = (record.get("comparison") or {}).get("deltaMetrics")
    if declared is not None:
        expected["deltaMetrics"] = declared
    if not expected["comparable"]:
        return expected
    current_order = (record["run"]["finishedAt"], record["run"]["id"])
    candidates = [
        candidate for _, candidate in existing
        if candidate.get("run", {}).get("id") != record["run"]["id"]
        and record_is_comparable(candidate)
        and key_of(candidate) == key
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
        "retainedMemoryV2",
    ):
        if key not in evidence and key in outer:
            evidence[key] = outer[key]
    if "screenshotDigests" not in evidence:
        evidence["screenshotDigests"] = outer.get("screenshotDigests") or screenshot_digests(artifact_dir)
    evidence["selectedEvidenceDigest"] = selected_evidence_digest(record)

    if not record.get("cells"):
        record["cells"] = aggregate_cells(record["takes"], cell_aggregate_version(record))
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
    # New v2+ records store only the trend metrics' deltas (see
    # COMPARISON_DELTA_METRICS); the legacy v1 shape never carries the key.
    if int(record.get("schemaVersion", 1)) >= 2:
        comparison.setdefault("deltaMetrics", DEFAULT_COMPARISON_DELTA_METRICS)
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


def language_families(record: dict[str, Any]) -> list[str]:
    """The recognizer families a language record cites; legacy records are Apple Speech."""
    evidence = record.get("evidence") if isinstance(record.get("evidence"), dict) else {}
    verification = evidence.get("languageVerification")
    if not isinstance(verification, dict) or "families" not in verification:
        return list(LEGACY_LANGUAGE_FAMILIES)
    families = verification["families"]
    if (
        not isinstance(families, list) or not families
        or any(family not in RECOGNITION_FAMILIES for family in families)
        or families != sorted(set(families))
    ):
        raise HistoryError("evidence.languageVerification.families must list known families once, sorted")
    return list(families)


def validate_segmentation_aware_metrics(
    metrics: dict[str, Any], aware_key: str, boundary_key: str, *, plain_rate: float,
    plain_edits: float | None = None, reference_count: Any = None,
) -> None:
    """One family's WER v2 decomposition (audit #43).

    The segmentation-aware rate never exceeds the plain rate; the credited
    boundary edits are a whole count; with the family's edit counts published,
    the v2 rate is exactly the plain edits less the credited ones.
    """
    if aware_key not in metrics or boundary_key not in metrics:
        raise HistoryError("segmentation-aware word metrics are incomplete")
    aware, boundary = float(metrics[aware_key]), float(metrics[boundary_key])
    if aware < 0 or aware > plain_rate + 1e-12 or boundary < 0 or not boundary.is_integer():
        raise HistoryError("segmentation-aware word metrics are inconsistent")
    if plain_edits is not None and isinstance(reference_count, (int, float)) and reference_count > 0:
        if boundary > plain_edits or not math.isclose(
            aware, (plain_edits - boundary) / float(reference_count), rel_tol=1e-9, abs_tol=1e-12,
        ):
            raise HistoryError("segmentation-aware word rate does not match its credited edits")


def validate_channel_consensus(
    takes: list[dict[str, Any]],
    language_verification: dict[str, Any] | None,
    families: list[str],
    negative_control_count: int,
) -> None:
    """Per-channel two-family consensus and the accuracy control (audit #42).

    A take's `channelConsensus` must be the family rule applied to the
    per-family verdicts it publishes, channel by channel, and must meet the
    take's declared outcome; the run's `channelVerdicts` must follow from them.
    """
    verification = language_verification if isinstance(language_verification, dict) else {}
    if "negativeControlKind" in verification and (
        verification["negativeControlKind"] != NEGATIVE_CONTROL_KIND or negative_control_count == 0
    ):
        raise HistoryError("negativeControlKind must declare the accuracy control of a run that has one")
    voted: list[tuple[dict[str, str], bool]] = []
    for take in takes:
        statuses = take.get("channelConsensus")
        if statuses is None:
            continue
        if (
            not isinstance(statuses, dict) or set(statuses) != set(LANGUAGE_CHANNELS)
            or any(value not in CHANNEL_STATUSES for value in statuses.values())
        ):
            raise HistoryError("take.channelConsensus must give each channel a consensus status")
        if "accuracyMetric" not in take or len(families) < 2 or any(
            family not in FAMILY_CHANNEL_METRICS for family in families
        ):
            raise HistoryError("take.channelConsensus requires two cited families that scored the take")
        metrics = take.get("metrics") or {}
        family_channels: dict[str, dict[str, bool]] = {}
        for family in families:
            keys = FAMILY_CHANNEL_METRICS[family]
            if any(metrics.get(keys[channel]) not in (0.0, 1.0) for channel in LANGUAGE_CHANNELS):
                raise HistoryError("take.channelConsensus lacks a family's channel verdicts")
            family_channels[family] = {
                channel: metrics[keys[channel]] == 1.0 for channel in LANGUAGE_CHANNELS
            }
        expect_failure = take.get("expectedOutcome") == "fail"
        agreement = channel_consensus(family_channels, expect_failure=expect_failure)
        if agreement["statuses"] != statuses:
            raise HistoryError("take.channelConsensus does not follow from its families' verdicts")
        if agreement["outcome"] != "met":
            raise HistoryError("take.channelConsensus does not meet the take's declared outcome")
        voted.append((statuses, expect_failure))
    has_run_verdict = "channelVerdicts" in verification or "channelConsensusAlgorithm" in verification
    if not has_run_verdict:
        if voted:
            raise HistoryError("take.channelConsensus requires the run's channelVerdicts")
        return
    if (
        verification.get("channelConsensusAlgorithm") != CHANNEL_CONSENSUS_ALGORITHM
        or not voted
        or len(voted) != sum(1 for take in takes if "accuracyMetric" in take)
        or verification.get("channelVerdicts") != run_channel_verdicts(voted)
    ):
        raise HistoryError("channelVerdicts must follow from every scored take's channel consensus")


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
    definition = rtf_semantics.record_definition(record)
    for mode, limit in (("lightweight", 5.0), ("verbose", 10.0)):
        candidate_rtf = statistics.median(metrics_by_mode[mode]["rtf"])
        candidate_ttfc = statistics.median(metrics_by_mode[mode]["ttfcMS"])
        rtf_regression = rtf_semantics.regression_percent(baseline_rtf, candidate_rtf, definition)
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
    if not required_metrics <= set(take["metrics"]) <= required_metrics | {"analyzerAlgorithmVersion"}:
        raise HistoryError("prosody calibration aggregate metrics are incomplete")
    analyzer_version = take["metrics"].get("analyzerAlgorithmVersion")
    if analyzer_version is not None and (analyzer_version < 1 or not float(analyzer_version).is_integer()):
        raise HistoryError("prosody calibration analyzerAlgorithmVersion must be a positive integer")
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
    allowed_sets = [expected_scenarios, expected_scenarios - UI_PERF_SCENARIOS_ADDED[run["platform"]]]
    if len(set(scenarios)) != len(takes) or set(scenarios) not in allowed_sets:
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
        # Memory profiles since 2026-09-25 (audit #69).
        "keptByDefault": True,
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
    if capture_settings["profileKind"] not in TRACE_PROFILE_KINDS:
        raise HistoryError("trace captureSettings.profileKind is unsupported")
    if retention_policy == "keptByDefault" and capture_settings["profileKind"] != "memory":
        raise HistoryError("only a memory profile keeps its raw trace by default")
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
    expected_kind = (
        "memory" if memory_profile
        else "witness" if trace.get("template") == WITNESS_TRACE_TEMPLATE
        else "cpu"
    )
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
    capture_settings = trace.get("captureSettings")
    witness = (
        isinstance(capture_settings, dict) and capture_settings.get("profileKind") == "witness"
    )
    required = SCHEMA_REQUIRED_KEYS["traceSummary"]
    if witness:
        required = required - CPU_TRACE_SUMMARY_KEYS
        if CPU_SAMPLER_TRACE_SUMMARY_KEYS.intersection(summary):
            raise HistoryError("a witness trace summary carries CPU sampler evidence")
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
        "capturedDataRowCount", "processCount", "schemaCount",
        "signpostEventCount", "signpostSchemaCount", "tableCount",
    }
    if not witness:
        count_fields.add("cpuSampleCount")
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
    # The capture label names the sampler whose table the CPU rows came from,
    # and on the Mac the sampler follows the measurement version, so a CPU
    # Profiler and a Time Profiler capture never share a comparison key.
    template = str(trace.get("template", ""))
    named = {name for name in TRACE_CPU_SAMPLER_SCHEMAS.values() if name in template}
    sampled = {name for schema, name in TRACE_CPU_SAMPLER_SCHEMAS.items() if rows.get(schema)}
    if named != sampled:
        raise HistoryError("trace CPU sampler rows do not match the sampler its template names")
    if named and (record.get("run") or {}).get("platform") == "macos":
        measurement = (record.get("inputs") or {}).get("lineageMeasurementVersion")
        time_profiler_era = (
            isinstance(measurement, int) and not isinstance(measurement, bool)
            and measurement >= MACOS_TIME_PROFILER_MEASUREMENT_VERSION
        )
        if named != {"Time Profiler" if time_profiler_era else "CPU Profiler"}:
            raise HistoryError(
                "a macOS profile samples with Time Profiler from instrument-profile measurement "
                f"version {MACOS_TIME_PROFILER_MEASUREMENT_VERSION} and with CPU Profiler before it"
            )
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
    signpost_rows = sum(value for name, value in rows.items() if "signpost" in name.lower())
    if cpu_rows != summary.get("cpuSampleCount", 0) or signpost_rows != summary["signpostEventCount"]:
        raise HistoryError("trace summary row counts do not match CPU/signpost totals")
    if sum(rows.values()) != summary["capturedDataRowCount"]:
        raise HistoryError("trace summary captured-row total is inconsistent")
    if not witness:
        if not isinstance(summary["cpuSampleSpanMS"], (int, float)) or summary["cpuSampleSpanMS"] <= 0:
            raise HistoryError("trace summary CPU sample span is empty")
        weight = summary.get("cpuCycleWeight", summary.get("cpuSampleWeightMS"))
        if not isinstance(weight, (int, float)) or isinstance(weight, bool) or weight <= 0:
            raise HistoryError("trace summary lacks positive CPU sample weight")
    if "cpuPlausibility" in summary:
        try:
            trace_cpu.validate_cpu_plausibility(
                summary["cpuPlausibility"],
                take_indices=[take.get("takeIndex") for take in record["takes"]],
            )
        except ValueError as error:
            raise HistoryError(str(error)) from error
    signpost_keys = SIGNPOST_TRACE_SUMMARY_KEYS.intersection(summary)
    if witness and not signpost_keys:
        raise HistoryError("a witness trace summary lacks its per-take interval statistics")
    if signpost_keys:
        if missing := sorted(
            SIGNPOST_TRACE_SUMMARY_KEYS - {"recordedDurationSeconds"} - signpost_keys
        ):
            raise HistoryError("trace signpost summary is missing: " + ", ".join(missing))
        try:
            trace_intervals.validate_signpost_summary(
                summary,
                take_indices=[take.get("takeIndex") for take in record["takes"]],
                # A macOS profile publishes its statistics only when every take
                # kept 36 decode-loop intervals per step it ran.
                require_complete=record["run"].get("platform") == "macos",
            )
        except ValueError as error:
            raise HistoryError(str(error)) from error
        interval_rows = sum(
            value for name, value in rows.items()
            if name.lower() in {"os-signpost-interval", "ossignpostintervals"}
        )
        if summary["signpostIntervalCount"] != interval_rows:
            raise HistoryError("trace summary interval count does not match its exported rows")


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
        if version == 1 and section == "run":
            allowed = allowed - V2_ONLY_RUN_KEYS
        if version == 1 and section == "inputs":
            allowed = allowed - LINEAGE_INPUT_KEYS
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
    definition = run.get("rtfDefinition")
    if definition is not None and definition != rtf_semantics.STANDARD_RTF_DEFINITION:
        raise HistoryError("run.rtfDefinition must be \"wall/audio\" when present")
    if (
        definition is None
        and run["kind"] in RTF_BEARING_KINDS
        and run["finishedAt"] >= rtf_semantics.RTF_DEFINITION_CUTOVER
    ):
        raise HistoryError(
            "records published since the RTF cutover must declare run.rtfDefinition"
        )
    ttfc_definition = run.get("ttfcDefinition")
    if ttfc_definition is not None:
        if ttfc_definition not in rtf_semantics.TTFC_DEFINITIONS:
            raise HistoryError("run.ttfcDefinition is not a known first-chunk definition")
        if not any(
            "ttfcMS" in (take.get("metrics") or {})
            for take in record.get("takes", []) if isinstance(take, dict)
        ):
            raise HistoryError("run.ttfcDefinition declares a ttfcMS that no take carries")
    if "runtimePolicy" in run:
        validate_runtime_policy(run)
    if "seedPolicy" in run:
        validate_seed_policy(record)

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

    for key in sorted(SECTION_KEYS["inputs"] - LINEAGE_INPUT_KEYS):
        if key not in record["inputs"]:
            raise HistoryError(f"inputs is missing: {key}")
        require_digest(record["inputs"][key], f"inputs.{key}")
    validate_lineage_inputs(record)

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
    negative_control_count = 0
    declared_verification = record["evidence"].get("languageVerification")
    # The gated word score under the record's accuracy metric version (v2 and
    # v3: segmentation-aware, audit #43); v1 records keep the plain rate. Each
    # version is validated under its own rules, so legacy records keep theirs.
    declared_metric_version = (
        declared_verification.get("accuracyMetricVersion")
        if isinstance(declared_verification, dict) else None
    )
    segmentation_aware = declared_metric_version in SEGMENTATION_AWARE_METRIC_VERSIONS
    # Filler counts exist only under text normalization v2 (accuracy metric v3).
    counts_fillers = (
        declared_metric_version in ACCURACY_METRIC_VERSIONS
        and ACCURACY_METRIC_NORMALIZATIONS[declared_metric_version] == TEXT_NORMALIZATION_V2
    )
    # Records since 2026-09-25 declare the negative control an accuracy control
    # (audit #42): it must fail on accuracy; its language check is reported only.
    accuracy_control = isinstance(declared_verification, dict) and (
        declared_verification.get("negativeControlKind") == NEGATIVE_CONTROL_KIND
    )
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
        if take.get("expectedOutcome", "pass") not in {"pass", "fail"}:
            raise HistoryError("take expectedOutcome is invalid")
        capture_status = take.get("playbackCaptureStatus")
        if capture_status is not None and capture_status not in PLAYBACK_CAPTURE_STATUSES:
            raise HistoryError("take playbackCaptureStatus is invalid")
        if "playbackCaptureDigest" in take:
            if capture_status not in {"captured", "silent", "referenceUnresolved"}:
                raise HistoryError("take playbackCaptureDigest requires a captured take")
            require_digest(take["playbackCaptureDigest"], "take.playbackCaptureDigest", allow_na=False)
        if capture_status != "captured" and any(
            key.startswith("playbackCapture") and key not in (
                "playbackCaptureFirstAudibleMS", "playbackCaptureStepBurstPeakCount",
            ) for key in take.get("metrics", {})
        ):
            raise HistoryError("playback capture comparison metrics require a captured take")
        if take.get("expectedOutcome") == "fail" and "accuracyMetric" not in take:
            raise HistoryError("a negative-control take needs its language accuracy gate")
        # A negative control (a pinned hint over a script in another language)
        # is evidence only when its output verification ran and failed.
        negative_control = take.get("expectedOutcome") == "fail"
        if negative_control:
            negative_control_count += 1
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
        startup_keys = (*rtf_semantics.STARTUP_WINDOW_KEYS, "excludedStartupMS")
        present_startup = [key for key in startup_keys if key in take["metrics"]]
        if present_startup:
            windows = [float(take["metrics"].get(key, -1)) for key in startup_keys]
            if (
                len(present_startup) != len(startup_keys)
                or any(value < 0 for value in windows)
                or not math.isclose(windows[-1], sum(windows[:-1]), rel_tol=0, abs_tol=1e-6)
            ):
                raise HistoryError(
                    "startup windows must be complete, non-negative and sum to excludedStartupMS"
                )
        if version >= 2 and run["kind"] in MEMORY_QUALIFIED_KINDS:
            memory_contract = record["evidence"].get("memoryContractVersion")
            required_memory = set(MEMORY_REQUIRED_METRICS)
            if run["platform"] == "ios":
                required_memory |= IOS_MEMORY_REQUIRED_METRICS
            if memory_contract == 1 and run["kind"] == "ui-generation" and run["platform"] == "macos":
                required_memory |= MACOS_UI_MEMORY_REQUIRED_METRICS
            if memory_contract == 2:
                required_memory |= MEMORY_V2_REQUIRED_METRICS
            if missing := sorted(required_memory - set(take["metrics"])):
                raise HistoryError(
                    "memory-qualified take metrics are incomplete: " + ", ".join(missing)
                )
            metrics = take["metrics"]
            if memory_contract == 2:
                validate_memory_contract_v2_take(metrics)
            else:
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
            if "policyCacheClearCount" in metrics and not (
                float(metrics["policyCacheClearCount"]).is_integer()
                and 0 <= metrics["policyCacheClearCount"] <= metrics["memoryTrimCount"]
            ):
                raise HistoryError("policyCacheClearCount must be a subset of memoryTrimCount")
            has_memory_warning = any(
                warning.startswith("memory.") for warning in take.get("warnings", [])
            )
            expected_memory_status = "qualifiedWithWarnings" if has_memory_warning else "qualified"
            if take["memoryStatus"] != expected_memory_status:
                raise HistoryError("take memory status does not match its memory warnings")
        for key in (*DELETION_RUN_METRIC_KEYS, *FILLER_COUNT_METRIC_KEYS):
            if key in take["metrics"] and (
                not float(take["metrics"][key]).is_integer() or take["metrics"][key] < 0
            ):
                raise HistoryError(f"take metric {key} must be a nonnegative count")
        if not counts_fillers and any(key in take["metrics"] for key in FILLER_COUNT_METRIC_KEYS):
            raise HistoryError("filler counts require text normalization v2 (accuracy metric v3)")
        if "accuracyMetric" in take and "whisper" in language_families(record):
            metrics = take["metrics"]
            if missing := sorted(INDEPENDENT_ACCURACY_METRIC_KEYS - set(metrics)):
                raise HistoryError(
                    "independent recognition metrics are incomplete: " + ", ".join(missing)
                )
            metric = take["accuracyMetric"]
            independent_score = metrics["independent" + metric[0].upper() + metric[1:]]
            if segmentation_aware:
                aware_key, boundary_key = SEGMENTATION_AWARE_METRIC_KEYS["whisper"]
                validate_segmentation_aware_metrics(
                    metrics, aware_key, boundary_key, plain_rate=float(metrics["independentWordErrorRate"]),
                )
                if metric == "wordErrorRate":
                    independent_score = metrics[aware_key]
            independent_within = float(independent_score) <= float(take["accuracyThreshold"])
            if (
                not math.isclose(
                    float(metrics["independentPrimaryAccuracyScore"]), float(independent_score),
                    rel_tol=1e-9, abs_tol=1e-12,
                )
                or (metrics["independentAccuracyPass"] == 1.0) != independent_within
                or metrics["independentLanguagePass"] not in (0.0, 1.0)
                or not 0.0 <= float(metrics["independentLanguageMatchScore"]) <= 1.0
                or float(metrics["independentRecognitionDurationSeconds"]) <= 0
                or not 0.0 <= float(metrics.get("independentMaximumNoSpeechProbability", 0.0)) <= 1.0
                or float(metrics.get("independentMeanAverageLogProbability", 0.0)) > 0.0
            ):
                raise HistoryError("independent recognition gate metrics are inconsistent")
            independent_passed = (
                metrics["independentLanguagePass"] == 1.0 and metrics["independentAccuracyPass"] == 1.0
            )
            if negative_control and independent_passed:
                raise HistoryError("negative-control take passed its independent verification")
            if negative_control and accuracy_control and metrics["independentAccuracyPass"] != 0.0:
                raise HistoryError("accuracy-control take passed its independent accuracy check")
            if not negative_control and not independent_passed:
                raise HistoryError("independent recognition gate metrics are inconsistent")
        if "accuracyMetric" in take and "apple-speech" not in language_families(record):
            if present := sorted((LANGUAGE_ACCURACY_METRIC_KEYS - {"accuracyThreshold"}) & set(take["metrics"])):
                raise HistoryError(
                    "in-app recognizer metrics without the apple-speech family: " + ", ".join(present)
                )
        if "accuracyMetric" in take and "apple-speech" in language_families(record):
            metrics = take["metrics"]
            if missing := sorted(LANGUAGE_ACCURACY_METRIC_KEYS - set(metrics)):
                raise HistoryError(
                    "language accuracy metrics are incomplete: " + ", ".join(missing)
                )
            selected_score = metrics[take["accuracyMetric"]]
            if segmentation_aware:
                aware_key, boundary_key = SEGMENTATION_AWARE_METRIC_KEYS["apple-speech"]
                validate_segmentation_aware_metrics(
                    metrics, aware_key, boundary_key, plain_rate=float(metrics["wordErrorRate"]),
                    plain_edits=sum(metrics.get(key, -1) for key in ("substitutions", "insertions", "deletions")),
                    reference_count=metrics.get("referenceTokenCount"),
                )
                if take["accuracyMetric"] == "wordErrorRate":
                    selected_score = metrics[aware_key]
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
                or (metrics["outputAccuracyPass"] == 1.0)
                != (float(selected_score) <= float(take["accuracyThreshold"]))
                or metrics["outputLanguagePass"] not in (0.0, 1.0)
                or not (0.0 if negative_control else 0.5) <= metrics["languageMatchScore"] <= 1.0
                or metrics["recognitionPassCount"] != 3.0
                or metrics["recognitionDurationSeconds"] <= 0
            ):
                raise HistoryError("language accuracy gate metrics are inconsistent")
            output_passed = metrics["outputLanguagePass"] == 1.0 and metrics["outputAccuracyPass"] == 1.0
            if negative_control and output_passed:
                raise HistoryError("negative-control take passed its in-app verification")
            if negative_control and accuracy_control and metrics["outputAccuracyPass"] != 0.0:
                raise HistoryError("accuracy-control take passed its in-app accuracy check")
            if not negative_control and not output_passed:
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
    families = language_families(record)
    expected_language_verification = dict(
        APPLE_SPEECH_VERIFICATION_IDENTITY if "apple-speech" in families
        else INDEPENDENT_VERIFICATION_IDENTITY
    )
    if isinstance(language_verification, dict) and language_verification.get(
        "accuracyMetricVersion"
    ) in ACCURACY_METRIC_VERSIONS:
        # Every record keeps the version it declares: v1, WER v2 (records since
        # 2026-09-25, audit #43) or v3 (text normalization v2, AQ-02).
        expected_language_verification["accuracyMetricVersion"] = language_verification["accuracyMetricVersion"]
    if accuracy_evidence_required and (
        run["kind"] != "language" or language_verification is None
        or {key: language_verification.get(key) for key in LANGUAGE_VERIFICATION_IDENTITY_KEYS}
        != expected_language_verification
    ):
        raise HistoryError("language accuracy takes require exact verifier provenance")
    if language_verification is not None:
        has_independent = "independentRecognitionAlgorithm" in language_verification
        if has_independent != ("whisper" in families) or (has_independent and (
            language_verification["independentRecognitionAlgorithm"]
            != INDEPENDENT_VERIFICATION_IDENTITY["recognitionAlgorithm"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(language_verification.get("independentModelIdentitySHA256")))
        )):
            raise HistoryError("independent recognizer provenance does not match the declared families")
    if language_verification is not None and run["kind"] != "language":
        raise HistoryError("language verifier provenance belongs only to language records")
    if (
        language_verification is not None
        and "negativeControlsConfirmed" in language_verification
        and language_verification["negativeControlsConfirmed"] != negative_control_count
    ):
        raise HistoryError("negativeControlsConfirmed does not match the negative-control takes")
    if language_verification is not None and "languageCheckKinds" in language_verification:
        if language_verification["languageCheckKinds"] != {
            family: LANGUAGE_CHECK_KINDS[family] for family in families
        }:
            raise HistoryError("languageCheckKinds must declare exactly the cited families' checks")
    for take in takes:
        detected = take.get("detectedLanguages")
        if detected is None:
            continue
        if (
            not isinstance(detected, dict) or not detected
            or any(family not in families for family in detected)
            or not all(
                isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9-]{1,31}", value)
                for value in detected.values()
            )
        ):
            raise HistoryError("take.detectedLanguages must map cited families to language names")
    validate_channel_consensus(takes, language_verification, families, negative_control_count)

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
    aggregate_version = cell_aggregate_version(record)
    if aggregate_version >= 2 and version < 2:
        raise HistoryError("schema-v1 records cannot declare a cell aggregate version")
    validate_cold_take_flags(takes, aggregate_version)
    if cells != aggregate_cells(takes, aggregate_version):
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
        if (
            evidence.get("memoryContractVersion") not in MEMORY_CONTRACT_VERSIONS
            or isinstance(evidence.get("memoryContractVersion"), bool)
            or evidence.get("memoryQualified") is not True
        ):
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
        if "retainedMemoryV2" in evidence:
            validate_retained_memory_v2(evidence["retainedMemoryV2"], takes)
    elif "retainedMemoryV2" in evidence:
        raise HistoryError("retainedMemoryV2 belongs only to a memory-qualification record")
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
    allowed_delta_metrics(record)   # an unknown declaration is an error
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
    # The key reads only non-comparison content, so it is computed once per record.
    keys = {id(record): comparison_key(record) for _, record in records}
    for path, record in records:
        expected = expected_comparison_metadata(record, records, keys=keys)
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


RETAINED_MEMORY_V2_MODES = ("custom", "design", "clone")


def validate_retained_memory_v2(block: Any, takes: list[dict[str, Any]]) -> None:
    """retained-memory-v2 evidence must recompute from the takes' end-of-take MLX values."""
    if not isinstance(block, dict):
        raise HistoryError("retainedMemoryV2 must be an object")
    calibration = block.get("calibration")
    growth_by_mode = block.get("growthByModeMB")
    if (
        block.get("policyID") != "retained-memory-v2"
        or block.get("metric") != "withinModeRetainedMLXActiveGrowth"
        or calibration not in {"uncalibrated", "calibrated"}
        or not isinstance(growth_by_mode, dict)
        or set(growth_by_mode) != set(RETAINED_MEMORY_V2_MODES)
    ):
        raise HistoryError("retainedMemoryV2 identity is invalid")
    for mode in RETAINED_MEMORY_V2_MODES:
        ends = [
            (take.get("metrics") or {}).get("mlxEndActiveMB")
            for take in takes
            if take.get("mode") == mode and "/retained#" in str(take.get("cell"))
        ]
        if len(ends) < 2 or not all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
            for value in ends
        ):
            raise HistoryError(f"retainedMemoryV2 mode {mode} lacks end-of-take MLX values")
        expected = max(0.0, max(float(value) for value in ends[1:]) - float(ends[0]))
        if not math.isclose(float(growth_by_mode[mode]), expected, rel_tol=0, abs_tol=1e-6):
            raise HistoryError(f"retainedMemoryV2 growth for {mode} does not match its takes")
    if not math.isclose(
        float(block.get("maximumRetainedGrowthMB", -1)), max(float(value) for value in growth_by_mode.values()),
        rel_tol=0, abs_tol=1e-6,
    ):
        raise HistoryError("retainedMemoryV2 maximum does not match its modes")
    limits = block.get("growthLimitMBByMode")
    if calibration == "uncalibrated":
        if limits is not None or "passed" in block:
            raise HistoryError("an uncalibrated retainedMemoryV2 declares no bound and no verdict")
        return
    if (
        not isinstance(limits, dict)
        or set(limits) != set(RETAINED_MEMORY_V2_MODES)
        or block.get("passed") is not True
        or any(
            not isinstance(limits[mode], (int, float)) or isinstance(limits[mode], bool)
            or not float(limits[mode]) > 0
            or float(growth_by_mode[mode]) > float(limits[mode])
            for mode in RETAINED_MEMORY_V2_MODES
        )
    ):
        raise HistoryError("a calibrated retainedMemoryV2 must pass every mode's bound")


def validate_memory_contract_v2_take(metrics: dict[str, Any]) -> None:
    """Contract v2 take metrics: one series, a bounded gap and consistent peak fidelity."""
    if pairing := sorted(MACOS_UI_MEMORY_REQUIRED_METRICS & set(metrics)):
        raise HistoryError(
            "memory contract v2 gives one process one series and carries no pairing metrics: "
            + ", ".join(pairing)
        )
    if not 0 <= float(metrics["samplerCoverage"]) <= 1:
        raise HistoryError("memory sampler coverage is outside [0, 1]")
    gap = float(metrics["samplerMaximumUnobservedGapMS"])
    target = float(metrics["samplerTargetIntervalMS"])
    # The bound the publisher applied from the policy at publication; a later
    # recalibration of the policy never re-judges a published take.
    limit = float(metrics["samplerUnobservedGapLimitMS"])
    if target <= 0 or limit < target or gap < 0 or gap > limit + 1e-9:
        raise HistoryError(
            "memory-qualified take left the process unobserved for longer than its "
            "recorded unobserved-gap bound (at least one sampler cadence)"
        )
    expected_miss = max(0.0, float(metrics["mlxPeakMB"]) - float(metrics["peakGPUAllocatedMB"]))
    if not math.isclose(float(metrics["gpuPeakCaptureMissMB"]), expected_miss, rel_tol=0, abs_tol=1e-6):
        raise HistoryError("gpuPeakCaptureMissMB does not match mlxPeakMB and peakGPUAllocatedMB")
    present = KERNEL_LEDGER_METRICS & set(metrics)
    if present:
        exact = metrics.get("kernelPhysFootprintPeakExact")
        if (
            "kernelPhysFootprintPeakMB" not in metrics
            or isinstance(exact, bool)
            or exact not in (0, 1)
        ):
            raise HistoryError("the kernel footprint ledger metrics are incomplete")
        kernel_peak = float(metrics["kernelPhysFootprintPeakMB"])
        sampled_peak = float(metrics["peakPhysicalFootprintMB"])
        if kernel_peak + KERNEL_LEDGER_TOLERANCE_MB < sampled_peak:
            raise HistoryError("the kernel footprint ledger peak is below the sampled footprint peak")
        if (exact == 1) != ("footprintPeakCaptureMissMB" in metrics) or (
            exact == 1
            and not math.isclose(
                float(metrics["footprintPeakCaptureMissMB"]),
                max(0.0, kernel_peak - sampled_peak), rel_tol=0, abs_tol=1e-6,
            )
        ):
            raise HistoryError(
                "footprintPeakCaptureMissMB belongs only to an exact kernel peak and must match it"
            )


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


def sampled_peak_misses(record: dict[str, Any]) -> dict[str, Any]:
    """Takes whose sampled Metal peak sits below the exact MLX peak (audit #3).

    `mlxPeakMB` is MLX's own allocator high-water mark, reset for every
    request, and Metal-allocated memory is never below MLX's active memory.
    A sampled `peakGPUAllocatedMB` below it therefore proves that the periodic
    sampler missed the take's real peak. The footprint comparison is reported
    beside it for context only. Read-only: records are never rewritten.
    """
    compared = 0
    missed: list[dict[str, Any]] = []
    footprint_missed = 0
    for take in record.get("takes", []):
        metrics = take.get("metrics") if isinstance(take.get("metrics"), dict) else {}
        exact = metrics.get("mlxPeakMB")
        sampled = metrics.get("peakGPUAllocatedMB")
        if not all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in (exact, sampled)
        ):
            continue
        compared += 1
        footprint = metrics.get("peakPhysicalFootprintMB")
        if (
            isinstance(footprint, (int, float)) and not isinstance(footprint, bool)
            and float(footprint) < float(exact)
        ):
            footprint_missed += 1
        gap = float(exact) - float(sampled)
        if gap > 0:
            missed.append({
                "takeIndex": take.get("takeIndex"),
                "cell": take.get("cell"),
                "metalGapMB": gap,
            })
    gaps = [item["metalGapMB"] for item in missed]
    return {
        "runID": record.get("run", {}).get("id"),
        "kind": record.get("run", {}).get("kind"),
        "platform": record.get("run", {}).get("platform"),
        "comparedTakeCount": compared,
        "missedTakeCount": len(missed),
        "footprintMissedTakeCount": footprint_missed,
        "medianGapMB": statistics.median(gaps) if gaps else 0.0,
        "maximumGapMB": max(gaps, default=0.0),
        "takes": missed,
    }


def sampled_peak_warning(summary: dict[str, Any]) -> str | None:
    if not summary["missedTakeCount"]:
        return None
    return (
        f"benchmark history: WARN: {summary['runID']}: {summary['missedTakeCount']} of "
        f"{summary['comparedTakeCount']} takes sampled a Metal peak below the exact MLX peak "
        f"(median gap {summary['medianGapMB']:.0f} MB, maximum {summary['maximumGapMB']:.0f} MB); "
        "the sampled memory peaks understate those takes"
    )


def sampled_peak_report(records: list[tuple[Path, dict[str, Any]]]) -> dict[str, Any]:
    """Offline backfill of the missed-peak count over committed records."""
    per_record = [
        summary for _, record in records
        if (summary := sampled_peak_misses(record))["comparedTakeCount"]
    ]
    groups: dict[str, dict[str, Any]] = {}
    for summary in per_record:
        group = groups.setdefault(
            f"{summary['kind']}/{summary['platform']}",
            {"recordCount": 0, "comparedTakeCount": 0, "missedTakeCount": 0,
             "footprintMissedTakeCount": 0, "gaps": []},
        )
        group["recordCount"] += 1
        group["comparedTakeCount"] += summary["comparedTakeCount"]
        group["missedTakeCount"] += summary["missedTakeCount"]
        group["footprintMissedTakeCount"] += summary["footprintMissedTakeCount"]
        group["gaps"].extend(item["metalGapMB"] for item in summary["takes"])
    totals = {}
    for name, group in sorted(groups.items()):
        gaps = group.pop("gaps")
        group["medianGapMB"] = statistics.median(gaps) if gaps else 0.0
        group["maximumGapMB"] = max(gaps, default=0.0)
        totals[name] = group
    return {
        "records": [
            {key: value for key, value in summary.items() if key != "takes"}
            for summary in per_record
        ],
        "totals": totals,
    }


def print_sampled_peak_report(report: dict[str, Any]) -> None:
    print("| Run | Kind | Platform | Takes | Metal peak missed | Median gap MB | Max gap MB |")
    print("|---|---|---|---:|---:|---:|---:|")
    for item in report["records"]:
        print(
            f"| {item['runID']} | {item['kind']} | {item['platform']} | "
            f"{item['comparedTakeCount']} | {item['missedTakeCount']} | "
            f"{item['medianGapMB']:.1f} | {item['maximumGapMB']:.1f} |"
        )
    print()
    print("| Kind/platform | Records | Takes | Metal peak missed | Footprint below MLX peak | Median gap MB | Max gap MB |")
    print("|---|---:|---:|---:|---:|---:|---:|")
    for name, group in report["totals"].items():
        print(
            f"| {name} | {group['recordCount']} | {group['comparedTakeCount']} | "
            f"{group['missedTakeCount']} | {group['footprintMissedTakeCount']} | "
            f"{group['medianGapMB']:.1f} | {group['maximumGapMB']:.1f} |"
        )


class GitBlobReader:
    """Read committed files through one `git cat-file --batch` process (read-only)."""

    def __init__(self) -> None:
        self.process = subprocess.Popen(
            ["git", "cat-file", "--batch"], cwd=REPO_ROOT,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        )

    def _object(self, name: str) -> tuple[bytes, bytes] | None:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write(f"{name}\n".encode("utf-8"))
        self.process.stdin.flush()
        header = self.process.stdout.readline().split()
        if len(header) != 3:
            return None   # "<name> missing" or "<name> ambiguous"
        data = self.process.stdout.read(int(header[2]))
        self.process.stdout.read(1)   # the object's terminating newline
        return header[1], data

    def has_commit(self, commit: str) -> bool:
        found = self._object(commit)
        return found is not None and found[0] == b"commit"

    def read(self, commit: str, path: str) -> bytes | None:
        found = self._object(f"{commit}:{path}")
        return found[1] if found is not None and found[0] == b"blob" else None

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        self.process.wait()


LINEAGE_REPLAY_INPUT_NAMES = ("project.yml subset", "corpus", "analysis profile")


def lineage_identity_changes(previous: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Names of the lineage identity parts that differ between two records."""
    changed = []
    for name in current:
        if current[name] == previous.get(name):
            continue
        if name == "inputIdentity":
            changed.extend(
                label for label, before, after in zip(
                    LINEAGE_REPLAY_INPUT_NAMES, previous.get(name) or [], current[name],
                ) if before != after
            )
        else:
            changed.append(name)
    return sorted(changed)


def lineage_replay(
    records: list[tuple[Path, dict[str, Any]]], *, kind: str, platform: str,
    classification: str | None = "canonical",
) -> dict[str, Any]:
    """Offline replay of the current lineage contract over committed records.

    Each record's lineage identity is recomputed from its own source commit's
    files (Git objects, read-only; the reviewed measurement version at its
    current value), then linked the way rebuild-index links: to the nearest
    earlier comparable record with the same key. A record whose source commit
    is not in the local repository cannot be replayed and links to nothing.
    Nothing is written; stored keys are untouched."""
    if not lineage_identity.has_lineage(kind, platform):
        raise HistoryError(f"{kind}/{platform} defines no lineage identity")
    selected = sorted(
        (
            record for _, record in records
            if record["run"]["kind"] == kind and record["run"]["platform"] == platform
            and (classification is None or record["run"]["classification"] == classification)
            and record_is_comparable(record)
        ),
        key=lambda item: (item["run"]["finishedAt"], item["run"]["id"]),
    )
    reader = GitBlobReader()
    try:
        replayed: list[tuple[dict[str, Any], dict[str, Any] | None, str | None]] = []
        for record in selected:
            commit = record["source"]["commit"]
            if not reader.has_commit(commit):
                replayed.append((record, None, None))
                continue
            lineage = lineage_identity.lineage_inputs(
                kind, platform, lambda path, commit=commit: reader.read(commit, path),
            )
            assert lineage is not None
            candidate = {**record, "inputs": {**record["inputs"], **lineage}}
            replayed.append((
                record, lineage_comparison_identity(candidate), str(lineage["lineageHarnessHash"]),
            ))
    finally:
        reader.close()
    rows: list[dict[str, Any]] = []
    for index, (record, identity, harness) in enumerate(replayed):
        key = sha256_bytes(canonical_bytes(identity)) if identity is not None else None
        earlier = [
            position for position in range(index)
            if key is not None and rows[position]["lineageKey"] == key
        ]
        previous = next(
            (replayed[position][1] for position in range(index - 1, -1, -1)
             if replayed[position][1] is not None),
            None,
        )
        rows.append({
            "runID": record["run"]["id"],
            "finishedAt": record["run"]["finishedAt"],
            "commit": record["source"]["commit"],
            "sourceAvailable": identity is not None,
            "lineageKey": key,
            "lineageBaselineRunID": rows[earlier[-1]]["runID"] if earlier else None,
            "harnessChangedFromBaseline": bool(earlier) and replayed[earlier[-1]][2] != harness,
            "legacyBaselineRunID": record["comparison"].get("baselineRunID"),
            "changedFromPrevious": (
                lineage_identity_changes(previous, identity)
                if previous is not None and identity is not None else []
            ),
        })
    return {
        "kind": kind, "platform": platform, "classification": classification,
        "lineageContractVersion": lineage_identity.LINEAGE_CONTRACT_VERSION,
        "recordCount": len(rows),
        "unavailableSourceCount": sum(1 for row in rows if not row["sourceAvailable"]),
        "lineageLinkedCount": sum(1 for row in rows if row["lineageBaselineRunID"]),
        "legacyLinkedCount": sum(1 for row in rows if row["legacyBaselineRunID"]),
        "records": rows,
    }


def print_lineage_replay(report: dict[str, Any]) -> None:
    scope = report["classification"] or "comparable"
    print(
        f"lineage replay ({report['kind']}/{report['platform']}, {scope}, contract "
        f"v{report['lineageContractVersion']}): {report['lineageLinkedCount']} of "
        f"{report['recordCount']} records link to an earlier record "
        f"(legacy keys: {report['legacyLinkedCount']}; source commit unavailable: "
        f"{report['unavailableSourceCount']})"
    )
    for row in report["records"]:
        if not row["sourceAvailable"]:
            print(f"  {row['finishedAt'][:10]} {row['runID'][-8:]} source commit {row['commit'][:10]} unavailable")
            continue
        baseline = row["lineageBaselineRunID"]
        link = f"baseline {baseline[-8:]}" if baseline else "no baseline"
        if row["harnessChangedFromBaseline"]:
            link += " (harness changed)"
        changed = ", ".join(row["changedFromPrevious"]) or "-"
        print(
            f"  {row['finishedAt'][:10]} {row['runID'][-8:]} key {row['lineageKey'][:12]} "
            f"{link} | changed from previous: {changed}"
        )


# A trend term names a direction only when the median per-cell delta clears the
# noise band, max(5 %, 3 x the median absolute deviation of the per-cell deltas);
# below it the term reads "within noise". Cells with fewer than three takes
# (single cold takes) stay out of the trend (audit #71).
TREND_NOISE_FLOOR_PERCENT = 5.0
TREND_NOISE_MAD_MULTIPLIER = 3.0
TREND_MINIMUM_CELL_TAKES = 3
# The first-chunk latency each kind's trend reads: UI takes carry the app's
# submit-to-first-chunk span, not the engine's ttfcMS.
TREND_TTFC_METRIC = {"ui-generation": "submitToFirstChunkMS"}


def trend_direction(term: str, percent: float, record: dict[str, Any]) -> str:
    if term == "RTF":
        # Standard RTF: lower is faster. Legacy speedup: higher is faster.
        faster = percent < 0 if rtf_semantics.is_standard(record) else percent > 0
        return "faster" if faster else "slower"
    if term == "TTFC":
        return "faster" if percent < 0 else "slower"
    return "lower" if percent < 0 else "higher"


def trend_summary(record: dict[str, Any], baseline_record: dict[str, Any] | None = None) -> str:
    comparison = record["comparison"]
    baseline = comparison.get("baselineRunID")
    if not baseline:
        return "baseline"
    terms = {"RTF": "rtf", "TTFC": TREND_TTFC_METRIC.get(record["run"]["kind"], "ttfcMS")}
    if record.get("schemaVersion", 0) >= 2 and memory_contract_status(record).startswith("qualified"):
        terms["RAM"] = "peakPhysicalFootprintMB"
    take_counts = {
        cell.get("key"): cell.get("count", 0)
        for cell in record.get("cells", []) if isinstance(cell, dict)
    }
    collected: dict[str, list[float]] = {term: [] for term in terms}
    too_small = False
    for cell_key, metrics in comparison.get("deltas", {}).items():
        if not isinstance(metrics, dict):
            continue
        percents = {
            term: float(metrics[metric]["percent"]) for term, metric in terms.items()
            if isinstance(metrics.get(metric), dict)
            and isinstance(metrics[metric].get("percent"), (int, float))
        }
        if take_counts.get(cell_key, 0) < TREND_MINIMUM_CELL_TAKES:
            too_small = too_small or bool(percents)
            continue
        for term, percent in percents.items():
            collected[term].append(percent)
    # A trend delta that exists only on cells too small to trend is not "no change".
    parts = (
        [f"no cell with ≥{TREND_MINIMUM_CELL_TAKES} takes (not trended)"]
        if too_small and not any(collected.values()) else []
    )
    for term, values in collected.items():
        if not values:
            continue
        percent = statistics.median(values)
        spread = statistics.median(abs(value - percent) for value in values)
        band = max(TREND_NOISE_FLOOR_PERCENT, TREND_NOISE_MAD_MULTIPLIER * spread)
        direction = "within noise" if abs(percent) < band else trend_direction(term, percent, record)
        parts.append(f"{term} {percent:+.1f}% ({direction})")
    # A lineage-keyed record links across harness edits its reviewers judged not
    # to change the measurement; the reader still sees that the harness moved.
    harness = record["inputs"].get("lineageHarnessHash")
    if (
        harness is not None and baseline_record is not None
        and baseline_record["inputs"].get("lineageHarnessHash") != harness
    ):
        parts.append("harness changed")
    suffix = ", ".join(parts) if parts else "compatible"
    return f"vs {baseline}: {suffix}"


def history_classification(run: dict[str, Any]) -> str:
    """The HISTORY classification cell. A forced or emulated memory tier is
    never comparable; under lineage contract 1 it kept the hardware profile's
    comparison key (contract 2 gives it its own), so its row names the tier it
    ran under beside the classification instead of reading as that host's."""
    policy = run.get("runtimePolicy")
    if not isinstance(policy, dict) or policy.get("deviceClassForced") is not True:
        return run["classification"]
    simulated = policy.get("simulatedPhysicalMemoryMB")
    tier = f"emulated {simulated} MB" if simulated else f"forced {policy['deviceClass']}"
    return f"{run['classification']} ({tier})"


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
        "",
        "**RTF** is the standard real-time factor: synthesis wall seconds ÷ generated audio seconds,",
        "lower is faster, below 1.0 is faster than real time. Records published since 2026-09-12 declare",
        "`run.rtfDefinition: \"wall/audio\"` and measure the engine request span (prepare entry to the",
        "final WAV write, minus model load and prewarm). Older records stored the inverted decode-loop",
        "speedup (audio ÷ decode seconds, higher is faster) under `rtf`; they are never rewritten. The",
        "RTF column below shows a standard value for every record, the median over all of its takes",
        "(cold takes included): measured for new records, and `~`-prefixed when derived from the legacy",
        "take's app submit→completed span (or the inverse of its end-to-end speedup for CLI records).",
        "The two lineages never share a comparison key.",
        "",
        "A **trend** compares a record with the nearest earlier record of its comparison key: each term",
        "is the median of the per-cell median deltas over cells with at least three takes, and reads",
        "\"within noise\" unless it exceeds max(5%, 3 × the median absolute deviation of those cell",
        "deltas); otherwise its direction is given in words. When only cells with fewer than three",
        "takes carry a delta, the trend reads \"not trended\" instead of a direction. TTFC is the",
        "engine's first-chunk latency, or the app's submit→first-chunk span for UI records. Records",
        "keyed by a lineage contract (`inputs.lineageContractVersion`) note \"harness changed\" when",
        "their harness files differ from the baseline's.",
        "",
    ]
    by_run_id = {record["run"]["id"]: record for _, record in records}
    if not grouped:
        lines.extend(["_No structured benchmark runs have been recorded yet._", ""])
        return "\n".join(lines)
    for kind, platform, profile, configuration in sorted(grouped):
        lines.extend([
            f"## {kind} / {platform} / {profile} / config `{configuration[:12]}`", "",
            "| completed (UTC) | run | scope | classification | status | memory | takes | RTF | source | comparison | trend | label |",
            "|---|---|---|---|---|---|---:|---:|---|---|---|---|",
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
            rtf_value, rtf_derived = rtf_semantics.record_rtf_median(record)
            lines.append(
                "| {date} | [`{run_id}`]({relative}) | {scope} | {classification} | {status} | {memory} | {takes} | {rtf} | `{sha}`{dirty} | `{comparison}` | {trend} | {label} |".format(
                    date=run["finishedAt"].split("T", 1)[0], run_id=markdown_escape(run["id"]),
                    relative=relative, scope=run["matrixScope"], classification=history_classification(run),
                    status=run["status"], takes=len(record["takes"]),
                    rtf=rtf_semantics.format_rtf(rtf_value, rtf_derived),
                    sha=source["commit"][:12],
                    memory=memory_contract_status(record),
                    dirty=" dirty" if source["dirty"] else "", comparison=comparable,
                    trend=markdown_escape(trend_summary(
                        record, by_run_id.get(comparison.get("baselineRunID") or ""),
                    )),
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
    # Every record was validated above and a replacement changes only its
    # comparison block and digest, so only replacements are validated again
    # (run IDs and evidence digests, the uniqueness keys, are untouched).
    for path, replacement in updates:
        validate_record(replacement, expected_path=path)
    # Reconciliation reads only non-comparison content: one pass is a fixed point.
    if comparison_reconciliation_updates(reconciled):
        raise HistoryError("comparison reconciliation did not reach a fixed point")
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

    peak_parser = subparsers.add_parser(
        "peak-miss-report",
        help="read-only report of takes whose sampled Metal peak is below the exact MLX peak",
    )
    peak_parser.add_argument("--json", action="store_true", help="print the report as JSON")

    replay_parser = subparsers.add_parser(
        "lineage-replay",
        help="read-only replay of the current lineage contract over committed records",
    )
    replay_parser.add_argument("--kind", default="ui-generation")
    replay_parser.add_argument("--platform", default="macos", choices=sorted(PLATFORMS))
    replay_parser.add_argument(
        "--classification", default="canonical",
        help="replay only this classification ('any' for every comparable record)",
    )
    replay_parser.add_argument("--json", action="store_true", help="print the report as JSON")

    annotate_parser = subparsers.add_parser("annotate", help="attach a listening verdict")
    annotate_parser.add_argument("--run-id", required=True)
    annotate_parser.add_argument("--listening", choices=sorted(LISTENING_STATUSES), required=True)
    annotate_parser.add_argument("--note", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv if argv is not None else sys.argv[1:])
    try:
        if args.command == "record":
            destination = record_manifest(args.artifact_dir.resolve())
            # Advisory only, on stderr: callers read the record path from stdout.
            if warning := sampled_peak_warning(sampled_peak_misses(load_json(destination))):
                print(warning, file=sys.stderr)
            print(destination.relative_to(REPO_ROOT))
        elif args.command == "validate":
            if args.all:
                records = read_all_records()
                validate_all(records)
                report = sampled_peak_report(records)
                affected = [item for item in report["records"] if item["missedTakeCount"]]
                if affected:
                    print(
                        f"benchmark history: WARN: {len(affected)} of {len(report['records'])} "
                        f"memory-bearing records have takes whose sampled Metal peak is below the "
                        f"exact MLX peak ({sum(item['missedTakeCount'] for item in affected)} of "
                        f"{sum(item['comparedTakeCount'] for item in report['records'])} takes); "
                        "see peak-miss-report",
                        file=sys.stderr,
                    )
                print(f"benchmark history: PASS ({len(records)} records)")
            else:
                path = args.record.resolve()
                record = load_json(path)
                validate_record(record, expected_path=path if RUNS_ROOT in path.parents else None)
                if warning := sampled_peak_warning(sampled_peak_misses(record)):
                    print(warning, file=sys.stderr)
                print(f"benchmark history: PASS ({path})")
        elif args.command == "peak-miss-report":
            report = sampled_peak_report(read_all_records())
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print_sampled_peak_report(report)
        elif args.command == "lineage-replay":
            replay = lineage_replay(
                read_all_records(), kind=args.kind, platform=args.platform,
                classification=None if args.classification == "any" else args.classification,
            )
            if args.json:
                print(json.dumps(replay, indent=2, sort_keys=True))
            else:
                print_lineage_replay(replay)
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
