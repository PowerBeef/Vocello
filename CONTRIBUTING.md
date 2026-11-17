# Contributing to Vocello

Thank you for helping improve Vocello. This guide is the human contribution path. Claude Code,
the repository's coding agent (a lead session on `main`, optionally with parallel agents in
integrated worktrees), follows [`CLAUDE.md`](CLAUDE.md) and the
[development workflow](docs/reference/development-workflow.md).

## Before starting

- Use an Apple Silicon Mac with full Xcode (CI pins the version in `config/toolchain.json`) and set
  it up with [New Mac setup](docs/reference/development-workflow.md#new-mac-setup): Xcode
  components, the pinned command-line tools, Python and Node. The no-phone
  `-destination generic/platform=iOS` compile needs the selected Xcode's iOS platform component; it
  never authorizes Simulator testing.
- Read the current checkpoint in [`docs/development-progress.md`](docs/development-progress.md).
- Check existing [issues](https://github.com/PowerBeef/Vocello/issues) and pull requests before starting overlapping work.
- Keep changes focused. Do not mix unrelated refactors into a bug fix or feature.

Models, a physical iPhone, and UI automation are not required for ordinary source changes. They are needed only for the explicit model or frontend acceptance lane being exercised.

## Build and verify

Repository scripts are the authoritative interface:

```sh
scripts/dev.sh check                     # lint, contracts, selected tests, the native lanes the dirty tree touches
./scripts/regenerate_project.sh --fast   # after editing project.yml (never edit the .xcodeproj)
scripts/dev.sh ci                        # every gate push CI runs, serially (no lane skipped by routing)
```

`scripts/dev.sh check` is advisory: it routes the dirty tree into the Python, native and website lanes
without scheduling model generation, UI acceptance or release operations. The commit lint is the only
local block and CI on `main` is the gate. Use the [development workflow](docs/reference/development-workflow.md)
for the single-lane commands and cache policy. State exactly what ran and any deferred acceptance in the pull request.
`CI required` runs on every push to `main` and on pull requests against `main`. A pull request runs
only the Linux jobs (contracts, Python, website) with a read-only token and no secrets; the macOS
lanes run when a maintainer pushes the change to `main`. Jobs skipped by path routing (for example
docs-only changes) count as passing, and a red push is fixed forward or reverted.

The Xcode project is generated from [`project.yml`](project.yml). Never edit `QwenVoice.xcodeproj/project.pbxproj` directly. Native output belongs under the paths declared by [`config/build-output-policy.json`](config/build-output-policy.json); do not add another DerivedData root or a `.build` directory inside vendored source.

## Project layout

```text
Sources/                 the apps and the engine
  QwenVoiceApp.swift       macOS app (Views/, ViewModels/, Services/)
  iOS/                     iPhone app
  QwenVoiceCore/           engine host: runtime factory, generation, model delivery
  VocelloCLI/              the vocello command line
Packages/VocelloQwen3Core/ the owned Qwen3-TTS runtime on MLX, with its own tests
Tests/                   unit and iPhone logic tests, Mac and iPhone UI tests
scripts/                 build, test, benchmark and release lanes, and the README art generator
config/                  machine-readable contracts: models, privacy, release, roadmap
benchmarks/              published benchmark records and the optimization ledger
website/                 vocello.vercel.app (React and Vite)
docs/                    architecture, references, audits, release notes, README images
```

## Platform and UI rules

- macOS and iOS application UI acceptance uses XCUITest only.
- iOS runtime and UI work uses a paired physical iPhone. Simulator is not supported for Vocello.
- UI suites run only when frontend acceptance is explicitly needed:

```sh
scripts/ui_test.sh macos smoke
scripts/ui_test.sh ios smoke
```

- Preserve stable accessibility identifiers on real visible controls.
- Do not add hidden test routes, seeded production UI, invisible markers, fixed-coordinate actions, or fixed sleeps.

See [`docs/reference/testing-runbook.md`](docs/reference/testing-runbook.md) for platform lanes and prerequisites.

## Design system

Dark-first, warm neutrals on a charcoal canvas, and one accent per mode. Liquid Glass stays on chrome
and falls back to solid surfaces under Reduce Transparency and while audio generates. The tokens live
in the app's theme and in [`website/src/tokens.css`](website/src/tokens.css).

| Token | Color | Use |
| --- | --- | --- |
| Gold | `#EDCC8A` | Built-in Voice, the brand accent |
| Lavender | `#BFAADB` | Voice Design |
| Terracotta | `#DBA887` | Voice Cloning |
| Charcoal | `#16181E` | The canvas |
| Text | `#F5F6F8` | Primary text |

The README's images are generated, never drawn by hand: `python3 scripts/generate_readme_charts.py`
writes every SVG under `docs/readme/` from these tokens (`scripts/lib/readme_art.py`), the app's launch
lockup, the benchmark records and `config/public-product-facts.json`, and `--check` fails when one is
stale. The screenshots under `docs/screenshots/` come from the marketing capture lane
(`scripts/ui_test.sh macos marketing`).

## Source and documentation expectations

- Code and machine-readable contracts take precedence over prose.
- Update relevant documentation in the same change when behavior, public facts, commands, platform support, models, or test contracts change.
- Keep dated run details in preserved evidence/checkpoints, not general instructions. During a frozen acceptance campaign, record progress untracked; a deliberate source/documentation checkpoint creates a new acceptance identity.
- Keep dependencies pinned. MLX dependency changes require the backend review and benchmark process in the [native engineering rules](docs/reference/native-engineering.md).
- Keep external Actions pinned to the full SHA in [`config/toolchain.json`](config/toolchain.json).
  Dependabot proposals must update that manifest and the adjacent workflow version comment together.
- Do not commit prompts, transcripts, usernames, device identifiers, absolute paths, secrets, raw telemetry, WAV evidence, screenshots from test results, traces, or `.xcresult` bundles.
- Successful benchmark runners publish only their compact privacy-safe record. They never commit or push it automatically.

## Pull request checklist

- [ ] The change has one clear purpose.
- [ ] The Xcode project was regenerated after a `project.yml` or file-membership change.
- [ ] `scripts/dev.sh check` ran, and the pull request says what it skipped.
- [ ] Public facts and active documentation match the implementation.
- [ ] No generated build output or private evidence is tracked.
- [ ] The pull request explains test coverage and any intentionally deferred device, model, or UI acceptance.

For architecture and ownership, use [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the [native engineering rules](docs/reference/native-engineering.md). Security-sensitive reports should use GitHub's [private security advisory form](https://github.com/PowerBeef/Vocello/security/advisories/new).
