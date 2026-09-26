"""Audio-QC take mapping shared by the publisher and the two UI benchmark gates.

The engine writes one `audioQC` report per generation (thresholds live once, in
Swift, in `makeAudioQCReport`). Three Python consumers fold that report into a
tracked benchmark take: `publish_benchmark_history.py`, `check_macos_ui_bench.py`
and `check_ios_ui_benchmark.py`. This module holds the one copy of the
finish-reason predicate, the QC failure predicate, the five-key metric rename,
the quality-registry identity fold and the record schema-version rule.
"""

from __future__ import annotations

import math
from typing import Any


class AudioQCError(ValueError):
    """A take set cannot be published as one consistent record."""


# The engine emits `eos` and `max_tokens`; the other spellings appear in
# older telemetry rows and are compared case-insensitively.
SUCCESS_FINISH = frozenset({"eos", "max_tokens", "maxtokens", "completed", "complete", "success", "ok"})

# Engine `audioQC` key → tracked take metric key.
QC_METRIC_MAP = (
    ("clickEvents", "discontinuityCount"),
    ("clippedSamples", "clipCount"),
    ("nonFiniteSamples", "nonFiniteCount"),
    ("longestSilenceMS", "longestSilenceMS"),
    ("dcOffset", "dcOffset"),
    # Since 2026-09-13: densest 20 ms cluster of large output steps and where it
    # starts; absent on older rows.
    ("stepBurstPeakCount", "stepBurstPeakCount"),
    ("stepBurstPeakStartMS", "stepBurstPeakStartMS"),
    # QC v8 (2026-09-25): the take's duration per letter or digit of its spoken
    # text (the `speaking_rate_slow` warning's measure); absent on older rows.
    ("secondsPerTextUnit", "secondsPerTextUnit"),
    # Since 2026-09-25 (audit #85, additive on QC v8): slew-limited samples clustered into click
    # events (10 ms apart at most), those starting in a quiet envelope, and
    # events per second, a rate that does not grow with take length.
    # Observational; `discontinuityCount` keeps the per-sample count.
    ("clickEventCount", "clickEventCount"),
    ("lowEnergyClickEventCount", "lowEnergyClickEventCount"),
    ("clickEventsPerSecond", "clickEventsPerSecond"),
)
# Since 2026-09-26 (AQ-04, additive on QC v8): the Stage 0 observational signal
# measures, read from the report's `signal` block (AudioQCSignalObservations,
# mirrored by lib/audio_qc_observations.py) under the same names. Observational;
# no verdict reads them. Absent on older rows.
QC_SIGNAL_METRIC_MAP = (
    ("integratedLoudnessLUFS", "integratedLoudnessLUFS"),
    ("shortTermLoudnessMaxLUFS", "shortTermLoudnessMaxLUFS"),
    ("loudnessRangeLU", "loudnessRangeLU"),
    ("truePeakDBTP", "truePeakDBTP"),
    ("noiseFloorDBFS", "noiseFloorDBFS"),
    ("wadaSNRDB", "wadaSNRDB"),
    ("effectiveBandwidthHz", "effectiveBandwidthHz"),
    ("spectralFluxEventsPerSecond", "spectralFluxEventsPerSecond"),
    ("codecFrameModulationIndex", "codecFrameModulationIndex"),
    ("seamDiscontinuityMaxZ", "seamDiscontinuityMaxZ"),
    ("repetitionStripeLongestMS", "repetitionStripeLongestMS"),
)
VERDICT_KEYS = ("verdict", "instabilityVerdict", "writtenOutputVerdict")
VERDICT_RANK = {"pass": 0, "warn": 1, "fail": 2}


def finish_succeeded(value: Any) -> bool:
    return str(value).lower() in SUCCESS_FINISH


def finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def raw_audio_qc(row: dict[str, Any]) -> dict[str, Any]:
    """The engine's report, whether it sits at the row root or under outputMetrics."""
    output = row.get("outputMetrics") if isinstance(row.get("outputMetrics"), dict) else {}
    qc = row.get("audioQC") or output.get("audioQC") or {}
    return qc if isinstance(qc, dict) else {}


def qc_metrics(raw_qc: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    for source, target in QC_METRIC_MAP:
        if (value := finite_number(raw_qc.get(source))) is not None:
            metrics[target] = value
    signal = raw_qc.get("signal") if isinstance(raw_qc.get("signal"), dict) else {}
    for source, target in QC_SIGNAL_METRIC_MAP:
        if (value := finite_number(signal.get(source))) is not None:
            metrics[target] = value
    return metrics


def qc_verdicts(raw_qc: dict[str, Any]) -> list[str]:
    return [str(raw_qc.get(key)).lower() for key in VERDICT_KEYS if raw_qc.get(key) is not None]


def audio_qc_failure(row: dict[str, Any]) -> str | None:
    """Why the take's overall verdict blocks publication, or None when pass/warn."""
    qc = raw_audio_qc(row)
    verdict = qc.get("verdict")
    if verdict in {"pass", "warn"}:
        return None
    if verdict == "fail":
        return f"failed: {qc.get('flags') or []}"
    return f"verdict is missing or invalid: {verdict!r}"


def output_failure(row: dict[str, Any]) -> str | None:
    """The full per-take output predicate: finish, atomic readable WAV, duration, QC."""
    output = row.get("outputMetrics") if isinstance(row.get("outputMetrics"), dict) else {}
    if not finish_succeeded(row.get("finishReason")):
        return f"unsuccessful finishReason={row.get('finishReason')!r}"
    if output.get("readableWAV") is not True:
        return "outputMetrics.readableWAV is not true"
    if output.get("atomicallyPublished") is not True:
        return "outputMetrics.atomicallyPublished is not true"
    duration = finite_number(output.get("durationSeconds"))
    if duration is None or duration <= 0:
        return "output duration is missing or non-positive"
    if failure := audio_qc_failure(row):
        return f"audioQC {failure}"
    return None


def qc_record(row: dict[str, Any]) -> dict[str, Any]:
    """The tracked `audioQC` block of one take (publisher shape)."""
    qc = raw_audio_qc(row)
    verdicts = qc_verdicts(qc)
    verdict = max(verdicts or ["pass"], key=lambda item: VERDICT_RANK.get(item, 99))
    flags = [str(item) for item in qc.get("flags", []) if isinstance(item, str)]
    if str(qc.get("instabilityVerdict", "pass")).lower() == "warn":
        flags.append("instability-warn")
    if str(qc.get("writtenOutputVerdict", "pass")).lower() == "warn":
        flags.append("written-output-warn")
    return {
        "algorithmVersion": int(qc.get("algorithmVersion", 1)),
        "verdict": verdict,
        "instabilityVerdict": str(qc.get("instabilityVerdict", qc.get("verdict", "pass"))).lower(),
        "writtenOutputVerdict": str(qc.get("writtenOutputVerdict", qc.get("verdict", "pass"))).lower(),
        "warningCodes": sorted(set(flags)) if verdict == "warn" else [],
        "metrics": qc_metrics(qc),
    }


def qc_algorithm_version(rows: list[dict[str, Any]]) -> int:
    return max((int(raw_audio_qc(row).get("algorithmVersion", 1)) for row in rows), default=1)


def quality_identity_fields(row: dict[str, Any]) -> dict[str, Any]:
    """Typed quality-registry identity from the engine row's open telemetry notes.

    Empty when the row predates the phase-12 registry; the record then
    publishes at schema v2. A run mixing both is refused by
    `history_record_schema_version`.
    """
    notes = row.get("notes") if isinstance(row.get("notes"), dict) else {}
    outcome = notes.get("quality_registry_outcome")
    gates = notes.get("quality_registry_required_gates")
    if not isinstance(outcome, str) or not isinstance(gates, str) or not gates:
        return {}
    fields: dict[str, Any] = {
        "qualityRegistryOutcome": outcome,
        "qualityRegistryRequiredGates": sorted(set(gates.split(","))),
    }
    issues = notes.get("quality_registry_issues")
    if isinstance(issues, str) and issues:
        fields["qualityRegistryIssues"] = sorted(set(issues.split(",")))
    return fields


def history_record_schema_version(takes: list[dict[str, Any]]) -> int:
    """3 when every take carries the quality identity, 2 when none does.

    A mix would publish a record silently missing evidence for some takes.
    """
    carrying = sum(1 for take in takes if "qualityRegistryOutcome" in take)
    if carrying == 0:
        return 2
    if carrying == len(takes):
        return 3
    raise AudioQCError("takes mix quality-registry identity presence; refusing a partial schema-v3 record")


# --------------------------------------------------------------------------- #
# Fast QC v8 mirror (AQ-03, "measure the present")
# --------------------------------------------------------------------------- #
# A float64 NumPy replay of the engine's persisted-WAV Fast QC: the
# `PCM16StreamLimiter` pass over the model's float output, a second pass over
# the PCM16 it wrote, and `makeAudioQCReport` (algorithm v8). It exists so the
# qualification engine can measure the v8 flags on constructed fixtures; the
# engine's report stays the only product verdict. Swift owns every value in
# FASTQC_V8: this mirror never reads Swift source. Both sides are pinned to
# the calibration record config/audio-qc-stage0-calibration.json, Swift by
# AudioQCStage0CalibrationTests and this dict by test_audio_qc.py. The
# Swift limiter runs in Float32 and releases its gain sample by sample; this
# mirror computes the same recurrence in float64, so a decision within Float32
# rounding of a boundary can differ.
#
# PCM16 scale. Both write at x 32767 (Int16.max). The mirror reads the
# persisted PCM16 back at 1/32767; the engine reads its WAV through
# AVAudioFile's float processing format, whose Int16 conversion Core Audio does
# at 1/32768 (only its Int16 fallback path divides by Int16.max). The persisted
# pass supplies only the output sums and the silence runs, so the difference
# scales RMS and DC by 32767/32768 (-0.00027 dB); no PCM16 value falls on the
# other side of the 0.001 silence floor under either scale (32.767 and 32.768
# LSB); no written value reaches the 0.965 ceiling; and a persisted-pass step
# can be clamped differently only within one LSB of the 0.42 slew bound.
#
# Chunk QC and WAV-format checks are out of scope (a fixture has neither).
# NumPy is imported only when the mirror runs.

FASTQC_V8_ALGORITHM_VERSION = 8
FASTQC_V8_MIRROR = "fastqc-v8-numpy/1"
FASTQC_V8 = {
    # PCM16StreamLimiter
    "ceiling": 0.965,
    "maxSingleSampleStep": 0.42,
    "releaseStepPerSample": 0.002,
    "stepBurstStepThreshold": 0.25,
    "stepBurstWindowSamples": 480,
    "clickEventGapSamples": 240,
    "clickEnvelopeCoefficient": 1.0 / 240.0,
    "lowEnergyClickEnvelope": 0.02,
    "silenceFloor": 0.001,
    "interiorRunRecordFloorSamples": 2_400,
    "interiorRunRecordCap": 256,
    # makeAudioQCReport
    "silentFailDBFS": -60.0,
    "lowLevelWarnDBFS": -45.0,
    "clipFailFraction": 0.001,
    "clickFailFraction": 0.005,
    "clickWarnFraction": 0.0005,
    "hotWarnFraction": 0.02,
    "dcOffsetWarn": 0.05,
    "dcOffsetFail": 0.20,
    "onsetStepBurstMinSteps": 3,
    "onsetStepBurstWindowMS": 50.0,
    "longContentSeconds": 45.0,
    "cadencePauseMS": {"short": 350, "long": 600},
    "egregiousMS": {"noDeclaredPause": 1_200, "declaredPauseOrLong": 2_000},
    "suspiciousSingleMS": {"noDeclaredPause": 900, "declaredPause": 1_200, "long": 1_500},
    # AudioSpeakingRateQC: seconds per unit above which a take warns, and the
    # fewest units a take needs to be judged.
    "speakingRateBands": {
        "alphabetic": {"slowSecondsPerUnit": 0.145, "minimumJudgedUnits": 20},
        "chinese": {"slowSecondsPerUnit": 0.45, "minimumJudgedUnits": 8},
        "japanese": {"slowSecondsPerUnit": 0.40, "minimumJudgedUnits": 8},
        "korean": {"slowSecondsPerUnit": 0.40, "minimumJudgedUnits": 8},
    },
}
# `StreamingExecutionContext.expectedPauseCount`: pause punctuation runs.
PAUSE_PUNCTUATION = frozenset(".,;:!?…—。、，；：！？")
# The flag families of the v8 report and the verdicts each can raise.
FASTQC_V8_FLAGS = {
    "nonfinite": ("fail",), "empty": ("fail",), "near_silent": ("fail",), "silent": ("fail",),
    "low_level": ("warn",), "dropout": ("warn", "fail"), "cadence": ("warn",),
    "terminal_silence": ("fail",), "clipping": ("warn", "fail"), "clicks": ("warn", "fail"),
    "hot": ("warn",), "onset_step_burst": ("warn",), "dc_offset": ("warn", "fail"),
    "speaking_rate_slow": ("warn",),
}


def flag_family(flag: str) -> str:
    """`dropout:1300ms` -> `dropout`: the family a v8 flag belongs to."""
    return flag.split(":", 1)[0]


def expected_pause_count(text: str) -> int:
    """Interior pause budget: runs of pause punctuation, less a trailing terminal mark."""
    trimmed = text.strip()
    count = 0
    in_run = False
    for character in trimmed:
        if character in PAUSE_PUNCTUATION:
            if not in_run:
                count += 1
                in_run = True
        else:
            in_run = False
    if trimmed and trimmed[-1] in PAUSE_PUNCTUATION and count > 0:
        count -= 1
    return count


def speaking_rate_measure(text: str) -> tuple[int, str] | None:
    """(letters and digits, script class) as `AudioSpeakingRateQC.measure` counts them."""
    units = han = kana = hangul = 0
    for character in text:
        if not (character.isalpha() or character.isnumeric()):
            continue
        units += 1
        value = ord(character)
        if 0x3040 <= value <= 0x30FF or 0x31F0 <= value <= 0x31FF or 0xFF66 <= value <= 0xFF9F:
            kana += 1
        elif 0x3400 <= value <= 0x4DBF or 0x4E00 <= value <= 0x9FFF or 0xF900 <= value <= 0xFAFF:
            han += 1
        elif 0x1100 <= value <= 0x11FF or 0x3130 <= value <= 0x318F or 0xAC00 <= value <= 0xD7AF:
            hangul += 1
    if units == 0:
        return None
    if (han + kana + hangul) * 2 < units:
        script_class = "alphabetic"
    elif kana > 0:
        script_class = "japanese"
    elif hangul > han:
        script_class = "korean"
    else:
        script_class = "chinese"
    return units, script_class


def _silence_runs(np: Any, silent: Any) -> dict[str, Any]:
    """Interior near-silent runs (closed by audio, after audio) and the open trailing run."""
    result: dict[str, Any] = {
        "longestInteriorSilentRunSamples": 0, "longestInteriorSilentRunStartSample": None,
        "interiorSilentRunSamples": [], "trailingSilentRunSamples": 0, "trailingSilentRunStartSample": None,
    }
    audible = np.flatnonzero(~silent)
    if audible.size == 0:
        return result
    offset = int(audible[0])
    tail = silent[offset:].astype(np.int8)
    edges = np.diff(np.concatenate(([0], tail, [0])))
    recorded: list[int] = []
    for start, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
        length = int(end - start)
        if end == tail.size:
            result["trailingSilentRunSamples"] = length
            result["trailingSilentRunStartSample"] = offset + int(start)
            continue
        if length > result["longestInteriorSilentRunSamples"]:
            result["longestInteriorSilentRunSamples"] = length
            result["longestInteriorSilentRunStartSample"] = offset + int(start)
        if (length >= FASTQC_V8["interiorRunRecordFloorSamples"]
                and len(recorded) < FASTQC_V8["interiorRunRecordCap"]):
            recorded.append(length)
    result["interiorSilentRunSamples"] = recorded
    return result


def _limiter_pass(np: Any, raw: Any) -> tuple[dict[str, Any], Any]:
    """One `PCM16StreamLimiter` pass: its metrics and the PCM16 it writes."""
    constants = FASTQC_V8
    ceiling = constants["ceiling"]
    step = constants["maxSingleSampleStep"]
    finite = np.isfinite(raw)
    samples = np.where(finite, raw, 0.0)
    count = int(samples.size)
    magnitude = np.abs(samples)
    metrics: dict[str, Any] = {
        "processedSamples": count,
        "nonFiniteSamples": int(count - int(finite.sum())),
        "rawPeak": float(magnitude.max()) if count else 0.0,
        "samplesAboveCeiling": int((magnitude > ceiling).sum()),
        "samplesOutsideUnitRange": int((magnitude > 1.0).sum()),
    }
    # Gain: g[t] = min(target[t], g[t-1] + release) from g = 1, in closed form.
    target = np.where(magnitude > ceiling, ceiling / np.maximum(magnitude, 1e-38), 1.0)
    index = np.arange(count, dtype=np.float64)
    release = constants["releaseStepPerSample"]
    gain = np.minimum.accumulate(target - release * index) + release * index if count else target
    limited = samples * gain
    output = np.clip(limited, -ceiling, ceiling)
    slewed: list[int] = []
    position = 1
    while position < count:
        stop = min(count, position + 8_192)
        jumps = np.flatnonzero(np.abs(limited[position:stop] - output[position - 1:stop - 1]) > step)
        if jumps.size == 0:
            position = stop
            continue
        sample = position + int(jumps[0])
        previous = float(output[sample - 1])
        moved = previous + step if limited[sample] - previous > step else previous - step
        output[sample] = min(ceiling, max(-ceiling, moved))
        slewed.append(sample)
        position = sample + 1
    metrics["slewLimitedSamples"] = len(slewed)
    metrics["slewLimitedSampleIndices"] = slewed
    # Step bursts: the densest 20 ms cluster of pre-clamp steps above the threshold.
    steps = np.flatnonzero(np.abs(limited[1:] - output[:-1]) > constants["stepBurstStepThreshold"]) + 1
    metrics["stepBurstPeakCount"] = 0
    metrics["stepBurstPeakStartSample"] = None
    if steps.size:
        window_start = np.searchsorted(steps, steps - constants["stepBurstWindowSamples"] + 1, side="left")
        counts = np.arange(steps.size) - window_start + 1
        peak = int(np.argmax(counts))
        metrics["stepBurstPeakCount"] = int(counts[peak])
        metrics["stepBurstPeakStartSample"] = int(steps[window_start[peak]])
    # Click events: slew-limited samples at most the gap apart are one event;
    # the input envelope before the event's first sample decides "low energy".
    events = low_energy = 0
    last: int | None = None
    coefficient = constants["clickEnvelopeCoefficient"]
    for sample in slewed:
        if last is None or sample - last > constants["clickEventGapSamples"]:
            events += 1
            history = magnitude[max(0, sample - 12_000):sample]
            weights = coefficient * (1.0 - coefficient) ** np.arange(history.size - 1, -1, -1)
            if float((history * weights).sum()) < constants["lowEnergyClickEnvelope"]:
                low_energy += 1
        last = sample
    metrics["clickEventCount"] = events
    metrics["lowEnergyClickEventCount"] = low_energy
    metrics["outputSum"] = float(output.sum())
    metrics["outputSumOfSquares"] = float((output * output).sum())
    metrics.update(_silence_runs(np, magnitude < constants["silenceFloor"]))
    scaled = output * 32767.0
    pcm16 = (np.sign(scaled) * np.floor(np.abs(scaled) + 0.5)).astype(np.int16)
    return metrics, pcm16


def fast_qc_v8(samples: Any, *, sample_rate: int = 24_000, text: str | None = None,
               expected_pauses: int | None = None, slew_positions: bool = False,
               signal: bool = True, seam_offsets: Any = ()) -> dict[str, Any]:
    """The v8 `audioQC` report the engine would write for this float output.

    `text` is the spoken request text: it sets the pause budget (unless
    `expected_pauses` is given) and the speaking-rate check, which is skipped
    without it, as for a bare persisted file. `slew_positions` adds the
    mirror-only `slewLimitedSampleIndices` (the samples the click counter
    clamped), for locating what a click alarm responded to. `signal` adds the
    report's observational `signal` block (AQ-04) over the persisted PCM16,
    with `seam_offsets` the streaming seams in the written file; it moves no
    flag or verdict, so callers that score only the v8 flags may skip it.
    """
    import numpy as np

    raw = np.asarray(samples, dtype=np.float64).reshape(-1)
    stream, pcm16 = _limiter_pass(np, raw)
    persisted, _ = _limiter_pass(np, pcm16.astype(np.float64) / 32767.0)
    combined = dict(stream)
    for key in ("processedSamples", "outputSum", "outputSumOfSquares", "longestInteriorSilentRunSamples",
                "longestInteriorSilentRunStartSample", "interiorSilentRunSamples", "trailingSilentRunSamples",
                "trailingSilentRunStartSample"):
        combined[key] = persisted[key]
    pauses = expected_pauses if expected_pauses is not None else (expected_pause_count(text) if text else 0)
    duration = raw.size / sample_rate if sample_rate > 0 else 0.0
    report = fast_qc_v8_report(combined, sample_rate=sample_rate, duration_seconds=duration,
                               expected_pauses=pauses, text=text)
    if slew_positions:
        report["slewLimitedSampleIndices"] = list(stream["slewLimitedSampleIndices"])
    if signal:
        from lib import audio_qc_observations

        report["signal"] = audio_qc_observations.signal_observations(
            pcm16, sample_rate=sample_rate, seam_offsets=seam_offsets
        )
    return report


def _ms(samples: int, sample_rate: int) -> int:
    return int(samples * 1000 / sample_rate) if sample_rate > 0 else 0


def fast_qc_v8_report(metrics: dict[str, Any], *, sample_rate: int, duration_seconds: float,
                      expected_pauses: int, text: str | None = None) -> dict[str, Any]:
    """`makeAudioQCReport` (v8) over limiter metrics, flags spelled as the engine spells them."""
    constants = FASTQC_V8
    count = metrics["processedSamples"]
    rms = math.sqrt(metrics["outputSumOfSquares"] / count) if count > 0 else 0.0
    rms_dbfs = 20.0 * math.log10(rms) if rms > 0 else None
    dc_offset = metrics["outputSum"] / count if count > 0 else None
    longest_ms = _ms(metrics["longestInteriorSilentRunSamples"], sample_rate)
    trailing_ms = _ms(metrics["trailingSilentRunSamples"], sample_rate)
    interior_ms = [_ms(length, sample_rate) for length in metrics["interiorSilentRunSamples"]]
    denominator = max(count, 1)
    clipped_fraction = metrics["samplesOutsideUnitRange"] / denominator
    click_fraction = metrics["slewLimitedSamples"] / denominator
    hot_fraction = metrics["samplesAboveCeiling"] / denominator
    long_content = duration_seconds >= constants["longContentSeconds"]
    declared = expected_pauses > 0
    cadence_ms = constants["cadencePauseMS"]["long" if long_content else "short"]
    egregious_ms = constants["egregiousMS"]["declaredPauseOrLong" if long_content or declared
                                            else "noDeclaredPause"]
    suspicious = constants["suspiciousSingleMS"]
    suspicious_ms = (suspicious["long"] if long_content
                     else suspicious["declaredPause"] if declared else suspicious["noDeclaredPause"])
    cadence_count = sum(1 for value in interior_ms if value >= cadence_ms)
    excess_cadence = max(0, cadence_count - max(0, expected_pauses))
    suspicious_count = sum(1 for value in interior_ms if value >= suspicious_ms)
    excess_suspicious = max(0, suspicious_count - max(0, expected_pauses))

    flags: list[str] = []
    levels: dict[str, str] = {}
    verdicts = {"instability": "pass", "written": "pass"}

    def raise_to(level: str, channel: str, flag: str) -> None:
        flags.append(flag)
        family = flag_family(flag)
        if levels.get(family) != "fail":
            levels[family] = level
        if level == "fail":
            verdicts[channel] = "fail"
        elif verdicts[channel] != "fail":
            verdicts[channel] = "warn"

    if metrics["nonFiniteSamples"] > 0:
        raise_to("fail", "instability", "nonfinite")
    if count == 0:
        raise_to("fail", "written", "empty")
    if rms_dbfs is not None:
        if rms_dbfs < constants["silentFailDBFS"]:
            raise_to("fail", "written", "near_silent")
        elif rms_dbfs < constants["lowLevelWarnDBFS"]:
            raise_to("warn", "written", "low_level")
    elif count > 0:
        raise_to("fail", "written", "silent")
    if longest_ms >= egregious_ms:
        raise_to("fail", "written", f"dropout:{longest_ms}ms")
    elif excess_suspicious >= 2:
        raise_to("fail", "written", f"dropout:excess{excess_suspicious}({suspicious_count}/{expected_pauses})")
    elif longest_ms >= suspicious_ms:
        raise_to("warn", "written", f"dropout:{longest_ms}ms")
    elif excess_cadence > 0:
        raise_to("warn", "written", f"cadence:excess{excess_cadence}({cadence_count}/{expected_pauses})")
    if trailing_ms >= egregious_ms:
        raise_to("fail", "written", f"terminal_silence:{trailing_ms}ms")
    if clipped_fraction > constants["clipFailFraction"]:
        raise_to("fail", "instability", "clipping")
    elif metrics["samplesOutsideUnitRange"] > 0:
        raise_to("warn", "instability", "clipping")
    if click_fraction > constants["clickFailFraction"]:
        raise_to("fail", "instability", "clicks")
    elif click_fraction > constants["clickWarnFraction"]:
        raise_to("warn", "instability", "clicks")
    if hot_fraction > constants["hotWarnFraction"]:
        raise_to("warn", "instability", "hot")
    burst_start = metrics["stepBurstPeakStartSample"]
    if (metrics["stepBurstPeakCount"] >= constants["onsetStepBurstMinSteps"] and sample_rate > 0
            and burst_start is not None
            and burst_start * 1000 / sample_rate < constants["onsetStepBurstWindowMS"]):
        raise_to("warn", "instability", "onset_step_burst")
    if dc_offset is not None:
        if abs(dc_offset) > constants["dcOffsetFail"]:
            raise_to("fail", "written", "dc_offset")
        elif abs(dc_offset) > constants["dcOffsetWarn"]:
            raise_to("warn", "written", "dc_offset")
    measurement = speaking_rate_measure(text) if text else None
    seconds_per_unit = duration_seconds / measurement[0] if measurement and duration_seconds > 0 else None
    if measurement and seconds_per_unit is not None:
        band = constants["speakingRateBands"][measurement[1]]
        if measurement[0] >= band["minimumJudgedUnits"] and seconds_per_unit > band["slowSecondsPerUnit"]:
            raise_to("warn", "instability", "speaking_rate_slow")
    verdict = max(verdicts.values(), key=VERDICT_RANK.__getitem__)
    return {
        "algorithmVersion": FASTQC_V8_ALGORITHM_VERSION,
        "mirror": FASTQC_V8_MIRROR,
        "verdict": verdict,
        "instabilityVerdict": verdicts["instability"],
        "writtenOutputVerdict": verdicts["written"],
        "flags": flags,
        # Mirror-only: the verdict each flag family raised (the engine report
        # keeps only the two channel verdicts).
        "flagLevels": dict(sorted(levels.items())),
        "rmsDBFS": rms_dbfs,
        "dcOffset": dc_offset,
        "peak": metrics["rawPeak"],
        "clippedSamples": metrics["samplesOutsideUnitRange"],
        "hotSamples": metrics["samplesAboveCeiling"],
        "nonFiniteSamples": metrics["nonFiniteSamples"],
        "clickEvents": metrics["slewLimitedSamples"],
        "longestSilenceMS": longest_ms,
        "trailingSilenceMS": trailing_ms,
        "stepBurstPeakCount": metrics["stepBurstPeakCount"],
        "stepBurstPeakStartMS": _ms(burst_start, sample_rate) if burst_start is not None else None,
        "durationSeconds": duration_seconds,
        "expectedPauseCount": expected_pauses,
        "speakingRateTextUnits": measurement[0] if measurement else None,
        "secondsPerTextUnit": seconds_per_unit,
        "clickEventCount": metrics["clickEventCount"],
        "lowEnergyClickEventCount": metrics["lowEnergyClickEventCount"],
        "clickEventsPerSecond": metrics["clickEventCount"] / duration_seconds if duration_seconds > 0 else None,
    }
