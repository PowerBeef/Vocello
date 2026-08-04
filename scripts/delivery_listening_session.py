#!/usr/bin/env python3
"""Build, run, and score the blind delivery listening session.

The 2026-08-04 delivery-control audit found that the two instruments built to
answer the product question — free identification ("what emotion do you
hear?") and the 2AFC attractor test in
``scripts/delivery_identification_check.py`` — were never run on real audio,
while every roster decision consumed the acoustic classifier's verdicts in
exactly the region the one human datapoint contradicts. This tool closes that
gap with one ~30-minute session:

* ``build`` assembles a blind session from ``vocello bench`` evidence archives
  (``outputs/bench-archive/<runID>``) plus optional clone-transfer clips:
  clips are copied under opaque trial IDs, the trial order is deterministically
  shuffled, and the answer keys are written separately so the listener never
  sees a cell name.
* ``run`` plays each trial with ``afplay`` and records answers incrementally
  (resumable; replay allowed; "Unsure" is a first-class answer).
* ``score`` feeds the recorded answers through the existing
  ``delivery_identification_check`` instruments and evaluates the session's
  pre-registered decision rules (exact binomial, computed for the trial counts
  that actually survived generation — never hand-stated).

Listening remains calibration, never a gate: nothing consumes these verdicts
automatically, and the session exists so the acoustic instruments can be
checked against perception instead of against each other.

Usage:
  scripts/delivery_listening_session.py build --out SESSION_DIR \
      [--archive-root DIR] [--clone-dir DIR] [--session-seed N]
  scripts/delivery_listening_session.py run --session SESSION_DIR
  scripts/delivery_listening_session.py score --session SESSION_DIR
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from delivery_identification_check import (
    UNSURE,
    _difference_interval,
    _wilson,
    evaluate_discrimination,
    evaluate_identification,
)

SESSION_VERSION = 1
DEFAULT_SESSION_SEED = 20260804
DEFAULT_ARCHIVE_ROOT = (
    Path.home() / "Library" / "Application Support" / "QwenVoice-Debug"
    / "outputs" / "bench-archive"
)

IDENTIFY_PRESETS = [
    "neutral", "happy", "sad", "angry", "fearful", "surprised", "calm", "whisper",
]
REPEAT_COUNT = 6

# 2AFC design: the angry-attractor test plus the pair the acoustic study
# flagged as marginal (happy vs surprised), with anchors as the engagement
# gate. Each entry: (group, target preset, other preset, tier, trials).
DISCRIMINATION_DESIGN = [
    ("angry", "angry", "happy", "strong", 4),
    ("angry", "angry", "happy", "normal", 4),
    ("angry", "angry", "surprised", "strong", 4),
    ("angry", "angry", "surprised", "normal", 4),
    ("angry", "angry", "fearful", "strong", 4),
    ("angry", "angry", "fearful", "normal", 4),
    ("control", "happy", "surprised", "strong", 4),
    ("control", "happy", "surprised", "normal", 4),
    ("control", "sad", "calm", "strong", 2),
    ("control", "sad", "calm", "normal", 2),
    ("anchor", "whisper", "angry", "strong", 4),
]


def _load_archives(archive_root: Path, label_prefix: str) -> dict[str, dict]:
    """Newest archive per label whose label starts with the prefix.

    Returns label → {"seed": int|None, "takes": {(preset, tier): wav path}}.
    """
    by_label: dict[str, tuple[str, dict]] = {}
    if not archive_root.is_dir():
        return {}
    for run_dir in sorted(archive_root.iterdir()):
        manifest_path = run_dir / "bench-results.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        label = manifest.get("label") or ""
        if not label.startswith(label_prefix):
            continue
        started = str(manifest.get("startedAt") or "")
        previous = by_label.get(label)
        if previous is not None and previous[0] >= started:
            continue
        takes: dict[tuple[str, str], Path] = {}
        for take in manifest.get("takes") or []:
            delivery = take.get("delivery")
            name = take.get("outputFileName")
            if not delivery or not isinstance(name, str):
                continue
            preset, _, tier = str(delivery).partition(".")
            wav = run_dir / name
            if wav.is_file():
                takes[(preset, tier)] = wav
        if takes:
            by_label[label] = (started, {"seed": manifest.get("seed"), "takes": takes})
    return {label: entry for label, (_, entry) in by_label.items()}


def _clip_index(archives: dict[str, dict]) -> dict[tuple[str, str], list[tuple[object, Path]]]:
    """(preset, tier) → [(seed, wav)] across archives, stable order."""
    index: dict[tuple[str, str], list[tuple[object, Path]]] = {}
    for label in sorted(archives):
        entry = archives[label]
        for (preset, tier), wav in sorted(entry["takes"].items()):
            index.setdefault((preset, tier), []).append((entry["seed"], wav))
    return index


def build_session(
    out_dir: Path,
    archive_root: Path,
    clone_dir: Path | None,
    session_seed: int = DEFAULT_SESSION_SEED,
    strong_prefix: str = "calib-a-",
    normal_prefix: str = "calib-n-",
) -> dict:
    rng = random.Random(session_seed)
    strong = _clip_index(_load_archives(archive_root, strong_prefix))
    normal = _clip_index(_load_archives(archive_root, normal_prefix))
    if not strong:
        raise ValueError(f"no strong-tier archives under {archive_root} with prefix {strong_prefix!r}")

    clips_dir = out_dir / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)
    options = [preset.capitalize() for preset in IDENTIFY_PRESETS] + [UNSURE]

    trial_counter = 0

    def next_id() -> str:
        nonlocal trial_counter
        trial_counter += 1
        return f"t{trial_counter:03d}"

    def stage(trial_id: str, wav: Path, suffix: str = "") -> str:
        target = clips_dir / f"{trial_id}{suffix}.wav"
        shutil.copy2(wav, target)
        return f"clips/{target.name}"

    # ---- Block A: free identification over the strong-tier roster ----
    identification_key: list[dict] = []
    identify_trials: list[dict] = []
    for preset in IDENTIFY_PRESETS:
        for _, wav in strong.get((preset, "strong"), []):
            trial_id = next_id()
            identification_key.append({"id": trial_id, "cell": f"{preset}.strong"})
            identify_trials.append({
                "id": trial_id,
                "phase": "identify",
                "audio": [stage(trial_id, wav)],
                "question": "Which delivery do you hear?",
                "options": options,
            })

    # Exact repeats bound listener self-consistency (the ceiling for any
    # automated judge's agreement with this listener).
    repeat_pool = rng.sample(identify_trials, min(REPEAT_COUNT, len(identify_trials)))
    for original in repeat_pool:
        trial_id = next_id()
        identification_key.append({
            "id": trial_id,
            "cell": next(e["cell"] for e in identification_key if e["id"] == original["id"]),
            "kind": "repeat",
            "repeatOf": original["id"],
        })
        identify_trials.append({
            "id": trial_id,
            "phase": "identify",
            "audio": list(original["audio"]),
            "question": "Which delivery do you hear?",
            "options": options,
        })

    # ---- Clone-transfer rows: same task, separate key ----
    clone_key: list[dict] = []
    if clone_dir is not None and clone_dir.is_dir():
        for wav in sorted(clone_dir.glob("*.wav")):
            preset = wav.stem.split("_")[0]
            if preset not in IDENTIFY_PRESETS:
                continue
            trial_id = next_id()
            clone_key.append({"id": trial_id, "cell": f"{preset}.clone"})
            identify_trials.append({
                "id": trial_id,
                "phase": "identify",
                "audio": [stage(trial_id, wav)],
                "question": "Which delivery do you hear?",
                "options": options,
            })

    rng.shuffle(identify_trials)

    # ---- Block B: 2AFC discrimination ----
    discrimination_key: list[dict] = []
    discrimination_trials: list[dict] = []
    skipped: list[str] = []
    for group, target, other, tier, count in DISCRIMINATION_DESIGN:
        source = strong if tier == "strong" else normal
        target_clips = source.get((target, tier), [])
        other_clips = source.get((other, tier), [])
        available = min(len(target_clips), len(other_clips))
        if available == 0:
            skipped.append(f"{group}:{target}-vs-{other}@{tier}")
            continue
        for trial_index in range(count):
            pick = trial_index % available
            target_wav = target_clips[pick][1]
            other_wav = other_clips[(pick + 1) % len(other_clips)][1]
            trial_id = next_id()
            target_is_a = rng.random() < 0.5
            side_a, side_b = (target, other) if target_is_a else (other, target)
            wav_a, wav_b = (target_wav, other_wav) if target_is_a else (other_wav, target_wav)
            discrimination_key.append({
                "id": trial_id,
                "group": group,
                "tier": tier,
                "sideA": side_a,
                "sideB": side_b,
                "correctSide": "A" if target_is_a else "B",
                "target": target,
            })
            discrimination_trials.append({
                "id": trial_id,
                "phase": "discriminate",
                "audio": [stage(trial_id, wav_a, "_A"), stage(trial_id, wav_b, "_B")],
                "question": f"Which clip is {target.capitalize()}?",
                "options": ["A", "B"],
            })
    rng.shuffle(discrimination_trials)

    manifest = {
        "sessionVersion": SESSION_VERSION,
        "sessionSeed": session_seed,
        "trials": identify_trials + discrimination_trials,
        "skippedDesignRows": skipped,
    }
    (out_dir / "session-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "key-identification.json").write_text(
        json.dumps(identification_key, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "key-clone.json").write_text(
        json.dumps(clone_key, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "key-2afc.json").write_text(
        json.dumps(discrimination_key, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out_dir / "README.txt").write_text(
        "Blind delivery listening session.\n"
        "Run: python3 scripts/delivery_listening_session.py run --session "
        f"{out_dir}\n"
        "Do not open the key-*.json files before answering; the session is\n"
        "blind only if the keys stay sealed until scoring.\n",
        encoding="utf-8",
    )
    return {
        "identifyTrials": len(identify_trials),
        "cloneTrials": len(clone_key),
        "discriminationTrials": len(discrimination_trials),
        "skippedDesignRows": skipped,
    }


def _key_membership(session_dir: Path) -> dict[str, str]:
    """trial id → answers file stem, derived from the keys at score/run time."""
    membership: dict[str, str] = {}
    for stem in ("identification", "clone", "2afc"):
        key_path = session_dir / f"key-{stem}.json"
        if not key_path.is_file():
            continue
        for entry in json.loads(key_path.read_text(encoding="utf-8")):
            membership[entry["id"]] = stem
    return membership


def _answers_path(session_dir: Path, stem: str) -> Path:
    return session_dir / f"answers-{stem}.json"


def _load_answers(session_dir: Path, stem: str) -> dict[str, str]:
    path = _answers_path(session_dir, stem)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def run_session(session_dir: Path, player: str = "/usr/bin/afplay") -> None:
    manifest = json.loads((session_dir / "session-manifest.json").read_text(encoding="utf-8"))
    membership = _key_membership(session_dir)
    answers = {stem: _load_answers(session_dir, stem) for stem in ("identification", "clone", "2afc")}

    def save(stem: str) -> None:
        _answers_path(session_dir, stem).write_text(
            json.dumps(answers[stem], indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    trials = manifest["trials"]
    pending = [
        trial for trial in trials
        if trial["id"] not in answers[membership[trial["id"]]]
    ]
    print(f"{len(trials)} trials, {len(trials) - len(pending)} already answered.")
    print("Keys: number = answer, r = replay, q = save and quit.\n")

    for position, trial in enumerate(pending, start=1):
        stem = membership[trial["id"]]
        print(f"— trial {position}/{len(pending)} —")
        while True:
            for index, clip in enumerate(trial["audio"]):
                if len(trial["audio"]) > 1:
                    print(f"  clip {'AB'[index]} …")
                subprocess.run([player, str(session_dir / clip)], check=False)
            for index, option in enumerate(trial["options"], start=1):
                print(f"  {index}. {option}")
            choice = input(f"{trial['question']} > ").strip().lower()
            if choice == "r":
                continue
            if choice == "q":
                return
            if choice.isdigit() and 1 <= int(choice) <= len(trial["options"]):
                answers[stem][trial["id"]] = trial["options"][int(choice) - 1]
                save(stem)
                break
            print("  (enter an option number, r to replay, q to quit)")
    print("\nSession complete. Score with:")
    print(f"  python3 scripts/delivery_listening_session.py score --session {session_dir}")


def _binomial_sf(successes: int, trials: int, probability: float) -> float:
    """P(X >= successes) for X ~ Binomial(trials, probability), exact."""
    total = 0.0
    for count in range(successes, trials + 1):
        total += (
            math.comb(trials, count)
            * probability ** count
            * (1.0 - probability) ** (trials - count)
        )
    return min(1.0, total)


def score_session(session_dir: Path) -> dict:
    reports: dict[str, object] = {}
    identification_key = json.loads((session_dir / "key-identification.json").read_text(encoding="utf-8"))
    identification_answers = _load_answers(session_dir, "identification")
    identification = evaluate_identification(identification_key, identification_answers)
    reports["identification"] = identification

    clone_key_path = session_dir / "key-clone.json"
    clone = None
    if clone_key_path.is_file():
        clone_key = json.loads(clone_key_path.read_text(encoding="utf-8"))
        if clone_key:
            clone = evaluate_identification(clone_key, _load_answers(session_dir, "clone"))
            reports["clone"] = clone

    discrimination = None
    discrimination_key_path = session_dir / "key-2afc.json"
    if discrimination_key_path.is_file():
        discrimination_key = json.loads(discrimination_key_path.read_text(encoding="utf-8"))
        if discrimination_key:
            discrimination = evaluate_discrimination(
                discrimination_key, _load_answers(session_dir, "2afc")
            )
            reports["discrimination"] = discrimination

    # ---- Pre-registered decision rules, computed for the surviving counts ----
    decisions: dict[str, object] = {}
    trials = identification["trials"]
    chance = 1.0 / len(IDENTIFY_PRESETS)
    correct = round(identification["overallAccuracy"]["rate"] * trials) if trials else 0
    pooled_p = _binomial_sf(correct, trials, chance) if trials else 1.0
    decisions["identificationPooled"] = {
        "correct": correct,
        "trials": trials,
        "chance": round(chance, 4),
        "exactBinomialP": round(pooled_p, 5),
        "aboveChance": pooled_p < 0.05,
        "humanActorAnchor": "voice-only 6-way ID of acted emotion is ~0.41 (CREMA-D)",
    }
    per_preset = {}
    for preset, entry in identification["perPreset"].items():
        n = entry["n"]
        hits = round(entry["recall"] * n) if n else 0
        p_value = _binomial_sf(hits, n, chance) if n else 1.0
        per_preset[preset] = {
            "hits": hits, "n": n,
            "exactBinomialP": round(p_value, 5),
            "aboveChance": p_value < 0.05,
        }
    decisions["identificationPerPreset"] = per_preset

    if clone is not None and clone["trials"]:
        clone_trials = clone["trials"]
        clone_correct = round(clone["overallAccuracy"]["rate"] * clone_trials)
        decisions["cloneVersusInstruct"] = {
            "cloneRecall": _wilson(clone_correct, clone_trials),
            "instructRecall": _wilson(correct, trials) if trials else None,
            "cloneMinusInstruct": _difference_interval(
                clone_correct, clone_trials, correct, trials
            ) if trials else None,
        }

    if discrimination is not None:
        decisions["discriminationVerdict"] = discrimination["verdict"]
        decisions["sessionEngaged"] = discrimination["sessionEngaged"]

    reports["decisions"] = decisions
    (session_dir / "session-report.json").write_text(
        json.dumps(reports, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return reports


def _print_score(reports: dict) -> None:
    decisions = reports["decisions"]
    pooled = decisions["identificationPooled"]
    print("== identification (instruct presets) ==")
    print(
        f"  pooled {pooled['correct']}/{pooled['trials']} correct, chance {pooled['chance']}, "
        f"exact binomial p = {pooled['exactBinomialP']}"
        f" → {'ABOVE chance' if pooled['aboveChance'] else 'not distinguishable from chance'}"
    )
    print(f"  calibration anchor: {pooled['humanActorAnchor']}")
    identification = reports["identification"]
    for preset in sorted(identification["perPreset"], key=lambda p: -identification["perPreset"][p]["recall"]):
        entry = identification["perPreset"][preset]
        rule = decisions["identificationPerPreset"][preset]
        heard = entry["mostCommonLabel"]
        note = "" if heard == preset.capitalize() else f"  most often heard as {heard}"
        print(
            f"    {preset:10} recall {entry['recall']:.2f} (n={entry['n']}, p={rule['exactBinomialP']})"
            f"{'  *above chance*' if rule['aboveChance'] else ''}{note}"
        )
    agreement = identification.get("selfAgreement")
    if agreement:
        print(f"  self-agreement on {agreement['n']} repeats: {agreement['agreement']}")
    if "cloneVersusInstruct" in decisions:
        comparison = decisions["cloneVersusInstruct"]
        difference = comparison.get("cloneMinusInstruct")
        print("== clone-transfer rows ==")
        print(
            f"  clone recall {comparison['cloneRecall']['rate']} vs instruct "
            f"{comparison['instructRecall']['rate']}"
            + (
                f"; difference {difference['difference']} "
                f"[{difference['lower']}, {difference['upper']}]"
                + ("  (excludes zero)" if difference["excludesZero"] else "")
                if difference else ""
            )
        )
    if "discriminationVerdict" in decisions:
        print("== 2AFC ==")
        print(f"  verdict: {decisions['discriminationVerdict']}"
              f"  (session engaged: {decisions['sessionEngaged']})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build", help="assemble a blind session from bench archives")
    build.add_argument("--out", required=True, type=Path)
    build.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    build.add_argument("--clone-dir", type=Path, default=None)
    build.add_argument("--session-seed", type=int, default=DEFAULT_SESSION_SEED)
    build.add_argument("--strong-prefix", default="calib-a-")
    build.add_argument("--normal-prefix", default="calib-n-")

    run = commands.add_parser("run", help="play the session and record answers")
    run.add_argument("--session", required=True, type=Path)

    score = commands.add_parser("score", help="score recorded answers")
    score.add_argument("--session", required=True, type=Path)

    arguments = parser.parse_args()
    if arguments.command == "build":
        summary = build_session(
            arguments.out,
            arguments.archive_root,
            arguments.clone_dir,
            session_seed=arguments.session_seed,
            strong_prefix=arguments.strong_prefix,
            normal_prefix=arguments.normal_prefix,
        )
        print(json.dumps(summary, indent=2, sort_keys=True))
        estimated = summary["identifyTrials"] * 9 + summary["discriminationTrials"] * 20
        print(f"estimated session length: ~{estimated // 60} minutes")
        return 0
    if arguments.command == "run":
        run_session(arguments.session)
        return 0
    reports = score_session(arguments.session)
    _print_score(reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
