#!/usr/bin/env python3
"""Clone-fidelity lane: reference vs fixed-seed clone takes, plus controls.

Generates N fixed-seed clone takes of a saved voice with the CLI, then scores
every take against the voice's reference clip with QC v2 (`docs/reference/qc.md`),
lane ``clone-lane`` of ``config/qc/detectors.json`` (roles speaker, pitchA and
pitchB):

  1. ``qc.lanes.run``       — ReDimNet2+ speaker embeddings and the FCPE and
                              SwiftF0 pitch tracks of every take and of the
                              reference clip, then the QC v2 detectors. The
                              clone takes gate; the matched controls and
                              cross-clone negatives are scored against the same
                              clip as negative controls and never gate.
  2. ``qc.fidelity``        — per take: the register shift from the reference
                              (signed semitones, on the frames both trackers
                              agree on), the largest sustained shift, octave
                              jumps, and the identity similarity of the whole
                              take and of its least similar 4 s window.
  3. ``qc.lanes.gate``      — the lane's gate over the clone takes: exit 0 pass,
                              3 warn (reported), 1 fail, 2 not computed. Until an
                              evaluated thresholds file gives a detector a level,
                              every flag is report-only and the gate passes.

Generates negative controls of the same text so the identity separation is
measured from same-voice vs different-voice scores instead of assumed (audit
#103 part 1; the maintainer delegated the decision to the audit's
recommendation on 2026-09-25): by default eight built-in-speaker takes matched
to the reference voice's gender (two controls, one cross-gender, were too few
and too easy). Eight negatives is the separation's calibration minimum.

Cross-clone negatives, clone takes of other saved voices, share every clone
artifact and differ only in identity, so they are the hard case. Cloning a voice
records the invocation's consent (`--confirm-consent`, PA-17), so the lane clones
only voices the operator names: each `--cross-clone-voice NAME` is the
operator's attestation that they own or may clone that voice. The lane never
lists the voices directory to find more, and generates no cross-clone take by
default.

ADVISORY dev lane: not a CI gate, not a packaging prerequisite, never
publishes benchmark history. Evidence-lane rule: no analyzer beside a resident
generator — takes are generated one process at a time, and the QC v2 models
start only after the last generation process has exited, one at a time, each
in its own runner process.

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
import math
import os
import random
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2 (audit #103): gender-matched controls by default, and cross-clone negatives.
# 3 (2026-09-25 review): cross-clone negatives only for voices the operator names;
# none by default, and no discovery of the other saved voices.
# 4 (2026-09-25, audit decision 1a): the speech-emotion column is gone with its
# retired judge (trained on non-commercial corpora).
# 5 (2026-10-01, QC v2): ReDimNet2+ identity and FCPE/SwiftF0 pitch against the
# reference clip, and the QC v2 lane gate, replace the ECAPA similarity, the
# pYIN prosody distances and the v1 lane gates (CAM++ similarity, onset drift).
LANE_VERSION = 5
FIXED_TEXT = (
    "The harbor lights flickered as the evening ferry pulled away, and she "
    "wondered how many more crossings the old captain had left in him."
)
FIXED_TEXT_LANGUAGE = "english"
GATED_LANE = "clone-lane"
QC_TAKES_FILE = "qc-takes.json"
GATE_VERDICTS = {0: "pass", 3: "warn", 1: "fail", 2: "error"}
# Separation of same-voice from different-voice similarity (audit #103): enough
# negatives to estimate it, and a reproducible bootstrap for its intervals.
MINIMUM_CALIBRATION_NEGATIVES = 8
SEPARATION_BOOTSTRAP_RESAMPLES = 2_000
SEPARATION_BOOTSTRAP_SEED = 20_260_925
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


def area_under_curve(positives, negatives):
    """P(a same-voice score beats a different-voice score); ties count half."""
    wins = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive in positives for negative in negatives
    )
    return wins / (len(positives) * len(negatives))


def equal_error_rate(positives, negatives):
    """(EER, threshold): accept a score at or above the threshold; the threshold
    where the false-accept and false-reject rates meet (their mean at the
    closest observed crossing)."""
    best = None
    for threshold in sorted(set(positives) | set(negatives)) + [math.inf]:
        false_accept = sum(value >= threshold for value in negatives) / len(negatives)
        false_reject = sum(value < threshold for value in positives) / len(positives)
        candidate = (abs(false_accept - false_reject), (false_accept + false_reject) / 2.0, threshold)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    return best[1], best[2]


def _percentile_interval(values):
    ordered = sorted(values)
    low = ordered[int(0.025 * (len(ordered) - 1))]
    high = ordered[int(math.ceil(0.975 * (len(ordered) - 1)))]
    return [round(low, 4), round(high, 4)]


def separation(positives, negatives, *, resamples=SEPARATION_BOOTSTRAP_RESAMPLES,
               seed=SEPARATION_BOOTSTRAP_SEED):
    """Same-voice versus different-voice separation with 95% intervals.

    Positives (clone takes) and negatives (controls) are resampled separately
    with a fixed seed, so an interval is reproducible. ``bandCalibrationReady``
    says only whether enough negatives exist to read a band off the scores.
    """
    if not positives or not negatives:
        return None
    generator = random.Random(seed)
    aucs, eers = [], []
    for _ in range(resamples):
        sample_positive = [generator.choice(positives) for _ in positives]
        sample_negative = [generator.choice(negatives) for _ in negatives]
        aucs.append(area_under_curve(sample_positive, sample_negative))
        eers.append(equal_error_rate(sample_positive, sample_negative)[0])
    eer, threshold = equal_error_rate(positives, negatives)
    return {
        "positives": len(positives),
        "negatives": len(negatives),
        "auc": round(area_under_curve(positives, negatives), 4),
        "aucInterval95": _percentile_interval(aucs),
        "equalErrorRate": round(eer, 4),
        "equalErrorRateThreshold": None if math.isinf(threshold) else round(threshold, 4),
        "equalErrorRateInterval95": _percentile_interval(eers),
        "bootstrap": {"method": "stratified-percentile", "resamples": resamples, "seed": seed},
        "minimumCalibrationNegatives": MINIMUM_CALIBRATION_NEGATIVES,
        "bandCalibrationReady": len(negatives) >= MINIMUM_CALIBRATION_NEGATIVES,
    }


def qc_takes(plan, run_dir, reference, label):
    """The lane's takes as a QC v2 takes manifest: every take against the voice's reference clip.

    The clone takes gate; the matched controls and cross-clone negatives are
    negative controls (``control``), scored against the same clip for the
    identity separation and never gated."""
    from qc import store

    takes = []
    reference_sha = store.audio_sha256(reference)
    for item in plan:
        take_id = os.path.splitext(item["name"])[0]
        audio = os.path.join(run_dir, item["name"])
        takes.append({
            "takeID": take_id,
            "token": store.take_token(label, take_id),
            "audio": audio,
            "audioSHA256": store.audio_sha256(audio),
            "language": FIXED_TEXT_LANGUAGE,
            "text": FIXED_TEXT,
            "mode": item["mode"],
            "voice": f"clone-{item['voice']}" if item["mode"] == "clone" else item["speaker"],
            "cell": "clone" if item["kind"] != "control" else "standard",
            "reference": reference,
            "referenceSHA256": reference_sha,
            "referenceText": None,
            "finishReason": None,
            "seed": item["seed"],
            "family": "clone-fidelity-fixed-text",
            "control": item["kind"] != "clone",
            "kind": item["kind"],
        })
    return {"schema": store.TAKES_SCHEMA, "source": label, "kind": "clone-fidelity", "takes": takes}


def score_takes(plan, run_dir, reference, label, *, layout=None, run=None, gate=None):
    """Score every take with QC v2 after the last generation, then gate the clone takes.

    Returns ``(run_id, verdict, exit_code)``: the gate's verdict (pass, warn,
    fail; ``error`` when it could not be computed) and its exit code.
    """
    from qc import lanes, runtime, store
    from qc.store import Layout

    layout = layout or Layout()
    manifest_path = os.path.join(run_dir, QC_TAKES_FILE)
    store.write_json_atomic(manifest_path, qc_takes(plan, run_dir, reference, label))
    try:
        directory = (run or lanes.run)(layout, manifest_path, GATED_LANE)
    except (runtime.LockBusy, ValueError, OSError) as error:
        print(f"qc · {GATED_LANE}: ERROR · not computed: {error}", file=sys.stderr)
        return None, "error", 2
    code = (gate or lanes.gate)(layout, GATED_LANE, directory.name)
    return directory.name, GATE_VERDICTS.get(code, "error"), code


def fidelity_report(plan, run_id, *, layout=None):
    """Per-kind fidelity sections and the identity separation, from the QC run's cached results."""
    from qc import fidelity
    from qc.store import Layout

    layout = layout or Layout()
    rows = fidelity.take_fidelity(layout, run_id)
    kinds = {os.path.splitext(item["name"])[0]: item["kind"] for item in plan}
    by_kind = {"clone": [], "control": [], "cross-clone": []}
    for row in rows:
        by_kind[kinds[row["takeID"]]].append(row)
    sections = {
        "clones": {"aggregate": fidelity.aggregate(by_kind["clone"]), "takes": by_kind["clone"]},
    }
    if by_kind["control"]:
        sections["controls"] = {"aggregate": fidelity.aggregate(by_kind["control"]), "takes": by_kind["control"]}
    if by_kind["cross-clone"]:
        sections["crossClones"] = {"aggregate": fidelity.aggregate(by_kind["cross-clone"]),
                                   "takes": by_kind["cross-clone"]}

    def scores(kind):
        return [row["identity"]["similarity"] for row in by_kind[kind]
                if row["identity"].get("similarity") is not None]

    positives = scores("clone")
    similarity = {"metric": "redimnet2-plus-cosine-to-reference"}
    negatives = []
    for kind, key in (("control", "controlSeparation"), ("cross-clone", "crossCloneSeparation")):
        if by_kind[kind]:
            similarity[key] = separation(positives, scores(kind))
            negatives.extend(scores(kind))
    if negatives:
        # AUC and EER with intervals over every negative, measured rather than
        # read off two controls.
        similarity["separation"] = separation(positives, negatives)
    return sections, similarity, fidelity.run_models(layout, run_id)


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

    for item in plan:
        path = os.path.join(run_dir, item["name"])
        if not os.path.isfile(path):
            raise SystemExit(f"expected take missing: {path}")

    # Evidence-lane rule: the QC v2 models start only after the last generation
    # process has exited.
    run_id, verdict, code = score_takes(plan, run_dir, reference, os.path.basename(os.path.normpath(run_dir)))
    report = {
        "laneVersion": LANE_VERSION,
        "label": args.label,
        "voice": args.voice,
        "referenceClip": os.path.basename(reference),
        "seedBase": args.base_seed,
        "referenceGender": reference_gender,
        "controlPlan": {
            "matchedControls": sum(1 for item in plan if item["kind"] == "control"),
            "crossCloneNegatives": sum(1 for item in plan if item["kind"] == "cross-clone"),
            # Operator-named only: each one attested consent for its clone takes.
            "crossCloneVoicesNamed": len(cross_clone_voices),
        },
        "qcGate": {"lane": GATED_LANE, "run": run_id, "verdict": verdict, "exitCode": code},
    }
    if run_id is not None:
        report["fidelity"], report["speakerSimilarity"], report["qcModels"] = fidelity_report(plan, run_id)
    report_path = os.path.join(run_dir, "clone-fidelity-report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    clones = (report.get("fidelity") or {}).get("clones", {}).get("aggregate", {})
    print(json.dumps({
        "report": report_path,
        "qcRun": run_id,
        "registerShiftSemitones": clones.get("registerShiftSemitones"),
        "similarity": clones.get("similarity"),
        "separation": (report.get("speakerSimilarity") or {}).get("separation"),
        "qcGate": verdict,
    }, indent=2))
    if verdict in ("fail", "error"):
        # A warn gate's flags report above; a fail gate or a gate that could not
        # be computed fails the lane.
        raise SystemExit(1 if verdict == "fail" else 2)


if __name__ == "__main__":
    main()
