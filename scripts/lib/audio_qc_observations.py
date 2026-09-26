"""Stage 0 observational signal measures and the engine introspection summary (AQ-04).

A float64 NumPy mirror of two Swift producers, both observational: no flag, no
verdict and no Fast QC version reads them (audit 2026-09-25, AQ-F08 to F12 and
F49, decision 8(a): Fast QC stays v8 and these join it additively).

- `signal_observations` mirrors `AudioQCSignalObserver`
  (Sources/QwenVoiceCore/AudioQCSignalObserver.swift), which runs over the
  persisted PCM16 of every take inside `makePersistedWAVAudioQCReport` and
  lands in `AudioQCReport.signal`. It reads the persisted samples at
  1/32768, exactly as AVAudioFile hands them to the engine.
- `introspection_summary` mirrors `Qwen3GenerationIntrospector`
  (Packages/VocelloQwen3Core/Sources/MLXAudioTTS/ModelDiagnostics.swift), the
  engine's fixed-state summary of codebook-0 token cycles, the per-step entropy
  and EOS probability of the talker distribution, and the streaming seams. It
  lands in the telemetry row's `engineIntrospection`.

Swift owns every constant. Both sides are pinned to the record
config/audio-qc-stage0-observations.json (Swift by
AudioQCSignalObservationTests, this module by test_audio_qc_observations.py)
and scored on the shared fixtures in
scripts/tests/fixtures/audio_qc_stage0_observations.json. The Swift side runs
its FFT, K-weighting and true-peak filters through Accelerate and sums in a
different order, so continuous values agree to rounding, not bit for bit;
every reported real is rounded to four decimals on both sides.

Measures (algorithm version 1):

- BS.1770-4 loudness of the mono signal: K-weighting from the analog
  prototype at the take's rate (libebur128's biquad design), 400 ms blocks
  every 100 ms gated at -70 LUFS and -10 LU (integrated), the maximum 3 s
  short-term loudness every 100 ms, and the EBU Tech 3342 loudness range over
  3 s windows every second (-70 LUFS, -20 LU; the 10th to 95th percentile).
- 4x true peak: a 49-tap Hann-windowed sinc interpolator (libebur128's design;
  phase 0 is the input itself), in dBTP.
- Pause-percentile noise floor: the 10th percentile (nearest rank) of 10 ms
  frame levels, floored at -120 dBFS.
- WADA-SNR (Kim and Stern, Interspeech 2008) over the nonzero samples:
  log E|x| - E log|x| looked up in the Gamma (alpha 0.4) table, which
  `wada_gamma_table` derives by quadrature of the paper's model and the record
  stores.
- Effective bandwidth: the highest bin of the long-term average spectrum of
  active frames (windowed RMS >= -60 dBFS) within 50 dB of its maximum.
- Log-spectral-flux events: the mean positive dB rise per bin between
  consecutive 10 ms STFT frames; frames rising at least 10 dB start an event
  unless another did within 50 ms.
- Codec-frame modulation index: 2 |DFT at 12.5 Hz| / sum of the 10 ms frame
  RMS envelope (the tokenizer frame rate; one period is exactly 8 frames).
- Seam discontinuity z-score: at each streaming seam, the first difference
  against the 10 ms either side, (d - mean) / max(std, 1 LSB); the maximum.
- Self-similarity repetition stripe: 40 ms frames of 16 mean-removed log band
  levels; the longest run along one lag (200 ms to 15 s) of active frames whose
  cosine is at least 0.95 and that holds at least two spectral changes (so a
  steady tone forms none), and how many such runs last 600 ms or more.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Sequence

REPO = Path(__file__).resolve().parents[2]
RECORD_PATH = REPO / "config" / "audio-qc-stage0-observations.json"

OBSERVATIONS_ALGORITHM_VERSION = 1
OBSERVATIONS_MIRROR = "stage0-observations-numpy/1"
INTROSPECTION_ALGORITHM_VERSION = 1

# The constants Swift owns (AudioQCSignalObserver and Qwen3GenerationIntrospector),
# pinned to the record by test_audio_qc_observations.py.
STAGE0_OBSERVATIONS: dict[str, Any] = {
    "kWeighting": {
        "shelfFrequencyHz": 1681.974450955533,
        "shelfGainDB": 3.999843853973347,
        "shelfQ": 0.7071752369554196,
        "shelfBandwidthExponent": 0.4996667741545416,
        "highPassFrequencyHz": 38.13547087602444,
        "highPassQ": 0.5003270373238773,
    },
    "loudness": {
        "offsetLU": -0.691,
        "subBlocksPerSecond": 10,
        "blockSubBlocks": 4,
        "shortTermSubBlocks": 30,
        "rangeHopSubBlocks": 10,
        "absoluteGateLUFS": -70.0,
        "relativeGateLU": -10.0,
        "rangeRelativeGateLU": -20.0,
        "rangeLowQuantile": 0.10,
        "rangeHighQuantile": 0.95,
    },
    "truePeak": {"oversampling": 4, "taps": 49, "coefficientFloor": 1e-6},
    "framesPerSecond": 100,
    "noiseFloor": {"quantileTenths": 1, "levelFloorDBFS": -120.0},
    "wada": {"magnitudeGridSteps": 32_768},
    "spectrum": {
        "fftSize": 512,
        "fftSizeAboveRate": 1024,
        "fftSizeRateLimit": 25_600,
        "minimumSampleRate": 16_000,
        "powerFloor": 1e-10,
        "activeMeanSquare": 1e-6,
    },
    "spectralFlux": {"eventThresholdDB": 10.0, "clusterGapFrames": 5},
    "bandwidth": {"thresholdDB": 50.0, "ltasFloor": 1e-20},
    "modulation": {"frequencyHz": 12.5, "periodFrames": 8},
    "seam": {"halfWindowFrames": 1, "sigmaFloor": 1.0 / 32_768.0},
    "repetition": {
        "poolFrames": 4,
        "bandEdgesAt512": [2, 3, 4, 5, 7, 9, 12, 17, 23, 31, 41, 56, 76, 103, 140, 189, 257],
        "cosineThreshold": 0.95,
        "minimumLagFrames": 5,
        "maximumLagFrames": 375,
        "minimumStripeFrames": 15,
        "minimumChangingFrames": 2,
        "featureNormFloor": 1e-6,
    },
    "roundingDecimals": 4,
}

INTROSPECTION: dict[str, Any] = {
    "maximumCyclePeriod": 32,
    "entropyHistogramBinsPerNat": 32,
    "entropyHistogramBins": 256,
    "highEntropyNats": 4.0,
    "likelyEOSProbability": 0.5,
    "maximumSeams": 256,
}

# 12.5 Hz at 100 frames per second: the eight phases of one period, exact.
_HALF_ROOT_TWO = 0.7071067811865476
_COS8 = (1.0, _HALF_ROOT_TWO, 0.0, -_HALF_ROOT_TWO, -1.0, -_HALF_ROOT_TWO, 0.0, _HALF_ROOT_TWO)
_SIN8 = (0.0, _HALF_ROOT_TWO, 1.0, _HALF_ROOT_TWO, 0.0, -_HALF_ROOT_TWO, -1.0, -_HALF_ROOT_TWO)

_record_cache: dict[str, Any] | None = None


def load_record() -> dict[str, Any]:
    global _record_cache
    if _record_cache is None:
        _record_cache = json.loads(RECORD_PATH.read_text(encoding="utf-8"))
    return _record_cache


def round4(value: float | None) -> float | None:
    """Half away from zero to four decimals, as the Swift side rounds; never -0."""
    if value is None or not math.isfinite(value):
        return None
    scaled = math.floor(abs(value) * 10_000.0 + 0.5) / 10_000.0
    return -scaled if value < 0 and scaled != 0 else scaled


# --------------------------------------------------------------------------- #
# WADA-SNR Gamma table
# --------------------------------------------------------------------------- #

def wada_gamma_table(snr_db: Sequence[int] = tuple(range(-20, 101)), *, alpha: float = 0.4,
                     nodes: int = 4000) -> list[float]:
    """G(SNR) = log E|z| - E log|z| for z = x + v, x double-sided Gamma(alpha), v ~ N(0, 1).

    Kim and Stern's model, by quadrature instead of their simulation. Given the
    noise at unit variance, E|x + v| is the folded-normal mean and E log|x + v|
    is half the mean log of a noncentral chi-square with one degree of freedom:
    a Poisson mixture of central ones, E ln chi2_(1+2j) = ln 2 + psi(1/2 + j),
    with ln m - 1/(2 m^2) - 3/(4 m^4) - 5/(2 m^6) past m = 30. Both are tabulated
    on a log grid and integrated against the Gamma density after the
    substitution x = (u^(1/alpha)) / beta, which removes its singularity.
    """
    import numpy as np

    euler = 0.5772156649015329
    grid = np.logspace(-12, 12, 24_001)
    near = grid <= 30.0
    terms = 800
    psi = np.empty(terms)
    psi[0] = -euler - 2.0 * math.log(2.0)
    for j in range(1, terms):
        psi[j] = psi[j - 1] + 1.0 / (j - 0.5)
    log_factorial = np.array([math.lgamma(j + 1.0) for j in range(terms)])
    half_lambda = grid[near] ** 2 / 2.0
    j = np.arange(terms)
    weights = np.exp(-half_lambda[:, None] + j[None, :] * np.log(half_lambda)[:, None] - log_factorial[None, :])
    log_mean = np.empty_like(grid)
    log_mean[near] = 0.5 * (math.log(2.0) + (weights * psi[None, :]).sum(axis=1))
    far = grid[~near]
    log_mean[~near] = np.log(far) - 1 / (2 * far ** 2) - 3 / (4 * far ** 4) - 5 / (2 * far ** 6)
    folded = np.array([math.sqrt(2 / math.pi) * math.exp(-m * m / 2) + m * math.erf(m / math.sqrt(2))
                       for m in grid])
    log_grid = np.log(grid)

    legendre, legendre_weights = np.polynomial.legendre.leggauss(nodes)
    upper = 6.0
    u = (legendre + 1.0) * upper / 2.0
    du = legendre_weights * upper / 2.0
    s = u ** (1.0 / alpha)
    density = np.exp(-s) * du / math.gamma(alpha + 1.0)
    density /= density.sum()
    table = []
    for value in snr_db:
        beta = math.sqrt(alpha * (alpha + 1.0) / 10.0 ** (value / 10.0))
        x = np.log(np.maximum(s / beta, grid[0]))
        mean_abs = float((density * np.interp(x, log_grid, folded)).sum())
        mean_log = float((density * np.interp(x, log_grid, log_mean)).sum())
        table.append(math.log(mean_abs) - mean_log)
    return table


def _wada_lookup(value: float, snr_db: Sequence[float], g: Sequence[float]) -> float:
    """The last table entry below the statistic, interpolated (MATLAB wada_snr.m)."""
    index = -1
    for position, entry in enumerate(g):
        if entry < value:
            index = position
    if index < 0:
        return float(snr_db[0])
    if index == len(g) - 1:
        return float(snr_db[-1])
    return float(snr_db[index] + (value - g[index]) / (g[index + 1] - g[index])
                 * (snr_db[index + 1] - snr_db[index]))


def wada_snr(samples: Any) -> float | None:
    """WADA-SNR in dB over the nonzero samples; None without any.

    Magnitudes are counted on the PCM16 grid (k / 32768, capped at 32768) and
    summed from the histogram in ascending k, as `AudioQCSignalObserver` does.
    Exact digital zeros are excluded: the paper's 1e-10 floor would otherwise
    read any take with digital silence as the table's 100 dB ceiling.
    """
    import numpy as np

    full_scale = STAGE0_OBSERVATIONS["wada"]["magnitudeGridSteps"]
    grid = np.minimum(np.floor(np.abs(np.asarray(samples, dtype=np.float64)) * full_scale + 0.5),
                      full_scale).astype(np.int64)
    histogram = np.bincount(grid, minlength=full_scale + 1)
    nonzero = 0
    total = 0.0
    logs = 0.0
    for k in range(1, full_scale + 1):
        entries = int(histogram[k])
        if entries == 0:
            continue
        magnitude = k / full_scale
        nonzero += entries
        total += entries * magnitude
        logs += entries * math.log(magnitude)
    if nonzero == 0:
        return None
    table = load_record()["wadaGammaTable"]
    statistic = math.log(total / nonzero) - logs / nonzero
    return _wada_lookup(statistic, table["snrDB"], table["g"])


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #

def k_weighting_sections(sample_rate: int) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(b0, b1, b2, a1, a2) of the K-weighting shelf and high-pass at this rate."""
    kw = STAGE0_OBSERVATIONS["kWeighting"]
    k = math.tan(math.pi * kw["shelfFrequencyHz"] / sample_rate)
    q = kw["shelfQ"]
    vh = math.pow(10.0, kw["shelfGainDB"] / 20.0)
    vb = math.pow(vh, kw["shelfBandwidthExponent"])
    a0 = 1.0 + k / q + k * k
    shelf = ((vh + vb * k / q + k * k) / a0, 2.0 * (k * k - vh) / a0, (vh - vb * k / q + k * k) / a0,
             2.0 * (k * k - 1.0) / a0, (1.0 - k / q + k * k) / a0)
    k = math.tan(math.pi * kw["highPassFrequencyHz"] / sample_rate)
    q = kw["highPassQ"]
    d = 1.0 + k / q + k * k
    high_pass = (1.0, -2.0, 1.0, 2.0 * (k * k - 1.0) / d, (1.0 - k / q + k * k) / d)
    return shelf, high_pass


def _k_weighted(samples: list[float], sample_rate: int) -> list[float]:
    """The two sections in direct form 1, from zero state (vDSP_biquadD's form)."""
    (b0, b1, b2, a1, a2), (c0, c1, c2, d1, d2) = k_weighting_sections(sample_rate)
    x1 = x2 = y1 = y2 = z1 = z2 = 0.0
    out = [0.0] * len(samples)
    for index, x in enumerate(samples):
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        z = c0 * y + c1 * y1 + c2 * y2 - d1 * z1 - d2 * z2
        x2, x1 = x1, x
        y2, y1 = y1, y
        z2, z1 = z1, z
        out[index] = z
    return out


def true_peak_phases() -> list[list[float]]:
    """Per-phase taps h[f][d] (delay d = 0...12) of the 4x interpolator."""
    constants = STAGE0_OBSERVATIONS["truePeak"]
    taps = constants["taps"]
    factor = constants["oversampling"]
    center = (taps - 1) / 2.0
    phases = [[0.0] * ((taps + factor - 1) // factor) for _ in range(factor)]
    for j in range(taps):
        m = j - center
        c = 1.0 if m == 0 else math.sin(m * math.pi / factor) / (m * math.pi / factor)
        c *= 0.5 * (1.0 - math.cos(2.0 * math.pi * j / (taps - 1)))
        if abs(c) > constants["coefficientFloor"]:
            phases[j % factor][j // factor] = c
    return phases


# --------------------------------------------------------------------------- #
# Signal observations
# --------------------------------------------------------------------------- #

def _loudness(np: Any, kw: Any, sample_rate: int) -> dict[str, float | None]:
    constants = STAGE0_OBSERVATIONS["loudness"]
    result: dict[str, float | None] = {
        "integratedLoudnessLUFS": None, "shortTermLoudnessMaxLUFS": None, "loudnessRangeLU": None,
    }
    per_second = constants["subBlocksPerSecond"]
    if sample_rate % per_second != 0:
        return result
    length = sample_rate // per_second
    count = kw.size // length
    if count == 0:
        return result
    sub = [float(value) for value in (kw[:count * length].reshape(count, length) ** 2).sum(axis=1) / length]
    offset = constants["offsetLU"]

    def loudness(energy: float) -> float:
        return offset + 10.0 * math.log10(energy) if energy > 0 else -math.inf

    def window(start: int, size: int) -> float:
        total = 0.0
        for value in sub[start:start + size]:
            total += value
        return total / size

    block = constants["blockSubBlocks"]
    blocks = [window(j, block) for j in range(count - block + 1)]
    gated = [z for z in blocks if loudness(z) > constants["absoluteGateLUFS"]]
    if gated:
        relative = loudness(sum(gated) / len(gated)) + constants["relativeGateLU"]
        kept = [z for z in gated if loudness(z) > relative]
        if kept:
            result["integratedLoudnessLUFS"] = loudness(sum(kept) / len(kept))
    short = constants["shortTermSubBlocks"]
    if count >= short:
        values = [loudness(window(k, short)) for k in range(count - short + 1)]
        finite = [value for value in values if math.isfinite(value)]
        if finite:
            result["shortTermLoudnessMaxLUFS"] = max(finite)
        hop = constants["rangeHopSubBlocks"]
        windows = [window(k, short) for k in range(0, count - short + 1, hop)]
        absolute = [z for z in windows if loudness(z) > constants["absoluteGateLUFS"]]
        if absolute:
            threshold = loudness(sum(absolute) / len(absolute)) + constants["rangeRelativeGateLU"]
            levels = sorted(loudness(z) for z in absolute if loudness(z) > threshold)
            if levels:
                size = len(levels)
                low = levels[int((size - 1) * constants["rangeLowQuantile"] + 0.5)]
                high = levels[int((size - 1) * constants["rangeHighQuantile"] + 0.5)]
                result["loudnessRangeLU"] = high - low
    return result


def _frames(np: Any, samples: Any, size: int, hop: int) -> Any:
    count = (samples.size - size) // hop + 1 if samples.size >= size else 0
    if count <= 0:
        return np.zeros((0, size))
    index = np.arange(size)[None, :] + hop * np.arange(count)[:, None]
    return samples[index]


def signal_observations(pcm16: Any, *, sample_rate: int = 24_000,
                        seam_offsets: Sequence[int] = ()) -> dict[str, Any]:
    """The `AudioQCReport.signal` block for PCM16 samples (read at 1/32768)."""
    import numpy as np

    constants = STAGE0_OBSERVATIONS
    samples = np.asarray(pcm16, dtype=np.float64).reshape(-1) / 32_768.0
    count = int(samples.size)
    duration = count / sample_rate if sample_rate > 0 else 0.0
    observations: dict[str, Any] = {"algorithmVersion": OBSERVATIONS_ALGORITHM_VERSION}

    # Loudness and true peak.
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    kw = np.asarray(_k_weighted(samples.tolist(), sample_rate), dtype=np.float64)
    observations.update(_loudness(np, kw, sample_rate))
    peak = float(np.abs(samples).max()) if count else 0.0
    for phase in true_peak_phases():
        if count:
            peak = max(peak, float(np.abs(np.convolve(samples, np.asarray(phase))[:count]).max()))
    observations["truePeakDBTP"] = 20.0 * math.log10(peak) if peak > 0 else None

    # WADA-SNR over the nonzero samples, from a histogram of PCM16 magnitudes so
    # both sides sum the same terms in the same order.
    observations["wadaSNRDB"] = wada_snr(samples)

    # 10 ms frames: noise floor and the codec-frame modulation index.
    per_second = constants["framesPerSecond"]
    hop = sample_rate // per_second if sample_rate % per_second == 0 else 0
    observations["noiseFloorDBFS"] = None
    observations["codecFrameModulationIndex"] = None
    if hop > 0 and count >= hop:
        frames = count // hop
        mean_square = (samples[:frames * hop].reshape(frames, hop) ** 2).sum(axis=1) / hop
        rms = np.sqrt(mean_square)
        floor = constants["noiseFloor"]["levelFloorDBFS"]
        levels = sorted(20.0 * math.log10(max(float(value), 10.0 ** (floor / 20.0))) for value in rms)
        tenths = constants["noiseFloor"]["quantileTenths"]
        rank = max(0, (frames * tenths + 9) // 10 - 1)
        observations["noiseFloorDBFS"] = levels[min(rank, frames - 1)]
        period = constants["modulation"]["periodFrames"]
        whole = frames - frames % period
        if whole > 0:
            real = imaginary = total = 0.0
            for index, value in enumerate(rms[:whole].tolist()):
                real += value * _COS8[index % period]
                imaginary += value * _SIN8[index % period]
                total += value
            observations["codecFrameModulationIndex"] = (
                2.0 * math.sqrt(real * real + imaginary * imaginary) / total if total > 0 else None
            )

    # Spectral measures: flux events, bandwidth and the repetition stripe.
    spectrum = constants["spectrum"]
    observations.update({
        "effectiveBandwidthHz": None, "spectralFluxEventCount": None, "spectralFluxEventsPerSecond": None,
        "repetitionStripeLongestMS": None, "repetitionStripeLagMS": None, "repetitionStripeCount": None,
    })
    if hop > 0 and sample_rate >= spectrum["minimumSampleRate"]:
        size = spectrum["fftSize"] if sample_rate <= spectrum["fftSizeRateLimit"] else spectrum["fftSizeAboveRate"]
        observations.update(_spectral(np, samples, sample_rate, hop, size, duration))

    # Streaming seams.
    observations.update(_seams(samples, sample_rate, hop, seam_offsets))

    for key in ("integratedLoudnessLUFS", "shortTermLoudnessMaxLUFS", "loudnessRangeLU", "truePeakDBTP",
                "wadaSNRDB", "noiseFloorDBFS", "codecFrameModulationIndex", "effectiveBandwidthHz",
                "spectralFluxEventsPerSecond", "seamDiscontinuityMaxZ"):
        observations[key] = round4(observations.get(key))
    return observations


def _spectral(np: Any, samples: Any, sample_rate: int, hop: int, size: int, duration: float) -> dict[str, Any]:
    constants = STAGE0_OBSERVATIONS
    spectrum = constants["spectrum"]
    window = 0.5 - 0.5 * np.cos(2.0 * np.pi * np.arange(size) / size)
    window_energy = float((window * window).sum())
    frames = _frames(np, samples, size, hop)
    result: dict[str, Any] = {}
    frame_count = frames.shape[0]
    windowed = frames * window[None, :]
    mean_square = (windowed * windowed).sum(axis=1) / window_energy if frame_count else np.zeros(0)
    power = (np.abs(np.fft.rfft(windowed, axis=1)) ** 2) / window_energy if frame_count else np.zeros((0, size // 2 + 1))
    half = size // 2

    # Log-spectral flux events.
    flux_constants = constants["spectralFlux"]
    events = 0
    last_above: int | None = None
    if frame_count:
        logs = np.log10(np.maximum(power[:, 1:half], spectrum["powerFloor"]))
        for index in range(1, frame_count):
            rise = logs[index] - logs[index - 1]
            flux = 10.0 * float(rise[rise > 0].sum()) / (half - 1)
            if flux >= flux_constants["eventThresholdDB"]:
                if last_above is None or index - last_above > flux_constants["clusterGapFrames"]:
                    events += 1
                last_above = index
    result["spectralFluxEventCount"] = events
    result["spectralFluxEventsPerSecond"] = events / duration if duration > 0 else None

    # Effective bandwidth.
    active = mean_square >= spectrum["activeMeanSquare"]
    result["effectiveBandwidthHz"] = None
    if active.any():
        ltas = power[active].sum(axis=0) / int(active.sum())
        bandwidth = constants["bandwidth"]
        levels = 10.0 * np.log10(np.maximum(ltas[1:], bandwidth["ltasFloor"]))
        threshold = float(levels.max()) - bandwidth["thresholdDB"]
        highest = int(np.flatnonzero(levels >= threshold).max()) + 1
        result["effectiveBandwidthHz"] = highest * sample_rate / size

    result.update(_repetition(np, power, mean_square, size, hop, sample_rate))
    return result


def _repetition(np: Any, power: Any, mean_square: Any, size: int, hop: int, sample_rate: int) -> dict[str, Any]:
    constants = STAGE0_OBSERVATIONS["repetition"]
    spectrum = STAGE0_OBSERVATIONS["spectrum"]
    pool = constants["poolFrames"]
    # Bin edges scale with the FFT; the last band always ends past the Nyquist bin.
    scale = size // 512
    edges = [edge * scale for edge in constants["bandEdgesAt512"][:-1]] + [size // 2 + 1]
    bands = len(edges) - 1
    pooled = power.shape[0] // pool
    features = np.zeros((pooled, bands))
    active = np.zeros(pooled, dtype=bool)
    for u in range(pooled):
        band_power = np.zeros(bands)
        pooled_square = 0.0
        for frame in range(u * pool, (u + 1) * pool):
            for b in range(bands):
                band_power[b] += float(power[frame, edges[b]:edges[b + 1]].sum()) / (edges[b + 1] - edges[b])
            pooled_square += float(mean_square[frame])
        band_power /= pool
        levels = 10.0 * np.log10(np.maximum(band_power, spectrum["powerFloor"]))
        levels -= float(levels.sum()) / bands
        norm = math.sqrt(float((levels * levels).sum()))
        if pooled_square / pool >= spectrum["activeMeanSquare"] and norm >= constants["featureNormFloor"]:
            features[u] = levels / norm
            active[u] = True

    threshold = constants["cosineThreshold"]
    changing_prefix = [0] * (pooled + 1)
    for u in range(pooled):
        changes = 0
        if u >= 1 and active[u] and active[u - 1]:
            changes = int(float(features[u] @ features[u - 1]) < threshold)
        changing_prefix[u + 1] = changing_prefix[u] + changes

    best_length = 0
    best_lag = 0
    stripes = 0
    upper = min(constants["maximumLagFrames"], pooled - 1)
    for lag in range(constants["minimumLagFrames"], upper + 1):
        dots = np.zeros(pooled - lag)
        for b in range(bands):
            dots += features[:pooled - lag, b] * features[lag:, b]
        match = active[:pooled - lag] & active[lag:] & (dots >= threshold)
        start: int | None = None
        for u in range(pooled - lag + 1):
            if u < pooled - lag and match[u]:
                if start is None:
                    start = u
                continue
            if start is None:
                continue
            end = u - 1
            length = end - start + 1
            if changing_prefix[end + 1] - changing_prefix[start + 1] >= constants["minimumChangingFrames"]:
                if length > best_length:
                    best_length, best_lag = length, lag
                if length >= constants["minimumStripeFrames"]:
                    stripes += 1
            start = None
    frame_ms = pool * hop * 1000 // sample_rate
    return {
        "repetitionStripeLongestMS": best_length * frame_ms,
        "repetitionStripeLagMS": best_lag * frame_ms if best_length else None,
        "repetitionStripeCount": stripes,
    }


def _seams(samples: Any, sample_rate: int, hop: int, seam_offsets: Sequence[int]) -> dict[str, Any]:
    count = int(samples.size)
    half = hop * STAGE0_OBSERVATIONS["seam"]["halfWindowFrames"]
    sigma_floor = STAGE0_OBSERVATIONS["seam"]["sigmaFloor"]
    best: float | None = None
    best_start: int | None = None
    evaluated = 0
    if half > 0:
        for seam in sorted({int(offset) for offset in seam_offsets}):
            if seam < 1 or seam >= count:
                continue
            total = squares = 0.0
            neighbours = 0
            for index in range(max(1, seam - half), min(count - 1, seam + half) + 1):
                if index == seam:
                    continue
                step = abs(float(samples[index]) - float(samples[index - 1]))
                total += step
                squares += step * step
                neighbours += 1
            if neighbours == 0:
                continue
            evaluated += 1
            mean = total / neighbours
            sigma = math.sqrt(max(squares / neighbours - mean * mean, 0.0))
            z = (abs(float(samples[seam]) - float(samples[seam - 1])) - mean) / max(sigma, sigma_floor)
            if best is None or z > best:
                best, best_start = z, int(seam * 1000 / sample_rate)
    return {"seamCount": evaluated, "seamDiscontinuityMaxZ": best, "seamDiscontinuityMaxZStartMS": best_start}


# --------------------------------------------------------------------------- #
# Shared parity fixtures
# --------------------------------------------------------------------------- #

def synthesize_fixture(segments: Sequence[dict[str, Any]], sample_rate: int = 24_000) -> list[int]:
    """The PCM16 samples of a fixture recipe; AudioQCSignalObservationTests builds the same.

    Every value is computed in the order written here, then quantized as the
    engine writes PCM16: sign(v) * floor(|v| * 32767 + 0.5), capped at 32767.
    Noise is a 32-bit linear congruential stream, so both languages draw the
    same integers.
    """
    values: list[float] = []
    rate = float(sample_rate)
    for segment in segments:
        kind = segment["kind"]
        count = int(segment.get("samples", 0))
        if kind == "silence":
            values.extend([0.0] * count)
        elif kind == "sine":
            frequency, amplitude = float(segment["frequencyHz"]), float(segment["amplitude"])
            phase = float(segment.get("phase", 0.0))
            values.extend(amplitude * math.sin(2.0 * math.pi * frequency * float(i) / rate + phase)
                          for i in range(count))
        elif kind == "am":
            frequency, amplitude = float(segment["frequencyHz"]), float(segment["amplitude"])
            modulation, depth = float(segment["modulationHz"]), float(segment["depth"])
            values.extend(amplitude * (1.0 + depth * math.cos(2.0 * math.pi * modulation * float(i) / rate))
                          * math.sin(2.0 * math.pi * frequency * float(i) / rate) for i in range(count))
        elif kind == "chirp":
            start, end = float(segment["startHz"]), float(segment["endHz"])
            amplitude = float(segment["amplitude"])
            span = float(count)
            values.extend(amplitude * math.sin(2.0 * math.pi * (start * float(i) / rate
                                                                 + (end - start) * float(i) * float(i)
                                                                 / (2.0 * span * rate)))
                          for i in range(count))
        elif kind == "noise":
            amplitude = float(segment["amplitude"])
            state = int(segment["seed"]) % 4_294_967_296
            for _ in range(count):
                state = (state * 1_664_525 + 1_013_904_223) % 4_294_967_296
                values.append(amplitude * (2.0 * float(state) / 4_294_967_296.0 - 1.0))
        elif kind == "copy":
            start = int(segment["start"])
            values.extend(values[start:start + count])
        elif kind == "impulses":
            amplitude = float(segment["amplitude"])
            for position in segment["positions"]:
                values[int(position)] += amplitude
        else:
            raise ValueError(f"unknown fixture segment kind {kind!r}")
    pcm = []
    for value in values:
        magnitude = min(32_767.0, math.floor(abs(value) * 32_767.0 + 0.5))
        pcm.append(int(-magnitude if value < 0 else magnitude))
    return pcm


# --------------------------------------------------------------------------- #
# Engine introspection
# --------------------------------------------------------------------------- #

def introspection_summary(tokens: Sequence[int], *, entropies: Sequence[float] = (),
                          eos_probabilities: Sequence[float] = (), stopped_at_eos: bool = False,
                          seam_frames: Sequence[int] = ()) -> dict[str, Any]:
    """`Qwen3GenerationIntrospector.summary()` for a codebook-0 sequence and its steps.

    `entropies` and `eos_probabilities` hold one value per observed step: every
    codec token, plus the step that sampled EOS when `stopped_at_eos`.
    """
    constants = INTROSPECTION
    period_limit = constants["maximumCyclePeriod"]
    runs = [0] * (period_limit + 1)
    history: list[int] = []
    longest_constant = 0
    cycle: tuple[int, int, int] | None = None  # (span, period, start)
    for frame, token in enumerate(tokens):
        for period in range(1, period_limit + 1):
            if len(history) >= period and history[-period] == token:
                runs[period] += 1
            else:
                runs[period] = 0
        history.append(token)
        if len(history) > period_limit:
            history.pop(0)
        dominant = 0
        dominant_span = 0
        for period in range(1, period_limit + 1):
            if runs[period] >= period and runs[period] + period > dominant_span:
                dominant, dominant_span = period, runs[period] + period
        if frame == 0:
            longest_constant = 1
        if dominant == 1:
            longest_constant = max(longest_constant, dominant_span)
        elif dominant >= 2 and (cycle is None or dominant_span > cycle[0]):
            cycle = (dominant_span, dominant, frame - dominant_span + 1)

    bins = constants["entropyHistogramBins"]
    per_nat = constants["entropyHistogramBinsPerNat"]
    histogram = [0] * bins
    total = 0.0
    observed = 0
    high_run = longest_high = 0
    for value in entropies:
        if not math.isfinite(value):
            high_run = 0
            continue
        observed += 1
        total += value
        histogram[min(bins - 1, max(0, int(math.floor(value * per_nat))))] += 1
        high_run = high_run + 1 if value >= constants["highEntropyNats"] else 0
        longest_high = max(longest_high, high_run)
    p95 = None
    if observed:
        rank = (observed * 95 + 99) // 100
        cumulative = 0
        for index, entries in enumerate(histogram):
            cumulative += entries
            if cumulative >= rank:
                p95 = (index + 1) / per_nat
                break

    steps = len(eos_probabilities)
    final = maximum = None
    maximum_step = first_likely = None
    likely_without_stop = 0
    for step, value in enumerate(eos_probabilities):
        if not math.isfinite(value):
            continue
        stopped = stopped_at_eos and step == steps - 1
        final = value
        if maximum is None or value > maximum:
            maximum, maximum_step = value, step
        if value >= constants["likelyEOSProbability"]:
            if first_likely is None:
                first_likely = step
            if not stopped:
                likely_without_stop += 1

    frames = len(tokens)
    seams = sorted({int(seam) for seam in seam_frames if 0 < int(seam) < frames})[:constants["maximumSeams"]]
    return {
        "algorithmVersion": INTROSPECTION_ALGORITHM_VERSION,
        "codecFrameCount": frames,
        "longestRepeatedTokenRunFrames": longest_constant,
        "tokenCyclePeriod": cycle[1] if cycle else None,
        "tokenCycleSpanFrames": cycle[0] if cycle else None,
        "tokenCycleRepeats": cycle[0] // cycle[1] if cycle else None,
        "tokenCycleStartFrame": cycle[2] if cycle else None,
        "observedStepCount": observed,
        "entropyMeanNats": round4(total / observed) if observed else None,
        "entropyP95Nats": p95,
        "longestHighEntropyRunSteps": longest_high,
        "eosProbabilityFinal": round4(final),
        "eosProbabilityMax": round4(maximum),
        "eosProbabilityMaxStep": maximum_step,
        "eosFirstLikelyStep": first_likely,
        "eosLikelyStepsWithoutStop": likely_without_stop,
        "seamCodecFrames": seams,
    }
