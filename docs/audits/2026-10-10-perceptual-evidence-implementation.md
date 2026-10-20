---
status: historical
owner: backend-and-platform
summary: Installed-model QC v2 evidence for French pronunciation, expected phone paths and intervals and Clone register, its retained-clip verification and the held-out normalization fix; diagnostic only, with no qualified pass/fail decision.
sourceOfTruth:
  - scripts/qc/evidence.py
  - scripts/qc/pronunciation.py
  - scripts/qc/fit.py
  - config/roadmap.json
---
# Automatic audio-quality evidence: implementation and retained-clip verification

> Historical: QC v2 stays a report-only diagnostic, and for 3.0 nobody listens (maintainer decision
> 2026-10-13). [The QC reference](../reference/qc.md) holds the current contract; the follow-ups are
> parked under QC-06 in `config/roadmap.json`.

Date: 2026-10-10. Baseline: `9a1df218`. First integrated checkpoint: `17554ec9`.
This implements the installed-model/offline phase of the
[research recommendations](2026-10-10-automatic-audio-quality-research.md), following the
[generation-flow investigation](2026-10-10-generation-quality-investigation.md).

## Outcome and scope

QC can now expose narrow French pronunciation disagreements, score competing expected phone
paths from existing posteriors, inspect expected intervals independently of recognized errors,
and compare Clone register with an independent DSP witness. It can evaluate retained timed
candidates against explicitly annotated, group-disjoint private panels. The supervised fit's
held-out normalization leakage is corrected.

These are diagnostic and evaluation capabilities. The reported accent, whisper, liaison and
voice-fidelity problems have **not** become qualified automatic pass/fail decisions. No shipping
generation, decoder, finishing, model weights, dependency pins or release policy changed.
QC-06 remains in flight; QC-04, QC-08 and RF-14 remain open. No phone operation, acoustic model
inference, audio upload or model/data download was performed for this implementation.

## Implemented evidence flow

The ordinary [lane](../../scripts/qc/lanes.py) verifies take/reference audio digests and reads
current-identity model results. [Feature extraction](../../scripts/qc/features.py) decodes each
take once and passes its audio and cached outputs to [perceptual evidence](../../scripts/qc/evidence.py).
References are analyzed once per unique digest. New runs retain:

- `features.json`: existing detector features and legacy phonetic evidence, plus separate
  `perceptualEvidence` with posterior provenance, pronunciation, local acoustics, Clone pitch,
  Clone identity and explicit unsupported accent/intent decisions.
- `events.json`: exact audio/scoring/model identities, actual unrounded PCM duration, per-class
  coverage and timed pronunciation candidates with recognizer source and candidate type.
- Existing `flags.json`: the strict coverage/qualification decision contract remains authoritative.

`qc.py report --json` reads retained evidence without re-analysis. `qc.py run --cache-only`
recomputes diagnostics using installed cache bytes, with a new run identity. It does not invoke
an inference runner. Old runs and frozen calibration hashes are preserved.

The [scoring identity](../../scripts/qc/detectors.py) includes the new producer modules and
fidelity implementation. Consequently old thresholds do not silently qualify new scores.
Posterior loading checks the exact audio/model filename, rejects cache symlinks, bounds compressed
and expanded sizes, checks NPY headers before allocation, disables pickle and rejects malformed
arrays. Zero-probability negative infinity remains valid log-probability input. The digest records
the NPZ bytes actually read. Older runner envelopes do not attest their NPZ digest; this limitation
is explicitly retained rather than reconstructed retrospectively.

## French pronunciation hypotheses

[Pronunciation analysis](../../scripts/qc/pronunciation.py) preserves original IPA and a narrow
alignment separately from the broad legacy detector. It retains single-witness substitutions,
insertions, deletions and repeat candidates; agreement is optional evidence, not a requirement
that hides observations. Deletions without usable timing remain in the pronunciation artifact
and do not acquire invented event spans.

Each recognizer's existing CTC posteriors score the canonical expected path, bounded G2P optional
omission hypotheses and optional reviewed full paths from the private manifest. Optional G2P flags
are labeled heuristic: they do not grant linguistic permission for a liaison or an omitted sound.
Inventory tokenization requires full phone coverage and retains alternate tokenizations; an unknown
phone cannot silently disappear. Frame, vocabulary, state-cell, path, tokenization and operation
budgets produce explicit incomplete evidence.

Outputs include canonical/path likelihoods, constrained versus greedy sequence fit, entropy,
inventory coverage and canonical expected-phone occupancy windows, even when the recognized
sequence has no error. Stress, boundaries, ties and tones do not enter this CTC scoring view;
the original tokens remain available. Likelihood differences are model support, not calibrated
error probabilities or evidence of a speaker's native language. Current support does not establish
target-variety compliance or native French pronunciation.

## Acoustic localization and register

[Local acoustics](../../scripts/qc/acoustics.py) uses bounded NumPy frame batches without another
model. It measures energy, normalized autocorrelation, spectral flatness, spectral tilt, high/low
band ratio and a precisely defined cepstral peak contrast. The latter is not Praat CPP/CPPS and
must not be presented as a calibrated phonation metric.

The autocorrelation pitch track is independent of FCPE and SwiftF0. Its extraction correlation
setting is not a speech-quality threshold. Timestamps identify frame centers and full support;
silent, short, invalid and nonfinite inputs retain missing measurements rather than zero pitch.
Reference comparisons disclose compatible settings, periodic-frame coverage and content/channel/
prosody confounds. Periodic-frame count is not equivalent to voiced speech duration.

Expected and recognized timing windows preserve their recognizer identity. Strict phone crops
include only frames wholly inside the supplied interval. A uniform 250 ms discovery grid also
reports supporting frame overlap. The first retained run exposed how narrow CTC occupancy can
be: only 11 of 74 Design crops and 13 of 80 Dylan crops supported a full 60 ms frame. This is a
measurement-coverage limitation, not evidence that the other phones were unvoiced or absent.
A separate phone-centered context view addresses inspection of short intervals; its wider crop
can include neighboring phones and cannot attribute a spectral measurement to one phone alone.
Strict phone-only missingness remains intact.

## Retained-clip observations

The subsequent [regression-panel experiment](2026-10-10-retained-audio-regression-panel.md) recovered
byte-bound timed Dylan annotations from the existing training batch and added acceptable/objectionable
training comparisons. It documents the missed false start and candidate-count overlap; the observations
below are diagnostic measurements, not evidence of qualified defect discrimination.

All observations reuse the earlier private WAVs and cached model outputs. The first integrated
checkpoint produced the following immutable runs:

| Artifact run | Evidence | Observation |
|---|---|---|
| `qc-takes-20261010-230450-ff85` | French Design and Dylan | 13 and 27 timed single-witness pronunciation candidates; 74 and 80 expected acoustic crops; both posterior vocabularies available. |
| `clone-lane-20261010-230503-b4a9` | Existing English/French Clone pairs | Existing two-tracker offsets −1.843/+0.852 semitones; independent witness −0.772/+0.743. |
| `clone-lane-20261010-230518-2d6a` | Identity and octave/speed controls | Both pitch methods report 0 for identical audio; existing trackers +12.032, independent witness +11.881 for the transformed control. |

Every strict gate exited **4 (`NOT_ASSESSED`)**, with no execution error. The French candidates
are recognizer discrepancies, may overlap, and are not counts of confirmed defective syllables.
The previous zero-agreement result is preserved and is compatible with newly retained individual
witnesses. These data do not establish which candidates correspond to the documented whisper,
false start or over-linked liaison, nor their false-positive rate on acceptable French varieties.

The English Clone methods differ by about a semitone. That is useful uncertainty to inspect, not
a justified majority vote or a certified pitch error. The transformed control changes both pitch
and duration; it checks register sensitivity and is not a pitch-only or perceptual-fidelity control.
The exact recent user-observed failing reference/output pairs are still required for causal and
acceptance qualification. No listening judgment was added by the implementation.

## Held-out event evaluation and review corrections

[Qualification evaluation](../../scripts/qc/qualification.py), exposed through `qc.py qualify`,
accepts private `vocello.qc.panel/1` manifests. Panels bind audio, scoring, model runners,
annotation protocol, matching policy and explicit train/calibration/held-out groups for speaker,
reference, source, prompt and derived families. One digest-to-split index covers **both** take and
reference roles. A training take therefore cannot reappear as a held-out reference under another
group name. Declared groups still cannot prove complete model-training provenance.

Repeated same-class event annotations are supported. Event matching uses maximum-cardinality
one-to-one overlap matching. Unknown dimensions abstain; per-row pronunciation completeness cannot
stand in for an unsupported whisper or accent detector. Positive-only annotations cannot establish
precision or clean negatives. Reports separate input coverage, conditional recall, end-to-end misses,
event precision/recall and clean-clip false positives. Challenge panels describe an enriched sample,
not deployment prevalence. Current reports give point estimates and explicitly do not supply
acceptance qualification or uncertainty-based release tolerances.

Reports are immutable private artifacts with panel/run/evaluator digests and a versioned matching
contract. Existing evaluation identities are never overwritten. The command does not modify
thresholds, levels, public benchmark records or release gates. No observed annotations were invented
for the retained clips, and no real-failure precision/recall claim was generated from candidate counts.

Independent review reproduced and corrected malformed cache envelopes/inner phone lists, unbounded
recognized-window collection, lost timing-source attribution, manifest duration overriding measured
audio, rounded-duration incompatibility, cross-role split leakage and missing-dimension inheritance.
The [fit](../../scripts/qc/fit.py) now stores each fold's training-only normalization and evaluation
uses that exact transform. Unlabelled rows do not influence the final all-labelled fit either.
Historical supervised fits without this transform contract cannot be re-evaluated as leakage-free;
the separate human-reference path is preserved.

## Verification and remaining work

At the first integration checkpoint, routed `scripts/dev.sh check --since 9a1df218` passed
**2,207 tests and 2,597 subtests**, with one existing skip, plus contracts, privacy, roadmap and
invariant checks. The tree remained fixed during testing. Independent reviewers examined
pronunciation orchestration, reference/DSP handling, evaluation and fold transforms. The initial
sandbox-restricted fixture run could not bind localhost or inspect process memory; its justified
host-access rerun passed. No native build was selected for these Python-only changes. Hook delivery
was observed; doctor still cannot confirm persisted project trust.

The context-window refinement at `170eb020` received a fresh routed check: **2,211 tests and
2,597 subtests passed**, one existing skip, with contracts/privacy/invariants/roadmap passing.
Source remained fixed during the check; the added context view does not alter strict phone-only
or whole-clip measurements.

Final cache-only verification used clean source `cf3061eb`, after every worker completed:

| Final run | Result |
|---|---|
| `qc-takes-20261010-231206-aafb` | Design context 74/74, Dylan context 80/80 usable; strict crops remain 11/74 and 13/80. Timed candidates remain 13 and 27. |
| `clone-lane-20261010-231207-64e0` | Clone evidence retained with unchanged register, identity and reference comparisons. |
| `clone-lane-20261010-231208-d75d` | Identical and octave/speed control measurements unchanged. |

All final gates again exited 4 with current scoring identity. A structural comparison confirms
existing detector features, strict/recognized crops, discovery intervals, whole-clip acoustic
summaries, pitch tracks and reference comparisons are identical across the two rounds. Complete
context availability means that contextual statistics can be inspected, not that individual
phonation defects or quality dimensions have been assessed. The second receipt records the new
identity and rationale for re-analysis; the first runs remain intact. All roadmap statuses, gates,
dependencies and unblock conditions are unchanged from the baseline.

Raw run artifacts, command outputs, gate/report JSON and the clean source checkpoint receipt remain
ignored under `build/private/qc/perceptual-implementation-20261010/` and the referenced QC run
directories. Earlier failed/partial evidence remains preserved.

The next qualification work requires exact failing Clone pairs, representative acceptable French
varieties and localized genuine defects, declared intended delivery, independently assigned labels,
group-disjoint held-out evaluation and suitable uncertainty bounds. A new French phone challenger,
learned phonation/accent/intent judge or corpus installation remains a separate specifically
authorized acquisition. Shipping regeneration or decoder interventions require causal evidence
and a distinct product change. RF-14's release decision is unchanged.
