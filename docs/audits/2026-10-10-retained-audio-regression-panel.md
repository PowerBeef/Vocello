# Retained audio regression panel: annotated defects and detector limits

Date: October 10, 2026 (local). New cache-only analysis checkpoint: `545bc80a`.
This follows the [perceptual evidence implementation](2026-10-10-perceptual-evidence-implementation.md)
and [generation investigation](2026-10-10-generation-quality-investigation.md).

## Result

The retained private listening record contains exact, timed annotations for all three Dylan
defect classes. They can anchor a development regression case now; another listening pass over
that recording is unnecessary to recover the existing observations. The record is already in the
training split and has informed earlier investigations. It cannot become an independent test.

The installed tools expose useful acoustic evidence around the whispered syllable, but current
recognizer-event export does not recover the marked false start. Acceptable French comparisons
produce as many generic pronunciation candidates as objectionable clips. Counting those candidates,
requiring two recognizers to agree, or treating any overlap as a confirmed defect would not solve
the reported problem. There is still no qualified automatic native-accent or local-defect decision.

No shipping code, acceptance threshold, model, dependency, decoder or finishing behavior changed.
This batch assembled and analyzed existing evidence, preserving the protected split. QC-06 remains
in flight; QC-04, QC-08 and RF-14 remain open.

## Evidence recovered and verified

The source documents were rechecked against the original attachments. The emotion PDF has nine
pages; the earlier QC PDF has sixteen. Neither embeds an audio attachment. Their filename and
duration descriptions are useful provenance, but alone do not attest WAV identity. In particular,
the older PDF's gap/cutoff interpretation must not supersede later corrected listening evidence.

The stronger source is the private `batch-1` record:

- Its listening token maps through the retained batch inventory to the exact Dylan take used in
  the previous cache-only run. Current WAV bytes match that inventory's SHA-256.
- The record identifies the maintainer as rater, records full playback, and retains explicit severe
  labels with start/end times. Its protocol digest matches the current **canonical JSON** protocol
  digest used by [the label writer](../../scripts/qc/label.py). A raw file-byte hash is a different
  identity and must not be used to declare these labels stale.
- Its family split is `train`, consistent with the existing fixed family hash. It was deliberately
  enriched as an already heard stutter example. It is development evidence, not a blind discovery.

| Historical label | Retained interval | Interpretation boundary |
|---|---|---|
| `devoiced`, severe | 3.07–3.43 s | Existing whispered/devoiced-syllable annotation; not digital silence. |
| `mispronunciation`, severe | 2.16–2.84 s | Existing broad marked region; project history describes the liaison/inserted-vowel problem. This does not supply the inserted vowel's exact boundaries or a separately adjudicated subtype label. |
| `stutter`, severe | 3.92–3.98 s | Existing short marked event; project history describes the false start. It does not supply a new phonetic transcription. |

These are human-marked intervals, not sample-exact phone boundaries. Their uncertainty remains
material when matching a 20–40 ms recognizer token to a 360–680 ms annotated region.
The retained record recovers earlier observations; it is not new independent adjudication of the
defect subtypes or how those boundaries were chosen.

All 39 later confirmation records also map to intact, digest-verified WAVs and match the canonical
protocol digest. Their latest verdicts are 23 acceptable, 11 objectionable and five uncertain.
Thirty-three contain no class annotation; six contain only untimed class annotations. Combined with
Dylan, the inventory contains 40 reviewed clips and just three timed events, all on that one clip.
An acceptable whole-clip verdict does not establish absence of every local phenomenon. An objectionable
verdict without a class does not establish accent, whisper, liaison or Clone pitch ground truth.

The confirmation inventory retains 26 training and 13 held-out clips. Five of its fifteen voice
identities occur on both sides of that historical family split. This does not invalidate its stated
family-based partition, but it prevents representing the entire historical split as speaker-disjoint.
No new group IDs were invented to hide the overlap, and no historical splits were rewritten.

## Private panel and execution

The development inventory contains thirteen clips:

| Component | Count | Role |
|---|---:|---|
| Previously examined French Design and annotated Dylan | 2 | Existing challenge evidence; only Dylan has timed human labels. |
| Existing English/French Clone output-reference pairs | 2 | Exact pair measurements; no confirmed recent failing-pair label. |
| Identical-reference and octave/speed controls | 2 | Measurement sanity controls; not realistic Clone defects. |
| Previously acceptable French training clips | 3 | Whole-clip comparisons; not class-complete negatives. |
| Previously acceptable English Dylan training clips | 2 | Same Built-in voice comparison; not native-French controls. |
| Previously objectionable French Design training clips | 2 | Whole-clip failures; no confirmed accent subtype. |

The thirteen historical held-out confirmation clips were excluded from the new feature analysis.
Their provenance and audio identities were inventoried, but their scores were not used to select a
threshold. Existing acceptable French Design confirmations are held out, so none was borrowed as a
development control. This leaves a meaningful matched-control gap.

Seven added training comparisons were processed by the ordinary
[cache-only lane](../../scripts/qc/lanes.py), yielding `qc-takes-20261011-005911-3d20`
(run names use UTC). Execution completed with zero acquisition errors, zero fail/warn flags and three
report-only flags. The strict gate returned **4, NOT_ASSESSED**. No inference runner was invoked.
The original six clips reuse immutable prior runs rather than manufacture new measurement identities:

- `qc-takes-20261010-231206-aafb` — French Design and Dylan.
- `clone-lane-20261010-231207-64e0` — retained Clone pairs.
- `clone-lane-20261010-231208-d75d` — identical and octave/speed controls.

All four runs have the same scoring digest, verified against current source, and the same configured
model IDs/runner digests. Availability differs by lane. The development event panel binds only the
compatible French/comparison runs; Clone/control results remain separate supplementary evidence.
The private analysis's first raw-envelope comparison incorrectly included availability/count fields
and stopped before producing its report. A second analysis identity records the corrected comparison
and its reason; no native/QC failure or earlier run was overwritten.

Every known delegated worker was completed before analysis. Host preflight outside restricted process
inspection confirmed valid tracking, zero active workers, load 1.36 on twelve cores and normal memory
pressure. The tracked tree remained clean at `545bc80a` throughout measurements. This is an offline
diagnostic analysis, not a latency/memory benchmark or optimized native-generation qualification.

Private inputs, PDF hashes, annotation provenance, reproducible experiment script, source receipts,
run digests, acoustic output and check logs remain ignored under
`build/private/qc/regression-panel-20261010/`. No prompt, transcript, reference recording or listening
data was added to Git.

## What the installed evidence actually detects

### Whispered/devoiced region

The [independent acoustic analyzer](../../scripts/qc/acoustics.py) provides 31 complete 60 ms analysis
frames, overlapping at 10 ms hops, inside the marked 360 ms interval. These are correlated frames,
not 31 independent examples. Its median measurements are:

| Measurement | Marked whisper interval | Whole Dylan clip |
|---|---:|---:|
| Level | −34.10 dBFS | −31.68 dBFS |
| Normalized autocorrelation | 0.307 | 0.723 |
| Spectral flatness | 0.131 | 0.055 |
| High/low band ratio | +17.62 dB | −16.28 dB |
| Periodic pitch candidate fraction | 0 | 0.562 |

The interval contains measurable energy with reduced periodicity and different spectral balance.
This is useful support for investigating phonation, rather than the invalid silence diagnosis.
Both recognizers' expected-phone occupancy paths place the expected `/y/` inside this human-marked
region, even though that expectation is not acoustic truth. It supplies a concrete entry point for
an expected-vowel phonation detector.

The generic event export contains one overlapping insertion candidate at 3.28–3.32 s, with maximum
intersection-over-union 0.111 against the broad annotation. It does not identify whisper. Low pitch
coverage alone cannot distinguish whisper from a fricative, noise, weak recording, alignment error
or tracker failure; an expected vowel and the request's permitted delivery are essential context.

### False start

No exported pronunciation candidate overlaps 3.92–3.98 s. Neither recognizer supplies an expected
phone window there. A method restricted to recognized errors or expected phones therefore has a
blind spot precisely where the retained human marked a short false start.

The strict acoustic crop contains only one complete 60 ms frame: −29.34 dBFS, normalized
autocorrelation 0.569, and no periodic pitch candidate at the current extraction floor. A wider
120 ms context yields three periodic candidate frames among seven and a roughly 454 Hz median.
That context crosses the annotated boundaries. It cannot establish the false start's F0 or classify
it as voiced/unvoiced. Reporting zero Hz, silence or a confident pitch from either crop would be wrong.

The next candidate producer needs an independent scan of inter-word/non-aligned audio, with shorter
energy/spectral windows and longer contextual periodicity support. A local speech-like burst between
quiet spans can nominate a region; an extra speech fragment requires a separate sequence/content
check. Breath, plosives, natural hesitation and ordinary word transitions remain comparison cases.

### Liaison/inserted-vowel region

Four generic phone candidates overlap 2.16–2.84 s: three from one recognizer and one from the other.
Their maximum individual overlap ratio against the broad human annotation is only 0.059. The acoustic
crop is mostly periodic (62 of 63 frames) with median F0 about 114 Hz. Nothing in those values identifies
an inappropriate liaison or inserted vowel: correctly pronounced speech can look the same acoustically.

This needs a reviewed word-boundary pronunciation hypothesis and evidence for an extra vowel-bearing
segment, rather than a global phone-edit count or a requirement that recognizers agree. The existing
annotation is a broad positive region; it does not authorize substituting model timings for the actual
inserted-vowel boundaries. Native variety and permitted liaison alternatives must remain explicit.

### Acceptable comparisons

| Prior whole-clip verdict | Language/voice category | Timed generic pronunciation candidates |
|---|---|---:|
| Acceptable | French, Built-in comparison A | 29 |
| Acceptable, with an untimed mild pause annotation | French, Built-in comparison B | 18 |
| Acceptable | French, Built-in comparison C | 19 |
| Objectionable | French, Design comparison A | 26 |
| Objectionable | French, Design comparison B | 19 |
| Objectionable, three timed labels | French, Dylan challenge | 27 |

The two acceptable English Dylan clips produce no timed French pronunciation candidates because
this producer supports French. That is a support boundary, not evidence of their superior quality.
These small, selected counts do not estimate a false-positive rate. They do directly show why a
simple nonzero-candidate/count rule cannot separate these available acceptable and objectionable clips.
They also do not establish whether either objectionable Design clip has an Anglophone accent.

### Clone register

The exact retained pairs preserve the preceding measurements:

| Evidence | FCPE/SwiftF0 agreeing-track offset | Independent autocorrelation offset |
|---|---:|---:|
| English Clone pair | −1.843 st | −0.772 st |
| French Clone pair | +0.852 st | +0.743 st |
| Identical audio/reference | 0 st | 0 st |
| Octave/speed control | +12.032 st | +11.881 st |

These support signed measurement and a large transformation sanity check. The transformed control
also changes duration; it is not a pitch-only perturbation. Only 1.26/1.17 s of generated speech has
two-tracker agreement for the retained English/French pairs. Content, prosody, channel, phonation and
tracker disagreement remain confounds. Neither pair is established as the user's recent wrong-register
failure. No perceptual tolerance can be learned from these four examples alone.

## Qualification outcome and next engineering work

The development panel records the three historical events as positive-only annotations; other
classes remain unreviewed or uncertain. Whole-clip acceptable labels were not expanded into complete
negative annotations. Exported events use the generic `pronunciation` class, while historical labels
use `devoiced`, `mispronunciation` and `stutter`. There is no justified automatic alias from that
generic class to any of the three semantic defects; their class-specific producers remain unsupported.
Its event evaluator correctly refused to report held-out metrics with
`panel has no protected heldout takes`. No held-out precision, recall, false-alarm rate or acceptance
qualification is claimed. Changing this guard or relabeling exposed clips would hide the evidence gap.

The next implementation should be narrow and measurable:

1. **Phonation candidates:** condition on eligible expected vowels/sonorants, use periodicity plus
   spectral/energy evidence, retain alignment and request-delivery uncertainty, and scan beyond emitted
   recognizer errors. The recovered whisper interval is a development regression anchor.
2. **Unaligned short-fragment candidates:** add an independent inter-word burst scan with explicit
   support at multiple time scales. The 60 ms false-start annotation demonstrates a miss to fix;
   one analysis frame is insufficient for a confident phonation judgment.
3. **Boundary pronunciation candidates:** compare reviewed word-boundary alternatives and local vowel
   evidence. Preserve a generic mispronunciation annotation until the liaison subtype and its boundaries
   are independently established. Raw candidate counts and two-model agreement are inadequate.
4. **Clone fidelity qualification:** obtain byte-bound, genuinely failing output/reference pairs and
   matched acceptable pairs, then declare reference adequacy and tolerances by relevant speaker/style
   slices. Preserve the installed independent witness; adding another generic quality judge does not
   repair missing paired ground truth.
5. **Independent validation:** retain the existing protected clips and family partition, explicitly
   account for speaker/source overlap, and use independently labeled examples for new defect classes.
   Existing labeled corpora can reduce fresh listening where their labels, provenance and usage terms
   support the claim. This task authorizes no new corpus/model downloads. Initial qualification needs
   trustworthy labels; the intended future per-clip detection can run automatically without new listening.

No new plugin or model is needed to start the first two candidate producers. Their quality decisions
must remain report-only until independent data demonstrates useful discrimination. Shipping a generation
repair or regeneration policy still requires causal replay and the existing release-quality decision.

**Verification:** 47 targeted qualification/acoustic tests plus 38 subtests passed. Routed checks passed
contracts/privacy/invariants/strict roadmap validation and **2,211 tests plus 2,597 subtests**, with one
existing skip. The first restricted run failed on fixture sockets/process inspection; its log is retained
alongside the justified host-capable rerun. Final prose received a separate contracts-only check.
The new cache-only comparison run retained zero acquisition errors and strict gate exit 4. No native
build, phone operation, new listening, cloud audio upload or dependency download was performed. Hook
delivery was observed; `doctor` still reports persisted hook activation as unconfirmed.
