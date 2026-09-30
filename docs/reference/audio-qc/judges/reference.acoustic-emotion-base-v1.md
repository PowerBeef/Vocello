# `reference.acoustic-emotion-base@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `reference.acoustic-emotion-base@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Digest-pinned numerical comparison of paired acoustic deltas against a licensed acted-emotion reference base; descriptive only.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `advisory` | legacy-unqualified | dsp | - | no | no | 1 (dsp) | unmeasured |

`advisory`: Reported beside verdicts; never gates.

## Provenance

- License tier **A** (share-alike-database-internal-only): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: none
- Code: Vocello (owned)
- Training data: CREMA-D derived features (ODbL 1.0, contents DbCL 1.0) and Thorsten (CC0 1.0); development-only exposure
- Notices: CREMA-D attribution: Cheyney Computer Science and CREMA-D contributors; the derived database stays ODbL if ever distributed
- Independence: vendor Vocello; architecture deterministic DSP against a reference base; training data acted emotion corpora; label lineage corpus actor labels; correlated with the generator's lab: no.
- Sources: <https://github.com/CheyneyComputerScience/CREMA-D>, <https://huggingface.co/datasets/Thorsten-Voice/TV-44kHz-Full>

## Pins

- Digest status: `no-learned-weights`.
- Verification: The reference base manifest and its source files are digest-pinned; no recording is redistributed.

## Execution

- Stage 1; lane dsp; not orchestrated.
- Note: An advisory comparison inside run_local_delivery_cascade.py only; it never changes a route or a verdict.
- Resources: canonical-host peak -; admission ceiling - (provisional); policy: bounded by construction.
- Ceiling basis: Bounded-memory comparator.
- Output identity: referenceBaseSHA256, comparatorSourceSHA256, numpyVersion, canonicalizationIdentity. Envelope identity: -.
- Legacy identifiers: sources: scripts/delivery_acoustic_reference.py, config/delivery-acoustic-reference-base.json.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Default acoustic reference base](../../audio-qc-engineering.md#default-acoustic-reference-base).
