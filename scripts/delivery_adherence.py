#!/usr/bin/env python3
"""Objective DELIVERY-ADHERENCE bench (deterministic).

The committed, reproducible measurement of whether a delivery preset actually
moves the voice the way its instruction asks. Replaces the earlier multimodal
ear-based review, which proved too unreliable to decide on (flips on byte-
identical audio, abstains under load -- see benchmarks/OPTIMIZATION.md section I.3).

Method -- paired neutral-vs-instructed, same seed:
  for each (preset, variant, seed):
    1. generate a NEUTRAL take (no delivery) at that seed         [cached per seed/variant]
    2. generate an INSTRUCTED take with the preset's instruction  [same seed/speaker/text]
    3. analyze both with scripts/analyze_delivery.py and take the delta
A real high-arousal delivery effect = F0 up + syllable rate up + duration down
(+ wider F0 range) vs the same-seed neutral. RMS is ignored (engine limiter).
Per (preset, variant) we report median deltas, an arousal score, and the
fraction of seeds whose arousal moved positive ("posRate"). Generation is serial
(the engine is single-mutator); analysis is instant.

Preset instructions come from `vocello deliveries --json` (the DRY source is
EmotionPreset). Dev tool only; no Python ships in the app.

Usage:
  scripts/delivery_adherence.py [--presets happy.normal,angry.strong,surprised.normal]
      [--variants speed[,quality]] [--seeds 8] [--speaker aiden] [--text "..."]
      [--vocello build/vocello] [--out <jsonl>] [--workdir <dir>] [--keep] [--json]
"""
import sys, os, json, argparse, subprocess, tempfile, shutil, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from analyze_delivery import analyze
from analyze_prosody import analyze as analyze_prosody
from prosody_profile import builtin_profile, load_profile, delivery_weight

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_TEXT = ("The morning train slipped quietly out of the station, carrying a handful "
                "of sleepy travelers toward the coast.")
DEFAULT_PRESETS = ["happy.normal", "surprised.normal", "angry.normal"]


def _weight(profile, section, key):
    return delivery_weight(profile, section, key)


def deliveries_map(vocello):
    """preset-id -> instruction, from `vocello deliveries --json`."""
    out = subprocess.run([vocello, "deliveries", "--json"], cwd=REPO,
                         capture_output=True, text=True)
    if out.returncode != 0:
        sys.exit(f"`vocello deliveries --json` failed: {out.stderr.strip()[:200]}")
    return {r["id"]: r["instruction"] for r in json.loads(out.stdout)}


def generate(vocello, variant, speaker, text, seed, out_path, instruction=None, data_dir=None):
    cmd = [vocello, "generate", "--mode", "custom", "--variant", variant,
           "--speaker", speaker, "--text", text, "--seed", str(seed), "--out", out_path]
    if instruction:
        cmd += ["--delivery", instruction]
    if data_dir:
        cmd += ["--data-dir", data_dir]
    r = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True)
    return r.returncode == 0 and os.path.exists(out_path)


def arousal(inst, neu, profile=None):
    """Signed arousal delta: +pitch, +rate, +range, -duration. Gain-independent."""
    prof = profile if profile is not None else builtin_profile()
    return ((inst["f0_median_hz"] - neu["f0_median_hz"]) / _weight(prof, "arousal", "f0_median_divisor")
            + (inst["syllable_rate_hz"] - neu["syllable_rate_hz"]) / _weight(prof, "arousal", "syllable_rate_divisor")
            + (inst["f0_range_hz"] - neu["f0_range_hz"]) / _weight(prof, "arousal", "f0_range_divisor")
            - (inst["durationSec"] - neu["durationSec"]) / _weight(prof, "arousal", "duration_divisor"))


def prosody_effect(p_inst, p_neu, profile=None):
    """Signed prosodic expressiveness delta beyond static pitch/rate.

    High-arousal deliveries should increase F0 dynamics and rate variability
    while trimming pauses. Gain-independent (energy roughness is normalized).
    """
    prof = profile if profile is not None else builtin_profile()
    d_f0_std = p_inst["f0_std_hz"] - p_neu["f0_std_hz"]
    d_rate_cv = p_inst["rate_cv"] - p_neu["rate_cv"]
    d_pause_ratio = p_inst["pause_ratio"] - p_neu["pause_ratio"]
    d_roughness = p_inst["energy_roughness"] - p_neu["energy_roughness"]
    return (d_f0_std / _weight(prof, "prosody_effect", "f0_std_divisor")
            + d_rate_cv / _weight(prof, "prosody_effect", "rate_cv_divisor")
            - d_pause_ratio / _weight(prof, "prosody_effect", "pause_ratio_divisor")
            + d_roughness / _weight(prof, "prosody_effect", "energy_roughness_divisor"))


def med(xs):
    return round(statistics.median(xs), 2) if xs else 0.0


def main():
    ap = argparse.ArgumentParser(description="Objective delivery-adherence bench.")
    ap.add_argument("--presets", default=",".join(DEFAULT_PRESETS),
                    help="comma list of preset ids (default high-arousal set)")
    ap.add_argument("--variants", default="speed", help="comma list: speed[,quality]")
    ap.add_argument("--seeds", type=int, default=8, help="paired seeds 1..N (default 8)")
    ap.add_argument("--speaker", default="aiden")
    ap.add_argument("--text", default=DEFAULT_TEXT)
    ap.add_argument("--vocello", default=os.path.join(REPO, "build", "vocello"))
    ap.add_argument("--data-dir", default="", help="runtime dir passed to vocello generate")
    ap.add_argument("--out", default="", help="write per-seed JSONL here")
    ap.add_argument("--workdir", default="", help="WAV scratch dir (default: temp, removed unless --keep)")
    ap.add_argument("--keep", action="store_true", help="keep generated WAVs")
    ap.add_argument("--json", action="store_true", help="emit the summary table as JSON")
    ap.add_argument("--prosody-profile", default="", help="path to a prosody profile JSON (default: built-in)")
    args = ap.parse_args()

    profile = load_profile(args.prosody_profile) if args.prosody_profile else None

    if not os.path.exists(args.vocello):
        sys.exit(f"vocello binary not found at {args.vocello} (build it: ./scripts/build.sh cli)")
    dmap = deliveries_map(args.vocello)
    presets = [p.strip() for p in args.presets.split(",") if p.strip()]
    for p in presets:
        if p not in dmap:
            sys.exit(f"unknown delivery preset '{p}' (see `vocello deliveries`)")
    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    seeds = list(range(1, args.seeds + 1))

    workdir = args.workdir or tempfile.mkdtemp(prefix="delivery_adh_")
    os.makedirs(workdir, exist_ok=True)
    records = []      # per (preset, variant, seed)
    try:
        for variant in variants:
            neutral_feat = {}
            neutral_pros = {}
            for s in seeds:
                npath = os.path.join(workdir, f"neutral_{variant}_s{s}.wav")
                if generate(args.vocello, variant, args.speaker, args.text, s, npath, data_dir=args.data_dir):
                    neutral_feat[s] = analyze(npath)
                    neutral_pros[s] = analyze_prosody(npath)
                else:
                    print(f"WARN: neutral gen failed {variant}/s{s}", file=sys.stderr)
            for pid in presets:
                instr = dmap[pid]
                for s in seeds:
                    if s not in neutral_feat:
                        continue
                    ipath = os.path.join(workdir, f"{pid}_{variant}_s{s}.wav")
                    if not generate(args.vocello, variant, args.speaker, args.text, s, ipath, instr, data_dir=args.data_dir):
                        print(f"WARN: gen failed {pid}/{variant}/s{s}", file=sys.stderr)
                        continue
                    inst = analyze(ipath)
                    neu = neutral_feat[s]
                    p_inst = analyze_prosody(ipath)
                    p_neu = neutral_pros[s]
                    records.append({
                        "preset": pid, "variant": variant, "seed": s,
                        "dF0": round(inst["f0_median_hz"] - neu["f0_median_hz"], 1),
                        "dRange": round(inst["f0_range_hz"] - neu["f0_range_hz"], 1),
                        "dRate": round(inst["syllable_rate_hz"] - neu["syllable_rate_hz"], 2),
                        "dDur": round(inst["durationSec"] - neu["durationSec"], 2),
                        "arousal": round(arousal(inst, neu, profile), 2),
                        "dF0Std": round(p_inst["f0_std_hz"] - p_neu["f0_std_hz"], 2),
                        "dRateCV": round(p_inst["rate_cv"] - p_neu["rate_cv"], 3),
                        "dPauseRatio": round(p_inst["pause_ratio"] - p_neu["pause_ratio"], 3),
                        "dRoughness": round(p_inst["energy_roughness"] - p_neu["energy_roughness"], 3),
                        "prosodyEffect": round(prosody_effect(p_inst, p_neu, profile), 2),
                    })
    finally:
        if not args.keep and not args.workdir:
            shutil.rmtree(workdir, ignore_errors=True)

    # Aggregate per (preset, variant).
    cells = {}
    for r in records:
        cells.setdefault((r["preset"], r["variant"]), []).append(r)
    summary = []
    for (preset, variant), rs in sorted(cells.items()):
        ar = [r["arousal"] for r in rs]
        pe = [r["prosodyEffect"] for r in rs]
        summary.append({
            "preset": preset, "variant": variant, "n": len(rs),
            "dF0": med([r["dF0"] for r in rs]),
            "dRange": med([r["dRange"] for r in rs]),
            "dRate": med([r["dRate"] for r in rs]),
            "dDur": med([r["dDur"] for r in rs]),
            "arousal": med(ar),
            "posRate": round(sum(1 for a in ar if a > 0) / len(ar), 2) if ar else 0.0,
            "dF0Std": med([r["dF0Std"] for r in rs]),
            "dRateCV": med([r["dRateCV"] for r in rs]),
            "dPauseRatio": med([r["dPauseRatio"] for r in rs]),
            "dRoughness": med([r["dRoughness"] for r in rs]),
            "prosodyEffect": med(pe),
            "prosodyPosRate": round(sum(1 for a in pe if a > 0) / len(pe), 2) if pe else 0.0,
        })

    if args.out:
        with open(args.out, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    if args.json:
        print(json.dumps(summary, indent=2)); return
    print(f"\n=== delivery adherence (instructed - neutral, paired; speaker={args.speaker}) ===")
    hdr = (f"{'preset':18s} {'variant':8s} {'n':>2s} {'dF0(Hz)':>8s} {'dRange':>7s} {'dRate':>6s} "
           f"{'dDur(s)':>8s} {'arousal':>8s} {'posRate':>7s} {'dF0Std':>7s} {'dRateCV':>8s} "
           f"{'dPauseR':>8s} {'dRough':>7s} {'prosEff':>8s} {'prosPos':>7s}")
    print(hdr); print("-" * len(hdr))
    for r in summary:
        print(f"{r['preset']:18s} {r['variant']:8s} {r['n']:>2d} {r['dF0']:>8.1f} {r['dRange']:>7.1f} "
              f"{r['dRate']:>6.2f} {r['dDur']:>8.2f} {r['arousal']:>+8.2f} {r['posRate']:>7.2f} "
              f"{r['dF0Std']:>+7.2f} {r['dRateCV']:>+8.3f} {r['dPauseRatio']:>+8.3f} "
              f"{r['dRoughness']:>+7.3f} {r['prosodyEffect']:>+8.2f} {r['prosodyPosRate']:>7.2f}")
    print("\narousal>0 / high posRate = instruction reliably pushes toward high arousal vs neutral.")
    print("prosodyEffect>0 / high prosodyPosRate = instruction adds pitch/rate dynamics and trims pauses.")
    print("(F0 + rate + duration are gain-independent; RMS ignored due to the engine limiter.)")


if __name__ == "__main__":
    main()
