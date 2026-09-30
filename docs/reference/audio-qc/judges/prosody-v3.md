# `prosody@3`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `prosody@3` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Bounded reference-free prosody analyzer (pitch, cadence, pauses, energy, voice quality, spectral balance) feeding the warn-first prosody and delivery gates.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `advisory` | legacy-unqualified | dsp | - | no | no | 1 (dsp) | unmeasured |

`advisory`: Reported beside verdicts; never gates.

## Provenance

- License tier **A** (none): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: none
- Code: Vocello (owned)
- Training data: none
- Independence: vendor Vocello; architecture deterministic DSP; training data none; label lineage none; correlated with the generator's lab: no.

## Pins

- Digest status: `no-learned-weights`.
- Verification: Owned deterministic code bound by source digest in every cache identity.

## Execution

- Stage 1; lane dsp; engine in-process; device cpu; threads 1; batch size 1; orchestrated; worker `scripts/audio_qc_orchestrator.py`.
- Thread control: orchestrator-process
- Resources: canonical-host peak -; admission ceiling - (provisional); policy: bounded by construction.
- Ceiling basis: Bounded-memory analyzer.
- Output identity: analyzerSourceSHA256, analyzerAlgorithmVersion, numpyVersion, canonicalizationIdentity, threads. Envelope identity: -.
- Legacy identifiers: algorithms: analyzerAlgorithmVersion 3; sources: scripts/analyze_prosody.py.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Harmonicity and emotion claims need recalibration](../../audio-qc-engineering.md#harmonicity-and-emotion-claims-need-recalibration).
