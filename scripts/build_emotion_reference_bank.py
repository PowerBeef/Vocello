#!/usr/bin/env python3
"""Build a curated per-emotion reference bank for the design-then-clone path.

The 2026-08-04 calibration session settled which lever carries emotion: the
clone path's in-context reference transfer delivered the only anger the
listener ever heard (angry.clone 0.667 vs 0/11 for the instructed preset) —
and it also showed exactly where naive banks fail. Three of four single-shot
VoiceDesign references never audibly carried their emotion, so their clones
read as neutral. The lossy hop is instruct→reference, not reference→clone.
Curation is therefore the load-bearing step, exactly as the audit's prior-art
review predicted (`docs/reference/delivery-control-audit-2026-08.md`, F8/R3):
generate several candidates per emotion, keep only the ones that measurably
land, and verify the persona's identity stays coherent across the bank.

What `build` does, in two strictly ordered phases (no scorer runs beside a
resident generator; after the generator exits the canonical host's budget
governs):

1. **Generate** — a neutral anchor take plus N VoiceDesign candidates per
   emotion, same brief, same transcript, distinct fixed seeds, streaming
   (the app-matched chunk path; also immune to CM-7, fixed 2026-08-04, which
   made `--no-stream` publish nothing). Audio QC is fail-closed inside
   the engine, so every surviving candidate already passed it.
2. **Score and select** — per candidate: ECAPA identity cosine against the
   anchor (`scripts/clone_speaker_similarity.py` backend) and the paired,
   same-voice arousal and prosody deltas versus the neutral anchor
   (`scripts/analyze_prosody.py` features judged by the per-preset
   expectations of `scripts/delivery_quality_gate.py`). A candidate is
   eligible when its paired delivery adherence passes (whisper is judged by
   its voiced-fraction drop instead); among eligible candidates the winner is
   the one **most similar to the anchor** — the nearest-to-anchor selection
   that keeps the persona's identity coherent across emotions rather than
   chasing peak expressiveness. The speech-emotion classifier that used to
   decide eligibility was retired on 2026-09-25 (audit AQ-F03: trained on
   non-commercial corpora).

Winners (and the anchor) are enrolled as ordinary saved voices —
"<Persona>" and "<Persona> (Angry)" etc. — so every existing surface that
lists saved voices can use the bank today, with no engine changes: the clone
request machinery already accepts any reference plus transcript. A manifest
with every candidate's scores, the pinned scorer identities, and the
selection reasons is written beside the work files.

Advisory posture: ECAPA and the paired adherence verdict remain advisory
instruments (never CI, never benchmark history). The bank builder uses them to
*rank our own candidates against each other* — the relative use the audit's
judge review endorsed — and records everything so a selection can be
re-litigated.

Usage:
  .venv/bin/python3 scripts/build_emotion_reference_bank.py build \
      --persona "Warm Narrator" \
      --brief "A warm, calm middle-aged male narrator with a clear, measured pace." \
      [--emotions happy,sad,angry,whisper] [--candidates 4] [--base-seed 42000] \
      [--work-dir DIR] [--no-enroll]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 2 (2026-09-25): eligibility is the paired delivery adherence verdict, not
# the retired speech-emotion classifier's top-1 agreement.
BANK_VERSION = 2
DEFAULT_EMOTIONS = ["happy", "sad", "angry", "whisper"]
DEFAULT_CANDIDATES = 4
DEFAULT_BASE_SEED = 42_000
ANCHOR_SEED_RETRIES = 3

# A candidate must be at least this much less voiced than the anchor to count
# as whispered; whisper is judged by phonation, not by the adherence verdict.
WHISPER_VOICED_DELTA_MAX = -0.05
VOICED_FRACTION_PRESETS = frozenset({"whisper"})

# Same neutral-content passage the bench corpus uses for its long cell: known
# clean, semantically neutral (an emotional transcript would leak semantics
# into the in-context conditioning), and ~20 s of reference audio — inside the
# 10–30 s range reference-conditioned systems recommend.
DEFAULT_TRANSCRIPT = (
    "The morning train slipped quietly out of the station, carrying a handful of "
    "sleepy travelers toward the coast. Outside the fogged windows, pale fields "
    "gave way to grey water, and the rhythm of the rails settled into a steady, "
    "hypnotic hum. By the time the sun finally broke through, most of the "
    "passengers had drifted into an unhurried silence."
)


def sanitized_persona(name: str) -> str:
    cleaned = " ".join(str(name).split())
    if not cleaned or any(ch in cleaned for ch in "/\\:\0"):
        raise ValueError("persona name must be non-empty and filesystem-safe")
    return cleaned


def voice_name(persona: str, emotion: str | None) -> str:
    if emotion is None:
        return persona
    return f"{persona} ({emotion.capitalize()})"


def shipped_instruction(emotion: str, repo_root: pathlib.Path) -> str:
    """The preset's shipped strong-tier copy, parsed from the Swift table so
    the Swift source stays the single source of truth."""
    from check_delivery_instructions import load_presets

    presets = load_presets(repo_root)
    tiers = presets.get(emotion)
    if not tiers or "strong" not in tiers:
        raise ValueError(f"no shipped strong instruction for preset '{emotion}'")
    return tiers["strong"]


def plan_generation(
    work_dir: pathlib.Path,
    brief: str,
    transcript: str,
    emotions: list[str],
    instructions: dict[str, str],
    candidates: int,
    base_seed: int,
) -> list[dict[str, Any]]:
    """Pure generation plan. Streaming always: it matches the app's chunk
    path, and it was the route unaffected by CM-7 (fixed 2026-08-04), whose
    no-published-WAV shape would have silently emptied the bank."""
    plan: list[dict[str, Any]] = []
    for retry in range(ANCHOR_SEED_RETRIES):
        seed = base_seed + retry
        plan.append({
            "kind": "anchor",
            "attempt": retry,
            "seed": seed,
            "path": str(work_dir / f"anchor_s{seed}.wav"),
            "arguments": [
                "generate", "--mode", "design", "--variant", "speed",
                "--voice-brief", brief, "--text", transcript,
                "--seed", str(seed), "--out", str(work_dir / f"anchor_s{seed}.wav"),
            ],
        })
    for emotion_index, emotion in enumerate(emotions):
        for candidate_index in range(candidates):
            seed = base_seed + 100 * (emotion_index + 1) + candidate_index
            path = work_dir / f"{emotion}_s{seed}.wav"
            plan.append({
                "kind": "candidate",
                "emotion": emotion,
                "seed": seed,
                "path": str(path),
                "arguments": [
                    "generate", "--mode", "design", "--variant", "speed",
                    "--voice-brief", brief, "--delivery", instructions[emotion],
                    "--text", transcript, "--seed", str(seed), "--out", str(path),
                ],
            })
    return plan


def run_generation(
    plan: list[dict[str, Any]],
    runner: Callable[[list[str]], bool],
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    """Execute the plan. The anchor gets seed retries and is fatal if all
    fail; candidates are individually tolerated (audio QC aborts takes by
    design) and reported."""
    anchor_path: str | None = None
    for entry in (e for e in plan if e["kind"] == "anchor"):
        if anchor_path is not None:
            break
        if runner(entry["arguments"]) and pathlib.Path(entry["path"]).is_file():
            anchor_path = entry["path"]
    if anchor_path is None:
        raise RuntimeError("anchor generation failed on every retry seed")

    generated: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for entry in (e for e in plan if e["kind"] == "candidate"):
        if runner(entry["arguments"]) and pathlib.Path(entry["path"]).is_file():
            generated.append(entry)
        else:
            failed.append({"emotion": entry["emotion"], "seed": entry["seed"]})
    return anchor_path, generated, failed


def _adherence(metrics: dict[str, Any], anchor_metrics: dict[str, Any], emotion: str) -> dict[str, Any]:
    """The paired, same-voice delivery verdict of one candidate against the neutral anchor."""
    from delivery_quality_gate import evaluate_delivery

    verdict = evaluate_delivery(metrics, anchor_metrics, f"{emotion}.strong")
    return {
        "passed": verdict["passed"],
        "flags": verdict["flags"],
        "algorithmVersion": verdict["algorithmVersion"],
        "unavailableFeatures": verdict.get("unavailableFeatures", []),
        "arousalScore": verdict["metrics"].get("arousal_score"),
    }


def score_candidates(
    anchor_path: str,
    candidates: list[dict[str, Any]],
    embed: Callable[[str], list[float]],
    analyze: Callable[[str], dict[str, Any]],
) -> list[dict[str, Any]]:
    from clone_speaker_similarity import advisory_band, cosine_similarity, load_similarity_profile

    profile = load_similarity_profile(None)
    anchor_embedding = embed(anchor_path)
    anchor_metrics = analyze(anchor_path)
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        emotion = candidate["emotion"]
        path = candidate["path"]
        metrics = analyze(path)
        similarity = cosine_similarity(anchor_embedding, embed(path))
        # The analyzer flattens its F0 group with an `f0_` prefix; the bare
        # key is kept as a fallback for any older flat producer.
        voiced = metrics.get("f0_voiced_frac", metrics.get("voiced_frac"))
        anchor_voiced = anchor_metrics.get("f0_voiced_frac", anchor_metrics.get("voiced_frac"))
        scored.append({
            "emotion": emotion,
            "seed": candidate["seed"],
            "path": path,
            "deliveryAdherence": _adherence(metrics, anchor_metrics, emotion),
            "identityCosine": round(similarity, 4),
            "identityBand": advisory_band(similarity, profile),
            "voicedFrac": voiced,
            "voicedFracDelta": (
                round(voiced - anchor_voiced, 3)
                if isinstance(voiced, (int, float)) and isinstance(anchor_voiced, (int, float))
                else None
            ),
            "f0StdDelta": (
                round(metrics.get("f0_std_hz", 0.0) - anchor_metrics.get("f0_std_hz", 0.0), 2)
                if "f0_std_hz" in metrics and "f0_std_hz" in anchor_metrics
                else None
            ),
        })
    return scored


def select_winners(
    scored: list[dict[str, Any]], emotions: list[str]
) -> dict[str, dict[str, Any]]:
    """Pure selection: emotion criterion first, then nearest-to-anchor
    identity. Never peak expressiveness — overshoot is the documented
    reference-bank failure mode."""
    selection: dict[str, dict[str, Any]] = {}
    for emotion in emotions:
        rows = [row for row in scored if row["emotion"] == emotion]
        if emotion in VOICED_FRACTION_PRESETS:
            eligible = [
                row for row in rows
                if isinstance(row["voicedFracDelta"], (int, float))
                and row["voicedFracDelta"] <= WHISPER_VOICED_DELTA_MAX
            ]
            criterion = f"voicedFracDelta <= {WHISPER_VOICED_DELTA_MAX}"
        else:
            eligible = [row for row in rows if row["deliveryAdherence"].get("passed") is True]
            criterion = "paired delivery adherence against the neutral anchor"
        if not eligible:
            selection[emotion] = {
                "winner": None,
                "criterion": criterion,
                "reason": "no_eligible_candidate",
                "candidateCount": len(rows),
            }
            continue
        winner = max(eligible, key=lambda row: (row["identityCosine"], -row["seed"]))
        selection[emotion] = {
            "winner": winner,
            "criterion": criterion,
            "eligibleCount": len(eligible),
            "candidateCount": len(rows),
        }
    return selection


def enrollment_plan(
    persona: str,
    anchor_path: str,
    transcript: str,
    selection: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    plan = [{
        "name": voice_name(persona, None),
        "audio": anchor_path,
        "transcript": transcript,
    }]
    for emotion in sorted(selection):
        winner = selection[emotion].get("winner")
        if winner is not None:
            plan.append({
                "name": voice_name(persona, emotion),
                "audio": winner["path"],
                "transcript": transcript,
            })
    return plan


def enroll(plan: list[dict[str, Any]], vocello: str) -> list[str]:
    enrolled: list[str] = []
    environment = dict(os.environ, QWENVOICE_DEBUG="1")
    for entry in plan:
        # Replace-on-rebuild: a stale same-name voice must never survive a
        # rebuild, or the bank silently mixes generations.
        subprocess.run(
            [vocello, "voices", "delete", "--id", entry["name"]],
            capture_output=True, env=environment, check=False,
        )
        result = subprocess.run(
            [
                vocello, "voices", "enroll", "--name", entry["name"],
                "--audio", entry["audio"], "--transcript", entry["transcript"],
                # PA-17: enrollment needs the invocation's recorded consent;
                # the bank's references are repository-generated Voice Design takes.
                "--confirm-consent",
            ],
            capture_output=True, env=environment, check=False,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"enrollment failed for {entry['name']}: {detail}")
        enrolled.append(entry["name"])
    return enrolled


def write_manifest(path: pathlib.Path, manifest: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".emotion-bank-", suffix=".json", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def build(arguments: argparse.Namespace) -> int:
    repo_root = pathlib.Path(__file__).resolve().parent.parent
    persona = sanitized_persona(arguments.persona)
    emotions = [token.strip().lower() for token in arguments.emotions.split(",") if token.strip()]
    work_dir = pathlib.Path(
        arguments.work_dir
        or tempfile.mkdtemp(prefix=f"emotion-bank-{persona.replace(' ', '-')}-")
    )
    work_dir.mkdir(parents=True, exist_ok=True)
    instructions = {emotion: shipped_instruction(emotion, repo_root) for emotion in emotions}

    plan = plan_generation(
        work_dir, arguments.brief, arguments.transcript, emotions,
        instructions, arguments.candidates, arguments.base_seed,
    )

    def runner(generate_arguments: list[str]) -> bool:
        environment = dict(os.environ, QWENVOICE_DEBUG="1")
        result = subprocess.run(
            [arguments.vocello, *generate_arguments],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=environment, check=False,
        )
        return result.returncode == 0

    # Phase 1: every generation completes (and each CLI process exits) before
    # any ML scorer loads — no scorer beside a resident generator, structurally.
    print(f"generating: anchor + {arguments.candidates} candidates × {len(emotions)} emotions …")
    anchor_path, generated, failed = run_generation(plan, runner)
    print(f"  anchor: {pathlib.Path(anchor_path).name}; candidates: {len(generated)} ok, {len(failed)} failed QC")

    # Phase 2: scorers (operator-local heavy deps, loaded once, CPU).
    print("scoring: ECAPA identity + paired delivery adherence …")
    from clone_speaker_similarity import ecapa_embedder

    from bench_delivery_prosody import analyze

    embedder = ecapa_embedder()
    scored = score_candidates(anchor_path, generated, embedder, analyze)
    selection = select_winners(scored, emotions)

    enrolled: list[str] = []
    if not arguments.no_enroll:
        enrolled = enroll(
            enrollment_plan(persona, anchor_path, arguments.transcript, selection),
            arguments.vocello,
        )

    from clone_speaker_similarity import backend_identity
    from delivery_quality_gate import DELIVERY_GATE_ALGORITHM_VERSION

    manifest = {
        "bankVersion": BANK_VERSION,
        "persona": persona,
        "briefDigest": hashlib.sha256(arguments.brief.encode("utf-8")).hexdigest(),
        "transcriptDigest": hashlib.sha256(arguments.transcript.encode("utf-8")).hexdigest(),
        "emotions": emotions,
        "baseSeed": arguments.base_seed,
        "anchor": {"path": anchor_path},
        "failedCandidates": failed,
        "candidates": scored,
        "selection": {
            emotion: {
                key: (value if key != "winner" or value is None else {
                    "seed": value["seed"],
                    "path": value["path"],
                    "identityCosine": value["identityCosine"],
                    "identityBand": value["identityBand"],
                    "deliveryAdherence": value["deliveryAdherence"],
                    "voicedFracDelta": value["voicedFracDelta"],
                })
                for key, value in entry.items()
            }
            for emotion, entry in selection.items()
        },
        "enrolledVoices": enrolled,
        "scorers": {
            "deliveryAdherence": {"algorithmVersion": DELIVERY_GATE_ALGORITHM_VERSION,
                                  "tier": "strong", "reference": "neutral anchor"},
            # The pinned backend with the snapshot digests it verified.
            "identity": backend_identity(embedder),
        },
    }
    manifest_path = work_dir / "bank-manifest.json"
    write_manifest(manifest_path, manifest)

    print(f"\nbank manifest → {manifest_path}")
    for emotion in emotions:
        entry = selection[emotion]
        winner = entry.get("winner")
        if winner is None:
            print(f"  {emotion:10} NO WINNER ({entry['reason']}; {entry['candidateCount']} candidates)")
        else:
            adherence = winner["deliveryAdherence"]
            print(
                f"  {emotion:10} seed {winner['seed']}  identity {winner['identityCosine']}"
                f" ({winner['identityBand']})  arousal {adherence.get('arousalScore')}"
            )
    if enrolled:
        print("enrolled voices: " + ", ".join(enrolled))
    return 0 if all(selection[e].get("winner") for e in emotions) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    builder = commands.add_parser("build", help="generate, curate, and enroll a bank")
    builder.add_argument("--persona", required=True)
    builder.add_argument("--brief", required=True)
    builder.add_argument("--emotions", default=",".join(DEFAULT_EMOTIONS))
    builder.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES)
    builder.add_argument("--base-seed", type=int, default=DEFAULT_BASE_SEED)
    builder.add_argument("--transcript", default=DEFAULT_TRANSCRIPT)
    builder.add_argument("--work-dir", default=None)
    builder.add_argument("--vocello", default="./build/vocello")
    builder.add_argument("--no-enroll", action="store_true")
    arguments = parser.parse_args()
    return build(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
