---
status: active
owner: backend-mlx
summary: Operator's reference for the audio delivery analysis harness — the tools, the bench --delivery measurement protocol, evidence and provenance conventions, the statistics the separability scorer reports, the pre-registration discipline, the DP results ledger, and re-run recipes.
sourceOfTruth:
  - scripts/delivery_separability.py
  - scripts/bench_delivery_prosody.py
---
# The audio delivery analysis harness

> The consolidated operator's reference for measuring delivery/emotion quality without
> human listening. Everything here is deterministic and scriptable; human listening is
> optional calibration, never a gate (root `CLAUDE.md`, "Audio QA is autonomous").
> The program's item-by-item status and pre-registered results live in
> [`config/roadmap.json`](../../config/roadmap.json) (`delivery-prompting-2026-08` plan);
> the adversarial audit that shaped this harness is pinned at
> [`delivery-control-audit-2026-08.md`](delivery-control-audit-2026-08.md).

## 1. Tool inventory

Only `check_delivery_instructions.py` runs in the deterministic commit/CI gate; everything
else is an explicit measurement lane. Test files live under `scripts/tests/` and run in
the script self-test suite via `scripts/check_test_workflows.sh`.

| Tool | Purpose | Tests |
| --- | --- | --- |
| `scripts/delivery_separability.py` | Cross-preset separability: ridge-LDA over paired signed features, seed-grouped CV, UAR, computed chance floor, permutation null, Wilson intervals, per-cell BH-FDR, `--presets` subset probes | `test_delivery_separability.py` |
| `scripts/bench_delivery_prosody.py` | Post-processes the current `vocello bench --delivery` run from its immutable manifest into `bench-prosody.json`; fail-closed instruction-receipt provenance (§4) | via `test_bench_command_contract.py` |
| `scripts/delivery_listening_session.py` | Build / run / score the blind 2AFC + free-identification listening session from bench archives; sealed keys, pre-registered exact-binomial decision rules | `test_delivery_listening_session.py` |
| `scripts/build_emotion_reference_bank.py` | Generate → score → select → enroll curated per-emotion VoiceDesign reference banks (design-then-clone) → [`emotion-reference-banks.md`](emotion-reference-banks.md) | `test_build_emotion_reference_bank.py` |
| `scripts/emotion_advisory.py` | Advisory SER agreement column (pinned wav2vec2-XLSR checkpoint + revision); never a gate, never publication input → [`testing-runbook.md`](testing-runbook.md) | `test_emotion_advisory.py` |
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
  --warm 1 \
  --delivery neutral.strong,happy.strong,sad.strong,angry.strong,fearful.strong,surprised.strong,calm.strong,whisper.strong \
  --seed 20260810 --label "my-sweep-arm-label"
```

- **Cells** are `<preset>.<intensity>` over the live roster (`EmotionPreset.all`); a bare
  preset name defaults to `.strong` (DP-8 ship-strong). Every cell generates one
  instructed warm take on the medium text.
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
- A take that fails the engine's mandatory fast audio QC aborts that seed's run. Fixed
  seeds make such casualties deterministic — re-running the seed reproduces the failure,
  so the honest handling is to drop the seed and record the coverage (no silent caps).

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
codified in §6: exercise every new fail-closed check live in the arc that lands it.

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

## 6. Pre-registration discipline

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

## 7. Results ledger (headline numbers; the roadmap gate is the authority)

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

## 8. Re-run recipes

- **Sweep + score** (per arm): loop `bench --delivery` per seed (§2); collect archived
  sidecars whose manifest matches the arm's label and modelID; concatenate
  `records_from_sidecar(rows)` output into one records JSON; score with
  `delivery_separability.py --records … --label-mode preset --null-iters 1000
  --designation confirmatory --json`, plus `--presets …` for registered subset probes.
- **Listening calibration** (operator-local, never a gate):
  `delivery_listening_session.py build --out DIR` from bench archives → `run` (afplay,
  resumable, keys sealed) → `score`. Setup and posture:
  [`testing-runbook.md`](testing-runbook.md).
- **Reference bank**: [`emotion-reference-banks.md`](emotion-reference-banks.md) —
  generation strictly before scorers on the 8 GB canonical machine; SER + identity +
  prosody scoring; honest refusal when no candidate passes.
- **SER advisory**: pinned model/revision, `.venv`, after-generation only —
  [`testing-runbook.md`](testing-runbook.md).

Constraint that governs all of the above: the canonical dev machine is the 8 GB M2 —
never run analyzer models concurrently with the engine; generate first, score after.
