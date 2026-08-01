#!/usr/bin/env python3
"""Long-form acoustic-carryover probe (Tier-4 stage 2, exploratory-only).

Pre-registration: docs/decisions/long-form-acoustic-carryover-experiment.md.
Per seed: generate segment A once (custom), then segment B twice with the same
B-seed — control (custom, fresh context) vs carry (clone ICL conditioned on A's
full audio + exact text). Measures boundary-local prosody deltas (last 3 s of A
vs first 3 s of B via analyze_delivery), ECAPA identity cosine A↔B, and B wall
time. Generations run strictly sequentially; ECAPA runs only after all
generation completes (8 GB rule). Publishes nothing; artifacts stay local under
build/artifacts/macos/carryover-probe/. The ECAPA phase requires the .venv ML
environment (torch/speechbrain): run with .venv/bin/python3.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
import time
import wave
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_delivery import analyze  # noqa: E402

SEGMENT_A = (
    "The lighthouse keeper wrote the same entry every evening, wind steady, "
    "lamp trimmed, sea unremarkable. After forty years the logbook had become "
    "a kind of calendar of nothing happening."
)
SEGMENT_B = (
    "Then one October morning the entry changed. A pale ship stood off the "
    "point where no ship had anchored in living memory, and the keeper wrote "
    "three full pages before breakfast. His handwriting never quite settled "
    "down again."
)

SEEDS = [1001, 1002, 1003, 1004]
B_SEED_OFFSET = 500_000
SPEAKER = "aiden"
EDGE_SECONDS = 3.0


def run_vocello(args: list[str]) -> tuple[Path, float]:
    env = dict(os.environ, QWENVOICE_DEBUG="1")
    started = time.monotonic()
    proc = subprocess.run(
        [str(ROOT / "build" / "vocello"), *args, "--json", "--quiet"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    wall = time.monotonic() - started
    if proc.returncode != 0:
        raise SystemExit(
            f"vocello failed ({proc.returncode}): {' '.join(args)}\n{proc.stderr[-1500:]}"
        )
    payload = json.loads(proc.stdout)
    audio = payload.get("audioPath") or payload.get("outputPath") or payload.get("path")
    if not audio:
        raise SystemExit(f"no audio path in CLI JSON: {list(payload.keys())}")
    return Path(audio), wall


def slice_wav(source: Path, destination: Path, *, tail: bool, seconds: float) -> None:
    with wave.open(str(source), "rb") as reader:
        rate = reader.getframerate()
        frames = reader.getnframes()
        span = min(frames, int(seconds * rate))
        reader.setpos(frames - span if tail else 0)
        data = reader.readframes(span)
        params = reader.getparams()
    with wave.open(str(destination), "wb") as writer:
        writer.setparams(params)
        writer.writeframes(data)


def semitones(f0_a: float, f0_b: float) -> float:
    if f0_a <= 0 or f0_b <= 0:
        return float("nan")
    return abs(12.0 * math.log2(f0_b / f0_a))


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = ROOT / "build" / "artifacts" / "macos" / "carryover-probe" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    for seed in SEEDS:
        b_seed = seed + B_SEED_OFFSET
        a_path, _ = run_vocello(
            ["custom", "--speaker", SPEAKER, "--text", SEGMENT_A, "--seed", str(seed)]
        )
        a_local = out_dir / f"A_{seed}.wav"
        shutil.copy2(a_path, a_local)

        control_path, control_wall = run_vocello(
            ["custom", "--speaker", SPEAKER, "--text", SEGMENT_B, "--seed", str(b_seed)]
        )
        control_local = out_dir / f"B_control_{seed}.wav"
        shutil.copy2(control_path, control_local)

        carry_path, carry_wall = run_vocello(
            [
                "clone",
                "--reference", str(a_local),
                "--transcript", SEGMENT_A,
                "--text", SEGMENT_B,
                "--seed", str(b_seed),
            ]
        )
        carry_local = out_dir / f"B_carry_{seed}.wav"
        shutil.copy2(carry_path, carry_local)

        a_tail = out_dir / f"A_tail_{seed}.wav"
        slice_wav(a_local, a_tail, tail=True, seconds=EDGE_SECONDS)
        tail_metrics = analyze(str(a_tail))

        row = {"seed": seed, "bSeed": b_seed}
        for arm, local, wall in (
            ("control", control_local, control_wall),
            ("carry", carry_local, carry_wall),
        ):
            head = out_dir / f"B_{arm}_head_{seed}.wav"
            slice_wav(local, head, tail=False, seconds=EDGE_SECONDS)
            head_metrics = analyze(str(head))
            row[arm] = {
                "wallSeconds": round(wall, 2),
                "joinDeltaF0Semitones": round(
                    semitones(
                        tail_metrics["f0_median_hz"], head_metrics["f0_median_hz"]
                    ),
                    3,
                ),
                "joinDeltaRateHz": round(
                    abs(
                        tail_metrics["syllable_rate_hz"]
                        - head_metrics["syllable_rate_hz"]
                    ),
                    3,
                ),
            }
        rows.append(row)
        print(f"seed {seed}: generated + sliced", flush=True)

    # ECAPA identity (strictly after all generation; 8 GB rule).
    from clone_speaker_similarity import cosine_similarity, ecapa_embedder

    embed = ecapa_embedder()
    for row in rows:
        seed = row["seed"]
        a_vec = embed(str(out_dir / f"A_{seed}.wav"))
        for arm in ("control", "carry"):
            b_vec = embed(str(out_dir / f"B_{arm}_{seed}.wav"))
            row[arm]["ecapaAB"] = round(cosine_similarity(a_vec, b_vec), 4)
        print(f"seed {seed}: ECAPA done", flush=True)

    def mean(values):
        finite = [v for v in values if not math.isnan(v)]
        return sum(finite) / len(finite) if finite else float("nan")

    summary = {}
    for arm in ("control", "carry"):
        summary[arm] = {
            "meanJoinDeltaF0Semitones": round(
                mean([r[arm]["joinDeltaF0Semitones"] for r in rows]), 3
            ),
            "meanJoinDeltaRateHz": round(
                mean([r[arm]["joinDeltaRateHz"] for r in rows]), 3
            ),
            "meanEcapaAB": round(mean([r[arm]["ecapaAB"] for r in rows]), 4),
            "meanWallSeconds": round(mean([r[arm]["wallSeconds"] for r in rows]), 2),
        }

    ctrl, carry = summary["control"], summary["carry"]
    f0_improvement = (
        1.0 - carry["meanJoinDeltaF0Semitones"] / ctrl["meanJoinDeltaF0Semitones"]
        if ctrl["meanJoinDeltaF0Semitones"] > 0
        else float("nan")
    )
    verdict = {
        "f0ImprovementFraction": round(f0_improvement, 3),
        "f0GatePassed": f0_improvement >= 0.25,
        "rateNoWorse": carry["meanJoinDeltaRateHz"] <= ctrl["meanJoinDeltaRateHz"] + 0.15,
        "ecapaGatePassed": carry["meanEcapaAB"] >= ctrl["meanEcapaAB"] - 0.05,
    }
    verdict["signal"] = all(
        (verdict["f0GatePassed"], verdict["rateNoWorse"], verdict["ecapaGatePassed"])
    )

    report = {
        "probe": "longform-acoustic-carryover-v1",
        "generatedAtUTC": datetime.now(timezone.utc).isoformat(),
        "preRegistration": "docs/decisions/long-form-acoustic-carryover-experiment.md",
        "speaker": SPEAKER,
        "seeds": SEEDS,
        "edgeSeconds": EDGE_SECONDS,
        "rows": rows,
        "summary": summary,
        "verdict": verdict,
    }
    (out_dir / "probe.json").write_text(json.dumps(report, indent=2) + "\n")

    print(json.dumps({"summary": summary, "verdict": verdict}, indent=2))
    print(f"probe artifacts → {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
