---
status: historical
owner: release-qa
summary: Point-in-time repository-wide audit of Vocello autonomous tests, benchmarks, voice-output analysis, evidence promotion, website validation, and release verification on 2026-08-21.
contentDigest: sha256:d2f6b05d044e602215f3c436ff3802ff42bfa9b54c07439e38a49bc9b26f8eae
---
# Vocello Autonomous Validation Audit — 2026-08-21

This report is a descriptive, point-in-time audit of commit
`2db998ce0e43c447fea6841435b5c95d2f77aac2` plus the maintainer's uncommitted iOS
Settings work present on `main` during the review. It does not authorize a release, publish a
benchmark, change a model installation, or replace any live contract. Source, `project.yml`, the
machine-readable contracts, and `config/roadmap.json` remain authoritative.

## Executive assessment

Vocello's autonomous validation system is unusually broad and generally fail-closed. It covers
deterministic source contracts, Swift core/XPC/runtime tests, generic iPhoneOS compilation,
physical-device XCUITest, production-path generation, PCM quality, memory, UI frame health,
benchmark provenance, evidence promotion, packaging, signing, notarization, supply chain, and
website rendering. Raw evidence is kept out of Git, compact records are digest-bound, and public
promotion is separated from ordinary deterministic publication.

The aggregate audit score is **82/100**, the arithmetic mean of the seven subsystem scores below.
There is no confirmed P0. Three P1 root causes can nevertheless combine into a public-promotion
false green: the curated Python lane is not complete, the evidence-impact classifier sends many
production and analyzer authorities to `repository-other`, and the minimum promotion matrix is
Speed-tier English UI generation even when a change affects Quality, language, delivery, or an
analyzer. Eight lower-severity roots reduce trend strength, calibration validity, device-lane
availability, and web-interaction coverage.

| Subsystem | Score | Principal deductions |
| --- | ---: | --- |
| Deterministic tests | 71 | AV-01 P1; existing F-03 P2; existing F-14 P3; AV-11 P3 |
| UI and device automation | 92 | AV-09 P2 |
| Performance benchmarks | 76 | AV-04, AV-05, and AV-06 P2 |
| Voice-output analysis | 84 | AV-07 and AV-08 P2 |
| Evidence and promotion | 70 | AV-02 and AV-03 P1 |
| Website validation | 97 | AV-10 P3 |
| Release verification | 85 | existing F-05 P1 |

Scores start at 100 and deduct 25/15/8/3 for independent P0/P1/P2/P3 root causes. Compound
consequences are not deducted twice. Cross-referenced F items remain in the engineering-review
plan rather than being duplicated as AV work.

## Scope and method

The audit followed every active result through this chain:

```text
test or generation
  -> raw evidence and source identity
  -> validator / quality composition
  -> compact privacy-safe record
  -> benchmark history, promotion, release, or human decision
```

The inspected authorities included `project.yml`, all workflows under `.github/workflows/`, the
three platform drivers, the repository and website gates, 446 Swift XCTest methods, 77 Python test
modules, seven Node tests, 270 benchmark records, benchmark schemas, language/delivery/prosody
configuration, the evidence-impact and promotion contracts, release ledgers, and the current
testing/benchmarking documentation. No new model output was generated because source, tracked
records, negative fixtures, and existing device evidence resolved every possible P0/P1 question.

Confidence labels mean:

- **source-proven:** the result follows directly from active code or machine-readable contracts;
- **fixture-reproduced:** a checked-in positive/negative fixture exercised the behavior;
- **live-reproduced:** an actual discovery, test, build, or device run demonstrated it.

## Complete harness and evidence inventory

The following table identifies the active autonomous harness families. “Raw” means local evidence
that remains untracked; “compact” means an allowlisted record that may be tracked after validation.

| Owner / family | Entry point and prerequisites | Production path and isolation | Artifact contract / validator | Decision consumer |
| --- | --- | --- | --- | --- |
| release-qa / project inputs | `./scripts/check_project_inputs.sh`; Python, `rg`, pinned local tools | Static repository inputs; fixture temp directories | Per-contract stdout verdicts; 906 curated Python tests in full mode; no persistent raw data | T1/T2 merge and release input validity |
| release-qa / Python discovery | `python3 -m unittest discover -s scripts` and `-s scripts/tests`; no models | Contract modules in isolated temporary directories | unittest exit status; negative/tamper fixtures for digests, rows, identities, warnings, thresholds, and stale evidence | Audit completeness; not currently the canonical curated gate |
| backend-and-platform / Swift deterministic | `scripts/macos_test.sh test`; macOS, Xcode, locked SwiftPM cache | `VocelloCoreTests`, injectable XPC transport integration, and owned Qwen3 runtime seeded Metal fixtures | `.xcresult`, logs, dSYMs, explicit four-part verdict under `build/artifacts/macos/tests/` | T2 native verdict and release readiness |
| ios / iPhoneOS compile policy | `./scripts/build_foundation_targets.sh ios`; Xcode iPhoneOS platform | Real app and `VocelloiOSLogicTests` compile for `generic/platform=iOS`; no Simulator and no execution | Xcode build result in governed scratch/cache roots | T2 compile safety; existing F-03 covers the missing assertion execution |
| macos / visible XCUITest | `scripts/ui_test.sh macos smoke|benchmark|perf`; built app, models when generation is used | Shipping app and XPC service, visible controls only, stable identifiers, run-scoped artifacts | `.xcresult`, screenshots, crash baseline/delta, telemetry, UI/perf or generation evidence; no automatic retry | Explicit frontend acceptance; benchmark/perf records when canonical |
| ios / visible XCUITest | `scripts/ui_test.sh ios smoke|benchmark|perf|model-download|saved-voice-lifecycle`; paired physical iPhone | Shipping app on a real device; model-download and saved-voice lanes are isolated opt-ins | `.xcresult`, screenshots, pulled diagnostics, crash checks, source provenance; no automatic retry | Explicit device acceptance and eligible benchmark/perf evidence |
| ios / headless device diagnostics | `scripts/ios_device.sh bench|lang-bench|memory|clone-conditioning|profile`; paired phone, signing, relevant models | In-process iOS engine through `IOSDeviceDiagnosticsRunner`; run sentinel and App Group mirror | Pulled telemetry, completion sentinel, quality/memory/profile validators; privacy-safe compact manifests | Diagnostic, benchmark, memory, language, and clone decisions |
| macos / CLI engine benchmark | `vocello bench` or bounded `scripts/macos_test.sh gate` opt-in; installed Speed fixtures | In-process CLI engine with isolated runtime data root, fixed seeds, cold/warm matrix | JSONL telemetry, `bench-results.json`, WAV/output sidecars, summary and history publisher | Focused engine correctness/performance and optional promotion evidence |
| release-qa / UI generation benchmark | `scripts/ui_test.sh macos|ios benchmark`; canonical hardware for publication | Production UI and app/XPC or in-process engine; Custom/Design/Clone | XCUITest result plus run-scoped generation sidecars; `publish_benchmark_history.py` and history schema | Platform-minimum public promotion evidence |
| backend-mlx / language matrix | `scripts/macos_test.sh lang-bench` or `scripts/ios_device.sh lang-bench`; speech assets as applicable | Production generation with pinned/Auto language hints; six-language matrix | ASR consensus, script/hint checks, language record validator; diagnostic cohort never publishes | Advisory/focused language evidence, not platform-minimum promotion |
| backend-mlx / delivery cohort | delivery bench commands and `scripts/ui_test.sh ios delivery-cohort`; models and fixed prompt/seed protocol | Neutral-vs-instructed delivery takes through CLI/UI; run-scoped paired cells | PCM/prosody/delivery reports, seed-grouped cross-validation, permutation tests, BH-FDR, results ledger | Delivery-rule calibration and advisory/promotion input when explicitly applicable |
| backend-mlx / PCM quality composition | shipping `AudioQualityGate`, `GenerationQualityReportProducer`, `summarize_generation_telemetry.py`, ASR and continuity checkers | Every finalized take gets fast QC; deeper analyzers consume exact WAV/sidecar identity | Schema-v3 quality identity; fast/deep/canonical gate composition; fail-closed required analyzer set | Generation acceptance, benchmark warnings/failures, promotion eligibility |
| backend-mlx / prosody calibration | `scripts/prosody_calibration.py`, `analyze_prosody.py`, `prosody_profile.py` | Labeled WAV corpus and per-take delivery/prosody features | Versioned profile JSON, calibration summary, per-take flags | Prosody warnings and delivery evidence; calibration validity remains limited |
| backend-mlx / advisory ML analyzers | `mos_advisory.py`, SER and speaker-similarity tools; pinned weights where used, run after generation | Local archived WAVs; CPU and memory scheduling constraints | Relative scores with explicit `gate:false`; digests and resource use recorded | Human/research interpretation only; never promotion authority by themselves |
| performance / retained memory | `scripts/macos_test.sh memory`, `scripts/ios_device.sh memory`; canonical hardware and models | Custom→Design→Clone retained sequence; telemetry v8/v9 lifecycle and wired-memory facts | Coverage/pressure/forced-unload policy, marking peak equality, compact memory-qualification record | Path-relevant promotion and memory safety |
| performance / UI frame health | `scripts/ui_test.sh macos|ios perf`; canonical hardware for publication | Visible workload markers around navigation, scrolling, typing, sheets, and active generation | Exact scenario markers, probe coverage, cadence/hitch thresholds, environment snapshot | UI-performance record and path-relevant promotion |
| performance / Instruments profile | `scripts/macos_test.sh profile`, `scripts/ios_device.sh profile`; exact PID and explicit opt-in | CLI engine or physical-device process under xctrace | Trace digest, source/probe manifest, compact summary; raw trace removed unless explicitly retained | Diagnostic attribution; instrumented records are not canonical baselines |
| performance / telemetry overhead | `scripts/macos_test.sh telemetry-overhead`; models and counterbalanced rotations | Same seeded generation with telemetry off/lightweight/verbose | Local verdict with RTF/TTFC deltas; intentionally not history-eligible | Diagnostic overhead budget |
| release-qa / benchmark registry | `python3 scripts/benchmark_history.py record|validate|rebuild-index` | Accepts only validated compact evidence from an already successful run | Immutable JSON schema v1-v3, clean source fingerprints, privacy allowlist, digest, generated history | PASS-only benchmark history and promotion lookup |
| release-qa / evidence impact | `python3 scripts/evidence_impact.py classify`; changed paths | Static routing from paths to deterministic, quality, and promotion requirements | `config/evidence-impact.json` plus contract self-tests | Required evidence plan for merge/release/promotion |
| release-qa / quality promotion | `quality_promotion.py capture|create|validate`; exact tag and release evidence | Reads source-bound records and managed-command receipts; does not generate quality itself | Seven-day freshness, canonical hardware, tag/source/build/digest/warning checks | Only authority that can permit public macOS release or external iOS promotion |
| release-qa / release evidence | `release_evidence.py`, `required_step_ledger.py`, `release.sh`, bundle/DMG verifiers | Clean exact tag; signed/notarized app, XPC, CLI, archive, or IPA | Schema-v2 evidence, hashed verification, managed subprocess, SBOM, UUID/entitlement/signature/notary continuity | Draft candidate creation, internal TestFlight, and promotion input |
| security / supply chain | `security.yml`, `supply_chain_contract.py`, dependency snapshot, CodeQL, npm audit | Source/dependency metadata; no product runtime mutation | Pinned tools/actions, lockfile identities, dependency review, CodeQL, SBOM/attestation | Security posture and candidate provenance |
| website / source and SSR | `npm --prefix website run check`; Node/npm pins | Source contract, seven Node tests, React SSR render, Vite client/SSR builds, prerender | Static/source assertions, rendered markup accessibility contract, `dist`/`dist-ssr` build | Website CI and deploy eligibility |

### Test-discovery reconciliation

| Population | Modules/files | Tests observed | T1/T2 status |
| --- | ---: | ---: | --- |
| Swift XCTest | 61 files | 446 `test...` methods | macOS core/XPC/runtime execute; UI tests explicit; iOS logic compiles only |
| Python top-level `scripts/test_*.py` | 9 modules | 105 unittest tests | Executed by the full project gate |
| Python `scripts/tests/test_*.py` | 68 modules | 879 unittest-discovered tests plus 10 pytest-only functions | Curated gate executes 801 unittest tests; 78 tests in ten modules and the pytest-only module are omitted |
| Website Node | 2 files | 7 tests | Executed by `npm run check` |

Full `scripts/tests` discovery passed 879 tests. Full project input validation passed 906 curated
tests because it combines the 105 top-level tests with 801 explicitly listed submodule tests. The
counts are therefore internally consistent but the curated lane is incomplete by design accident,
not by documented classification.

## Coverage matrices

### Product and platform paths

| Path | Deterministic ordinary CI | Explicit live lane | Promotion-capable evidence | Material blind spot |
| --- | --- | --- | --- | --- |
| macOS app | Core compile/tests and build | smoke, benchmark, perf | UI generation, UI perf | Packaged launch skipped in release workflow (F-05) |
| macOS XPC engine | Injectable transport + runtime tests | app UI, crashes, profile | UI/engine/memory | No scheduled TSan (F-14) |
| CLI | Version contract and compile through builds | bench, models, telemetry/profile | engine/memory when qualified | Engine perf records use `-Onone` |
| iOS app | Generic iPhoneOS compile | physical-device XCUITest only | UI generation, UI perf | No ordinary execution of iOS logic assertions (F-03) |
| iOS in-process engine | Shared core tests + iPhoneOS compile | headless bench/language/memory/profile | engine/memory | Device/model availability and state isolation cost |
| Website | Source, SSR markup, builds | manual browser inspection only | none | No real browser hydration/interaction matrix |

### Generation and quality population represented by canonical evidence

| Dimension | Canonical UI generation | Specialized evidence | Unsupported inference |
| --- | --- | --- | --- |
| Model tier | Speed | Quality can be invoked on macOS in selected diagnostics | Public promotion does not establish Quality-tier parity |
| Modes | Custom, Design, Clone | Same three in engine/memory/delivery subsets | No population claim across arbitrary saved voices or design briefs |
| Length | Short, medium, long | Focused engine/memory often medium | Long-form project/segment diversity is not a benchmark population |
| Warm state | Cold and warm cells where matrix specifies | Memory uses ordered retained transitions | Arbitrary cache/thermal histories are not represented |
| Language | English fixed corpus | Six-language language matrix | Canonical promotion is not multilingual evidence |
| Speakers/voices | One built-in speaker, one design fixture, one clone fixture | Language uses mostly one speaker; delivery has fixed personas | Speaker and clone population coverage is not established |
| Seeds | Fixed reproducible seeds; warm repetitions | Delivery uses grouped seed analysis | Repetition is not independent speaker/script evidence |
| PCM defects | Fast QC on every finalized take | ASR, continuity, prosody, delivery when applicable | MOS/SER/similarity remain advisory |
| Accessibility | Smoke walks and Settings evidence at selected Dynamic Type sizes | VoiceOver identifiers/semantics asserted in UI/source tests | Not platform-minimum promotion evidence and not every screen/state combination |

### Voice-analysis validity

| Analyzer | Input integrity | Calibration / uncertainty | Gate status |
| --- | --- | --- | --- |
| PCM fast QC | Exact finalized PCM/WAV, nonfinite/clipping/click/dropout/silence checks | Deterministic thresholds and negative fixtures | Required fast gate |
| ASR / WER / CER | Locale-locked transcription of exact generated WAV | Three passes check analyzer stability but are not independent generations | Required only in applicable language/promotion protocols |
| Long-form continuity | Segment/join sidecars and exact output identity | Deterministic structural/acoustic checks | Applicable deep/canonical gate |
| Prosody | Exact WAV features and versioned profile | Current tracked calibration is four clips, dirty source, 50% TPR, no holdout | Warning/advisory until independently validated |
| Delivery adherence | Paired neutral/instructed rows, signed expectations | 272-row calibration, seed-group CV, permutation tests, BH-FDR | Promoted rule, usually warning-first |
| Separability | Fixed delivery roster and acoustic features | Permutation-null evidence; does not imply human emotion identity | Research/diagnostic |
| Speaker similarity | Generated/reference embeddings | Reference and domain limitations documented | Advisory |
| MOS proxy / SER | Pinned model/weights and exact WAVs | Domain shifted; relative evidence only | Explicitly `gate:false` |
| Clone fidelity | Fixed enrolled voice, transcript-backed/x-vector checks, similarity | One principal fixture is not a clone population | Diagnostic/advisory beyond basic lifecycle and PCM gates |
| Publication marking | Exact WAV/chunk and zero-new-peak memory checks | Deterministic marking identity and equality policy | Required where applicable |

## Findings

### P1 — AV-01: curated Python execution is not discovery-complete

**Confidence:** live-reproduced. **Affected decision:** T1/T2 deterministic green.

There are 68 modules under `scripts/tests`. The manually curated invocation omits eleven modules:
ten contain 78 unittest tests, and `test_compare_baseline.py` contains ten pytest-style free
functions that unittest discovers as zero tests. The omitted modules cover characterization
controls, marking equality, generated schemes/charts, iOS download cancellation, release evidence,
runtime security, secret-sauce cells, and iOS release artifacts.

The omission is not harmless redundancy. Direct `pytest` execution of
`test_compare_baseline.py` produced **3 failed, 7 passed**. The production comparator and active
documentation correctly define higher RTF as better; three stale tests assert the opposite. The
full project gate still reported 906/906 PASS because it never invoked this module.

**Remediation gate:** replace or mechanically verify the curated module list so every tracked test
is executed or explicitly classified; run pytest-style modules with their actual runner; fail when
a test module discovers zero tests unexpectedly; add a self-test that introduces an unlisted
module and proves T1/T2 reject it.

### P1 — AV-02: evidence-impact routing has material `repository-other` holes

**Confidence:** source-proven. **Affected decision:** path-relevant quality and promotion evidence.

The classifier has only nine explicit path classes and a permissive fallback requiring project
inputs but no quality or promotion evidence. A full tracked-path classification placed 852 paths in
`repository-other`, including 176 paths below `Sources/` or `Packages/`, 187 scripts, and 22 config
files. Examples with direct quality or promotion authority include:

- `Sources/Services/AudioQualityGate.swift` and the iOS counterpart;
- `Sources/SharedSupport/Services/GenerationOutputVerifier.swift`;
- `Sources/VocelloCLI/BenchCommand.swift`;
- `Sources/iOS/IOSDeviceDiagnosticsRunner.swift`;
- `scripts/analyze_prosody.py`, `analyze_delivery.py`, language checkers, and quality gates;
- language, delivery, marking, promotion, and release-evidence configuration;
- nested iOS UI files such as `Sources/iOS/Settings/VoiceModelsScreen.swift`.

The current uncommitted Settings files classify only as `repository-other`, so even a material UI
change does not request the platform UI-performance evidence the classifier claims to own.

**Remediation gate:** classify every production UI, engine, audio-quality, analyzer, benchmark,
evidence, and promotion-authority path; add representative positive and negative fixtures; reject
an unexplained fallback for designated critical roots; report fallback counts in project health.

### P1 — AV-03: minimum public-promotion evidence is narrower than the quality claims it can authorize

**Confidence:** source-proven. **Affected decision:** public macOS release and external iOS
promotion.

`config/quality-promotion-contract.json` requires one canonical UI-generation record per promoted
platform. The canonical command and current records exercise the three modes with Speed artifacts
and an English corpus. Engine, memory, UI-performance, and model-lifecycle evidence become required
only when the path classifier asks for them. Language, prosody, delivery, Quality-tier, speaker
diversity, and most deep analyzers are not platform minima.

This is defensible for a change that cannot affect those dimensions, but AV-02 means many relevant
changes are not recognized. A source-bound, fresh, canonical manifest can therefore be valid while
the changed quality dimension was never exercised.

**Remediation gate:** define a capability/change matrix for model tier, mode, language, delivery,
analyzer, and lifecycle authority; require the smallest evidence set that actually covers the
changed capability; prove with tamper fixtures that each authority path demands detecting evidence;
label unsupported dimensions explicitly in the promotion manifest.

### P2 — AV-04: the local baseline comparator is permissive about missing coverage

**Confidence:** source-proven. **Affected decision:** local performance-regression review.

`compare_summaries` ignores a cell present only in the baseline, ignores a cell present only in the
current run, and skips a metric when either value is `None`. Its omitted tests explicitly encode
those choices. That makes a shrunk matrix or lost metric capable of producing “No regressions
detected.” The RTF implementation itself is correct; the stale tests are part of AV-01, not a
production direction bug.

**Remediation gate:** make missing baseline cells/required metrics a distinct fail-closed coverage
error unless an explicit, reviewed migration maps them; version baseline schemas; add CLI fixtures
for removed cells, added cells, missing metrics, directionality, and intentional migration.

### P2 — AV-05: engine benchmark timing is not shipping-optimization evidence

**Confidence:** source-proven and registry-reproduced. **Affected decision:** engine performance
claims and regression baselines.

All 156 tracked `engine-generation` records identify `-Onone`. The CLI build and benchmark command
also force `-Onone`; release packaging uses `-O`. Canonical UI-generation records are optimized and
partly cover shipping behavior, so this is not a total absence of optimized evidence. It does mean
engine-only RTF, stage timing, and memory comparisons cannot be interpreted as shipping-binary
performance without qualification.

**Remediation gate:** add an explicitly optimized, source-bound CLI/engine benchmark build or make
engine records correctness/memory-only; prevent cross-optimization comparisons; require the
optimization identity in every performance baseline and public claim.

### P2 — AV-06: benchmark history is too fragmented for strong trend detection

**Confidence:** source-proven. **Affected decision:** longitudinal regression detection.

The registry contains 270 records but 216 distinct comparison keys. Only 19 records have a
non-null baseline. Classification and matrix diversity are valuable, but the present key space,
frequent exploratory records, source dirtiness rules, and sparse repeated canonical cells mean most
records are snapshots rather than a powered trend series. Many cells use small warm repetition
counts; medians/IQRs describe repeated measurements, not independent scripts, speakers, or devices.

**Remediation gate:** designate a small stable trend matrix per platform, require minimum clean
repeat history and variance reporting, preserve run order/thermal/load/power qualification, define
practical regression thresholds with confidence or robust intervals, and report when no comparable
baseline exists instead of visually implying a trend.

### P2 — AV-07: prosody thresholds lack independent validation

**Confidence:** fixture-reproduced. **Affected decision:** prosody warnings and any future
promotion use.

The tracked calibration record is dirty, contains two “good” and two “bad” clips, reports 0% FPR
and only 50% observed TPR, and has no held-out corpus. The calibration script itself prints the
correct warning that thresholds need held-out validation and that per-metric FPR does not equal the
combined rule's FPR. The current analyzer/profile has continued to evolve after this record.

**Remediation gate:** create an independently labeled, source-bound train/holdout corpus with
multiple speakers, scripts, lengths, languages, and defect severities; freeze calibration before
holdout scoring; report confusion intervals and analyzer noise floors; keep the rule advisory until
predeclared acceptance targets pass on holdout data.

### P2 — AV-08: multilingual/ASR evidence measures a narrow cohort

**Confidence:** source-proven. **Affected decision:** language-quality claims.

The language matrix is a useful six-language diagnostic, but each language uses one script and
mostly one built-in speaker. The normal matrix uses a fixed generation seed. Three ASR passes are
repeated transcriptions of the same WAV, so they characterize analyzer stability rather than
independent output quality. Clone language behavior, speaker variety, code switching, punctuation,
numbers, and longer scripts are not population-covered. Documentation already warns against
population claims; promotion does not currently require the matrix.

**Remediation gate:** define a privacy-safe multilingual corpus with multiple scripts, lengths,
speakers/voices, and independent generation seeds; separate ASR-repeat uncertainty from generation
variance; predeclare WER/CER and language-ID handling; qualify each supported language/tier/mode or
label it unsupported/advisory.

### P2 — AV-09: physical-device UI lanes are fail-closed but not self-contained

**Confidence:** live-reproduced by the 2026-08-20 device records. **Affected decision:** explicit
iOS frontend acceptance availability.

The lanes correctly refuse to fake prerequisites, retry, or reset arbitrary device state. However,
the recent model-download lane found Custom already present in its supposedly isolated support root
and stopped before deletion; the broad smoke run later failed because a saved clone fixture was
absent even though its Settings methods passed. These are honest reds, not false greens, but they
make expensive device acceptance depend on residual local state and conflate independent journeys.

The fixed sleeps in `VocelloMacPerfUITests` and `VocelloiOSPerfUITests` were investigated and are
not a synchronization defect: `check_test_workflows.sh` explicitly restricts them to measured
idle/paced workload windows and rejects sleeps in other UI tests. The separate 300/700 ms sleeps in
`ModelDownloadChunkSchedulingTests` do cross real production throttles and remain a smaller
wall-clock testability issue.

**Remediation gate:** give each stateful lane a machine-readable prerequisite manifest and
non-destructive, test-owned run namespace; split fixture-dependent journeys from generic smoke;
preflight exact state before install/launch; inject a controllable clock into download scheduling
tests while preserving one integration proof against real throttles.

### P3 — AV-10: website checks do not execute a real browser interaction matrix

**Confidence:** source-proven. **Affected decision:** website deploy eligibility.

The website gate is strong for source rules, SSR markup, accessibility attributes, client/SSR
builds, and prerendering. Its “rendered” contract inspects server-rendered output; it does not load
the hydrated app in a browser, tab through controls, activate navigation, resize viewports, detect
console errors, or validate client-only state. For the current mostly static marketing site this is
low severity, but the gap will grow if interaction is added.

**Remediation gate:** add a small browser-level smoke matrix for hydration, keyboard navigation,
links/menus, console errors, and representative narrow/wide viewports; keep it deterministic and
separate from pixel-perfect visual approval.

### P3 — AV-11: marking-equality tests leak sidecar file descriptors

**Confidence:** live-reproduced. **Affected decision:** test hygiene and long-run reliability.

`scripts/check_marking_peak_equality.py` builds a list directly from `sidecar.open()` without a
context manager. Running its seven tests with `ResourceWarning` promoted produced ignored finalizer
warnings for unclosed files while the process still exited zero. The validator's numerical verdict
was correct, but the warning cannot currently fail the test process.

**Remediation gate:** use a context-managed file handle, add a warning-strict subprocess fixture
that fails on resource leakage, and retain all existing pass/fail marking fixtures.

## Confirmed strengths and ruled-out concerns

- No missing test assertion or swallowed error was found in the Swift deterministic lane; the
  macOS core, XPC transport, and owned runtime suites passed after the sandbox cache restriction was
  removed.
- UI automation is one-stack XCUITest, uses visible controls and stable identifiers, has no hidden
  shippable test UI, does not retry automatically, and preserves failed artifacts.
- UI-performance marker/coverage/cadence negative fixtures fail closed. Fixed UI sleeps are the
  workload window, not readiness synchronization.
- Benchmark publication accepts only successful, privacy-allowlisted compact records; raw audio,
  traces, screenshots, telemetry, and result bundles remain untracked.
- Source/fingerprint, dirty-tree, run identity, hardware, threshold, digest, warning, stale evidence,
  missing-row, and cross-run tamper fixtures are extensive and passed.
- Delivery evaluation is statistically stronger than the prosody calibration: it uses paired
  neutral/instructed data, seed grouping, cross-validation, permutation testing, and BH-FDR.
- MOS, SER, speaker similarity, listening, and noncanonical hardware are explicitly advisory rather
  than silently promoted.
- Memory qualification binds lifecycle boundaries, sampler coverage, pressure, forced unloads,
  wired-memory facts, and marking equality; app and engine peaks are not incorrectly added.
- Candidate production is deterministic-only, while public promotion separately requires exact
  source-bound quality evidence. The main release residual is the already tracked F-05 launch skip.

## Compound false-green analysis

The highest-risk sequence is not one catastrophic bug; it is the interaction of three moderate
governance gaps:

```text
quality/analyzer/UI authority changes
  -> AV-02 classifies the path as repository-other
  -> AV-03 asks only for canonical Speed/English UI generation
  -> AV-01 may omit the validator module meant to catch contract drift
  -> exact-source promotion manifest is internally valid
  -> changed Quality/language/delivery/analyzer behavior remains unobserved
```

The existing exact-source/digest/freshness controls prevent evidence substitution, but they cannot
make a too-narrow experiment detect an unmeasured dimension. AV-01 through AV-03 should therefore
be addressed before relying on promotion for broad quality claims.

A separate availability chain affects iOS acceptance rather than truthfulness:

```text
physical device prerequisite drifts
  -> stateful broad smoke encounters a missing fixture
  -> unrelated completed journeys are trapped in one red result
  -> rerun requires another long device sitting
```

AV-09 should preserve fail-closed behavior while making test-owned prerequisites explicit and
journeys independently repeatable.

## Prioritized remediation

### Immediate governance fixes

1. AV-01 — make Python execution discovery-complete and zero-discovery-aware.
2. AV-02 — eliminate unexplained evidence-impact fallback for critical paths.
3. AV-03 — bind promotion evidence to the actually changed quality capability.
4. AV-04 — make baseline coverage shrink/missing metrics fail closed.
5. AV-11 — close the sidecar handle and make resource warnings enforceable.

### Short-term harness work

1. AV-05 — add optimized engine performance evidence or narrow record semantics.
2. AV-06 — establish a small stable, statistically interpretable trend matrix.
3. AV-09 — isolate device-lane prerequisites and inject a scheduling clock.
4. AV-10 — add a minimal real-browser website smoke.
5. Complete existing F-03, F-05, and F-14 rather than duplicating them here.

### Longer-term evaluation research

1. AV-07 — build and freeze a labeled prosody calibration/holdout corpus.
2. AV-08 — expand multilingual scripts, speakers, seeds, and uncertainty decomposition.
3. Extend AV-03's capability matrix only when those dimensions have validated evidence; until
   then, state limitations instead of converting advisory signals into gates.

## Validation evidence from this audit

| Command | Result |
| --- | --- |
| `python3 -m unittest discover -s scripts -p 'test_*.py'` | PASS, 105 tests |
| `python3 -m unittest discover -s scripts/tests -p 'test_*.py'` | PASS, 879 tests |
| `python3 -m pytest scripts/tests/test_compare_baseline.py -q` | 3 failed, 7 passed; finding AV-01 |
| `python3 -W error::ResourceWarning -m unittest scripts.tests.test_check_marking_peak_equality` | Numerical tests PASS; ignored unclosed-file finalizer warnings reproduced AV-11 |
| `./scripts/check_project_inputs.sh` | PASS, including 906 curated tests and all contract/tamper suites |
| `scripts/macos_test.sh test` | PASS outside managed sandbox; initial sandbox run denied SwiftPM/Clang cache writes |
| `./scripts/build.sh build` | PASS outside managed sandbox; same cache restriction reproduced in sandbox |
| `./scripts/build_foundation_targets.sh ios` | PASS for app and logic-test bundle on generic iPhoneOS; no Simulator selected or launched |
| `npm --prefix website run check` | PASS; seven Node tests, rendered contract, client/SSR builds, prerender |

The initial macOS and iPhoneOS sandbox failures were environmental, not source failures:
`/Users/patricedery/.cache/clang/ModuleCache` and SwiftPM manifest caches were not writable, and the
Xcode runtime service was unavailable inside the sandbox. Approved unsandboxed reruns used the
existing locked caches and passed. No cache was deleted and no dependency pin changed.

No physical-device run was started during this audit because static, fixture, tracked-record, and
existing live evidence resolved every possible P0/P1. No benchmark record, release asset, model
installation, app-container state, or product source was changed by the audit.
