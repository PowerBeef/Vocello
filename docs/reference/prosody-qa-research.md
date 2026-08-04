---
status: active
owner: backend-mlx
summary: Research notes behind the automated tone/tempo/cadence quality gates — analyzer landscape, metric choices, and the usage entry points for the prosody lanes. Point-in-time sections are dated inline; commands reflect the live preset roster.
sourceOfTruth:
  - scripts/bench_delivery_prosody.py
  - Sources/QwenVoiceCore/EmotionPreset.swift
---
# Prosody QA Research Notes

> Research for improving Vocello's automated tone/tempo/cadence quality gate.
> Date: 2026-06-15

## Current pipeline

Vocello already has three audio QA layers:

1. **Signal-level QC** (`AudioQualityGate.swift` / `AudioQCReport`): deterministic, reference-free checks for clipping, DC offset, dropouts, discontinuities, silence, and duration.
2. **Delivery adherence** (`scripts/analyze_delivery.py` + `scripts/delivery_adherence.py`): deterministic, paired neutral-vs-instructed A/B using median F0, F0 range, syllable rate, and duration deltas.
3. **Optional listening annotation**: records subjective timbre/naturalness impressions without changing the automated verdict. An earlier external-model listening pass was removed after proving unreliable.

The gap: none of the automated layers reliably catches **monotone delivery**, **rushed/slurred cadence**, **unnatural pauses**, or **weak emotional differentiation** within a single take.

## Research findings

### Objective TTS prosody metrics in literature

Common objective metrics used in expressive/instructional TTS papers:

| Metric | What it measures | Reference-free | Notes |
|--------|------------------|----------------|-------|
| **F0 MSE / RMSE** | Frame-level pitch error vs ground truth | No | Needs reference audio |
| **F0 correlation (Pearson)** | Similarity of F0 contour to reference | No | Needs reference + alignment |
| **GPE (Gross Pitch Error)** | % frames with F0 off by > threshold | No | Standard in pitch trackers |
| **VDE (Voicing Decision Error)** | % frames misclassified voiced/unvoiced | No | Standard |
| **F0 std / range** | Intonation variability | Yes | Already used partially |
| **Duration std / pause ratio** | Rhythmic variability | Yes | Good for cadence |
| **MCD (Mel Cepstral Distortion)** | Spectral distance to reference | No | Captures quality, not prosody specifically |
| **STOI / PESQ / POLQA** | Perceptual quality/intelligibility | Mostly no | Speech-enhancement oriented |
| **F0 contour turning-point rate** | Prosodic dynamics | Yes | Captures monotone vs expressive |
| **Local syllable-rate CV** | Speaking-rate variability | Yes | Catches rushed/slurred |
| **RMS envelope dynamics** | Stress/energy variation | Yes | Complements F0 |

Key papers:

- *InstructTTS* (2023): uses MCD, SSIM, STOI for quality and GPE/VDE/FPE for prosody similarity.
- *InstructTTSEval* (2025): notes the lack of automated metrics for instruction-based acoustic control and uses Gemini as a judge.
- *SponTTS* (2024): uses **F0 std** and **duration std** to quantify spontaneous vs reading-style prosody.
- *TTScore-pro* (2025): uses discrete FACodec prosody tokens to evaluate pitch-pattern naturalness.

Takeaway: the most practical, reference-free prosody metrics are **F0 contour statistics**, **pause/duration structure**, and **speaking-rate variability**.

### Reference-free perceptual quality predictors

DNN-based reference-free metrics exist but are mostly trained for speech enhancement / general quality, not specifically for TTS prosody or instruction adherence:

| Tool | Output | License / Dependency | Fit for Vocello |
|------|--------|----------------------|-----------------|
| **DNSMOS** | MOS + SIG/BAK/OVRL | Microsoft research, ONNX model | General quality, not prosody-specific |
| **NISQA** | MOS + noisiness/discontinuity/coloration/loudness | Apache-ish, via torchmetrics; needs librosa | General quality, limited prosody |
| **UTMOS / SSL-MOS** | MOS | Various, SSL-based | General quality |
| **SQUIM** | MOS + PESQ + STOI | torchaudio, reference-free | General quality |

These could be added as an optional general-quality signal, but they do not solve the tone/tempo/cadence diagnosis problem directly and introduce heavy dependencies.

### Python tooling options

| Tool | Capabilities | License | Notes |
|------|--------------|---------|-------|
| **numpy + stdlib `wave`** | Everything if hand-rolled | Permissive | Current approach; slow to develop but zero deps |
| **librosa** | Pitch (YIN/piptrack), onset, RMS/MFCC, tempogram, silence detection, resampling | MIT | Best balance: robust, well-maintained, permissive |
| **parselmouth** | Full Praat pitch/formant/intensity/HNR/jitter/shimmer | GPL-linked (Praat) | Very robust pitch/pause, but GPL dependency risky for a commercial-adjacent product |
| **openSMILE** | ComParE / GeMAPS feature sets (6k+ features) | audEERING dual license; commercial use restricted | Too heavy and license-restricted |
| **torchaudio + SQUIM** | Neural MOS estimates | PyTorch | Heavy dependency, not prosody-specific |

Constraint: the target machine has **8 GB RAM** and `librosa` is not installed. Loading heavy neural quality models (DNSMOS/NISQA/SQUIM) would also push memory and add weakly prosody-specific dependencies.

Final choice: **numpy + stdlib `wave`** (zero new dependencies, bounded memory). Hand-rolled pitch tracking (NCF), syllable-nuclei detection, and pause/energy analysis are sufficient for a dev/benchmark gate and keep the pipeline deterministic and privacy-safe.

## Implemented solution

The Swift `GenerationQualityReport`, `QualityGateRegistry`, and `QualityReviewPolicy` types are a
deterministic convergence foundation for composing Fast, Standard, and Canonical evidence. They do
not yet replace this analyzer, persisted-WAV Fast QC, three-pass ASR, delivery adherence, or the
existing benchmark validators. Until one shipping scheduler emits and validates the unified report,
those specialized gates remain authoritative and one-pass ASR remains diagnostic only.

### New scripts

- **`scripts/analyze_prosody.py`** — numpy-only reference-free prosody analyzer:
  - **Bounded execution**: analyzer algorithm v2 makes exactly two fixed-block passes, retains no
    complete PCM or two-dimensional frame matrix, and reports both its measured managed-buffer
    high-water mark and a conservative estimated peak working set. The estimate excludes the
    already-loaded Python and NumPy runtimes.
  - **F0 contour**: median/mean/std/range/p10/p90, voiced fraction, rising/falling rates, turning-point rate.
  - **Relative pitch**: semitone standard deviation/range and p10/p90 offsets relative to the clip's
    median pitch, so cross-speaker comparisons do not confuse register with expressiveness.
  - **Speaking rate**: syllable-nuclei rate, local-rate mean/std/CV/p10/p90.
  - **Pauses**: count, total/mean/max duration, pause-to-speech ratio.
  - **Energy**: RMS mean/std/dynamic range, envelope roughness.
  - **Signal and boundaries**: clipping, adjacent-sample click evidence, and optional declared
    boundary sample/RMS/pitch/silence discontinuity aggregates. Boundary positions are supplied by
    the caller; the analyzer does not infer chunk or segment identity from audio.
- **`scripts/prosody_quality_gate.py`** — flags monotone, rushed, flat/slurred, and pause-issue takes with conservative thresholds. Run per-clip or import `evaluate(path)`.
- **`scripts/bench_delivery_prosody.py`** — post-processes `vocello bench --delivery` WAVs, pairs each instructed take with its neutral reference, and writes `diagnostics/bench-prosody.json`.

### Updated scripts

- **`scripts/delivery_adherence.py`** — now computes paired deltas on the richer prosody feature set and reports `prosodyEffect` + `prosodyPosRate` alongside the existing arousal score. Added `--data-dir` for non-default model locations.
- **`scripts/summarize_generation_telemetry.py`** — reads `bench-prosody.json` and renders `prosN`, `prosEff`, `dF0Std`, `dRateCV`, `dPauseR`, `dRough` in the delivery-cells table.
- **`Sources/VocelloCLI/BenchCommand.swift`** — `vocello bench --delivery` invokes `scripts/bench_delivery_prosody.py` from the immutable current-run manifest **before** final aggregation, so the summary includes the delivery block and stale `--keep` WAVs cannot enter it.

### Usage

```bash
# Per-clip prosody gate
scripts/prosody_quality_gate.py outputs/some_take.wav

# Delivery A/B with richer prosody deltas
scripts/delivery_adherence.py --presets happy,sad --seeds 4 --data-dir ~/Library/Application\ Support/QwenVoice

# Bench with delivery cells + automatic prosody analysis
build/vocello bench --delivery happy,calm --modes custom,design
```

Manual listening is independent of the automated gates and optional for every workflow. Engine
promotion requires the deterministic QC and applicable paired prosody/language gates to pass; a
listening note cannot waive a machine failure or warning.

### Calibration note

Thresholds in `prosody_quality_gate.py` and weights in `delivery_adherence.py` are intentionally conservative defaults. They should be calibrated against a labeled corpus of good/bad Vocello takes once enough examples are collected.

Analyzer algorithm v2 preserves the established consumer keys, but its p10, median, and p90 values
come from deterministic fixed-width histograms instead of duration-sized arrays. F0 quantiles can
therefore move by up to roughly half of the 0.25 Hz bin width, and RMS quantiles by roughly half of
the 0.05 dB bin width; a threshold exactly on a bin edge can change classification. New calibration
profiles record `analyzer_algorithm_version = 2`. Existing schema-v1 profiles remain readable, but
promotion should recalibrate or explicitly review their thresholds rather than claiming exact
numeric parity with the legacy full-array method.

Persisted Vocello outputs are PCM16, so NaN and infinity cannot exist in a supported WAV. The
analyzer reports a zero non-finite count for validated PCM16 and rejects float/unsupported sample
formats before producing signal claims. Pre-conversion NaN/Inf remains owned by the Swift limiter
and persisted-WAV QC path.
