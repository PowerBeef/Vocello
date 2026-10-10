"""Bounded, descriptive local acoustic evidence; no learned model or quality verdict.

The pitch witness is overlap-energy-normalized autocorrelation, independent of
FCPE/SwiftF0. Its correlation floor selects candidate estimates, not acceptable
speech. Cepstral peak contrast is the peak minus the median of a real log-power
cepstrum search band, in natural-log cepstrum units. It is deliberately neither
Praat CPP/CPPS nor a calibrated whisper/voice-quality measure.

Input is mono, normalized PCM. Frame timestamps refer to full-window support:
start = i * hop, end = start + window, center = (start + end) / 2. No padding.
Phone windows use only frames fully inside their bounds; the uniform discovery
grid uses frame centers and records overlapping support. No recognized error is
needed to supply expected windows. Separate phone-centered context windows can
include neighboring phones; they never replace strict phone support or establish
phone-only evidence. No window constitutes a defect decision.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Mapping

import numpy as np

SCHEMA = "vocello.qc.local-acoustic-evidence/1"
MAX_WINDOWS = 2048
MAX_BATCH_SAMPLES = 524288
MIN_COMPARISON_PITCH_FRAMES = 3
METRICS = {
    "level": "medianLevelDbfs",
    "correlation": "medianNormalizedAutocorrelation",
    "cepstrum": "medianCepstralPeakContrast",
    "flatness": "medianSpectralFlatness",
    "tilt": "medianSpectralTiltDbPerOctave",
    "band_ratio": "medianHighToLowBandDb",
}


def _number(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, 6) if np.isfinite(value) else None


def _median(values):
    finite = values[np.isfinite(values)]
    return _number(np.median(finite)) if finite.size else None


def _empty(reason, settings=None):
    return {"schema": SCHEMA, "inputStatus": "unavailable", "reason": reason,
            "qualification": "uncalibrated", "decision": "not-assessed",
            "settings": settings or {}, "coverage": {}, "summary": {},
            "pitchWitness": {}, "expectedWindows": [], "expectedContextWindows": [], "recognizedWindows": [],
            "intervals": [], "referenceComparison": {"inputStatus": "unavailable",
                                                        "reason": "missing-reference"},
            "uncertainties": [reason]}


def _summarize(profile, mask):
    result = {name: _median(profile[key][mask]) for key, name in METRICS.items()}
    f0 = profile["f0"][mask]
    voiced = np.isfinite(f0)
    result.update(pitchWitnessFrames=int(voiced.sum()),
                  pitchWitnessFrameFraction=_number(voiced.mean()) if f0.size else None,
                  pitchWitnessMedianHz=_median(f0),
                  pitchWitnessMedianSemitones=_median(12 * np.log2(f0 / 100)))
    return result


def _profile(raw, rate, size, step, batch_frames, minimum_correlation):
    count = 1 + (raw.size - size) // step
    profile = {key: np.full(count, np.nan) for key in (*METRICS, "f0")}
    profile["start"] = np.arange(count, dtype=float) * step / rate
    profile["end"] = profile["start"] + size / rate
    profile["center"] = (profile["start"] + profile["end"]) / 2
    low, high = int(math.ceil(rate / 800)), int(math.floor(rate / 50))
    lags = np.arange(low, high + 1)
    fft_size = 1 << (2 * size - 1).bit_length()
    spectral_size = 1 << (size - 1).bit_length()
    frequencies = np.fft.rfftfreq(spectral_size, 1 / rate)
    flat_band = (frequencies >= 300) & (frequencies <= 4000)
    low_band = (frequencies >= 100) & (frequencies < 1000)
    high_band = (frequencies >= 2000) & (frequencies <= 5000)
    tilt_x = np.log2(frequencies[flat_band] / 1000)
    tilt_x -= tilt_x.mean()
    tilt_denom = float(tilt_x @ tilt_x)
    quefrency = np.arange(spectral_size) / rate
    cep_band = (quefrency >= 1 / 800) & (quefrency <= 1 / 50)
    batch = min(batch_frames, max(1, MAX_BATCH_SAMPLES // size))
    hann = np.hanning(size)
    for offset in range(0, count, batch):
        length = min(batch, count - offset)
        segment = raw[offset * step: (offset + length - 1) * step + size]
        frames = np.lib.stride_tricks.sliding_window_view(segment, size)[::step]
        frames = np.array(frames, dtype=np.float64, copy=True)
        rms = np.sqrt(np.mean(frames * frames, axis=1))
        profile["level"][offset:offset + length] = 20 * np.log10(np.maximum(rms, 1e-12))
        frames -= frames.mean(axis=1, keepdims=True)
        centered_energy = np.sum(frames * frames, axis=1)
        usable = centered_energy > size * 1e-16  # numerical floor only, not a VAD
        transformed = np.fft.rfft(frames, n=fft_size, axis=1)
        autocorrelation = np.fft.irfft(transformed * transformed.conj(), n=fft_size, axis=1).real
        prefix = np.concatenate((np.zeros((length, 1)), np.cumsum(frames * frames, axis=1)), axis=1)
        left_energy = prefix[:, size - lags]
        right_energy = prefix[:, -1:] - prefix[:, lags]
        denominator = np.sqrt(left_energy * right_energy)
        correlation = np.divide(autocorrelation[:, lags], denominator,
                                out=np.zeros_like(denominator), where=denominator > 0)
        correlation = np.clip(correlation, -1, 1)
        peaks = np.ones(correlation.shape, dtype=bool)
        peaks[:, 1:] &= correlation[:, 1:] > correlation[:, :-1]
        peaks[:, :-1] &= correlation[:, :-1] >= correlation[:, 1:]
        for row in range(length):
            if not usable[row]:
                continue
            candidates = np.flatnonzero(peaks[row])
            maximum = float(np.max(correlation[row]))
            profile["correlation"][offset + row] = maximum
            if not candidates.size or maximum < minimum_correlation:
                continue
            # Earliest near-best peak avoids selecting a pure tone's repeated periods.
            eligible = candidates[correlation[row, candidates] >= max(minimum_correlation, maximum - .02)]
            if not eligible.size:
                continue
            index = int(eligible[0])
            lag = float(lags[index])
            if 0 < index < correlation.shape[1] - 1:
                before, middle, after = correlation[row, index - 1:index + 2]
                curvature = before - 2 * middle + after
                if curvature < 0:
                    lag += float(np.clip(.5 * (before - after) / curvature, -.5, .5))
            candidate = rate / lag
            if 50 <= candidate <= 800:
                profile["f0"][offset + row] = candidate
        spectrum = np.fft.rfft(frames * hann, n=spectral_size, axis=1)
        power = np.abs(spectrum) ** 2
        maximum_power = power.max(axis=1, keepdims=True)
        relative = np.divide(power, maximum_power, out=np.zeros_like(power), where=maximum_power > 0)
        log_power = np.log(np.maximum(relative, 1e-12))
        cepstrum = np.fft.irfft(log_power, n=spectral_size, axis=1)[:, cep_band]
        contrast = cepstrum.max(axis=1) - np.median(cepstrum, axis=1)
        profile["cepstrum"][offset:offset + length] = np.where(usable, contrast, np.nan)
        if rate / 2 >= 4000 and flat_band.sum() >= 2:
            band = np.maximum(relative[:, flat_band], 1e-12)
            flatness = np.exp(np.mean(np.log(band), axis=1)) / np.mean(band, axis=1)
            tilt = (10 / np.log(10)) * (log_power[:, flat_band] @ tilt_x) / tilt_denom
            profile["flatness"][offset:offset + length] = np.where(usable, flatness, np.nan)
            profile["tilt"][offset:offset + length] = np.where(usable, tilt, np.nan)
        if rate / 2 >= 5000 and low_band.any() and high_band.any():
            low_power = relative[:, low_band].sum(axis=1)
            high_power = relative[:, high_band].sum(axis=1)
            ratio = 10 * np.log10(np.maximum(high_power, 1e-12) / np.maximum(low_power, 1e-12))
            profile["band_ratio"][offset:offset + length] = np.where(usable, ratio, np.nan)
    return profile


def _window(profile, start, end, duration, *, source, phone=None, voiced_target=None, alignment_source=None, centered=False):
    result = {"start": _number(start), "end": _number(end), "source": source,
              "decision": "not-assessed", "uncertainties": []}
    if isinstance(alignment_source, str) and alignment_source:
        result["alignmentSource"] = alignment_source[:64]
    if phone is not None:
        result["phone"] = str(phone)[:64]
    if isinstance(voiced_target, bool):
        result["voicedTarget"] = voiced_target
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
               for value in (start, end)) or start < 0 or end <= start or end > duration + 1e-9:
        result.update(inputStatus="unavailable", reason="invalid-or-out-of-audio-window", frames=0)
        return result
    if centered:
        mask = (profile["center"] >= start) & (profile["center"] < end)
    else:
        mask = (profile["start"] >= start - 1e-9) & (profile["end"] <= end + 1e-9)
    count = int(mask.sum())
    result["frames"] = count
    if not count:
        result.update(inputStatus="unavailable", reason="no-full-analysis-frame")
        return result
    first, last = np.flatnonzero(mask)[[0, -1]]
    support_start, support_end = float(profile["start"][first]), float(profile["end"][last])
    covered = max(0., min(support_end, end) - max(support_start, start))
    result.update(inputStatus="complete", analysisSupportStart=_number(support_start),
                  analysisSupportEnd=_number(support_end), supportFraction=_number(covered / (end - start)),
                  **_summarize(profile, mask))
    if centered and (support_start < start - 1e-9 or support_end > end + 1e-9):
        result["uncertainties"].append("analysis-support-overlaps-interval-boundary")
    if covered < end - start - 1e-9:
        result["uncertainties"].append("incomplete-window-support")
    if not result["pitchWitnessFrames"]:
        result["uncertainties"].append("no-periodic-pitch-candidate")
    if source != "uniform":
        result["uncertainties"].append("alignment-boundaries-not-acoustic-ground-truth")
    return result


def _windows(items, profile, duration, source):
    result, truncated = [], False
    if items is None:
        return result, truncated
    try:
        iterator = iter(items)
    except TypeError:
        return [{"source": source, "inputStatus": "unavailable", "reason": "invalid-window-collection",
                 "decision": "not-assessed", "frames": 0}], False
    for index, item in enumerate(iterator):
        if index >= MAX_WINDOWS:
            truncated = True
            break
        if not isinstance(item, Mapping):
            result.append({"source": source, "inputStatus": "unavailable", "reason": "invalid-window",
                           "decision": "not-assessed", "frames": 0})
            continue
        result.append(_window(profile, item.get("start"), item.get("end"), duration, source=source,
                              phone=item.get("phone"), voiced_target=item.get("voicedTarget"),
                              alignment_source=item.get("alignmentSource", item.get("source"))))
    return result, truncated


def _expected_contexts(windows, profile, duration, context_seconds):
    """Summarize the existing profile around valid targets, never padding PCM.

    `windows` is the already bounded strict inventory, including valid targets
    too short for an analysis frame. Keep invalid targets unavailable instead of
    silently moving them into the recording. Context support can mix phones.
    """
    contexts = []
    for target in windows:
        start, end = target.get("start"), target.get("end")
        valid = ((target.get("inputStatus") == "complete"
                  or target.get("reason") == "no-full-analysis-frame")
                 and start is not None and end is not None and end > start)
        center = (start + end) / 2 if valid else None
        context_start = max(0., center - context_seconds / 2) if valid else None
        context_end = min(duration, center + context_seconds / 2) if valid else None
        context = _window(profile, context_start, context_end, duration, source="expected-context",
                          phone=target.get("phone"), voiced_target=target.get("voicedTarget"),
                          alignment_source=target.get("alignmentSource"))
        context.update(targetStart=start, targetEnd=end)
        context["uncertainties"].append("context-may-include-adjacent-phones")
        if not valid:
            context["reason"] = "invalid-target-window"
        elif center - context_seconds / 2 < 0 or center + context_seconds / 2 > duration:
            context["uncertainties"].append("context-cropped-to-audio-bounds")
        contexts.append(context)
    return contexts


def compare(take, reference):
    """Reference-conditioned descriptive differences; never a pitch-fidelity verdict."""
    result = {"inputStatus": "unavailable", "decision": "not-assessed",
              "pitchWitnessRegisterShiftSt": None, "deltas": {}, "uncertainties": []}
    if not isinstance(reference, Mapping) or reference.get("schema") != SCHEMA:
        result["reason"] = "missing-or-incompatible-reference"
        return result
    if (not isinstance(take, Mapping) or take.get("schema") != SCHEMA
            or any(item.get("inputStatus") not in ("complete", "partial")
                   or not isinstance(item.get("settings"), Mapping)
                   or not isinstance(item.get("summary"), Mapping)
                   for item in (take, reference))):
        result["reason"] = "unavailable-audio-evidence"
        return result
    keys = ("windowSeconds", "hopSeconds", "fminHz", "fmaxHz", "candidateMinimumCorrelation",
            "nearBestCorrelationTolerance", "minimumComparisonPitchFrames",
            "cepstralContrastDefinition", "spectralBandsHz")
    if any(take["settings"].get(key) != reference["settings"].get(key) for key in keys):
        result["reason"] = "incompatible-analysis-settings"
        return result
    a, b = take["summary"], reference["summary"]
    if any(not isinstance(item.get("pitchWitnessFrames"), int)
           or isinstance(item["pitchWitnessFrames"], bool) or item["pitchWitnessFrames"] < 0
           or (item["pitchWitnessFrames"] > 0 and _number(item.get("pitchWitnessMedianSemitones")) is None)
           or any(value is not None and _number(value) is None for value in item.values())
           for item in (a, b)):
        result["reason"] = "malformed-audio-summary"
        return result
    result["inputStatus"] = "complete"
    for name in METRICS.values():
        result["deltas"][name] = _number(float(a[name]) - float(b[name])) if a.get(name) is not None and b.get(name) is not None else None
    result["takePitchWitnessFrames"] = a["pitchWitnessFrames"]
    result["referencePitchWitnessFrames"] = b["pitchWitnessFrames"]
    if min(a["pitchWitnessFrames"], b["pitchWitnessFrames"]) < MIN_COMPARISON_PITCH_FRAMES:
        result.update(inputStatus="partial", reason="insufficient-periodic-pitch-coverage")
    else:
        result["pitchWitnessRegisterShiftSt"] = _number(float(a["pitchWitnessMedianSemitones"]) - float(b["pitchWitnessMedianSemitones"]))
    result["uncertainties"] = ["content-prosody-channel-and-phonation-confounds",
                               "no-calibrated-reference-tolerance", "frame-count-is-not-voiced-speech-duration"]
    return result


def analyze(samples, rate, *, expected_windows: Iterable[Mapping] | None = None,
            recognized_windows: Iterable[Mapping] | None = None, reference=None,
            window_seconds=.060, hop_seconds=.010, interval_seconds=.250,
            expected_context_seconds=.120, max_seconds=120., batch_frames=128):
    """Analyze at most max_seconds without padding or copying whole audio to float64.

    max_seconds is a rejection bound (no silent truncation); batch_frames is capped
    at 256 and additionally by MAX_BATCH_SAMPLES. Expected and recognized windows
    accept {start, end, phone?, voicedTarget?, alignmentSource?}; a supplied source
    is also preserved as alignmentSource. Each collection is bounded to 2048.
    Separate expectedContextWindows reuse the profile around the target center,
    crop to audio bounds, and explicitly disclose adjacent-phone uncertainty.
    Short, silent, nonfinite or unsupported audio cannot yield an assessed verdict.
    `reference` is another analyze() result, compared only with compatible settings.
    """
    settings = {"windowSeconds": window_seconds, "hopSeconds": hop_seconds,
                "intervalSeconds": interval_seconds, "expectedContextSeconds": expected_context_seconds,
                "maximumDurationSeconds": max_seconds,
                "fminHz": 50, "fmaxHz": 800, "candidateMinimumCorrelation": .6,
                "nearBestCorrelationTolerance": .02,
                "minimumComparisonPitchFrames": MIN_COMPARISON_PITCH_FRAMES,
                "timestampSemantics": "frame-start-plus-full-window; pitch-track-at-center",
                "cepstralContrastDefinition": "real-natural-log-relative-power-cepstrum-peak-minus-search-band-median",
                "cepstralContrastUnits": "natural-log-power-cepstrum",
                "spectralBandsHz": {"flatnessAndTilt": [300, 4000], "low": [100, 1000], "high": [2000, 5000]}}
    numeric = (rate, window_seconds, hop_seconds, interval_seconds, expected_context_seconds, max_seconds)
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0
               for value in numeric):
        return _empty("invalid-analysis-settings")
    if not (2000 <= rate <= 192000 and .04 <= window_seconds <= .120 and .002 <= hop_seconds <= window_seconds
            and .05 <= interval_seconds <= 5 and window_seconds <= expected_context_seconds <= 1 and max_seconds <= 600
            and isinstance(batch_frames, int) and not isinstance(batch_frames, bool) and 1 <= batch_frames <= 256):
        return _empty("unsupported-analysis-settings")
    try:
        if len(samples) > max_seconds * rate:
            return _empty("duration-limit-exceeded", settings)
        raw = np.asarray(samples)
    except (TypeError, ValueError):
        return _empty("audio-must-be-mono-real-numeric", settings)
    if raw.ndim != 1 or not np.issubdtype(raw.dtype, np.number) or np.iscomplexobj(raw):
        return _empty("audio-must-be-mono-real-numeric", settings)
    duration = raw.size / rate
    if duration > max_seconds:
        return _empty("duration-limit-exceeded", settings)
    size, step = int(round(window_seconds * rate)), int(round(hop_seconds * rate))
    if raw.size < size:
        return _empty("audio-shorter-than-analysis-window", settings)
    for offset in range(0, raw.size, MAX_BATCH_SAMPLES):
        segment = raw[offset:offset + MAX_BATCH_SAMPLES]
        if not np.isfinite(segment).all():
            return _empty("nonfinite-audio", settings)
        if np.min(segment) < -1.000001 or np.max(segment) > 1.000001:
            return _empty("audio-must-be-normalized-pcm", settings)
    profile = _profile(raw, rate, size, step, batch_frames, .6)
    result = _empty("", settings)
    result.pop("reason")
    result.update(inputStatus="complete", sampleRate=rate, durationSeconds=_number(duration), uncertainties=[
                  "autocorrelation-candidates-are-not-voicing-ground-truth",
                  "pitch-harmonic-and-subharmonic-ambiguity",
                  "spectral-measures-are-not-calibrated-phonation-classifiers"])
    result["summary"] = _summarize(profile, np.ones(len(profile["start"]), dtype=bool))
    support_end = float(profile["end"][-1])
    result["coverage"] = {"frames": len(profile["start"]), "frameGridSeconds": _number(len(profile["start"]) * step / rate),
                          "analyzedSupportSeconds": _number(support_end),
                          "tailUnanalyzedSeconds": _number(duration - support_end),
                          "spectralFullBandAvailable": rate / 2 >= 5000}
    result["pitchWitness"] = {"method": "overlap-energy-normalized-autocorrelation",
                              "startSeconds": _number(size / (2 * rate)), "hopSeconds": _number(step / rate),
                              "f0Hz": [_number(value) for value in profile["f0"]],
                              "normalizedCorrelation": [_number(value) for value in profile["correlation"]]}
    for key, items, source in (("expectedWindows", expected_windows, "expected"),
                               ("recognizedWindows", recognized_windows, "recognized")):
        result[key], truncated = _windows(items, profile, duration, source)
        if truncated:
            result["inputStatus"] = "partial"
            result["uncertainties"].append(source + "-window-limit-exceeded")
    result["expectedContextWindows"] = _expected_contexts(
        result["expectedWindows"], profile, duration, expected_context_seconds)
    for index in range(int(math.ceil(duration / interval_seconds))):
        start = index * interval_seconds
        result["intervals"].append(_window(profile, start, min(duration, start + interval_seconds), duration,
                                             source="uniform", centered=True))
    if result["summary"]["pitchWitnessFrames"] == 0:
        result["uncertainties"].append("no-periodic-pitch-candidate-is-not-a-whisper-or-silence-verdict")
    if rate / 2 < 5000:
        result["uncertainties"].append("insufficient-bandwidth-for-some-spectral-measures")
    if reference is not None:
        result["referenceComparison"] = compare(result, reference)
    return result
