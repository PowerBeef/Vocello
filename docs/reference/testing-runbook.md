---
status: active
owner: release-qa
summary: The cross-platform testing runbook — deterministic lanes as the routine contract, explicit XCUITest acceptance, model readiness, and the authority order for test guidance.
sourceOfTruth:
  - scripts/check_project_inputs.sh
  - scripts/macos_test.sh
  - scripts/ios_device.sh
  - scripts/ui_test.sh
---
# Testing runbook

Authority is `Sources/` → `project.yml` → repository scripts → this document. Deterministic checks
are the routine development, CI, and packaging contract. XCUITest is the sole autonomous app UI
driver and is reserved for explicit frontend acceptance.

## Routine development matrix

| Platform | Required for development/CI/release packaging | Explicit UI lanes |
| --- | --- | --- |
| macOS | `scripts/macos_test.sh test` + `./scripts/build.sh build` | `scripts/ui_test.sh macos smoke|benchmark` |
| iOS | `./scripts/check_project_inputs.sh` + `./scripts/build_foundation_targets.sh ios` | `scripts/ui_test.sh ios smoke|benchmark` on a paired physical iPhone |

No UI lane, model download, paired phone, or UI result is mandatory for ordinary development
publishing.

The no-phone iOS compile still requires matching iOS Platform Support/runtime availability in the
selected Xcode installation. `scripts/lib/ios_platform_preflight.py check` validates that external
toolchain prerequisite before package resolution and never runs or authorizes a Simulator. Repair
and interpretation are documented in [iOS physical-device testing](ios-device-testing.md#host-toolchain-prerequisite).

## Storage preflight and retention

Heavy commands read their host free-space floor from `config/build-output-policy.json` and stop
before starting another build, target, or evidence bundle when the floor is not met. The message
points to `python3 scripts/build_output_policy.py status` and one bounded cleanup command. This is a
capacity check for an explicitly selected lane, not a new development or publishing gate.

`scripts/clean_build_caches.sh --routine --dry-run` previews scratch and lifecycle-safe evidence
cleanup. `--prune-ui-results` keeps the latest pass and unresolved failure per platform/lane,
preserves exact publication-repair evidence, and compacts resolved failures. Use a selective
`--cache macos|ios|packages|runtime` only when that specific persistent cache must be rebuilt.
Cleanup never runs globally after an ordinary successful build, because another process may still
own a managed scratch/cache root.

## macOS

```sh
./scripts/check_project_inputs.sh
scripts/macos_test.sh test
./scripts/build.sh build

# Deterministic/runtime diagnostic; independent of XCUITest
scripts/macos_test.sh gate

# Explicit frontend acceptance only
scripts/ui_test.sh macos smoke
scripts/ui_test.sh macos benchmark
# Filtered benchmark example
scripts/ui_test.sh macos benchmark --modes custom --lengths short --warm 1 --label "focused"
```

## iOS

```sh
./scripts/check_project_inputs.sh
./scripts/build_foundation_targets.sh ios

# Physical-device diagnostics; independent of XCUITest
scripts/ios_device.sh preflight
scripts/ios_device.sh gate

# Explicit frontend acceptance only; never Simulator
scripts/ui_test.sh ios smoke
scripts/ui_test.sh ios benchmark
# Filtered benchmark example
scripts/ui_test.sh ios benchmark --modes custom --lengths short --warm 1 --label "focused"

# Opt-in three-artifact background-session restoration proof (~1.7 GB Custom full-wire,
# then Design and Clone with shared-component reuse); isolated data, genuine Settings controls
scripts/ui_test.sh ios model-download
```

Both benchmark commands accept `--modes`, `--lengths`, `--warm`, and `--label`. Without filters,
each runs the canonical 29-take matrix. Filtered runs are targeted diagnostics, not substitutes for
the full matrix when full frontend benchmark acceptance is explicitly requested.

`ios model-download` is not a third routine UI lane. It selects one isolated physical-device test
directly, backgrounds and relaunches the app during transfer, checks adopted progress, installs
Custom full-wire and then Design and Clone with mandatory shared-component reuse, validates
per-artifact wire-byte accounting and the throughput floor, and deletes all three isolated models
through Settings. It never runs in ordinary CI or release.
See [`model-delivery.md`](model-delivery.md).

## Model readiness

Generation UI tests inspect Settings and require Custom, Design, and Clone Speed to be ready,
Generate to be enabled, and the benchmark clone voice to exist before a take begins. On macOS,
use `scripts/macos_test.sh models ensure` or `scripts/macos_test.sh models install` only for explicit
repair/bootstrap after that visible check fails. On iOS, install or repair models only through
the visible Settings → Voice models section. Restart the affected UI lane after either repair.

## Evidence

XCTest assertions, activities, attachments, and `.xcresult` bundles own UI truth. Benchmark
validators own exact take counts/order plus matching telemetry, History/database, readable-WAV, and
audio-QC proof. The runner owns app/device identity and crash deltas. Smoke intentionally stops at
its visible journey, History assertion, and crash check rather than claiming benchmark evidence.

## ML-backed QA analyzers (operator-local)

The advisory analyzers (`scripts/emotion_advisory.py` SER column,
`scripts/clone_speaker_similarity.py` ECAPA identity, both consumed by
`scripts/clone_fidelity_lane.py`) run under the repo `.venv` with a one-time
operator install — never CI, never a packaging input:

```sh
python3 -m venv .venv
.venv/bin/pip install torch transformers speechbrain
```

Model identities are revision-pinned in the scripts (SER:
`firdhokk/speech-emotion-recognition-with-facebook-wav2vec2-large-xlsr-53`;
ECAPA: `speechbrain/spkrec-ecapa-voxceleb`), download on first use, and fail
closed on checkpoint drift or missing classifier weights. **8 GB rule** (dev
machine = canonical Mac mini M2 8 GB): ML analyzers run strictly after the
generation process exits — never concurrent with the resident engine — and
each analyzer records its measured peak RSS in its report (SER ≈ 2.4 GB).
Unit tests inject fake classifiers/embedders, so the deterministic suites
never import torch.

`scripts/mos_advisory.py` (CM-6) adds a naturalness MOS-proxy column with the
same advisory semantics: UTMOSv2 pinned by git commit and weights SHA-256
(fail-closed on drift), CPU-only, peak RSS recorded (≈ 3.6 GB — schedule
accordingly on the 8 GB floor). Install with
`.venv/bin/pip install "utmosv2 @ git+https://github.com/sarulab-speech/UTMOSv2.git@cc2700db57bb83ee13dc31ebe1b868c254e15d09"`;
the library's own weight downloader shells out to `wget` (absent here), so
fetch the pinned checkpoint with
`curl -sL -o ~/.cache/utmosv2/models/fusion_stage3/fold0_s42_best_model.pth https://huggingface.co/sarulab-speech/UTMOSv2/resolve/main/fold0_s42_best_model.pth`.
Treat the column as relative signal only (take-vs-take, instructed-vs-neutral,
build-vs-build): a synthetic-speech MOS predictor is domain-shifted for this
engine's audio, and the score is never a gate or a publication input.

## Listening calibration session (operator-local)

`scripts/delivery_listening_session.py` builds, runs, and scores the blind
delivery listening session recommended by the 2026-08-04 delivery-control
audit: `build` assembles opaque-ID trials from `vocello bench` evidence
archives (`outputs/bench-archive/<runID>`) plus optional clone-transfer
clips, `run` plays them with `afplay` and records answers resumably, and
`score` feeds the answers through `scripts/delivery_identification_check.py`
and evaluates the pre-registered exact-binomial decision rules. Listening
stays calibration, never a gate: no CI lane, benchmark record, or promotion
decision consumes the session report automatically.

## Fail-closed orchestration

The macOS gate and release-readiness command, the iOS gate, and every XCUITest lane write an
untracked `required-steps.json` beside their other run artifacts. The expected steps come from
`config/orchestration-contract.json`; final PASS is impossible while a required step is failed,
missing, duplicated, interrupted, or unknown. Optional retention cleanup cannot replace a failed
validator result.

The deterministic negative suite forces every declared required step to fail in isolation:

```sh
python3 -m unittest scripts.tests.test_required_step_ledger
```

Fault injection is test-only and requires both `QWENVOICE_TEST_ORCHESTRATION_FAULTS=1` and an exact
`QWENVOICE_TEST_FAIL_REQUIRED_STEP=<workflow>:<step>` selector. Normal workflows never enable it.

Release-candidate orchestration adds a stricter boundary. Its schema-v2 release evidence captures a
clean full-tree source identity, requires the platform steps to run as managed subprocesses in one
invocation using the command templates in `config/orchestration-contract.json`, and packages the
ledger plus step manifests into hashed `release-verification.json`. A successful substitute such as
`true` cannot mint a required-step result. Contract-declared step outputs are hashed when the managed
command completes and rechecked during evidence creation, so a verifier summary cannot be replaced
between verification and publication. The iOS candidate first runs `scripts/macos_test.sh gate`
and the generic physical-device SDK compile as its managed `platform-readiness` step, then requires
the archive/IPA identity and signing summary described in `ios-appstore-submission.md`.
The six-hour freshness rule applies when creating a candidate; offline verification of the copied
bundle rechecks identity, structure, outcomes, and digests without pretending the original clock is
still current.

For an inventory of direct tests, unsafe-concurrency annotations, canonical hardware evidence, and
path-based evidence freshness, generate the local project-health report:

```sh
python3 scripts/project_health.py report --output build/artifacts/project-health/current
```

The compact tracked snapshot is [`../project-health.md`](../project-health.md). It is an engineering
inventory, not a test result or release-readiness verdict; it never makes physical-device evidence
an ordinary development gate.

## CI and release

Ordinary CI builds app targets and runs deterministic checks; it neither compiles nor executes the
isolated UI-test bundles.
Release packaging uses deterministic build, test, signing, identity, crash, entitlement, and artifact
checks. XCUITest results may accompany an explicit frontend review, but missing or stale UI results
never block signing, notarization, a macOS package, or an iOS archive/TestFlight build.

## Artifacts

Raw result bundles, exported screenshots, telemetry, databases, WAVs, and traces remain ignored
build artifacts. Compact benchmark summaries must contain no user data. A failed Instruments run
keeps the newest raw trace per platform/profile kind unless it is explicitly pinned; superseded
failures are reduced to the required retention metadata plus at most 8 MiB of allowlisted auxiliary
diagnostics, with individual logs capped at 1 MiB.
