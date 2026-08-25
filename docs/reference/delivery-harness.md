---
status: active
owner: backend-mlx
summary: Operator's reference for the audio delivery analysis harness — the tools, the bench --delivery measurement protocol, evidence and provenance conventions, the statistics the separability scorer reports, the pre-registration discipline, the DP results ledger, and re-run recipes.
sourceOfTruth:
  - scripts/custom_delivery_matrix.py
  - scripts/delivery_experiment.py
  - scripts/delivery_experiment_runner.py
  - scripts/delivery_calibration_session.py
  - scripts/delivery_evaluator.py
  - scripts/delivery_evaluator_v2.py
  - scripts/delivery_listener_calibration_v2.py
  - scripts/delivery_analysis_cache.py
  - scripts/delivery_temporal_features.py
  - scripts/delivery_compact_model_adapter.py
  - scripts/delivery_compact_model_runtime.py
  - scripts/prepare_delivery_compact_model_config.py
  - scripts/qualify_delivery_compact_models.py
  - scripts/prepare_delivery_listener_anchors.py
  - scripts/delivery_resource_supervisor.py
  - scripts/run_local_delivery_cascade.py
  - scripts/delivery_promotion_decision.py
  - scripts/audio_cadence_qc.py
  - scripts/delivery_separability.py
  - scripts/bench_delivery_prosody.py
  - scripts/analyze_prosody.py
  - config/delivery-experiment-contract.json
  - config/delivery-evaluator-v2-contract.json
  - config/delivery-evaluator-v2-candidates.json
  - config/delivery-evaluation-corpus.json
  - config/audio-cadence-qc-contract.json
---
# The audio delivery analysis harness

> The consolidated operator's reference for measuring delivery/emotion quality. Deterministic
> analysis rejects broken or regressed candidates autonomously; blinded listening is the
> semantic authority for promoting delivery meaning because acoustic proxies do not establish
> what a listener hears. Ordinary commits and releases remain deterministic-only.
> The program's item-by-item status and pre-registered results live in
> [`config/roadmap.json`](../../config/roadmap.json) (`delivery-prompting-2026-08` plan);
> the adversarial audit that shaped this harness is pinned at
> [`delivery-control-audit-2026-08.md`](delivery-control-audit-2026-08.md), and the current Qwen
> prompting/evaluator research snapshot is
> [`qwen3-tts-emotion-tone-research-2026-08-22.md`](qwen3-tts-emotion-tone-research-2026-08-22.md).

## 1. Tool inventory

Only the text-only `check_delivery_instructions.py` and cadence-contract validation run in the
deterministic commit/CI gate; audio generation and calibration remain explicit measurement lanes.
Test files live under `scripts/tests/` and run in
the script self-test suite via `scripts/check_test_workflows.sh`.

| Tool | Purpose | Tests |
| --- | --- | --- |
| `scripts/custom_delivery_matrix.py` | Resumable, fail-closed 9-speaker × 8-shipped-preset screen with exact instruction receipts, typed failure preservation, rejected-WAV analysis, speaker-balanced reporting, held-speaker separability, and paired same-seed arm comparison | `test_custom_delivery_matrix.py` |
| `scripts/delivery_experiment.py` | Validates and compiles the six registered prompt arms, multilingual split-safe corpus, factorial sampling profiles, stable digests, and bounded seed-power plan | `test_delivery_experiment.py` |
| `scripts/delivery_experiment_runner.py` | Source-bound, serial and resumable CLI experiment runner; seals the binary, exact instructions, corpus, sampling, seeds, receipts, audio digests, failures, and analysis layers without publishing | `test_delivery_experiment_runner.py` |
| `scripts/delivery_calibration_session.py` | Builds and merges v1 calibration packets; its versioned v2 commands add per-listener shuffle, repeats, anchors, uncertainty, confidence, replay/latency, 2AFC, naturalness and intensity without weakening v1 | `test_delivery_calibration_session.py`, `test_delivery_listener_calibration_v2.py` |
| `scripts/delivery_evaluator.py` | Preserves ridge-v1 and exposes versioned v2 commands for preset-specific pairwise heads, elastic-net/PLS challengers, blocked validation, conformal intervals, OOD and typed abstention | `test_delivery_evaluator.py`, `test_delivery_evaluator_v2.py` |
| `scripts/delivery_analysis_cache.py` | Content-addressed, atomic analysis cache keyed by original and canonical audio plus exact analyzer/model/preprocessing provenance; cache hits launch no model | `test_delivery_analysis_cache.py` |
| `scripts/delivery_temporal_features.py` | Two-pass bounded-memory five-region contour analyzer plus same-identity instructed-minus-neutral deltas | `test_delivery_temporal_features.py` |
| `scripts/delivery_compact_model_adapter.py` | Contract-first CPU subprocess adapter for fully pinned SenseVoiceSmall Q8 or DistilHuBERT candidates; neither candidate is adopted or downloaded by the repository | `test_delivery_compact_model_adapter.py` |
| `scripts/delivery_compact_model_runtime.py` | Offline CPU DistilHuBERT executor; emits one deterministic, normalized 128-dimensional frozen representation and never receives a requested label | `test_delivery_compact_model_runtime.py` |
| `scripts/prepare_delivery_compact_model_config.py` | Validates the tracked candidate contract and exact local weights/runtime/dependencies, then emits an untracked path-bearing adapter configuration | `test_prepare_delivery_compact_model_config.py` |
| `scripts/qualify_delivery_compact_models.py` | Runs exactly two cache-cold probes, retains sanitized resource evidence, and refuses holdout bake-off on any unqualified run | `test_qualify_delivery_compact_models.py` |
| `scripts/prepare_delivery_listener_anchors.py` | Builds label-blind naturalness/attention anchors by pairing a real clip with a deterministic dropout control; audio and manifest remain untracked | `test_prepare_delivery_listener_anchors.py` |
| `scripts/delivery_resource_supervisor.py` | Single-process lock, peak RSS/pressure/swap/timeout capture, and post-exit memory-recovery qualification for heavy local analyzers | `test_delivery_resource_supervisor.py` |
| `scripts/run_local_delivery_cascade.py` | Existing-harness post-generation composer for always-on, ambiguous-only, finalist-only, abstention, rejection, and manual-listening routes | `test_run_local_delivery_cascade.py` |
| `scripts/delivery_promotion_decision.py` | Fail-closed decision over blinded listener evidence, paired statistics, multiplicity correction, acoustic guardrails, and runtime invariants | `test_delivery_promotion_decision.py` |
| `scripts/audio_cadence_qc.py` | Validates the Fast-QC cadence policy and audits untracked, privacy-safe, independently labelled calibration/development/confirmation cohorts before a threshold review | `test_audio_cadence_qc.py` |
| `scripts/delivery_separability.py` | Cross-preset separability: ridge-LDA over paired signed features, seed-grouped CV, UAR, computed chance floor, permutation null, Wilson intervals, per-cell BH-FDR, `--presets` subset probes | `test_delivery_separability.py` |
| `scripts/bench_delivery_prosody.py` | Post-processes the current `vocello bench --delivery` run from its immutable manifest into `bench-prosody.json`; fail-closed instruction-receipt provenance (§4) | via `test_bench_command_contract.py` |
| `scripts/delivery_listening_session.py` | Build / run / score the blind 2AFC + free-identification listening session from bench archives; sealed keys, pre-registered exact-binomial decision rules | `test_delivery_listening_session.py` |
| `scripts/build_emotion_reference_bank.py` | Generate → score → select → enroll curated per-emotion VoiceDesign reference banks (design-then-clone) → [`emotion-reference-banks.md`](emotion-reference-banks.md) | `test_build_emotion_reference_bank.py` |
| `scripts/emotion_advisory.py` | Advisory SER agreement column (pinned wav2vec2-XLSR checkpoint + revision); never a gate, never publication input → [`testing-runbook.md`](testing-runbook.md) | `test_emotion_advisory.py` |
| `scripts/mos_advisory.py` | Advisory naturalness MOS-proxy column (UTMOSv2 pinned by commit + weights digest, CPU, relative signal only); never a gate, never publication input → [`testing-runbook.md`](testing-runbook.md) | `test_mos_advisory.py` |
| `scripts/delivery_adherence.py` | Standalone paired neutral-vs-instructed adherence bench (drives `vocello generate` itself) | none |
| `scripts/delivery_quality_gate.py` | Per-preset delivery-adherence verdict + neutral-cohort dispersion, thresholds from the versioned prosody profile | `test_delivery_quality_gate.py` |
| `scripts/delivery_statistics.py` | Library: Wilcoxon, Cohen's d_z, BCa bootstrap, Wilson, Benjamini-Hochberg, required-pairs power | `test_delivery_statistics.py` |
| `scripts/delivery_identification_check.py` | Score a blind identification session: confusion matrix, per-preset recall, attractor test | `test_delivery_identification_check.py` |
| `scripts/delivery_matrix_report.py` | Matrix-level report over paired delivery rows | `test_delivery_matrix_report.py` |
| `scripts/separability_listening_check.py` | Human spot-check protocol against a separability verdict | `test_separability_listening_check.py` |
| `scripts/analyze_delivery.py` | Reference-free delivery acoustic analyzer (F0 median/range, syllable rate, duration, voicing) consumed by `delivery_adherence.py` and the bench sidecar | `test_analyze_delivery.py` |
| `scripts/analyze_prosody.py` | Bounded reference-free prosody analyzer (pitch/cadence/pause/energy + `voice_*` HNR/jitter/CPP + spectral balance) | `test_analyze_prosody.py` |
| `scripts/prosody_profile.py` | Versioned prosody profile: thresholds, delivery weights, per-preset expectations | via gate/separability tests |
| `scripts/prosody_quality_gate.py` | Reference-free per-take prosody gate (monotone / rushed / flat / pause issues) | `test_prosody_quality_gate.py` |
| `scripts/check_delivery_instructions.py` | Deterministic text-level contract gate on shipped delivery copy (T1/CI) → [`config/delivery-instruction-contract.json`](../../config/delivery-instruction-contract.json) | `test_check_delivery_instructions.py` |

## 2. Measurement protocol — `vocello bench --delivery`

One bench invocation generates one seed's worth of cells:

```sh
QWENVOICE_DEBUG=1 ./build/vocello bench --modes custom --variants speed --lengths medium \
  --speaker aiden \
  --warm 1 \
  --delivery neutral.strong,happy.normal,sad.strong,angry.normal,fearful.strong,surprised.strong,calm.strong,whisper.strong \
  --seed 20260810 --label "my-sweep-arm-label"
```

- **Cells** are `<preset>.<intensity>`. `vocello deliveries --shipped-only --json`
  is the machine-readable authority for the eight product-visible cells and their
  exact instructions; do not reconstruct the mixed shipped-tier policy in a shell
  script. Every cell generates one instructed warm take on the medium text.
- **The plain warm take is the neutral reference** for every paired delta — which is why
  `--warm 0` is rejected with `--delivery`.
- **Clone is excluded by design**: the clone checkpoints have no instruction channel, so
  delivery cells run for Custom/Design only. Clone delivery quality is measured through
  the reference-bank path instead ([`emotion-reference-banks.md`](emotion-reference-banks.md)).
- **Multi-seed sweeps loop one invocation per seed** (fixed seeds reproduce takes
  exactly). Use zsh brace expansion for seed ranges — macOS `seq` renders 8-digit
  integers in scientific notation and the CLI rejects them:

```sh
for seed in {20260810..20260827}; do
  QWENVOICE_DEBUG=1 ./build/vocello bench … --seed $seed --label "arm-label" || echo "seed $seed failed"
done
```

- **Arms** (e.g. 4-bit vs 8-bit) are distinguished by `--label` and, defensively, by the
  per-take `modelID` recorded in each run's `bench-results.json` — filter on both when
  collecting (DP-18's 8-bit arm ran under the wrong label; modelID separated the arms).
- Ordinary bench runs remain fail-fast when mandatory Fast QC rejects a take. The
  diagnostic-only `--continue-delivery-failures` mode requires `--delivery` and
  `--no-summary`; it records one typed success or failure for every attempted cell,
  preserves rejected WAVs, and is never eligible for history publication. It exists
  so a failed take stays in the planned denominator instead of silently dropping the
  whole speaker/seed unit or being replaced with a friendlier seed.

For the complete Built-in Voice speaker roster, prefer the autonomous runner:

```sh
python3 scripts/custom_delivery_matrix.py run \
  --binary ./build/vocello \
  --output build/artifacts/macos/custom-delivery-matrix/my-screen \
  --seeds 20261001,20261002,20261003,20261004,20261005
```

The runner discovers the exact speaker and shipped-delivery rosters from the CLI,
seals each speaker/seed unit, rejects missing/duplicate/cross-identity outcomes, and
resumes only at unit boundaries. `--instruction-set short|candidate-v2` selects a
registered debug-only arm; omit it for shipped production copy. Compare two complete
same-identity arms with `custom_delivery_matrix.py compare`.

### 2.1 Multilingual prompt and sampling experiments

The versioned experiment contract separates six attributable prompt arms: shipped copy,
official-minimal emotion, acoustic attributes, emotion plus attributes, one compatible scene,
and one anti-exaggeration constraint. Compiling an experiment never changes production
instructions. English and Mandarin are the only instruction-language arms; Japanese and Korean
remain output languages, not unproven instruction-language candidates.

The corpus has calibration, development, and untouched confirmation partitions. Each partition
uses distinct script identities and text, with short, medium, and long neutral, congruent, and
conflicting semantic conditions. Native coverage includes all nine built-in speakers in their
recommended language. Four fixed sentinels hold output language apart from speaker compatibility:
Aiden speaking Mandarin, and Vivian, Ono Anna, and Sohee speaking English. Non-English text is
provisional until a fluent reviewer accepts it and cannot authorize a locale claim before then.

One seed across this roster contains 936 instructed/reference pairs. Create and execute an
immutable plan explicitly:

```sh
python3 scripts/delivery_experiment.py validate
python3 scripts/delivery_experiment_runner.py plan \
  --binary ./build/vocello --split development \
  --arm emotion-acoustic --instruction-language english \
  --variant speed --sampling official-official \
  --seeds 32060822 --out build/artifacts/macos/delivery-experiment/plan.json
python3 scripts/delivery_experiment_runner.py run \
  --binary ./build/vocello \
  --plan build/artifacts/macos/delivery-experiment/plan.json \
  --run-dir build/artifacts/macos/delivery-experiment/run
python3 scripts/delivery_experiment_runner.py analyze \
  --plan build/artifacts/macos/delivery-experiment/plan.json \
  --run-dir build/artifacts/macos/delivery-experiment/run
```

The runner invokes one generator process at a time, retains typed failures, resumes from sealed
row state, refuses binary or plan drift, verifies the CLI's exact delivery receipt, and never
publishes. Its five sampler combinations vary the talker among official, balanced, and consistent
profiles while either holding the subtalker at official defaults or matching it. Sampling effects
are measured; no profile is presumed to improve adherence.

Development screens may narrow the matrix without weakening the holdout boundary. A screened plan
must name itself and records the exact selected cells, presets, lengths and semantic conditions.
Confirmation plans reject every selector. Compare otherwise identical runs with `summarize`; its
ranking is explicitly acoustic/advisory and includes failed or blocked takes in the denominator:

```sh
python3 scripts/delivery_experiment_runner.py plan \
  --binary ./build/vocello --split development --screen-label prompt-pilot \
  --cells aiden:English --presets happy,angry,sad,calm,surprised,whisper \
  --lengths medium --conditions neutral \
  --arm current --instruction-language english --variant speed \
  --sampling balanced-matched --seeds 32060823 \
  --out build/artifacts/macos/delivery-experiment/prompt-plan.json
python3 scripts/delivery_experiment_runner.py summarize \
  --runs current=build/artifacts/macos/delivery-experiment/current/run,candidate=build/artifacts/macos/delivery-experiment/candidate/run \
  --baseline current \
  --out build/artifacts/macos/delivery-experiment/screen-summary.json
```

Every new plan seals SHA-256 identities for the CLI, runner, analyzer, delivery gate and prosody
profile. Resume and comparison fail if any of those bytes drift. Failed CLI invocations retain only
an allowlisted failure class, line count and hashes; diagnostic prose and local paths never enter
the manifest. When `--baseline` is supplied, the summary also reports paired improvements,
regressions, ties and a two-sided exact sign-test probability overall and per preset. This prevents
a one-cell aggregate lead from being presented as a stable improvement.

### 2.2 Blinded dimensional calibration

The evaluator cannot learn valence, arousal or dominance from requested preset names. Build a
calibration-only packet from completed, analyzed calibration rows, collect ratings independently,
then merge them:

```sh
python3 scripts/delivery_calibration_session.py build \
  --plan build/artifacts/macos/delivery-experiment/calibration/plan.json \
  --run-dir build/artifacts/macos/delivery-experiment/calibration/run \
  --out build/artifacts/macos/delivery-experiment/calibration/session --session-seed 20260822
python3 scripts/delivery_calibration_session.py run \
  --session build/artifacts/macos/delivery-experiment/calibration/session \
  --listener-id local-pseudonym --fluent-languages English
python3 scripts/delivery_calibration_session.py merge \
  --session build/artifacts/macos/delivery-experiment/calibration/session \
  --out build/artifacts/macos/delivery-experiment/calibration/labels.json
```

The public packet exposes randomized clip identity, digest and output language only. Speaker,
script, seed, requested preset and acoustic features stay in the private key. A dataset qualifies
only with at least 20 rows spanning three speakers and three scripts, three independent complete
listeners, fluent coverage for every output language, and mean pairwise concordance of at least
0.60 for each dimension. Packet creation requires every planned generation and analysis row,
verifies every WAV digest, and binds the private key into the public session digest.
`delivery_evaluator.py train` rejects any other label provenance.

The first local packet, `dp28-calibration-packet-20260822`, contains 27 complete English clips:
Aiden, Ryan and Vivian across three script lengths and Happy, Angry and Sad. All nine paired neutral
references and all 27 instructed takes completed without a retained failure. The packet is ready
for rating but deliberately remains unqualified until three independent listeners complete it.

### 2.3 Compact local evaluator v2

[`config/delivery-evaluator-v2-contract.json`](../../config/delivery-evaluator-v2-contract.json)
extends this same harness; it is not another source of generation, split, or promotion authority.
The experiment runner now seals the temporal analyzer and places a `temporalDeltaV1` block beside
the existing acoustic result. Five equal-voiced-content regions preserve F0, energy, harmonicity,
spectral, cadence, and pause contours without building a duration-sized frame matrix. Synthetic
tests cover rises/falls, peak position, attacks, delayed pauses, persistent noise, tremor, zero
paired deltas, and duration-independent analyzer-owned memory.

Post-generation evaluation starts only after the TTS/MLX process has exited:

```sh
python3 scripts/delivery_evaluator.py validate-v2-contract \
  --contract config/delivery-evaluator-v2-contract.json
python3 scripts/run_local_delivery_cascade.py \
  --plan build/artifacts/macos/delivery-experiment/calibration/plan.json \
  --run-dir build/artifacts/macos/delivery-experiment/calibration/run \
  --out build/artifacts/macos/delivery-experiment/cascade-report.json
```

The cascade derives its input from the runner's retained plan, execution state, acoustic layer,
source identities and exact WAV digests after the generator has exited, then reuses neutral
controls through `build/cache/delivery-analysis`. Cache identity binds original and canonical
16 kHz mono PCM bytes to layer, binary, model, revision, weights, and preprocessing digests;
corruption or drift fails closed and a cache hit launches no model. Reports contain digests and
measurements, never local paths or audio. Always-on acoustics can reject a broken row, but absent a
qualified compact adapter and calibrated tiny head the honest result is `abstained`.

External candidates are governed separately by
[`config/delivery-evaluator-v2-candidates.json`](../../config/delivery-evaluator-v2-candidates.json).
The tracked contract pins the exact SenseVoiceSmall Q8 model revision, GGUF and runtime archive/
binary digests, and the exact DistilHuBERT revision, safetensors/support-file digests and Python,
Torch, Transformers, safetensors and NumPy versions. The local configuration additionally binds
the adapter layer and resource-supervisor source bytes into the preprocessing/cache identity.
No model file or absolute path is tracked:

```sh
python3 scripts/prepare_delivery_compact_model_config.py --validate-only
python3 scripts/prepare_delivery_compact_model_config.py sensevoice-small-q8 \
  --output build/artifacts/macos/delivery-evaluator-v2/candidate-configs/sensevoice.json
python3 scripts/prepare_delivery_compact_model_config.py distilhubert \
  --output build/artifacts/macos/delivery-evaluator-v2/candidate-configs/distilhubert.json
```

Qualification uses two byte-distinct real clips, one candidate at a time. It records peak process
RSS, wall time, pressure before/after, swap delta, clean exit and bounded post-exit recovery. An
unqualified result is returned for forensics but never cached and the next heavy layer does not
start. Post-exit recovery samples for up to 15 seconds because one immediate host-free-percentage
sample proved too noisy; the five-point recovery threshold itself remains fail closed. The runner
does not accept a caller-authored host label: it checks `hw.model` and `hw.memsize` against the
tracked canonical macOS hardware profile and binds the qualifier source in its report.

The versioned listener workflow remains under `delivery_calibration_session.py`:

```sh
python3 scripts/delivery_calibration_session.py build-v2 \
  --plan build/artifacts/macos/delivery-experiment/calibration/plan.json \
  --run-dir build/artifacts/macos/delivery-experiment/calibration/run \
  --anchors build/artifacts/macos/delivery-experiment/calibration/anchors.json \
  --out build/artifacts/macos/delivery-experiment/calibration/session-v2 \
  --session-seed 20260823
python3 scripts/delivery_calibration_session.py run-v2 \
  --session build/artifacts/macos/delivery-experiment/calibration/session-v2 \
  --listener-id local-pseudonym --fluent-languages English
python3 scripts/delivery_calibration_session.py merge-v2 \
  --session build/artifacts/macos/delivery-experiment/calibration/session-v2 \
  --out build/artifacts/macos/delivery-experiment/calibration/labels-v2.json
```

Each listener gets an independent deterministic order, 12.5% exact repeats, blinded anchors,
uncertainty/confidence/replay/latency fields, target-versus-neutral and candidate-versus-baseline
2AFC, and naturalness/intensity ratings. The merged report retains listener rows and reports repeat
agreement, pairwise CCC, free-identification agreement, anchor accuracy, order bias, uncertain
rate, and fluent-language coverage. Requested preset labels remain outside the public dimensional
block. A response file is written atomically after every trial; rerunning the same listener/session
identity verifies and resumes its exact retained prefix instead of replaying completed trials.

Calibration and confirmation use distinct plan seed partitions and session kinds. Model fitting
rejects confirmation labels; holdout scoring rejects calibration labels. Once listener labels are
qualified, blind compact deltas join only by exact generation identity and cannot change any label:

```sh
python3 scripts/delivery_evaluator.py attach-v2-compact \
  --input build/artifacts/macos/delivery-experiment/calibration/labels-v2.json \
  --cascade build/artifacts/macos/delivery-experiment/calibration/cascade-distilhubert.json \
  --out build/artifacts/macos/delivery-experiment/calibration/labels-v2-distilhubert.json
python3 scripts/delivery_evaluator.py calibrate-v2 \
  --input build/artifacts/macos/delivery-experiment/calibration/labels-v2-distilhubert.json \
  --out build/artifacts/macos/delivery-experiment/calibration/evaluator-v2.json
python3 scripts/delivery_evaluator.py score-v2-holdout \
  --input build/artifacts/macos/delivery-experiment/confirmation/labels-v2-distilhubert.json \
  --model build/artifacts/macos/delivery-experiment/calibration/evaluator-v2.json \
  --out build/artifacts/macos/delivery-experiment/confirmation/holdout-scores.json
```

Calibration blocked-validation metrics deterministically preselect at most one challenger before
the confirmation labels are opened. Holdout scoring refuses a model with no preselection and emits
scores only for ridge-v1 plus that one challenger; it never exposes the other challenger for
post-hoc selection. `compare-v2-holdout` verifies the sealed score digest and exact two-model set.

Ridge-v1 remains the adopted baseline. V2 adds per-preset regularized logistic heads, elastic-net
and PLS VAD challengers, fold-local reduction across speaker/translation/seed/language blocks,
blocked split-conformal intervals, robust Mahalanobis/nearest-neighbor OOD, and typed contradiction
or abstention reasons. No challenger is adopted until it improves an untouched qualified human
holdout without regressing any VAD dimension, preset, speaker or script group, with gains present
across both speaker and script groupings. SenseVoiceSmall Q8 and DistilHuBERT remain unadopted
adapter candidates until license/training provenance, immutable digests, two clean serial M2/8 GB
runs, post-exit memory release, and human-holdout gain all pass. UTMOS remains finalist-only and
legacy SER remains a bake-off comparator.

### 2.4 Cadence validity is separate from delivery adherence

Fast audio QC algorithm v5 retains the v4 pass/warn/fail boundaries and adds a bounded typed
`AudioCadenceQCReport`. It records the punctuation-derived expected pause count, observed and
excess cadence pauses, suspicious-pause count, the bounded pause-duration vector, cumulative
interior/cadence silence, median and p90 pause duration, and cadence-silence ratio. These fields
contain no script or audio. A `severe` cadence classification is still only the existing gross
defect rule: a context-sensitive egregious interior gap or repeated suspicious-scale gaps. An
ordinary excess remains `unusual`, not a hidden product rejection.

On iOS, an otherwise accepted unusual take remains in the completed player and History. The
player shows “Unusual pacing detected” with a visible “Generate again” action. The action uses the
currently visible request; Vocello does not silently retry, alter the seed, or choose among hidden
takes. A severe take still fails mandatory QC before publication. Cadence validity and semantic
delivery adherence remain independent decisions: a take can match Calm yet have pathological word
spacing, or have ordinary pauses while missing the requested emotion.

[`config/audio-cadence-qc-contract.json`](../../config/audio-cadence-qc-contract.json) keeps the
current boundary authoritative until an independently labelled cohort qualifies. Operator-local
datasets contain digests and measurements only, require three listeners per row, block compound
speaker/script/seed/language identities across calibration, development, and untouched
confirmation, and cover every preset, at least six speakers, English/Chinese/Japanese/Korean,
three script lengths, six script groups, and eight seeds in each split. Run:

```sh
python3 scripts/audio_cadence_qc.py validate-contract
python3 scripts/audio_cadence_qc.py evaluate \
  --dataset build/artifacts/macos/delivery-cadence/labelled-cohort.json \
  --output build/artifacts/macos/delivery-cadence/review-readiness.json
```

The untouched confirmation must have zero severe false rejection among human-acceptable takes,
at least 90% severe recall, and at most 25% warning notices among acceptable takes. The report can
authorize an explicit source review only; it cannot edit thresholds or claim semantic delivery
quality.

Live status on 2026-08-23: both exact candidate configurations passed two cache-cold probes on the
attested Mac14,3 / 8 GiB host. SenseVoice used 275-293 MB peak RSS and DistilHuBERT used 677-874 MB;
all four probes recorded zero swap growth, no pressure warning and clean post-exit recovery. A
balanced source-bound cohort completed 64 instructed rows plus eight shared neutral controls over
all eight presets, eight speakers, six scripts/three translation groups and three languages. A
prior cohort is retained but excluded because one fixed-seed cell reproducibly failed Fast QC with
a 4.613-second dropout. The accepted run's 64-row acoustic/temporal analysis and both compact
cascades passed; the cascades abstain pending human calibration. Its source-bound listener packet
contains 64 dimensional trials, 56 non-neutral 2AFC trials and three multilingual anchors. The
remaining gate is three independent qualified listeners with English/Chinese/Japanese fluency
coverage, followed by calibration-only preselection and a separately generated untouched holdout.
No production delivery copy or `EmotionPreset` changed.

### 2.4 Development-screen findings (2026-08-22)

These local artifacts are exploratory and untracked; they are not promotion evidence and did not
open the confirmation split.

- A 36-take Aiden prompt screen found 6/6 advisory acoustic passes for both shipped copy and the
  official-minimal arm. The four more elaborate structured arms reached 3-5/6, so prompt length and
  added attributes did not produce a global gain.
- A same-cell expansion across Ryan plus the Vivian, Ono Anna and Sohee English sentinels favored
  shipped copy 10/24 to 5/24. Failed generations stayed in the denominator. This rejects the
  official-minimal arm as a global replacement, not as a claim about every speaker or preset.
- Five sampler combinations over three Aiden seeds produced changing rankings. On the two newer
  seeds, consistent-matched led at 10/12, while balanced-matched, balanced-official and official-
  official each reached 9/12; the earlier seed had a three-way 4/6 tie. Happy and Surprised were
  the recurring weak cells. Lower sampling temperature is therefore not a universal adherence fix.
- A fresh source-bound Happy/Surprised screen then compared shipped copy, acoustic attributes only,
  and the constrained scene arm over Aiden, Ryan, Vivian-English and Sohee-English with two new
  seeds. All 48 instructed takes completed. Aggregate advisory passes were 10/16, 9/16 and 8/16.
  Against shipped copy, acoustic-only improved two cells and regressed one (`p=1.0`): both gains
  were Happy (`2-0`, `p=0.5`), while Surprised regressed `0-1`. The constrained arm improved one and
  regressed two (`p=1.0`). No global arm advances. Acoustic-only remains an exploratory Happy-only
  candidate; Surprised retains shipped copy until a different candidate is supported.

Production instructions and the default Expressive sampler remain unchanged. The next automatic
screen may expand the Happy-only acoustic arm to the pre-registered 8-20 seed range, but semantic
promotion still requires the blinded calibration and untouched listening gates below.

## 3. Evidence conventions

- **`~/Library/Application Support/QwenVoice-Debug/outputs/bench-archive/<runID>/` is the
  durable evidence copy** for every delivery run: all take WAVs plus `bench-results.json`
  (immutable manifest), `bench-prosody.json` (the paired-delta sidecar), and
  `bench-quality-composed.json`. Archiving is fail-closed for required files and happens
  before the sidecar analysis, so even an analysis-failed run keeps its audio. The
  archive is unbounded; prune manually.
- **Successful diagnostics run directories are cleaned after publication.** After a run
  publishes its registry record, its directory under `diagnostics/benchmark-runs/` is
  removed; only failed runs leave one behind. Score sweeps from the bench archive, never
  from the diagnostics run dirs.
- **Where results live**: compact PASS records in [`benchmarks/runs/`](../../benchmarks/runs/)
  (generated index [`benchmarks/HISTORY.md`](../../benchmarks/HISTORY.md)); the full
  per-take sidecars and WAVs in the bench archive; the pre-registered verdicts and their
  interpretation in the owning roadmap item's gate text; the narrative in
  [`development-progress.md`](../development-progress.md).

## 4. Instruction-provenance chain (fail closed)

A delivery measurement is only as good as its proof that the instruction actually entered
the engine. The chain:

1. The request payload carries the instruction (`GenerationRequest.Payload
   .deliveryInstructionText`; nil for clone).
2. The engine stamps a receipt on the take's telemetry row: `notes.instructChars` and
   `notes.instructDigest` (SHA-256 of the instruction text) —
   `Sources/QwenVoiceCore/GenerationOutputAdapter.swift`.
3. `bench_delivery_prosody.py` fails closed per instructed cell unless: the receipt
   exists, its digest matches the bench manifest's `deliveryInstruction` echo, and the
   paired neutral reference carries **no** receipt (an instruction on the reference would
   poison every delta).

`notes.promptChars` cannot prove any of this — it counts only the script text, which
never includes the instruction. The original guard compared prompt lengths and could
never pass live; it was replaced with the receipt on 2026-08-04
([`development-progress.md`](../development-progress.md) finding 21). The lesson is
codified in §7: exercise every new fail-closed check live in the arc that lands it.

## 5. Statistics the separability scorer reports

`delivery_separability.py --sidecar bench-prosody.json | --records records.json`:

- **Designation** (`--designation exploratory|confirmatory`): the verdict's evidentiary
  status. Decision-bearing claims require a pre-registered confirmatory run on fresh
  seeds. (Distinct from the benchmark registry's "exploratory = dirty worktree"
  classification — same word, different system.)
- **Chance floor** is computed (`1/cells`), never hand-stated.
- **Cross-validation** is seed-grouped (a seed's takes never straddle train/test); if
  every take has a unique seed the verdict flags `separability_degenerate_folds` and
  reports the fold grouping rather than hiding it.
- **Permutation null** (`--null-iters N`, fixed RNG seed in the verdict): label-shuffled
  UAR distribution and an exact-style p-value for the observed UAR. 1000 iterations is
  the confirmatory norm.
- **Per-cell honesty**: recall with Wilson interval; `aboveChance`/`belowChance` only
  when the whole interval clears/undershoots the floor; exact one-sided binomial
  `aboveChanceP`, Benjamini-Hochberg `aboveChanceQ`, and `aboveChanceFdr05` across the
  per-cell family (eight cells must not each borrow a single-test alpha).
- **Subset probes** (`--presets happy,angry`): run the discriminant on a preset subset
  for pre-registered K-way questions; the verdict records `presetFilter` so a subset can
  never pass as the full set.

The cross-speaker matrix also reports held-one-speaker-out folds. This measures whether
the acoustic features generalize to an unseen speaker, not whether a person recognizes
the intended emotion. Its adherence summary has two deliberately separate denominators:

- **Product adherence** counts only product-accepted takes and keeps every Fast-QC or
  generation failure as a failure.
- **Acoustic adherence** additionally analyzes a preserved rejected WAV when one exists.
  This is diagnostic evidence for locating an erroneous product rejection; it never
  upgrades the product outcome or makes the run publishable.

## 6. Analyzer accuracy and authority boundary

`analyze_prosody.py` is deterministic, bounded-memory PCM analysis. Its synthetic
contracts cover silence/noise rejection, pause placement, voiced-harmonic behavior,
spectral behavior, repeatability, and an 80–390 Hz harmonic F0 sweep with at most 1%
error. The matrix records the analyzer, profile, binary, source-diff, roster, and
instruction digests so results cannot be detached from the implementation that produced
them. Non-finite output, incomplete identity, missing audio, and cross-run contamination
fail closed.

Those properties establish implementation correctness and repeatability, not perceptual
ground truth. The built-in profile was calibrated from earlier generated takes rather
than an independently labelled holdout. The current complete screen uses Speed, one
English medium script, same-speaker/same-seed uninstructed references, and request labels.
It does not cover Quality, multiple scripts or lengths, other languages, independently
annotated defects, or listener-recognized emotion. Separability can therefore show that
presets make different acoustic regions without proving that they sound like the named
delivery. The layered evaluator and its fail-closed schemas are now present, but AV-07 remains
open until a frozen blinded-label corpus calibrates its dimensional model on grouped
speaker/script folds and an untouched multi-speaker/script/language holdout validates it. The SER
layer records its full posterior, entropy and top-two margin: calm-to-neutral is a hypothesis, not
a truth label, and whisper abstains from categorical emotion. Automatic scores can reject a
candidate or identify a regression, but cannot alone authorize a delivery-copy promotion.

## 7. Pre-registration discipline

- Register the design **in the owning roadmap item's gate text before any generation**:
  hypotheses, exact seeds, cells, arms, scoring commands, decision rules. The commit
  timestamp is the registration proof.
- Amendments (harness fixes discovered mid-sweep) are recorded in the gate with an
  explicit pre-data note; hypotheses/seeds/decision rules stay unchanged or the run
  restarts.
- Results append to the same gate text (`RESULTS <date>`), including coverage notes —
  dropped seeds, label slips, anything a reader would otherwise assume was clean.
- **Exercise every new fail-closed check live in the arc that lands it** — a check proven
  only on synthetic fixtures may be fixture-true, live-false (§4's history).

## 8. Results ledger (headline numbers; the roadmap gate is the authority)

| Item | Result |
| --- | --- |
| DP-3 | Long instruction register beats short: 57 vs 33 features over 12 seeds (register hypothesis refuted) |
| DP-4 | English diction append: prosodic null (28 vs 25), intelligibility saturated; append kept |
| DP-5 | Shipped labeled Voice Design merge best of three arms; borrowed quality anchor hurts |
| DP-6 | Angry pitch contradiction is textual only: shipped copy moves pitch +5.98 st, d=1.40, win 0.91 (23 seeds) |
| DP-10 | Roster cut to 8: 10-way UAR 0.311 vs 0.100 floor (18 seeds, exploratory); excited/dramatic retired |
| DP-11 | Audit: 10-way separability real (perm p<0.001); high-arousal cluster claim corrected to "no detectable separability" (p=0.28); 91%/55% figures retracted |
| DP-12 | 146-trial blind session (one listener): pooled ID 26/88 = 0.295 vs 0.125 (p=2e-05); calm/whisper 0.55, neutral/sad 0.36; angry 0/11; 2AFC `no_measured_strong_tier_collapse`; angry heard only via clone transfer (0.667) |
| DP-13 | First bank (Warm Narrator): SER-verified happy/sad/angry; whisper honestly refused; clone identity 0.81-0.89 |
| DP-14 | Measured split shipped: distinct = neutral/calm/whisper/sad (`EmotionPreset.distinctDeliveryIDs`); other four are directional hints with advisory copy |
| DP-15 | Seed retry/pin shipped: History schema v6 records each take's effective seed; pin from History reproduces a take |
| DP-17 | Whisper criterion prototype: candidates MORE harmonic than anchor (ΔHNR +1.0..+1.4 dB) — generation recipe needed before any criterion can select |
| DP-18 | Confirmatory two-arm sweep: H1 replicates (4-bit UAR 0.477 / 8-bit 0.375 vs 0.125, perm p=0.001 both); H2 all distinct cells clear FDR both arms; H3 refuted — happy-vs-angry 2-way at chance (p=0.43/0.24), valence bottleneck confirmed; H4 8-bit no better; angry+fearful meet the two-arm acoustic eligibility bar (promotion needs fresh listening — maintainer call) |
| DP-21 | Adherence expectations calibrated from the banked matrix (272 paired rows, 8 presets × strong × 2 variants × 17-18 seeds; gate algorithm v2, profile digest `133d46bd…`): fearful arousal direction flipped +1 (its `.strong` copy asks for panic/urgency; old seed scored adherence backwards, posRate 0.71 under +1); new binds whisper breathiness (posRate 0.97, strongest signature measured) + voicing drop (0.94), sad variation collapse (0.94), angry/happy tension (0.82/0.76); floors at the noise decile (supporting flags ≈10% by design); genuine misses kept warning at seed values — surprised pitch rise (0.62), fearful fast-pacing (slower in 74%). Bank replay: 181 pass / 91 warn (seeds scored 128/144) |
| DP-22 | Normal-tier acoustic arm (17/18 fresh seeds; one deterministic QC casualty recorded): angry-vs-happy separates at normal in the 4-bit arm — UAR 0.765 vs 0.5, perm p=0.007, replicating DP-12's perceptual 0.75 where DP-18's strong tier was null (0.531/p=0.43); 8-bit null at both tiers. Cross-tier exploratory: angry.strong-vs-happy.normal is the widest pairing (2.424 vs 1.469 shipped); happy.normal the only FDR-clear happy cell measured. DP-9 stays parked (tiers carry value); shipping candidate → DP-23. Floors deviation recorded: measured normal q10s mostly negative — the 1.15 intensity scale doubly refuted; floors stay strong-anchored |
| DP-26 | Full Custom/Built-in Voice screen: 9 speakers × 8 shipped cells × 5 fixed seeds = 360 instructed attempts with exact engine receipts. Baseline product 169/360, acoustic 182/360, held-speaker UAR 0.342. Audio QC v3 falsely rejected 29 delivery and 9 neutral-reference clips for ordinary cadence pauses; none had an analyzer pause ≥1.2 s and 13 rejected deliveries otherwise passed adherence. QC v4 now warns on ordinary excess cadence while retaining repeated suspicious-gap and context-sensitive ≥1.2/2.0 s hard failures. A same-seed candidate-v2 arm reduced product QC failures to two genuine ~2 s Sad gaps but did not improve acoustics (182/360) and reduced held-speaker UAR to 0.306, so no shipped prompt changed. Surprised improved only exploratorily and requires a fresh pre-registered holdout. |

## 9. Re-run recipes

- **Full shipped screen**: use `custom_delivery_matrix.py run` (§2), then rerun with
  `report` to validate sealed artifacts without generation. Candidate comparison requires
  the identical speaker/preset/seed identities and uses `compare` to emit paired exact
  outcomes; selection on that comparison requires a fresh holdout before promotion.
- **Focused sweep + score** (per arm): loop `bench --delivery` per seed (§2); collect archived
  sidecars whose manifest matches the arm's label and modelID; concatenate
  `records_from_sidecar(rows)` output into one records JSON; score with
  `delivery_separability.py --records … --label-mode preset --null-iters 1000
  --designation confirmatory --json`, plus `--presets …` for registered subset probes.
- **Blinded semantic confirmation** (operator-local; required only for a delivery-meaning
  promotion): `delivery_listening_session.py build --out DIR` from bench archives → `run`
  (afplay, resumable, keys sealed) → `score`; combine at least three pseudonymous listeners with
  `score-cohort`, then evaluate the untouched result with `delivery_promotion_decision.py`.
  Automatic analysis may reject before this step, but it cannot waive it. Setup and posture:
  [`testing-runbook.md`](testing-runbook.md).
- **Reference bank**: [`emotion-reference-banks.md`](emotion-reference-banks.md) —
  generation strictly before scorers on the 8 GB canonical machine; SER + identity +
  prosody scoring; honest refusal when no candidate passes.
- **SER advisory**: pinned model/revision, `.venv`, after-generation only —
  [`testing-runbook.md`](testing-runbook.md).

Constraint that governs all of the above: the canonical dev machine is the 8 GB M2 —
never run analyzer models concurrently with the engine; generate first, score after.
