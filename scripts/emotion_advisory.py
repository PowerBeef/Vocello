#!/usr/bin/env python3
"""ADVISORY speech-emotion agreement column for delivery takes.

Classifies generated WAVs with a pinned, permissively licensed speech-emotion
model and reports whether the top emotion agrees with the selected delivery
preset. This is a dev-lane advisory metric in the same class as
``clone_speaker_similarity.py``: it is not a CI gate, not a packaging
prerequisite, and never publishes benchmark history. The deterministic
delivery gate (``delivery_quality_gate.py``) remains the promoted verdict;
this column adds an independent perceptual cross-check.

Memory rule (Mac mini M2 8 GB dev floor): run strictly AFTER generation
completes — never while the engine is resident. The model is wav2vec2-large
(~1.3 GB fp32 weights, CPU); the report records the process peak RSS so the
first run on any machine documents its envelope.

Backend: torch + transformers, lazy-imported inside ``hf_classifier`` so this
module's verdict logic imports and unit-tests without them. One-time setup:

  python3 -m venv .venv && .venv/bin/pip install torch transformers

Usage:
  scripts/emotion_advisory.py --sidecar <diag>/bench-prosody.json \
      --outputs-dir <data>/outputs/bench [--out emotion-advisory.json]
  scripts/emotion_advisory.py clip.wav --delivery happy.strong [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

EMOTION_MODEL_SOURCE = "firdhokk/speech-emotion-recognition-with-facebook-wav2vec2-large-xlsr-53"
EMOTION_MODEL_REVISION = "611e6db8ee667aa07fe66596f9fc761e036ff5b9"
EMOTION_MODEL_SAMPLE_RATE = 16_000
# The pinned checkpoint's exact label set; classification fails closed if the
# loaded model's id2label drifts from this.
EMOTION_LABELS = (
    "angry", "disgust", "fearful", "happy", "neutral", "sad", "surprised",
)

# Preset id → emotion labels counted as agreement. Presets whose acoustic
# target is not an emotion category (whisper) abstain: whispered speech is
# out-of-distribution for emotion corpora, so the SER column reports the top
# emotion without judging.
PRESET_ALLOWED_EMOTIONS = {
    "happy": {"happy"},
    "sad": {"sad"},
    "angry": {"angry"},
    "fearful": {"fearful"},
    "surprised": {"surprised"},
    "calm": {"neutral"},
    "neutral": {"neutral"},
}
ABSTAIN_PRESETS = {"whisper"}

ADVISORY_VERSION = 1


def evaluate_agreement(probabilities, delivery_id):
    """Pure agreement verdict from a label→probability dict and delivery id."""
    preset = str(delivery_id).partition(".")[0]
    if not isinstance(probabilities, dict) or not probabilities:
        return {
            "deliveryID": delivery_id,
            "preset": preset,
            "topEmotion": None,
            "topProbability": None,
            "allowedEmotions": [],
            "agreement": None,
            "note": "classification_unavailable",
        }
    top_emotion, top_probability = max(probabilities.items(), key=lambda item: item[1])
    if preset in ABSTAIN_PRESETS:
        allowed: set[str] = set()
        agreement = None
        note = "preset_abstains"
    elif preset in PRESET_ALLOWED_EMOTIONS:
        allowed = PRESET_ALLOWED_EMOTIONS[preset]
        agreement = top_emotion in allowed
        note = None
    else:
        allowed = set()
        agreement = None
        note = "preset_unmapped"
    report = {
        "deliveryID": delivery_id,
        "preset": preset,
        "topEmotion": top_emotion,
        "topProbability": round(float(top_probability), 4),
        "allowedEmotions": sorted(allowed),
        "agreement": agreement,
    }
    if note:
        report["note"] = note
    return report


def _load_wav_mono_16k(path):
    """Read PCM16 WAV → mono float32 at the model rate (linear resample)."""
    import wave

    import numpy as np

    with wave.open(path, "rb") as reader:
        if reader.getsampwidth() != 2:
            raise ValueError(f"expected 16-bit PCM: {path}")
        rate = reader.getframerate()
        frames = reader.readframes(reader.getnframes())
    pcm = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    channels = 1
    with wave.open(path, "rb") as reader:
        channels = reader.getnchannels()
    if channels > 1:
        pcm = pcm.reshape(-1, channels).mean(axis=1)
    if rate != EMOTION_MODEL_SAMPLE_RATE and len(pcm) > 1:
        duration = len(pcm) / rate
        target_count = int(round(duration * EMOTION_MODEL_SAMPLE_RATE))
        positions = np.linspace(0.0, len(pcm) - 1, target_count)
        pcm = np.interp(positions, np.arange(len(pcm)), pcm).astype(np.float32)
    return pcm


def hf_classifier():
    """Build the pinned CPU classifier. Heavy imports stay inside this function."""
    import torch
    from transformers import AutoFeatureExtractor, AutoModelForAudioClassification

    extractor = AutoFeatureExtractor.from_pretrained(
        EMOTION_MODEL_SOURCE, revision=EMOTION_MODEL_REVISION
    )
    model, loading_info = AutoModelForAudioClassification.from_pretrained(
        EMOTION_MODEL_SOURCE, revision=EMOTION_MODEL_REVISION, output_loading_info=True
    )
    if loading_info.get("missing_keys"):
        raise RuntimeError(
            "pinned emotion model did not load cleanly — classifier weights "
            f"missing from checkpoint: {loading_info['missing_keys'][:4]}"
        )
    model.eval()
    loaded_labels = tuple(
        model.config.id2label[index] for index in sorted(model.config.id2label)
    )
    if loaded_labels != EMOTION_LABELS:
        raise RuntimeError(
            f"pinned emotion model label drift: {loaded_labels} != {EMOTION_LABELS}"
        )

    def classify(path):
        audio = _load_wav_mono_16k(path)
        inputs = extractor(
            audio, sampling_rate=EMOTION_MODEL_SAMPLE_RATE, return_tensors="pt"
        )
        with torch.no_grad():
            logits = model(**inputs).logits[0]
        probabilities = torch.softmax(logits, dim=-1).tolist()
        return dict(zip(EMOTION_LABELS, probabilities))

    return classify


def peak_rss_bytes():
    """Process peak RSS (macOS reports bytes; Linux kilobytes)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak if sys.platform == "darwin" else peak * 1024


def analyze_sidecar(sidecar_path, outputs_dir, classify):
    """Advisory rows for every delivery take in one bench-prosody sidecar."""
    with open(sidecar_path, "r", encoding="utf-8") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list) or not rows:
        raise ValueError("sidecar must be a non-empty array")
    reports = []
    for row in rows:
        wav_name = row.get("deliveryWav")
        delivery_id = row.get("delivery")
        if not isinstance(wav_name, str) or not isinstance(delivery_id, str):
            raise ValueError("sidecar row lacks deliveryWav/delivery")
        wav_path = os.path.join(outputs_dir, os.path.basename(wav_name))
        if not os.path.isfile(wav_path):
            raise ValueError(f"delivery output missing: {wav_name}")
        probabilities = classify(wav_path)
        report = evaluate_agreement(probabilities, delivery_id)
        report["clip"] = os.path.basename(wav_name)
        report["generationID"] = row.get("generationID")
        reports.append(report)
    judged = [report for report in reports if report["agreement"] is not None]
    agreed = sum(1 for report in judged if report["agreement"])
    return {
        "advisoryVersion": ADVISORY_VERSION,
        "modelSource": EMOTION_MODEL_SOURCE,
        "modelRevision": EMOTION_MODEL_REVISION,
        "takes": reports,
        "aggregate": {
            "count": len(reports),
            "judged": len(judged),
            "agreed": agreed,
            "agreementRate": round(agreed / len(judged), 3) if judged else None,
        },
        "peakRSSBytes": peak_rss_bytes(),
    }


def main():
    parser = argparse.ArgumentParser(description="Advisory SER agreement column.")
    parser.add_argument("clips", nargs="*", help="WAV file(s) (single-clip mode)")
    parser.add_argument("--delivery", help="delivery id for single-clip mode")
    parser.add_argument("--sidecar", help="bench-prosody.json (sidecar mode)")
    parser.add_argument("--outputs-dir", help="bench outputs dir (sidecar mode)")
    parser.add_argument("--out", help="write the advisory JSON here (sidecar mode)")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args()

    classify = hf_classifier()
    if args.sidecar:
        if not args.outputs_dir:
            parser.error("--sidecar requires --outputs-dir")
        report = analyze_sidecar(args.sidecar, args.outputs_dir, classify)
        if args.out:
            with open(args.out, "w", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2, sort_keys=True)
                handle.write("\n")
        print(json.dumps(report["aggregate"], indent=2))
        return
    if not args.clips or not args.delivery:
        parser.error("provide WAVs with --delivery, or --sidecar with --outputs-dir")
    reports = []
    for path in args.clips:
        report = evaluate_agreement(classify(path), args.delivery)
        report["clip"] = os.path.basename(path)
        reports.append(report)
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()
