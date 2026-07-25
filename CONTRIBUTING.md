# Contributing to Vocello

Thank you for helping improve Vocello. This guide is the human contribution path. Repository
automation and coding agents use the additional durable instructions in [`CLAUDE.md`](CLAUDE.md).

## Before starting

- Use an Apple Silicon Mac with Xcode 26. The selected Xcode must expose usable iOS Platform
  Support and a compatible iOS runtime component for the no-phone `generic/platform=iOS` compile;
  this toolchain prerequisite does not authorize Simulator testing.
- Read the current checkpoint in [`docs/development-progress.md`](docs/development-progress.md).
- Check existing [issues](https://github.com/PowerBeef/Vocello/issues) and pull requests before starting overlapping work.
- Keep changes focused. Do not mix unrelated refactors into a bug fix or feature.

Models, a physical iPhone, and UI automation are not required for ordinary source changes. They are needed only for the explicit model or frontend acceptance lane being exercised.

## Build and verify

Repository scripts are the authoritative interface:

```sh
./scripts/regenerate_project.sh        # required after project.yml changes
./scripts/check_project_inputs.sh
scripts/macos_test.sh test
./scripts/build.sh build
./scripts/build_foundation_targets.sh ios
```

The final four deterministic commands are sufficient for ordinary pull requests. Run only the checks relevant to the files you changed, then state exactly what you ran in the pull request.
Pull requests need the single green `CI required` check; jobs skipped by
path routing (for example docs-only changes) count as passing.

The Xcode project is generated from [`project.yml`](project.yml). Never edit `QwenVoice.xcodeproj/project.pbxproj` directly. Native output belongs under the paths declared by [`config/build-output-policy.json`](config/build-output-policy.json); do not add another DerivedData root or a `.build` directory inside vendored source.

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

## Source and documentation expectations

- Code and machine-readable contracts take precedence over prose.
- Update relevant documentation in the same change when behavior, public facts, commands, platform support, models, or test contracts change.
- Keep dependencies pinned. MLX dependency changes require the backend review and benchmark process in [`.claude/rules/backend-mlx.md`](.claude/rules/backend-mlx.md).
- Keep external Actions pinned to the full SHA in [`config/toolchain.json`](config/toolchain.json).
  Dependabot proposals must update that manifest and the adjacent workflow version comment together.
- Do not commit prompts, transcripts, usernames, device identifiers, absolute paths, secrets, raw telemetry, WAV evidence, screenshots from test results, traces, or `.xcresult` bundles.
- Successful benchmark runners publish only their compact privacy-safe record. They never commit or push it automatically.

## Pull request checklist

- [ ] The change has one clear purpose.
- [ ] `project.yml` was regenerated if needed.
- [ ] Relevant deterministic checks pass.
- [ ] Public facts and active documentation match the implementation.
- [ ] No generated build output or private evidence is tracked.
- [ ] The pull request explains test coverage and any intentionally deferred device, model, or UI acceptance.

For architecture and ownership, use [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the [domain rules](.claude/rules/). Security-sensitive reports should use GitHub's [private security advisory form](https://github.com/PowerBeef/Vocello/security/advisories/new).
