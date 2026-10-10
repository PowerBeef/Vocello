# Vocello engineering instructions

Codex owns implementation, verification and integration on the existing local `main` checkout.
Carry authorized work through to a reviewable result. Make routine engineering decisions, use the
smallest meaningful checks, fix failures and commit scoped changes. Pushes require an explicit
request, including any existing unpushed commits. Preserve unrelated edits and prior commits;
stage explicit paths, never stash or broadly stage the working tree.

## Start here

1. Read `git status --short --branch`, `git rev-parse HEAD`, `python3 scripts/roadmap.py status`
   and **Resume now** in `docs/development-progress.md`. Reconcile overlapping changes first.
2. Read the relevant maintained rules before editing:
   - Swift, owned packages, tests, project inputs: [native engineering](docs/reference/native-engineering.md).
   - Scripts, CI, contracts, diagnostics, evidence: [tooling and evidence](docs/reference/tooling-and-evidence.md).
   - Website, even when working from the root: [website/AGENTS.md](website/AGENTS.md).
   - Daily loop, agents, tool routing and trust: [development workflow](docs/reference/development-workflow.md).
3. Inspect source and tests; use installed Axiom guidance for relevant Apple domains, and MLX skills
   for runtime changes. Load only relevant skills. Repository skills in `.agents/skills` wrap the
   scripts; they add no execution engine or permission boundary.
4. Implement, verify, review the actual diff and commit assigned files on `main`. For substantive
   Swift changes use an independent read-only Swift review. Focus review on security, persistence,
   hooks and release changes. Record larger unrelated work in the existing roadmap.
5. Report results, evidence and real limitations. Update the existing roadmap and checkpoint when
   status changes; do not create another task ledger.

## Architecture and authority

Vocello is local-first Qwen3-TTS on MLX in Swift 6. macOS and iOS host the runtime in-process on
one shared store; the repository also owns the `vocello` CLI, Python tooling and React/Vite website.
No bundled weights or cloud inference. [Architecture](docs/ARCHITECTURE.md) traces ownership and
lifecycles; the [2026-10-10 audit](docs/audits/2026-10-10-codex-workflow-audit.md) records verified gaps.

Authority: `Sources/` → `project.yml` → `config/` contracts → `scripts/` → CI → these instructions
and maintained reference rules → other prose. Fix conflicting active prose in the same change.
`config/public-product-facts.json` and `project.yml` own public facts. `config/roadmap.json` owns
open work; `config/roadmap-archive.json` owns completed work; `docs/ROADMAP.md` is generated.

## Fast engineering loop

```sh
scripts/dev.sh doctor --json          # read-only capabilities, no installs/downloads
scripts/dev.sh status
scripts/dev.sh check --dry-run --json # structured plan, same routing as check
scripts/dev.sh test --only ClassName  # targeted deterministic XCTest
scripts/dev.sh lint                   # changed-file advisory SwiftLint
scripts/dev.sh build                  # warm incremental development build
scripts/dev.sh ios                    # generic physical-device SDK compile, no phone
scripts/dev.sh check                  # affected contracts/tests/builds before commit
scripts/dev.sh check --since <checkpoint> # verify a coherent committed batch
scripts/dev.sh triage <run-directory> --json # existing evidence only
npm --prefix website run check
scripts/hooks/commit_lint.sh --staged  # callable whitespace/privacy/Git safeguard
```

Use targeted deterministic tests while editing, routed checks before committing, then the smallest
relevant existing model, UI, device or performance lane at a coherent checkpoint. Local validation
is authorized; full matrices remain task/release-specific. Keep routine CI deterministic and free
of personal plugins, models, devices and native UI execution. Preserve warnings-as-errors,
sanitizers, quarantine, supply-chain and release gates. A local Xcode build does not prove the pinned
CI compiler accepts the change. Run CI observation only after an explicitly requested push.

## Boundaries

- **Git and agents:** lead commits on `main`; only `main` may be pushed, on explicit request.
  Use selective parallel agents for disjoint work when useful, at most four active agents including
  the lead, inheriting its selected model. Editing agents use Codex-managed worktrees based
  explicitly on the lead's committed checkpoint and scoped `codex/*` branches. Identify them via
  Git metadata; lead integrates and validates warm. Agents never push or run native/measured lanes.
  Join/stop workers before measurements. Unknown worker tracking requires declared lead-only
  execution after joining workers; an idle locked worktree is not a running worker.
- **Native execution:** every Xcode/SwiftPM build/test uses the host-wide native lock and owned
  caches. Physical iPhone only; generic iOS compilation is phone-free. Repository XCUITest via
  `scripts/ui_test.sh` is the only native UI driver. No computer-use, coordinate, browser or MCP
  native UI driving. Genuine shipped controls only; no hidden test UI.
- **Runtime:** MLX only, in-process shared store, actor-owned lifecycle, typed cancellation barrier,
  serialized prewarm, request-local sampling/memory and suspending bounded audio. Register unsafe
  concurrency. Activate only complete digest-verified catalog artifacts; never infer checksums.
- **Build:** Release only; no Debug configuration or generic `DEBUG`. Production overrides require
  registered diagnostics, `VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`. Edit project
  specifications and source membership, never `project.pbxproj`; the shared generation signature
  controls regeneration. Content edits retain incremental reuse.
- **iOS:** one StoreKit owner/export boundary. `IOSAppLanguage` owns interface language separately
  from generated speech. No macOS/CLI paywall. Preserve accessibility identifiers/localization.
- **Evidence:** source-bound measurements use committed checkpoints, fixed seeds, compatible
  baselines, optimized-build receipts and required memory qualification. Keep failed evidence;
  a justified rerun gets a new ID and explanation. Fast QC gates and report-only QC v2 differ;
  automated scores cannot imply human listening or unsupported quality claims. Debug retained
  verdicts/logs first, then symbolication, LLDB or profiling as indicated.
- **Privacy/output:** no PII, private paths, prompts, transcripts, credentials or raw diagnostics in
  Git. Persist failure summaries through `DiagnosticPrivacy`. `config/build-output-policy.json`
  owns caches/artifacts; never clear whole caches to resolve contention. Raw failures stay untracked.
- **Specific authorization:** new large downloads, model installs, dependency repins, global settings,
  releases, signing/publication, App Store/deployment changes and other external writes require a
  specific request. Reuse installed assets. Tool/skill availability is not authorization.

## Codex integration

`.codex/hooks.json` is the sole hook representation. Hooks require project trust and review of their
current definition in Codex; configuration alone does not establish activation. Report inactive or
unverified hooks. They supplement directly callable scripts and never replace gates. See the
[trust and smoke procedure](docs/reference/development-workflow.md#codex-setup-and-tool-routing).
Read-only agents live in `.codex/agents`; skills in `.agents/skills`. No personal plugins or accounts
are CI dependencies. Prefer repository scripts for canonical builds/tests/evidence, Sosumi/Apple
and Context7 for API research, XcodeBuildMCP for compatible discovery/debugging under native
serialization, browser tools for the website, and GitHub tools for repository/CI reads. Verified
Axiom helpers may interpret retained logs/crashes/traces without replacing native artifact contracts.
