"""QC v2 & MLX experiment synthesis workflow for Vocello.

Reads retained QC v2 / benchmark JSON outputs and optional Instruments `.trace`
metadata, then fans out three read-only analytical lenses:
  1. Per-cell & per-language QC v2 metric breakdown (`flash` tier)
  2. RF-57 decision-rule & noise-floor audit (`flash` tier — checks whether the
     screen's decision rule and self-test noise floor are recorded)
  3. MLX runtime / memory / Instruments trace diagnosis (`inherit` tier — uses
     `axiom` MCP `axiom_xcprof_analyze` / `axiom_xcprof_compare` when traces are
     provided, grounded in `docs/reference/mlx-guide.md`)

Args (JSON object):
  - run_dir (str, required): path to a retained QC v2 or benchmark run directory.
  - baseline_dir (str, optional): path to a compatible baseline run directory.
  - trace_path (str, optional): path to an Instruments `.trace` bundle to analyze.
  - hypothesis (str, optional): short description of the change being evaluated.
"""

import json
from pathlib import Path

ROOT = Path(WORKSPACES[0]) if WORKSPACES else Path.cwd()
raw_run_dir = str(args.get("run_dir") or "").strip()
if not raw_run_dir:
    raise ValueError("Args must include 'run_dir'.")

run_dir = Path(raw_run_dir)
if not run_dir.is_absolute():
    run_dir = (ROOT / run_dir).resolve()
if not run_dir.exists():
    raise FileNotFoundError(f"Run path not found: {run_dir}")

baseline_dir = str(args.get("baseline_dir") or "").strip()
trace_path = str(args.get("trace_path") or "").strip()
hypothesis = str(args.get("hypothesis") or "Unspecified experiment")

phase("Collect Retained Evidence Files")


def _summarize_dir(directory: Path):
    if directory.is_file():
        return [str(directory)]
    interesting = []
    for p in sorted(directory.rglob("*")):
        if p.is_file() and p.suffix in (".json", ".txt", ".md") and p.stat().st_size < 512_000:
            interesting.append(str(p))
    return interesting[:30]


run_files = _summarize_dir(run_dir)
baseline_files = _summarize_dir(Path(baseline_dir) if Path(baseline_dir).is_absolute() else (ROOT / baseline_dir)) if baseline_dir else []
log(f"Found {len(run_files)} artifact file(s) in {run_dir.name}; baseline files: {len(baseline_files)}")

LENS_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["SUPPORTIVE", "INCONCLUSIVE", "REGRESSION", "BLOCKED"]},
        "highlights": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["status", "highlights", "risks"],
}

phase("Parallel Experiment Analysis")

lenses = [
    {
        "name": "qc-metrics",
        "role": "QC v2 Metric Analyst",
        "type_name": "research",
        "model": "flash",
        "prompt": (
            "Read-only analysis — edit nothing, run no models. Remember: QC v2 is report-only, "
            "no automated score is a listening verdict, and nobody listens for 3.x (maintainer decision 2026-10-13).\n"
            f"Hypothesis: {hypothesis}\n"
            f"Inspect these retained artifact files with read_file and summarize per-cell / per-language "
            "deltas, refusals, EOS/duration anomalies, and Fast QC vs QC v2 outcomes. Never quote raw prompts or transcripts.\n"
            "Run files:\n" + "\n".join(f"- {f}" for f in run_files)
            + ("\nBaseline files:\n" + "\n".join(f"- {f}" for f in baseline_files) if baseline_files else "")
        ),
    },
    {
        "name": "rf57-gate-audit",
        "role": "RF-57 Methodology Auditor",
        "type_name": "research",
        "model": "flash",
        "prompt": (
            "Read-only methodology audit — edit nothing. Check the retained evidence against Vocello's "
            "AGENTS.md and RF-57 rules: (1) committed checkpoint / source binding, (2) fixed seeds untouched, "
            "(3) compatible baseline & optimized-build receipt, (4) memory qualification intact, "
            "(5) pre-registered decision rule and self-test noise floor before accepting sample-altering changes.\n"
            f"Hypothesis: {hypothesis}\n"
            "Run files:\n" + "\n".join(f"- {f}" for f in run_files)
            + ("\nBaseline files:\n" + "\n".join(f"- {f}" for f in baseline_files) if baseline_files else "")
        ),
    },
    {
        "name": "mlx-profile",
        "role": "MLX & Profile Analyst",
        "type_name": "self",
        "model": "inherit",
        "prompt": (
            "Read-only runtime & performance analysis — edit nothing, run no builds or models. "
            "Ground your analysis in `docs/reference/mlx-guide.md` and the retained run artifacts. "
            + (
                f"An Instruments trace was supplied at `{trace_path}` — inspect it with `axiom` MCP "
                "`axiom_xcprof_analyze` (and `axiom_xcprof_compare` if a baseline trace is present).\n"
                if trace_path
                else "No Instruments `.trace` was supplied; focus on telemetry/RTF/memory/Metal peaks in the retained files.\n"
            )
            + f"Hypothesis: {hypothesis}\n"
            "Run files:\n" + "\n".join(f"- {f}" for f in run_files)
        ),
    },
]

results = await parallel(
    lenses,
    lambda lens: agent(
        lens["prompt"],
        schema=LENS_SCHEMA,
        role=lens["role"],
        type_name=lens["type_name"],
        workspace="inherit",
        model=lens["model"],
    ),
)

phase("Synthesis")

print(f"EXPERIMENT: {hypothesis}")
print(f"RUN: {run_dir.name}")
for lens, res in zip(lenses, results):
    log(f"[{lens['name']}] {res['status']}")
    print(f"\n### {lens['role']} ({res['status']})")
    for h in res["highlights"]:
        print(f"- {h}")
    if res["risks"]:
        print("Risks / blockers:")
        for r in res["risks"]:
            print(f"  - {r}")
