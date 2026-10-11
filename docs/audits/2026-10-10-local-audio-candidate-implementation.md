# Local phonation, fragment and boundary evidence implementation

Date: October 10, 2026 (local). Implementation checkpoint: `5b141b4c`.
Follows the [retained regression panel](2026-10-10-retained-audio-regression-panel.md),
[perceptual evidence implementation](2026-10-10-perceptual-evidence-implementation.md)
and [automatic detection research](2026-10-10-automatic-audio-quality-research.md).

## Result and qualification boundary

Three bounded candidate producers now address the next implementation targets: acoustic
phonation evidence around expected vowels/sonorants, isolated short energy bursts outside
recognizer timing, and French vowel-bearing evidence at verified word joins. Ordinary QC runs
retain their measurements, coverage, candidate timing and uncertainty in existing private artifacts.
No extra inference model, download, runtime dependency or shipping generation change is involved.

These are **uncalibrated observation producers**, not qualified whisper, stutter, wrong-liaison,
Clone-fidelity or native-accent detectors. Existing broad historical defect labels have not been
renamed to match their output. No acceptance policy, Fast QC gate, model conditioning, sampling,
decoder behavior or automatic regeneration changed. QC-06 remains in flight; QC-04, QC-08 and
RF-14 remain open. The held-out confirmation recordings remain protected.

## Implemented flow and ownership

The normal [lane](../../scripts/qc/lanes.py) still verifies exact output/reference WAV digests
and current runner identities before feature extraction. Cache-only mode continues to skip runner
execution. [Evidence assembly](../../scripts/qc/evidence.py) uses the existing French pronunciation
diagnostic and canonical CTC expected-phone occupancy windows; recognizer errors are not required
to supply a target window. Recognized timing comes separately from either cached phone recognizer.

The [acoustic analyzer](../../scripts/qc/acoustics.py) retains its existing strict crops, contextual
crops, discovery grid, spectral measurements and independent pitch witness. Its shared internal
frame profile feeds [the acoustic producers](../../scripts/qc/candidates.py); the fragment producer
adds a bounded, shorter energy scan. [The boundary producer](../../scripts/qc/boundary.py) reads
complete narrow alignments and exact word membership, rather than guessing word boundaries from
error positions. Acoustic nomination consumes no human labels; boundary comparison consumes only
explicit reviewed paths. No producer rewrites a recording.

`features.json` retains the full producer results. `events.json` exports separately named timed
classes with candidate type, source, target provenance, acoustic values and uncertainty. Per-class
dimensions retain producer coverage/reasons and remain not assessed. PCM duration is the event
bound; a manifest hint cannot authorize an event beyond actual audio. Missing or invalid timing
does not borrow annotation or expected-phone timing. Rejected/truncated export makes coverage
partial, with explicit loss counts.

Both new source modules participate in [scoring identity](../../scripts/qc/detectors.py), alongside
the evidence and acoustic implementation. Historical runs/calibrations remain immutable and cannot
silently become compatible with this source. Recomputing existing caches must receive new run IDs.

## Phonation producer

The `phonation-anomaly` class has candidate type `expected-sonorant-low-periodicity`.
Eligible targets are canonical vowels plus `/m n ɲ ŋ l j w ɥ/`. Rhotics and fricatives are not
assumed to be voiced targets. This is a deliberately limited extraction inventory, not a complete
phonation model or a universal linguistic rule.

With default acoustic settings, frames have 60 ms support and 10 ms hops. The producer selects
frame centers within 120 ms around an eligible target's center. Its exported event covers full
support of the selected acoustic frames, which can extend approximately 30 ms beyond either side
of that center-selection interval. A 120 ms selection interval does not imply phone-only support.
The actual analyzer settings and candidate start/end remain available in the evidence.

Nomination requires correlation below 0.6, plus spectral flatness above 0.08 or high/low band
ratio above 0 dB, and level above the larger of −70 dBFS and whole-clip median level minus 25 dB.
At least two contiguous selected frames are required. These fixed extraction settings are recorded
and source-bound; they are not calibrated perceptual thresholds. Overlapping frames are correlated
observations, not independent samples.

Availability is checked **inside each target context** using joint finite periodicity and spectral
support. A tone elsewhere in a clip cannot make a silent target complete. No supported target
means unavailable; mixed supported/unsupported targets mean partial. Zero F0 is never substituted
for missing pitch, and silence is not nominated as whisper. Duration, eligible target count and
supported target count remain distinct from a quality verdict.

The output can still nominate normal contextual devoicing, neighboring unvoiced consonants, breath,
noise or alignment error. A genuinely whispered portion with no eligible expected window, incorrect
CTC timing, unsuitable bandwidth, too little support or signal below the level floor can be missed.
The whole-clip relative floor also cannot represent every local loudness condition. These limits
must be tested independently before a semantic whisper/devoicing decision exists.

## Short-fragment producer

The `short-fragment` class has candidate type `isolated-unaligned-burst`. It scans the full decoded
mono WAV with 20 ms RMS windows and 5 ms hops, rather than restricting discovery to recognizer
errors. The energy floor is the larger of −65 dBFS and the 80th-percentile frame level minus 20 dB.
Contiguous above-floor frame support must span 20–200 ms. Both flanks use existing full frames
within 80 ms, with at least eight on either side, and peak/flank contrast must reach 6 dB.
Edges receive no invented quiet padding.

Only after this acoustic nomination does the producer check expected and recognized timing.
Overlap with **either** inventory within a 20 ms margin suppresses the unaligned candidate and
increments the aligned-burst count. Missing inventories yield partial coverage and an `unknown`
alignment designation. CTC occupancy is not complete speech coverage; a recognizer's coverage does
not prove that an underlying syllable is correct.

The longer acoustic profile contributes an explicitly contextual maximum correlation. It is not
attributed to the burst alone, and no F0-presence test is required. An isolated click, breath or
hesitation may nominate just as an actual false start can. Connected bursts, weak events, insufficient
quiet flanks, events beyond 200 ms or masked by surrounding energy can be missed. Window support
can also merge nearby activity. The producer is not yet an extra-syllable or stutter classifier.

## Boundary pronunciation and the canonical-vowel blind spot

The `boundary-pronunciation` class has two descriptive candidate forms:

| Candidate type | Required evidence | Interpretation limit |
|---|---|---|
| `vowel-bearing-boundary-insertion` | Complete narrow alignment inserts a vowel at a verified join, or inside a disclosed contiguous optional suffix of at most two phones. | A recognizer insertion is not acoustic proof or a wrong-liaison verdict. |
| `reviewed-boundary-vowel-disagreement` | A provenance-bearing reviewed full path omits a canonical vowel near a verified join, and a recognizer supplies a timed canonical match. | A realized vowel differing from a reviewed path is not automatically unacceptable. |

Word phone membership must exactly cover the canonical narrow sequence. Multi-base IPA tokens are
segmented before indexing joins; deletions and substitutions cannot shift a guessed raw index.
Both recognizers remain separate witnesses. A second recognizer's disagreement does not erase a
single-witness candidate. Partial, corrupt or truncated alignment abstains.

The retained investigation identified an important limitation of insertion-only detection: canonical
G2P already includes an optional vowel in the disputed phrase. Realizing that vowel may produce
no insertion error at all. The implementation therefore supports a **reviewed comparison**; it
does not assume that optionality licenses a liaison, or manufacture a preferred pronunciation
from the historical broad annotation.

A private take may supply `boundaryPronunciationHypotheses` as documented in the
[QC runbook](../reference/qc.md). Each full alternative binds an opaque ID, canonical narrow join
index, full phone path, reason and human-reviewed provenance. The provenance includes source SHA-256,
annotation ID, opaque reviewer ID and target variety. Changes must stay within two canonical phones
on either side of the specified join. Source/reviewer authenticity must be checked by the caller:
the pure function validates bounded structure and identity syntax, not real-world review authority.

The implementation records reviewed-comparison availability separately from canonical insertion
coverage. Complete canonical scanning with no hypotheses does **not** mean the reviewed-vowel
capability was available. Exact full recognized-path matches remain comparisons, not acceptance.
No reviewed hypothesis was created for Dylan in this implementation: the retained broad marked
interval does not provide independent, precise pronunciation adjudication.

## Resource and evidence bounds

Acoustic producers accept at most 120 s, 2,048 timing windows and 128 candidates each. Phonation
retains at most sixteen target provenance records per event, reporting truncation as partial.
The energy scan processes bounded batches rather than materializing all raw windows at once.
Invalid/non-finite, out-of-normalized-range or stereo input is rejected upstream.

Boundary analysis accepts at most 512 phones, 256 operations per recognizer, 256 total candidates,
sixteen reviewed paths and 120 s. Every candidate's finite positive interval must fit actual audio
before event export. The existing analyzer's configurable longer duration budget cannot silently
expand these candidate budgets.

Private prompts, transcriptions, recordings, labels, reviewer identities and raw output remain under
ignored storage. No new public fixture is derived from private listening material. Deterministic
synthetic signals exercise extraction behavior without claiming that synthetic noise is a human
whisper or a tone burst is an actual stutter.

## Validation and independent review

Focused integration verification passed 86 tests and 91 subtests before the two review corrections.
Correction-focused tests passed 43 tests and 30 subtests. The final full routed check passed
**2,248 tests and 2,636 subtests**, with one existing skip, plus contracts, privacy, invariants and
strict roadmap/render freshness. No native build was selected for this Python/documentation change.

The first broader check failed an explicit scoring-source expectation in the calibration test:
the implementation correctly added the new modules, but that test still expected the old set.
The expectation was updated, and the justified second run has its own retained log. The earlier
failure was not overwritten.

Independent read-only review found two P2 coverage problems, both fixed and rechecked:

- Whole-clip signal availability could incorrectly make a silent expected target complete.
  Target-local joint support now controls availability; tests cover silence, mixed support and
  custom frame grids with no target centers.
- Invalid/truncated candidate export could discard observations while claiming complete input.
  Export now records loss counts and makes that class partial. Producer coverage and reasons
  also survive export, including missing reviewed comparisons.

Behavioral tests cover periodic vowels, unvoiced contexts, silence, noise away from eligible targets,
alignment-independent bursts, either-inventory overlap, edge/long events, malformed timing, budgets,
multi-base/nasal IPA, optional suffixes, reviewed provenance, canonical reviewed-vowel disagreement,
missing recognizers and corrupt/untimed alignments. None establishes deployed accuracy.

## Retained-audio regression: blocked before execution

This section records the initial attempts. The authorized cache-only follow-up below completed
the regression after changing the host-posture policy; the four original refusal logs remain intact.

Four separately retained host preflights refused execution at the clean implementation checkpoint.
All confirmed available worker tracking with zero active workers, zero stale records and zero unknown
records. Load was within the twelve-core limit; kernel memory-pressure level remained **2 (warning)**,
above the required normal level **1**. No audio run or inference started. A read-only free-memory
query does not supersede that kernel-pressure criterion, and unrelated applications were not stopped.

The repository [benchmark skill](../../.agents/skills/vocello-benchmark/SKILL.md) requires:
“Join/stop workers first, keep host-wide native serialization and load/memory preflight.” The actual
[host guard](../../scripts/lib/host_preflight.sh) refused the run. Its busy-host override requires
an explicit request; it was not used. This is an execution limitation, not a product defect or a
candidate accuracy result. No claim is made that these producers recover the Dylan whisper, marked
false start or disputed vowel on the actual recording. All previous evidence remains intact.

Ignored `build/private/qc/local-candidates-20261010/` retains test logs, the initial failed check,
its successful rerun, doctor inventory, four preflight refusals, a digest-bound verification receipt,
and the prepared private development-only regression script. There is no new experiment result,
new QC run identity or gate exit to report. Doctor continues to report hook activation unconfirmed;
hook delivery alone does not certify persistent trust. Installed Xcode/GitHub CLI pin mismatches
remain inventory limitations and did not prevent this Python-only check.

The prepared script validates a successful normal-pressure preflight before writing a source receipt,
then requires a committed clean source and excludes all protected held-out tokens. Its analysis checks
annotation/protocol byte bindings, unchanged pre-existing measurements and generic event counts, exact
WAV/reference identities, current scoring bindings and class-agnostic historical overlap. It is prepared
work, not executed validation. Use a new preflight filename when resuming; never overwrite refusals.

## Next qualification work

The thirteen-clip cache-only development regression completed in the authorized follow-up below.
Its source/run identities, exact WAV/reference bytes, scoring/model bindings, strict gate exits and
artifact digests are retained. Existing measurements are unchanged. New nominations overlap historical
windows as descriptive training evidence; they are not qualified semantic detections.

Obtain independently reviewed phonation/fragment/boundary definitions and appropriate positives,
complete negatives and uncertainty labels. Reviewed boundary paths need genuine linguistic annotation
for the target variety. Keep prototype-exposed Dylan in training, retain the thirteen old protected
confirmations, and address the historical speaker overlap when creating a new disjoint evaluation.
Select/calibrate extraction and decision settings using development data only; freeze before protected
evaluation. Report misses and confounds rather than tuning until this one known recording is hit.

Exact recent failing Clone output/reference pairs, matched acceptable French Design controls,
independently labeled accent examples and causal generation replay remain separate missing evidence.
These producers do not fix pitch conditioning or non-native French generation, and a language detector
recognizing French would not by itself validate native accent. New models/downloads or production
generation interventions need their own scoped work and existing authorization boundaries.

## Authorized cache-only follow-up

The maintainer requested removing the pressure refusal for this analysis. Commit `d52d5ae9` adds
`check_cache_only_host`: host load and pressure are recorded without blocking deterministic cached
audio rescoring. Live worker ownership and native-lock serialization remain mandatory, including
when the busy-host override is set. Ordinary `require_quiet_host` measurement behavior is unchanged.
Performance, memory, generation and inference lanes retain their pressure checks. Shared instructions,
the benchmark skill and maintained runbooks now distinguish these operations explicitly.

The change passed independent read-only review, fifteen host-preflight tests and twenty-nine focused
host/worker tests including twenty-three subtests. Full routed checks passed **2,305 tests and 2,685
subtests**, with one existing skip, contracts/privacy/invariants and generic iOS app/logic-bundle
compilation without a phone. The larger test count reflects the selected routing as well as new tests;
it is not a claim that fifty-seven new tests were authored. Existing timing/memory benchmark meaning
is unchanged, so no measurement lineage or compatible baseline was repinned.

At clean source `d52d5ae941f66aae7448f5b26cfa2ae449d97f10`, the new posture check recorded load
3.33 on twelve cores, memory pressure level 2, zero active/stale/unknown workers and no conflicting
native lock. This is deterministic offline evidence, with no performance or memory qualification
claim. The ordinary QC CLI then processed thirteen retained development clips in four fresh runs:

| Retained inputs | Run ID | Execution | Strict gate |
|---|---|---|---|
| French Design and annotated Dylan | `qc-takes-20261011-021302-bf41` | Complete | 4, NOT_ASSESSED |
| Seven training comparisons | `qc-takes-20261011-021303-b652` | Complete | 4, NOT_ASSESSED |
| Existing English/French Clone pairs | `clone-lane-20261011-021303-19f8` | Complete | 4, NOT_ASSESSED |
| Identical-reference and octave/speed controls | `clone-lane-20261011-021304-7e0e` | Complete | 4, NOT_ASSESSED |

All runs used `--cache-only` with no inference or download. All thirteen historical held-out
confirmation clips stayed excluded. WAV/reference identities, authentic retained annotation/protocol
bindings and identical configured model IDs/runner digests across old/new runs were verified. Existing
acoustic fields, pronunciation diagnostics, Clone pitch/identity and generic candidate counts are
exactly unchanged. New scoring identity is
`e68fe4dd2b063f24ddfbc20f242fa086d1d831d780bdf816b17abb7b310cd2f9`.

### Dylan: improved localization, still training evidence

| Historical annotation | New observation overlapping it | Intersection / union | Interpretation |
|---|---|---:|---|
| Whispered/devoiced region, 3.07–3.43 s | Phonation candidate, 3.05–3.25 s | 0.474 | Low-periodicity contextual evidence near expected `/y/`; not a qualified whisper verdict. |
| False-start region, 3.92–3.98 s | Isolated unaligned burst, 3.90–3.98 s | 0.750 | Recovers an acoustic candidate where generic recognizer events had none; not a confirmed stutter classification. |
| Broad pronunciation region, 2.16–2.84 s | Boundary vowel observations, 2.48–2.52 and 2.56–2.58 s | 0.059 / 0.029 | Separate recognizer witnesses around an optional-suffix join; does not identify the exact disputed vowel or prove wrong liaison. |

The phonation candidate uses fifteen overlapping frames and two expected `/y/` targets supplied
by different recognizers. Its median correlation is 0.268 and median level −34.55 dBFS. These
contextual measurements can include neighboring phones; the full human-marked region is not covered.
The short-fragment candidate uses thirteen overlapping energy frames, peak −26.99 dBFS and flank
contrast 37.31 dB. Its longer-context correlation remains descriptive and is not a burst-only F0.
No extraction setting was changed to force these particular overlaps after observing this run.

No reviewed boundary path was fabricated. All relevant French runs still explicitly report reviewed
comparison unavailable. The canonical optional-vowel limitation therefore remains open even though
some boundary insertions overlap the broad historical pronunciation mark.

### Comparison evidence prevents premature acceptance

The three historically acceptable French Built-in comparisons yield phonation candidate counts
15, 14 and 3; short-fragment counts 2, 2 and 0; and boundary counts 3, 0 and 0. Dylan yields 6, 1
and 4 respectively. The two objectionable French Design comparisons yield phonation counts 5 and
11, no short fragments, and boundary counts 2 and 6. Whole-clip verdicts do not establish class-complete
negative annotations, but the overlap already prevents treating any nomination as automatic failure.
No matched acceptable French Design training controls were borrowed from the held-out partition.

English clips have unavailable French phonation/boundary evidence. The identical-reference control
still nominates one short fragment, and the octave/speed control two; the latter has unknown alignment
and partial fragment coverage. These are not validated local-defect positives or negatives. The
unchanged Clone/control pitch results remain measurement sanity evidence, not quality qualification.

Raw source and posture receipts, command ledger, feature/event artifacts, gates, artifact digests,
regression script and verification receipt remain ignored under
`build/private/qc/cache-analysis-routing-20261010/`. The earlier failed check and pressure refusals
were preserved. No human listening, new labels, audio upload, automatic acceptance, repair or release
claim was introduced. Next work is independent defect definitions/localized labels and complete
negatives, genuine reviewed boundary paths, exact failing Clone pairs and accent/causal qualification.
