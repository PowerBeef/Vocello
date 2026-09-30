---
status: active
owner: backend-mlx
reviewed: 2026-09-29
summary: The audio QC threshold-change authority - the five carried-over rules, A1-A10, label tiers, populations, statistics, operating points and status transitions - rendered from config/audio-qc-qualification-policy.json.
sourceOfTruth:
  - config/audio-qc-qualification-policy.json
  - scripts/audio_qc_qualification.py
  - scripts/audio_qc_docs.py
---
# Audio QC qualification policy

A detector's threshold changes, and a detector gains or loses gating status, only under this
policy. The config is the authority and `scripts/audio_qc_qualification.py validate-policy` checks
it in the contract gate (sample sizes recomputed, fail stricter than warn, verdict vocabulary and lane
gating sets held to the composer's); this page renders it. The reasons behind each rule are in the
[audit](../../audits/2026-09-25-audio-qc-speech-analysis-audit.md), sections 5.1-5.9, and in
[audio-qc-engineering.md](../audio-qc-engineering.md#threshold-change-authority).

<!-- BEGIN GENERATED audio-qc-docs:policy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Rendered from [config/audio-qc-qualification-policy.json](../../../config/audio-qc-qualification-policy.json) (`audio-qc-qualification`, status `adopted`, adopted 2026-09-25).

- Decision 5: (a) warn at the existing 60/60/60 floor; fail at one-sided Clopper-Pearson FAR <= 1% pooled and <= 5% per language on N2 for any product-affecting fail, with (b) acceptable for evidence-lane gating only
- Decision 7: A1-A10 adopted into this file; Swift gains the abstained outcome

### The five authority rules

Source: the retired audio-cadence-qc-contract.json, carried over verbatim on 2026-09-12.

1. an untouched confirmation cohort is required (requiresUntouchedConfirmation)
2. independent reference evidence is required, independent human labels are not (requiresIndependentReferenceEvidence, requiresIndependentHumanLabels: false)
3. automatic metrics may screen candidates only, never qualify a change (automaticMetricsMayScreenOnly)
4. a source change requires an explicit review (sourceChangeRequiresExplicitReview)
5. the current boundary remains authoritative until a change is qualified (currentBoundaryRemainsUntilQualified)

### Additions A1-A10

| Id | Title | Rule |
|---|---|---|
| A1 | Scope-bound status | A detector gates only inside the scope of a qualified record (languages, modes, length class, F0 band, phonation). Outside it, the verdict is abstain (out-of-scope). |
| A2 | In-domain FAR | FAR must be confirmed on N2 and bounded on N3. N1 alone never qualifies fail. |
| A3 | Cross-mechanism TPR | The TPR bound must hold on at least two construction mechanisms, one of them not used for fitting. |
| A4 | Shams | Every processed-positive family has a matched sham. A sham FAR that departs from the N2 FAR beyond interval overlap refuses the detector. |
| A5 | Pre-registration | The rule, grid, alpha, strata and split are committed by digest before the confirmation cohort is scored. Confirmation runs once, with no top-ups. |
| A6 | No same-lineage labels | T5 labels never come from a judge that shares family, vendor lineage or label lineage with a consumed judge. This generalizes detectorSelfLabelsAllowed: false (config/prosody-holdout-policy.json). |
| A7 | Automatic de-qualification | Any change to a consumed judge's output identity, the metric definition or the rule reverts the detector to shadow. The registry enforces this by digest. |
| A8 | Status-specific operating points | Fail is stricter than warn (operatingPoints). |
| A9 | Heard defects | A defect the maintainer hears enters Stage 0 or 1 as a shadow detector with a test, and the heard takes become P4 positives. It fails takes once it qualifies under A1-A8. |
| A10 | Legacy bounds | Existing Fast QC fail bounds stay, labeled legacy-unqualified, with their measured FAR and TPR reported from M1 onward. A bound is replaced only by a qualified successor, never removed on evidence of weakness alone. |

### Label tiers

| Tier | Source | May qualify | May not qualify |
|---|---|---|---|
| T1 | PCM construction: a registered injector, verified by recipe replay (source digest, injector version, parameters, seed -> output digest) | TPR for that signal event, sham FAR | perceptual severity, realism |
| T2 | Codec construction: a code-trace mutation decoded by the production decoder, verified by trace, recipe and decoder digests | TPR in the product's acoustic domain | LM-origin pathologies |
| T3 | Controlled generation: a registered knob with a certain effect (token cap, EOS suppression, L2 text with L1 pinned) | natural positives for truncation, run-on and wrong language | any probabilistic knob (temperature, top-p) |
| T4 | Published labels: corpus transcripts and metadata | negatives for content, language and identity, SV trials | that a recording is defect-free |
| T5 | Cross-modal: a qualified detector of another modality and another family labels natural takes | confirmation cohorts | sole evidence for a new fail bound, any same-lineage label |
| T6 | Human annotation (optional): the existing speech-defects-1 protocol | as today | - |

### Populations

| Population | Content |
|---|---|
| N1 | Human originals with verified text |
| N2 | N1 resynthesized through the Qwen3-TTS tokenizer at full codebooks; FAR in domain |
| N3 | Natural Vocello takes over the script pool; with no labels, FAR <= f / (1 - pi_max) |
| S | Shams: the same processing at zero magnitude |
| P1 | PCM injections |
| P2 | Codec injections |
| P3 | Knob takes |
| P4 | Harvested natural failures with T5 labels |

### Statistics

- Method `clopper-pearson-one-sided` at confidence 0.95; legacy `wilson-two-sided` for records published before this policy; new claims use Clopper-Pearson.
- Unit of independence: `source-family`; crops, injections and resyntheses of one utterance are one family; one script x voice x seed is one Vocello family, deduplicated by PCM digest.
- Multiplicity: `bonferroni`; a per-language bound is a simultaneous claim over the languages it covers, so it holds at 1 - (1 - confidence) / languages; each operating point states that confidence for its minimum language count, and a claim over more languages uses more.

| Target bound | CP, 0 errors | CP, 1 errors | CP, 2 errors | CP, 5 errors | Wilson, 0 errors |
|---|---|---|---|---|---|
| 0.2 | 14 | 22 | 30 | 50 | 16 |
| 0.1 | 29 | 46 | 61 | 103 | 35 |
| 0.05 | 59 | 93 | 124 | 208 | 73 |
| 0.02 | 149 | 236 | 313 | 523 | 189 |
| 0.01 | 299 | 473 | 628 | 1049 | 381 |

### Operating points

| Field | `warn` | `fail` | `evidenceLaneFail` | `shadow` |
|---|---|---|---|---|
| `farPooledMax` | 0.1 | 0.01 | 0.02 | - |
| `farPerLanguageMax` | 0.2 | 0.05 | 0.1 | - |
| `tprSevereMin` | 0.7 | 0.9 | 0.9 | - |
| `cleanAbstentionMax` | 0.1 | 0.05 | 0.05 | - |
| `perLanguageConfidence` | 0.983333 | 0.995 | 0.995 | - |
| `minimumUnits` | calibration=60, good=60, bad=60, speakers=3, scripts=3, languages=3 | n2Negatives=1240, n2NegativesPerLanguage=124, languages=10, n3NegativesPerLanguage=60, positivesPerCell=60, cell="subtype x severity x mechanism" | n2Negatives=510, n2NegativesPerLanguage=51, languages=10, n3NegativesPerLanguage=60, positivesPerCell=60, cell="subtype x severity x mechanism" | - |
| `appliesTo` | - | ["product", "evidence-lane"] | ["evidence-lane"] | - |
| `farPopulation` | - | "N2" | "N2" | - |
| `n3FlagRateMax` | - | 0.05 | 0.05 | - |
| `n3FlagRateScope` | - | "pooled" | "pooled" | - |
| `tprModerateMin` | - | 0.7 | 0.7 | - |
| `mechanismsMin` | - | 2 | 2 | - |
| `productAffecting` | - | - | false | - |
| `blocks` | - | - | - | false |
| `countsAsPass` | - | - | - | false |

- `physicalEventsT1Only`: non-finite samples, digital silence, clipping above full scale, dc offset

### Threshold derivation

- `split`: calibration and confirmation cohorts disjoint by family, speaker and script
- `unitOfRates`: source family: a family counts once, as an error if any of its clips errs (a false alarm on a negative, a miss or an abstention on a positive)
- `commitment`: the plan file is committed in Git under config/audio-qc-preregistrations/ before any confirmation score exists; the derivation reads it
- `confirmationLedger`: one record per plan digest under config/audio-qc-preregistrations/, created exclusively, qualified or refused; a second confirmation of a digest is refused
- `fitOn`: clean-negatives-only
- `singleThresholdRule`: split-conformal
- `multiParameterRule`: learn-then-test-fixed-sequence
- `tprOptimized`: no
- `requiresPreRegistrationDigest`: yes
- `stratificationRequiresDeclaredReason`: yes
- `missedStratum`: scope-exclusion
- `confirmOnce`: yes
- `rederivationWritesNewRecord`: yes

### Status transitions

- `judgeStatuses`: candidate, shadow, warn, gating, retired, quarantined
- `toShadow`: two clean canonical-host resource runs, a measured determinism class and a canary record matching the output identity
- `toWarn`: a qualified calibration record at the warn operating point for the declared scope (A1-A8)
- `toGating`: a fail-level record on two mechanisms (A3), shams (A4), a phi audit of consensus partners and an N3 bound (A2)
- `backToShadow`: an output-identity, metric or rule change (A7), a canary mismatch or confirmed judge drift
- `toQuarantined`: a license or terms change, or digest drift at acquisition; execution stops until a decision
- `consensusRequiresPhiAudit`: yes
<!-- END GENERATED audio-qc-docs:policy -->
