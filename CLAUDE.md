# CLAUDE.md — Vocello (QwenVoice)

> Code and machine-readable contracts win; repository scripts are the gates; skills, plugins, MCP
> servers, devices and models never are. **Plans:** `docs/ROADMAP.md` · **Narrative:**
> `docs/development-progress.md` · **Architecture:** `docs/ARCHITECTURE.md` · **Rules:** `.claude/rules/`

## Product and authority

**Vocello** is local-first Qwen3-TTS on MLX in Swift 6: a macOS app with an XPC engine service, an iOS
app with an in-process engine, the `vocello` CLI, Python automation and benchmarks, and a React/Vite
website. No bundled weights or cloud inference; approved assets download from Hugging Face through the
production catalog. Monetization is iOS-only (one StoreKit owner, one export boundary); UI language
belongs to `IOSAppLanguage`, separate from speech and reference languages.

Source-of-truth order: `Sources/` → `project.yml` → `config/` contracts → `scripts/` →
`.github/workflows/` → this file and `.claude/rules/` → other prose. When source or a contract
invalidates documentation, fix the documentation in the same change. Versions and public facts come from
`project.yml` and `config/public-product-facts.json`. Release only on explicit request.

## Commands

```sh
scripts/dev.sh check [--dry-run]     # lint, contracts, selected tests, the native lanes the dirty tree touches
scripts/dev.sh test | py | lint | contracts | ios | status   # one lane at a time (py --lane product|research|darwin)
scripts/dev.sh ci                    # exactly what push CI runs, serially
scripts/dev.sh regen                 # regenerate roadmap render, model catalog, package inventories, charts
./scripts/regenerate_project.sh --fast   # after editing project.yml (never edit the .xcodeproj)
python3 scripts/roadmap.py status    # work authority: open plans and items
```

Consent-bound lanes, never run unasked: `scripts/ui_test.sh <macos|ios> <lane>`, `scripts/ios_device.sh`,
`scripts/macos_test.sh memory|lang-bench`, `.github/workflows/release.yml`.

## Working here

1. `git status --short --branch` (local `main`; preserve dirty work), `python3 scripts/roadmap.py status`,
   then the "Resume now" section of `docs/development-progress.md`.
2. Read the rule that matches your files (`.claude/rules/native.md` for Swift, `release.md` for
   scripts, CI, packaging and benchmarks, `website/CLAUDE.md` for the site), then only the reference
   docs the change needs. Inspect the exact code, tests and contracts before choosing an approach.
3. Make the smallest coherent change; keep module boundaries and stable accessibility identifiers.
4. Run `scripts/dev.sh check`, commit on `main`, push. CI on `main` is the gate; a red push is fixed
   forward or reverted. Update contracts, `config/roadmap.json` and the narrative in the same change
   when behavior or status changes.

Work autonomously within the requested scope with bounded, reversible changes; ask only for missing
authority, consequential product choices, external dependencies or unsafe ambiguity. Release,
publication and device consent are always explicit; ordinary work never needs a model or a phone.

## Hard invariants

| Invariant | Required behavior |
| --- | --- |
| **Main only** | Develop and commit on local `main`; no branches or worktrees. Never force-push. |
| **Physical iPhone only** | No Simulator build, launch or test. `build_foundation_targets.sh ios` is the phone-free generic compile. |
| **One UI driver** | `scripts/ui_test.sh` and checked-in XCUITest own native UI; no computer-use, browser, coordinate, vision or MCP UI routes. |
| **Genuine controls** | No hidden markers, preview routes, seeded UI state or onboarding bypasses in shippable targets. |
| **Generated project** | Edit `project.yml`, never `project.pbxproj`; `scripts/regenerate_project.sh --fast`. |
| **Release-only configuration** | No Debug configuration or `DEBUG` symbol. Production overrides are registered in `config/runtime-debug-knobs.json` behind `VOCELLO_INTERNAL_DIAGNOSTICS` plus `QWENVOICE_DEBUG=1`. |
| **Concurrency and MLX** | Owned unsafe concurrency is registered in `config/concurrency-safety.json`; MLX arrays stay isolated, randomness is request-local, pins move in lockstep, no Core ML. |
| **One lifecycle authority** | Actor-owned lifecycle, typed cancellation, serialized prewarm, frame-bounded suspending audio; phases in `config/runtime-refactor-contract.json`. |
| **Exact model delivery** | The production catalog is generated from `config/model-artifact-receipts.json` and activates only complete, digest-verified artifacts. |
| **Privacy** | Never track PII, private paths, prompts, transcripts, credentials or raw diagnostics; `scripts/privacy_scan.py` enforces it. |
| **Owned output** | `config/build-output-policy.json` owns `build/`; reuse `build/cache/xcode/{macos,macos-tsan,ios-device}`; no ad hoc DerivedData or whole-cache deletion. |
| **Evidence retention** | Only qualified privacy-safe PASS enters `benchmarks/runs/`; raw WAV, telemetry, screenshots and xcresult stay untracked. `rtf` is the standard real-time factor (synthesis wall ÷ audio, lower is faster; `decodeSpeedupX` is the old inverted figure) and `toolchain.optimization` comes from a hash-bound build receipt, never a literal. |
| **Exact-source releases** | Candidates need a GitHub-verified annotated tag on `origin/main` with green `CI required`; `scripts/release_source_authority.py` fails closed and the release workflow runs Security on the tagged commit. |
| **One work authority** | `config/roadmap.json` owns open work and generates `docs/ROADMAP.md`; finished work lives in `config/roadmap-archive.json`. |

## Verification

| Tier | When | What |
| --- | --- | --- |
| Inner loop | while editing | `dev.sh test --only Class`, `dev.sh py --changed`, `dev.sh lint`. The XCUITest bundles compile only inside `scripts/ui_test.sh`; after editing `Tests/*UITests` or `Tests/UIAutomationSupport`, run `xcodebuild build-for-testing` for `VocelloMacUI` and `VocelloiOSUI` (generic iOS destination, unsigned, `-skipPackagePluginValidation`) before committing. |
| Commit | `git commit` | `scripts/hooks/commit_lint.sh`: branch `main`, clean whitespace, no private path or credential in staged files. Nothing else blocks a commit. |
| Push CI | every push to `main` | `.github/workflows/ci.yml`: routed lanes, cached native builds, Linux Python suite, `CI required` aggregate |
| Nightly | 04:00 UTC | TSan subset, complete Python suite, cold compiles of both platforms; opens a `nightly` issue on failure |
| Weekly / release | schedule, tag | `security.yml` (CodeQL, npm audit); `release.yml` (signing, notarization, evidence) |

`./scripts/check_project_inputs.sh` is the deterministic contract gate (product contracts,
`scripts/repo_invariants.sh`, the privacy scan, the Python suite). Serialize native Xcode commands;
never clear caches to evade contention.

## Hooks and assists

`.claude/settings.json` wires `commit_lint.sh`, `policy_guard.sh` (Simulator destinations, whole-cache
deletion, force pushes, new branches, `project.pbxproj` writes), `generated_file_guard.sh` (generated
files), `project_yml_reminder.sh` (regenerate after editing `project.yml`) and `session_start.sh`. Behaviour is pinned by `scripts/tests/test_claude_hooks.py`. Personal
overrides live in the untracked `settings.local.json` under `.claude/`.

Optional assists, verified before relying on them: user-invoked skills `/ios-lane`, `/macos-ui-lane`,
`/device-diagnostics`, `/release-evidence`; subagents `swift-review` and `xcresult-triage`; the
XcodeBuildMCP server (profiles `macos` and `ios-device`, scratch builds, never Simulator or UI routes);
`axiom-*` skills and auditors for Apple frameworks, concurrency, testing, accessibility and crashes;
`gh` or the GitHub MCP for runs and releases. Repository invariants win over any assist.

## Explicit frontend acceptance

Only explicit QA scope authorizes `scripts/ui_test.sh` or model and device lanes; follow
`docs/reference/testing-runbook.md`. iOS lanes need an Apple Development identity and an unlocked paired
iPhone; preserve all user data. Runner PASS requires diagnostics, crash deltas and restoration, not just
XCTest success; no retries, a failed run keeps its artifacts, and changed source needs new run IDs.

## Security and release summary

macOS: protected tag → verified draft → notarized DMG via `.github/workflows/release.yml`. iOS: optional
TestFlight archive; identity from `project.yml`. Website: Vercel rooted at `website/`. Security posture in
`SECURITY.md`; boundaries in `docs/ARCHITECTURE.md` and `docs/reference/privacy-storage.md`.
