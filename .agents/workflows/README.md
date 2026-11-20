# Vocello Antigravity Workflows (`.agents/workflows/`)

Reusable Python orchestration scripts executed through Antigravity's `run_workflow` tool
(`run_workflow(ScriptPath="/abs/path/to/repo/.agents/workflows/<script>.py", Args={...}, Description="...")`).

These scripts use Antigravity's `run_workflow` primitives (`agent`, `parallel`, `pipeline`, `phase`,
`log`, `args`, `WORKSPACES`) and top-level `await`. They are excluded from Ruff (`ruff.toml`) and
Pyright (`pyrightconfig.json`), and never replace repository build/test/evidence scripts.

## Workflows

| Script | Purpose | Model routing | MCP / plugin / subagent integration |
| --- | --- | --- | --- |
| `swift_adversarial_review.py` | 3-lens read-only review of substantive Swift diffs (`Args`: `{"base_ref": "HEAD", "files": [...]}`) | `inherit` (Carbon/Neon) for architecture/Apple lenses; `flash` (Hydrogen) for privacy/policy sweep | `vocello-swift-review` subagent (fed exact diff chunks despite being shell-free), `axiom` MCP (`axiom_search_skills`, `axiom_read_skill`), `sosumi` MCP (`searchAppleDocumentation`) |
| `xcuitest_visual_qa.py` | Multimodal visual inspection of `<run_dir>/screenshots/index.json` + native triage (`Args`: `{"run_dir": "build/artifacts/..."}`) | `flash` (Hydrogen) for parallel PNG inspection; `inherit` for `vocello-xcresult-triage` | `vocello-xcresult-triage` subagent + `read_file` image inspection across screenshots |
| `debt_burndown_pipeline.py` | Bounded (<=3 workers) disjoint-file cleanup in isolated `workspace="share"` worktrees (`Args`: `{"buckets": [{"name": "...", "files": [...], "goal": "..."}]}`) | `inherit` for editing workers | Lead integrates returned worktree commits via `git cherry-pick` / `git merge --ff-only` and validates warm on `main` |
| `qc_experiment_synthesizer.py` | Multi-angle synthesis of a QC v2 run, optional Instruments trace, and `RF-57` self-test floor (`Args`: `{"run_dir": "...", "baseline_dir": "...", "trace_path": "..."}`) | `flash` for metric/cell sweep & RF-57 gate audit; `inherit` for MLX/profile lens | `axiom` MCP (`axiom_xcprof_analyze`, `axiom_xcprof_compare`) when `.trace` is present; respects `scripts/qc.py` report-only boundary |

## Model-tier mapping (Gemini 4)

Antigravity's `agent(..., model=...)` parameter maps onto the active Gemini 4 tiers:

- **`"inherit"`** (default — Carbon or Neon): editing workers (`AGENTS.md` rule), architecture/concurrency reviews, MLX runtime and profiling synthesis.
- **`"pro"`** (Carbon): deep root-cause debugging, release-critical audits, complex Swift 6 / MLX invariants.
- **`"flash"`** (Hydrogen): parallel screenshot QA, policy/privacy sweeps, log/metric fan-out, and read-only research.
- **`"flash_lite"`**: trivial classification or file-list extraction.

## Hard rules preserved

- Workflow agents never run native builds, devices, models, or measured lanes in parallel (`AGENTS.md`).
- Editing workflows (`debt_burndown_pipeline.py`) cap concurrency at **3 workers** (4 active agents total including the lead), assign strictly disjoint files, commit only on their `subagent-*` branch, and never touch `config/roadmap.json`, `docs/development-progress.md`, or `git push`.
- No raw PII, private paths, prompts, transcripts, reference audio, or credentials are emitted into workflow logs or outputs (`DiagnosticPrivacy`).
