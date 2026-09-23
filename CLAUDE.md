# Vocello development guide

Claude Code is the primary software engineer, responsible for delivering working changes from the
user's objective through implementation, verification and completion. The lead session works on the
existing local `main` checkout, owns integration and is the only one that pushes. Parallel agents are
allowed when they save time on the 16 GB development Mac: read-only subagents research, review, audit
and triage; editing agents work only in Claude Code worktrees (`.claude/worktrees/<name>`, branch
`worktree-<name>`) that the lead integrates into `main`. Native builds are serialized machine-wide by
the host lock; device, UI, model and benchmark lanes stay with the lead on a quiet host. Keep tooling
proportional to product work: reuse scripts and tests, load guidance only when relevant, and add a
check only for a demonstrated product or workflow risk. Parallel rules and budget:
`docs/reference/development-workflow.md#parallel-agents-and-worktrees`.

## Engineering ownership and autonomy

- Treat requests to improve, fix or build as authorization to carry the work through. Inspect the
  relevant code, choose a practical solution, implement it, resolve failures, verify and deliver.
  Do not stop at recommendations or wait for another developer to implement them.
- Make routine design and implementation decisions independently, following the approved product
  direction and repository conventions. Briefly state material assumptions and keep moving.
  Ask only when missing information blocks progress, a consequential product choice cannot be
  inferred, or an explicit consent boundary below applies.
- Fix related defects discovered within the requested scope. Record unrelated or substantially
  larger work in the existing roadmap without expanding the assignment. A review-only request
  remains read-only; self-review is otherwise part of implementation, not a separate handoff.
- Carry existing authorization through the task. Do not ask the user to approve each implementation
  step, routine check, or already-authorized action. When consent is genuinely missing, finish the
  independent work first and request only the blocked action, explaining the applicable boundary.
- Keep the workflow proportional: use the smallest meaningful checks, fix their failures, review
  the diff, commit and push the scoped change, and verify CI. Report the outcome and real limitations;
  do not turn ordinary product work into a tooling project or an approval checklist.

## Start here

On a fresh clone or a new machine, set up the toolchain first with
`docs/reference/development-setup.md`.

1. Read `git status --short --branch`, `git rev-parse HEAD`, `python3 scripts/roadmap.py status`,
   and the current **Resume now** section of `docs/development-progress.md` (the session hook prints
   a bounded summary). Preserve existing edits; reconcile unexpected changes before touching
   overlapping files. Never stash or broadly stage them.
2. Load only the domain guidance in scope. Path-scoped rules load automatically when you read
   matching files; read them directly when planning:
   - Swift, owned packages, tests and project inputs: `.claude/rules/native.md`.
   - Scripts, contracts, CI, packaging, evidence or Claude configuration: `.claude/rules/release.md`.
   - Website: `website/CLAUDE.md`; read `website/PRODUCT.md` and `website/DESIGN.md` for visual/copy work.
3. Implement the smallest coherent change, verify affected behavior, review the actual diff, then
   commit the assigned files on `main` and push. Split independent work across agents only when the
   file sets do not overlap. CI on the pushed commit is the gate.
4. Report changed behavior, checks and limitations, commit/CI evidence and remaining work. Update the
   existing roadmap and checkpoint when work status changes; do not introduce another task ledger.

The bounded session hook supplies local context only. Devices and optional tools are checked when
needed, not on startup. Detailed procedure: `docs/reference/development-workflow.md`.

## Product and authority

Vocello is local-first Qwen3-TTS on MLX in Swift 6: macOS and iOS host the engine in-process on
one shared store, alongside the `vocello` CLI, Python tooling and React/Vite website. No bundled
weights or cloud inference. Approved assets download through the production catalog.

Authority: `Sources/` → `project.yml` → `config/` contracts → `scripts/` → `.github/workflows/` →
this guide and `.claude/rules/` → other prose. Correct conflicting prose in the same change. Public
facts come from `config/public-product-facts.json` and `project.yml`.
`config/roadmap.json` owns open work; `config/roadmap-archive.json` owns completed work;
`docs/ROADMAP.md` is generated. Architecture lives in `docs/ARCHITECTURE.md`.

## Commands and verification

```sh
scripts/dev.sh status
scripts/dev.sh check --dry-run       # inspect routed work
scripts/dev.sh check                 # lint, contracts, affected tests/builds
scripts/dev.sh test --only ClassName # targeted native inner loop
scripts/dev.sh py                    # selected Python consumers
scripts/dev.sh contracts
scripts/dev.sh ios                   # generic device-SDK compile, no phone
scripts/dev.sh build                 # development macOS build
scripts/dev.sh run
scripts/dev.sh regen                 # registered generated artifacts
npm --prefix website run check       # independent website acceptance
```

Use targeted checks while editing, then the routed check before committing. Broaden only for new
changes, failures or unresolved risk. Use `check --paths <assigned paths...>` when unrelated dirty
work must remain paused; its contract gate still considers dirty tooling inputs. Native commands
are serialized host-wide by the native lock (`~/Library/Caches/Vocello/native-build.lock`, across
every checkout and worktree) and reuse owned caches. Website-only work never launches native builds or
devices.
`scripts/dev.sh ci` is the full serial CI replay when needed, not the default inner loop.
UI-test source changes compile their affected bundles locally; ordinary CI never runs native UI.
After a push, follow the run with `gh run list` / `gh run watch` until `CI required` settles.

## Hard boundaries

- **Main is the only published branch:** the lead commits on local `main` and pushes only `main`.
  Agents commit only in Claude Code worktrees on their `worktree-*` branch; the lead integrates with
  `git merge --ff-only` or `git cherry-pick`, then removes the worktree and branch. No hand-made
  branches or worktrees, never push another ref, never force-push; stage explicit paths.
- **Physical iPhone only:** no Simulator build, launch or test. Generic iOS compilation is phone-free.
- **One native UI driver:** repository XCUITest through `scripts/ui_test.sh`; no computer-use,
  coordinate, browser or MCP native UI routes. Genuine controls only; no hidden shippable test UI.
- **Explicit consent:** device/UI/model/benchmark runs, releases and publication need an explicit
  request. Consent covers that request only; none carries over. Lanes run one at a time on committed
  source, in the lead session, with no agent or native build running alongside. Tool or skill
  availability grants no consent. Never retry a failed evidence run silently.
- **Generated project:** edit `project.yml`, never `project.pbxproj`; run
  `./scripts/regenerate_project.sh --fast` after project inputs change.
- **Release-only:** no Debug configuration or generic `DEBUG` symbol. Production overrides require
  registered diagnostics plus `VOCELLO_INTERNAL_DIAGNOSTICS` and `QWENVOICE_DEBUG=1`.
- **Runtime:** MLX only, actor-owned lifecycle, typed cancellation, serialized prewarm, request-local
  sampling and suspending bounded audio. Unsafe concurrency is registered. Dependency pins move in
  lockstep under the native rules; no separate engine process.
- **Delivery:** activate only complete digest-verified production artifacts; never infer checksums.
- **iOS commerce/localization:** one StoreKit owner and export boundary; interface language is
  `IOSAppLanguage`, separate from generated speech. No macOS or CLI paywall.
- **Privacy:** no PII, private paths, prompts, transcripts, credentials or raw diagnostics in Git.
  The literal privacy scanner supplements source review; it cannot prove runtime privacy.
- **Owned output:** `config/build-output-policy.json` owns caches/artifacts under `build/`.
  Never clear whole caches to resolve contention. Keep failed raw evidence untracked; publish only
  qualified privacy-safe records. Source-bound evidence and signing rules stay in the runbooks.
- **Git/release:** never force-push. Releases require the existing verified tag, exact-source CI,
  signing and promotion gates. No changes to global installations or pins just to hide local drift.

## Claude Code setup

Repository scripts are authoritative; everything below assists them and never replaces a gate.

- **`.claude/settings.json`** wires the repository guards through `scripts/hooks/`:
  `session_start.sh` (bounded local context, open worktrees), `commit_lint.sh` (commits on `main`
  or an agent's `worktree-*` branch, pushes only from `main`, clean staged whitespace, staged privacy
  scan, all judged in the checkout the command acts on), `policy_guard.sh` (Simulator routes,
  whole-cache deletion, force pushes, pushes of any ref but `main`, hand-made branches/worktrees,
  `update-ref`, `project.pbxproj` writes), `generated_file_guard.sh` (generated or frozen files, also
  inside worktrees) and `project_yml_reminder.sh`. Its permissions allow the routine loop, including
  scoped commits, pushes to `main` and worktree integration (`merge --ff-only`, `cherry-pick`,
  `worktree remove`), ask before consent-bound lanes, cache cleanup and discarding agent work, and
  deny force pushes, pushes of other refs, hand-made branches, broad staging, stashing, releases,
  Simulator MCP tools and `.xcodeproj` edits. `worktree.baseRef: head` bases agent worktrees on local
  `main`. Hooks and permissions are guardrails, not proof of authorization.
  `scripts/tests/test_agent_hooks.py` pins the wiring; personal overrides belong in the untracked
  `.claude/settings.local.json`.
- **Skills** (user-invoked only; the invocation is the explicit request for that lane):
  `/ios-lane <lane>`, `/macos-ui-lane <lane>`, `/device-diagnostics <verb>` and
  `/release-evidence <tag>` (read-only). They call the existing scripts and add no gate.
- **Subagents:** `xcresult-triage` reads a finished UI run as the testing runbook describes and never
  reruns it; `swift-review` reviews Swift diffs against `.claude/rules/native.md`; Explore/Plan and the
  Axiom auditors research and audit. These stay read-only. Editing agents are general-purpose agents
  given `isolation: "worktree"`; they never push, touch `main`, edit `config/roadmap.json` or the
  progress log, or run consent-bound lanes.
- **Tool routing:** XcodeBuildMCP (profiles `macos` and `ios-device` in `.xcodebuildmcp/config.yaml`)
  for discovery, scratch builds and device debugging only, never Simulator or UI automation and never
  as evidence; swift-lsp through `buildServer.json` (needs a warm `build/cache/xcode/macos`); Axiom
  skills, Axiom auditor subagents, the mlx-swift skills and Apple documentation (sosumi) for platform
  and MLX APIs; Context7 for library documentation; `gh`, the GitHub connector and Monitor for CI and
  releases; Claude in Chrome or chrome-devtools for the website (and portal chores only on explicit
  request); the asc-* skills (tddworks `asc`) for App Store Connect, writes only on explicit request;
  Hugging Face tools read-only, with no implied download or pin change. Missing optional tools never
  block the script workflow, and CI never depends on personal plugins or credentials.
- **Guard literals:** hooks match raw Bash command text. Commit with a literal `git commit -F -`
  heredoc so the commit lint runs (a quote-split command would run the commit and skip the lint);
  build strings that merely *mention* Simulator routes, private home paths or the commit command from
  fragments in commands and fixtures.
- **Maintainer-run actions:** Hugging Face Hub commits, model installs and upload, deploy or repin
  commands are run by the maintainer (the `!` prefix in the prompt); prepare them, do not run them.

Detailed routing, permissions rationale and fresh-session verification:
`docs/reference/development-workflow.md#claude-code-setup-and-tool-routing`.
