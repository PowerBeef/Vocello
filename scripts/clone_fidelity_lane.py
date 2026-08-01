#!/usr/bin/env python3
"""Clone-fidelity lane: reference vs fixed-seed clone takes, plus controls.

Generates N fixed-seed clone takes of a saved voice with the CLI, then runs
the layered analyzers against the voice's reference clip:

  1. ``clone_prosody_fidelity``   — deterministic delivery/tone distances
                                    (warn-first bounds from the prosody profile)
  2. ``clone_speaker_similarity`` — ECAPA identity cosine (advisory bands);
                                    skipped with a note when torch is absent
  3. ``emotion_advisory``         — reference-vs-take top-emotion match;
                                    skipped with a note when torch is absent

Optionally generates built-in-speaker custom takes of the same text as
negative controls, so the identity bands can be calibrated from measured
same-voice vs different-voice separations instead of placeholders.

ADVISORY dev lane: not a CI gate, not a packaging prerequisite, never
publishes benchmark history. Memory rule (M2 8 GB): generation and the ML
analyzers run strictly sequentially — takes are generated one process at a
time, and the torch-backed analyzers start only after the last generation
process has exited.

Usage:
  python3 scripts/clone_fidelity_lane.py --voice A_warm_elderly_woman \
      [--takes 6] [--controls 2] [--base-seed 20260810] [--label ID]
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from clone_prosody_fidelity import evaluate_takes

LANE_VERSION = 1
FIXED_TEXT = (
    "The harbor lights flickered as the evening ferry pulled away, and she "
    "wondered how many more crossings the old captain had left in him."
)
CONTROL_SPEAKERS = ("aiden", "serena")


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_data_dir():
    return os.path.expanduser("~/Library/Application Support/QwenVoice-Debug")


def reference_path(data_dir, voice):
    return os.path.join(data_dir, "voices", f"{voice}.wav")


def build_take_plan(voice, take_count, control_count, base_seed):
    """Deterministic generation plan: clone takes then negative controls."""
    plan = []
    for index in range(take_count):
        plan.append({
            "kind": "clone",
            "mode": "clone",
            "voice": voice,
            "seed": base_seed + index,
            "name": f"clone_take_{index:02d}.wav",
        })
    for index in range(control_count):
        speaker = CONTROL_SPEAKERS[index % len(CONTROL_SPEAKERS)]
        plan.append({
            "kind": "control",
            "mode": "custom",
            "speaker": speaker,
            "seed": base_seed + index,
            "name": f"control_{speaker}_{index:02d}.wav",
        })
    return plan


def generation_command(vocello, item, out_dir):
    command = [
        vocello, "generate", "--mode", item["mode"], "--variant", "speed",
        "--text", FIXED_TEXT, "--seed", str(item["seed"]),
        "--variation", "consistent",
        "--out", os.path.join(out_dir, item["name"]),
    ]
    if item["kind"] == "clone":
        command += ["--voice", item["voice"]]
    else:
        command += ["--speaker", item["speaker"]]
    return command


def generate_all(plan, out_dir, vocello, run=subprocess.run):
    """One CLI process at a time; fail loudly with the take that broke."""
    for item in plan:
        result = run(
            generation_command(vocello, item, out_dir),
            capture_output=True,
            text=True,
            env={**os.environ, "QWENVOICE_DEBUG": "1"},
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"generation failed for {item['name']}: {result.stderr.strip()[-400:]}"
            )


def ecapa_section(reference, clone_paths, control_paths):
    """Identity similarity with measured positive/negative separation."""
    try:
        from clone_speaker_similarity import analyze_takes, ecapa_embedder, load_similarity_profile
    except Exception as error:  # pragma: no cover - import shape guard
        return {"skipped": f"clone_speaker_similarity unavailable: {error}"}
    try:
        embed = ecapa_embedder()
    except Exception as error:
        return {"skipped": f"torch/speechbrain not installed: {error}"}
    profile = load_similarity_profile(None)
    section = {"clones": analyze_takes(reference, clone_paths, embed, profile)}
    if control_paths:
        section["controls"] = analyze_takes(reference, control_paths, embed, profile)
    return section


def emotion_section(reference, clone_paths):
    """Reference-vs-take top-emotion agreement (advisory)."""
    try:
        from emotion_advisory import hf_classifier
    except Exception as error:  # pragma: no cover - import shape guard
        return {"skipped": f"emotion_advisory unavailable: {error}"}
    try:
        classify = hf_classifier()
    except Exception as error:
        return {"skipped": f"torch/transformers not installed: {error}"}
    reference_probabilities = classify(reference)
    reference_top = max(reference_probabilities.items(), key=lambda item: item[1])[0]
    takes = []
    matches = 0
    for path in clone_paths:
        probabilities = classify(path)
        top = max(probabilities.items(), key=lambda item: item[1])[0]
        matched = top == reference_top
        matches += int(matched)
        takes.append({
            "clip": os.path.basename(path),
            "topEmotion": top,
            "matchesReference": matched,
        })
    return {
        "referenceTopEmotion": reference_top,
        "takes": takes,
        "matchRate": round(matches / len(takes), 3) if takes else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Clone fidelity lane (advisory).")
    parser.add_argument("--voice", default="A_warm_elderly_woman")
    parser.add_argument("--takes", type=int, default=6)
    parser.add_argument("--controls", type=int, default=2)
    parser.add_argument("--base-seed", type=int, default=20_260_810)
    parser.add_argument("--label", default="clone-fidelity")
    parser.add_argument("--data-dir", default=default_data_dir())
    parser.add_argument("--skip-generation", action="store_true",
                        help="reuse takes already present in the run directory")
    parser.add_argument("--run-dir", help="explicit run directory (with --skip-generation)")
    args = parser.parse_args()

    root = repo_root()
    vocello = os.path.join(root, "build", "vocello")
    reference = reference_path(args.data_dir, args.voice)
    if not os.path.isfile(reference):
        raise SystemExit(f"reference clip not found: {reference}")

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = args.run_dir or os.path.join(
        root, "build", "artifacts", "macos", "clone-fidelity", f"{args.label}-{stamp}"
    )
    os.makedirs(run_dir, exist_ok=True)

    plan = build_take_plan(args.voice, args.takes, args.controls, args.base_seed)
    if not args.skip_generation:
        if not os.path.isfile(vocello):
            raise SystemExit(f"vocello CLI not built: {vocello}")
        generate_all(plan, run_dir, vocello)

    clone_paths = [os.path.join(run_dir, item["name"]) for item in plan if item["kind"] == "clone"]
    control_paths = [os.path.join(run_dir, item["name"]) for item in plan if item["kind"] == "control"]
    for path in clone_paths + control_paths:
        if not os.path.isfile(path):
            raise SystemExit(f"expected take missing: {path}")

    from analyze_prosody import analyze as analyze_wav

    reference_metrics = analyze_wav(reference)
    fidelity = evaluate_takes(
        reference_metrics, [analyze_wav(path) for path in clone_paths]
    )
    report = {
        "laneVersion": LANE_VERSION,
        "label": args.label,
        "voice": args.voice,
        "referenceClip": os.path.basename(reference),
        "seedBase": args.base_seed,
        "prosodyFidelity": fidelity,
        "speakerSimilarity": ecapa_section(reference, clone_paths, control_paths),
        "emotionAdvisory": emotion_section(reference, clone_paths),
    }
    report_path = os.path.join(run_dir, "clone-fidelity-report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(json.dumps({
        "report": report_path,
        "prosody": fidelity["aggregate"],
        "similarity": report["speakerSimilarity"].get("clones", {}).get("aggregate")
        if isinstance(report["speakerSimilarity"], dict) else None,
        "emotionMatchRate": report["emotionAdvisory"].get("matchRate")
        if isinstance(report["emotionAdvisory"], dict) else None,
    }, indent=2))


if __name__ == "__main__":
    main()
