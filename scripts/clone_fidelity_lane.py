#!/usr/bin/env python3
"""Clone-fidelity lane: reference vs fixed-seed clone takes, plus controls.

Generates N fixed-seed clone takes of a saved voice with the CLI, then runs
the layered analyzers against the voice's reference clip:

  1. ``clone_prosody_fidelity``   — deterministic delivery/tone distances
                                    (warn-first bounds from the prosody profile)
  2. ``clone_speaker_similarity`` — ECAPA identity cosine (advisory bands);
                                    skipped with a note when torch is absent

Generates negative controls of the same text so the identity bands can be
calibrated from measured same-voice vs different-voice separations instead of
placeholders (audit #103 part 1; the maintainer delegated the decision to the
audit's recommendation on 2026-09-25): by default eight built-in-speaker takes
matched to the reference voice's gender (two controls, one cross-gender, were
too few and too easy to fit a band). Eight negatives is
`clone_speaker_similarity`'s calibration minimum.

Cross-clone negatives, clone takes of other saved voices, share every clone
artifact and differ only in identity, so they are the hard case. Cloning a voice
records the invocation's consent (`--confirm-consent`, PA-17), so the lane clones
only voices the operator names: each `--cross-clone-voice NAME` is the
operator's attestation that they own or may clone that voice. The lane never
lists the voices directory to find more, and generates no cross-clone take by
default.

ADVISORY dev lane: not a CI gate, not a packaging prerequisite, never
publishes benchmark history. Evidence-lane rule: no analyzer beside a resident
generator — takes are generated one process at a time, and the torch-backed
analyzers start only after the last generation process has exited; after
that the canonical host's measured budget governs.

Usage:
  python3 scripts/clone_fidelity_lane.py --voice A_warm_elderly_woman \
      [--takes 6] [--controls 8] [--reference-gender female|male] \
      [--cross-clone-voice NAME ...] [--cross-clones N] \
      [--base-seed 20260810] [--label ID]
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

# 2 (audit #103): gender-matched controls by default, and cross-clone negatives.
# 3 (2026-09-25 review): cross-clone negatives only for voices the operator names;
# none by default, and no discovery of the other saved voices.
# 4 (2026-09-25, audit decision 1a): the speech-emotion column is gone with its
# retired judge (trained on non-commercial corpora).
LANE_VERSION = 4
FIXED_TEXT = (
    "The harbor lights flickered as the evening ferry pulled away, and she "
    "wondered how many more crossings the old captain had left in him."
)
DEFAULT_MATCHED_CONTROLS = 8
# Cross-clone takes without a named voice: none. Each clone take attests consent.
DEFAULT_CROSS_CLONES = 0
SPEAKER_CONTRACT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Sources", "Resources", "qwenvoice_contract.json",
)


def builtin_speaker_genders(contract_path=SPEAKER_CONTRACT):
    """Built-in speakers in contract order, each with the gender its description names."""
    with open(contract_path, "r", encoding="utf-8") as handle:
        contract = json.load(handle)
    metadata = contract.get("speakerMetadata") or {}
    speakers = [speaker for group in (contract.get("speakers") or {}).values() for speaker in group]
    genders = {}
    for speaker in speakers:
        description = str((metadata.get(speaker) or {}).get("shortDescription", "")).lower()
        genders[speaker] = (
            "female" if "female" in description else "male" if "male" in description else None
        )
    return genders


def infer_reference_gender(voice):
    """The gender a saved voice's name states, or None (then pass --reference-gender)."""
    words = set(str(voice).lower().replace("-", "_").split("_"))
    if words & {"woman", "female", "girl", "lady"}:
        return "female"
    if words & {"man", "male", "boy", "gentleman"}:
        return "male"
    return None


def matched_control_speakers(gender, genders=None):
    """Built-in speakers of the reference voice's gender; every speaker when unknown."""
    genders = genders if genders is not None else builtin_speaker_genders()
    if gender is None:
        return tuple(genders)
    matched = tuple(speaker for speaker, speaker_gender in genders.items() if speaker_gender == gender)
    if not matched:
        raise ValueError(f"no built-in speaker matches gender {gender!r}")
    return matched


def resolve_cross_clones(voice, named_voices, count=None):
    """The operator-named cross-clone voices and how many takes to clone from them.

    Each named voice is one the operator attests consent for, since every clone
    take passes `--confirm-consent`. Nothing is inferred: no name, no cross-clone
    take. `count` defaults to one take per named voice; a count without a named
    voice, a count of zero beside named voices, the reference voice itself and a
    repeated name are refused.
    """
    named = [str(name).strip() for name in (named_voices or ())]
    if any(not name for name in named):
        raise ValueError("--cross-clone-voice needs a saved voice name")
    if len(set(named)) != len(named):
        raise ValueError("each --cross-clone-voice may be named once")
    if voice in named:
        raise ValueError(f"{voice!r} is the reference voice, not a cross-clone negative")
    if count is None:
        count = len(named) if named else DEFAULT_CROSS_CLONES
    if count < 0:
        raise ValueError("--cross-clones cannot be negative")
    if count and not named:
        raise ValueError(
            "cross-clone negatives clone other saved voices, which records consent for each: "
            "name every voice you own or may clone with --cross-clone-voice NAME"
        )
    if named and not count:
        raise ValueError("--cross-clones 0 contradicts a named --cross-clone-voice")
    return named, count


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def default_data_dir():
    return os.path.expanduser("~/Library/Application Support/QwenVoice-Debug")


def reference_path(data_dir, voice):
    return os.path.join(data_dir, "voices", f"{voice}.wav")


def build_take_plan(voice, take_count, control_count, base_seed, *,
                    control_speakers=None, reference_gender=None,
                    cross_clone_voices=(), cross_clone_count=0):
    """Deterministic plan: clone takes, matched controls, then cross-clone negatives.

    Controls cycle through the built-in speakers of the reference's gender
    (inferred from the voice name unless given); cross-clone negatives cycle
    through the voices the operator named (`resolve_cross_clones`). Seeds
    advance per take within each kind.
    """
    if control_speakers is None:
        gender = reference_gender or infer_reference_gender(voice)
        control_speakers = matched_control_speakers(gender)
        matched = gender is not None
    else:
        matched = reference_gender is not None
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
        speaker = control_speakers[index % len(control_speakers)]
        plan.append({
            "kind": "control",
            "mode": "custom",
            "speaker": speaker,
            "matchedGender": matched,
            "seed": base_seed + index,
            "name": f"control_{speaker}_{index:02d}.wav",
        })
    others = [other for other in cross_clone_voices if other != voice]
    for index in range(cross_clone_count if others else 0):
        other = others[index % len(others)]
        plan.append({
            "kind": "cross-clone",
            "mode": "clone",
            "voice": other,
            "seed": base_seed + index,
            "name": f"cross_clone_{index:02d}.wav",
        })
    return plan


def generation_command(vocello, item, out_dir):
    command = [
        vocello, "generate", "--mode", item["mode"], "--variant", "speed",
        "--text", FIXED_TEXT, "--seed", str(item["seed"]),
        "--variation", "consistent",
        "--out", os.path.join(out_dir, item["name"]),
    ]
    if item["mode"] == "clone":
        # PA-17: clone generation needs the invocation's recorded consent.
        command += ["--voice", item["voice"], "--confirm-consent"]
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


def ecapa_section(reference, clone_paths, control_paths, cross_clone_paths=()):
    """Identity similarity with measured positive/negative separation.

    Negatives are the matched controls plus the cross-clone takes; each kind
    also reports its own separation, since cross-clone negatives are the hard
    case (same clone artifacts, different identity)."""
    try:
        from clone_speaker_similarity import analyze_takes, ecapa_embedder, load_similarity_profile
    except Exception as error:  # pragma: no cover - import shape guard
        return {"skipped": f"clone_speaker_similarity unavailable: {error}"}
    try:
        embed = ecapa_embedder()
    except Exception as error:
        return {"skipped": f"torch/speechbrain not installed: {error}"}
    from clone_speaker_similarity import separation

    profile = load_similarity_profile(None)
    section = {"clones": analyze_takes(reference, clone_paths, embed, profile)}
    positives = [row["cosineSimilarity"] for row in section["clones"]["takes"]]
    negatives = []
    if control_paths:
        section["controls"] = analyze_takes(reference, control_paths, embed, profile)
        control_scores = [row["cosineSimilarity"] for row in section["controls"]["takes"]]
        section["controlSeparation"] = separation(positives, control_scores)
        negatives.extend(control_scores)
    if cross_clone_paths:
        section["crossClones"] = analyze_takes(reference, list(cross_clone_paths), embed, profile)
        cross_scores = [row["cosineSimilarity"] for row in section["crossClones"]["takes"]]
        section["crossCloneSeparation"] = separation(positives, cross_scores)
        negatives.extend(cross_scores)
    if negatives:
        # AUC and EER with intervals over every negative, so the bands are
        # fitted from a measured separation instead of read off two controls.
        section["separation"] = separation(positives, negatives)
    return section


def main():
    parser = argparse.ArgumentParser(description="Clone fidelity lane (advisory).")
    parser.add_argument("--voice", default="A_warm_elderly_woman")
    parser.add_argument("--takes", type=int, default=6)
    parser.add_argument("--controls", type=int, default=DEFAULT_MATCHED_CONTROLS,
                        help="gender-matched built-in-speaker controls (default 8)")
    parser.add_argument("--cross-clone-voice", action="append", default=[], metavar="NAME",
                        help="another saved voice to clone as a hard negative; repeat per voice. "
                             "Naming a voice confirms you own or may clone it: the lane passes "
                             "--confirm-consent for it. Voices are never discovered.")
    parser.add_argument("--cross-clones", type=int, default=None,
                        help="cross-clone takes, cycling over the named voices "
                             "(default one per named voice; none without a name)")
    parser.add_argument("--reference-gender", choices=("female", "male"),
                        help="the reference voice's gender when its name does not state it")
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

    reference_gender = args.reference_gender or infer_reference_gender(args.voice)
    if reference_gender is None and args.controls:
        raise SystemExit(
            f"the gender of {args.voice!r} is not in its name; pass --reference-gender so the "
            "controls are matched (audit #103)"
        )
    try:
        cross_clone_voices, cross_clone_count = resolve_cross_clones(
            args.voice, args.cross_clone_voice, args.cross_clones,
        )
    except ValueError as error:
        raise SystemExit(str(error)) from None
    plan = build_take_plan(
        args.voice, args.takes, args.controls, args.base_seed,
        reference_gender=reference_gender,
        cross_clone_voices=cross_clone_voices, cross_clone_count=cross_clone_count,
    )
    if not args.skip_generation:
        if not os.path.isfile(vocello):
            raise SystemExit(f"vocello CLI not built: {vocello}")
        for name in cross_clone_voices:
            if not os.path.isfile(reference_path(args.data_dir, name)):
                raise SystemExit(f"named cross-clone voice has no saved reference: {name}")
        generate_all(plan, run_dir, vocello)

    clone_paths = [os.path.join(run_dir, item["name"]) for item in plan if item["kind"] == "clone"]
    control_paths = [os.path.join(run_dir, item["name"]) for item in plan if item["kind"] == "control"]
    cross_clone_paths = [
        os.path.join(run_dir, item["name"]) for item in plan if item["kind"] == "cross-clone"
    ]
    for path in clone_paths + control_paths + cross_clone_paths:
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
        "referenceGender": reference_gender,
        "controlPlan": {
            "matchedControls": len(control_paths),
            "crossCloneNegatives": len(cross_clone_paths),
            # Operator-named only: each one attested consent for its clone takes.
            "crossCloneVoicesNamed": len(cross_clone_voices),
        },
        "speakerSimilarity": ecapa_section(reference, clone_paths, control_paths, cross_clone_paths),
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
    }, indent=2))


if __name__ == "__main__":
    main()
