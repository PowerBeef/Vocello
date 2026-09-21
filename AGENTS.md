# Vocello development guide

Codex is the sole development agent. Work directly on the existing local `main` checkout;
no branches, worktrees, automatic delegation or additional agents. Keep tooling proportional to
product work: reuse scripts and tests, load guidance only when relevant, and add a check only for
a demonstrated product or workflow risk.

## Start here

1. Read `git status --short --branch`, `git rev-parse HEAD`, `python3 scripts/roadmap.py status`,
   and the current **Resume now** section of `docs/development-progress.md`. Preserve existing edits;
   reconcile unexpected changes before touching overlapping files. Never stash or broadly stage them.
2. Load only the domain guidance in scope (paths below are repository-relative):
   - Swift, owned packages, tests and project inputs: `docs/reference/agent-rules/native.md`.
   - Scripts, contracts, CI, packaging, evidence or agent configuration: `docs/reference/agent-rules/release.md`.
   - Website: `website/AGENTS.md`; read `website/PRODUCT.md` and `website/DESIGN.md` for visual/copy work.
3. Implement the smallest coherent change, verify affected behavior, review the actual diff, then
   commit the assigned files on `main` and push. CI on the pushed commit is the gate.
4. Report changed behavior, checks and limitations, commit/CI evidence and remaining work. Update the
   existing roadmap and checkpoint when work status changes; do not introduce another task ledger.

The bounded session hook supplies local context only. Devices and optional tools are checked when
needed, not on startup. Detailed procedure: `docs/reference/development-workflow.md`.

## Product and authority

Vocello is local-first Qwen3-TTS on MLX in Swift 6: macOS and iOS host the engine in-process on
one shared store, alongside the `vocello` CLI, Python tooling and React/Vite website. No bundled
weights or cloud inference. Approved assets download through the production catalog.

Authority: `Sources/` → `project.yml` → `config/` contracts → `scripts/` → `.github/workflows/` →
this guide and domain rules → other prose. Correct conflicting prose in the same change. Public
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
are serialized and reuse owned caches. Website-only work never launches native builds or devices.
`scripts/dev.sh ci` is the full serial CI replay when needed, not the default inner loop.
UI-test source changes compile their affected bundles locally; ordinary CI never runs native UI.

## Hard boundaries

- **Physical iPhone only:** no Simulator build, launch or test. Generic iOS compilation is phone-free.
- **One native UI driver:** repository XCUITest through `scripts/ui_test.sh`; no computer-use,
  coordinate, browser or MCP native UI routes. Genuine controls only; no hidden shippable test UI.
- **Explicit consent:** device/UI/model/benchmark runs, releases and publication need an explicit
  request. Tool or skill availability grants no consent. Never retry a failed evidence run silently.
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

## Tools and skills

Repository scripts are authoritative. Installed Axiom, Apple documentation, Swift/MLX, native-app,
GitHub, browser, Hugging Face and Vercel tools can assist relevant work when callable; choose the
smallest useful set, not every available skill. Preserve all boundaries above even when a plugin
suggests another route. Missing optional tools do not block the script workflow or require a second
server. CI does not depend on personal plugins or credentials.

The four explicit QA shortcuts live in `.agents/skills`; they call the same repository scripts.
`.codex/environments/environment.toml` exposes existing commands with no automatic setup.
`.codex/hooks.json` supplies fast guardrails. Project hooks require platform trust and have limited
coverage; they are neither a sandbox nor proof of authorization. See the development guide for tool
routing and fresh-session verification.
