# `quality.utmosv2@1`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `quality.utmosv2@1` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** Former naturalness MOS-proxy advisory (mos_advisory.py) and the relative-UTMOS promotion guardrail and cascade finalist layer.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `retired` | none | neural | - | no | no | - | unmeasured |

`retired`: Removed from every QC path; only what reads legacy records remains.

**Retired.**

- `date`: 2026-09-25
- `decision`: 1a
- `finding`: AQ-F02
- `reason`: Trained on SOMOS (CC BY-NC-SA 4.0) and Blizzard Challenge samples that may not be redistributed; out of domain for this engine.
- `successor`: The section 4.6 composite, as a DP-31/DP-32 guardrail only once it passes its ladder test (AQ-08); until then no relative-quality guardrail

## Provenance

- License tier **C** (non-commercial): Non-commercial weights, or training data under an explicit non-commercial or research-only term. Never runs in a QC path. Commercial use compatible: no.
- Weights: MIT (model card)
- Code: MIT
- Training data: VoiceMOS Challenge data: BVCC, SOMOS (CC BY-NC-SA 4.0) and Blizzard Challenge samples (no redistribution)
- Independence: vendor University of Tokyo (Saruwatari lab); architecture SSL plus spectrogram fusion MOS predictor; training data VoiceMOS Challenge corpora; label lineage listening-test MOS; correlated with the generator's lab: no.
- Sources: <https://github.com/sarulab-speech/UTMOSv2/blob/main/docs/datasets.md>, <https://zenodo.org/records/10691660>

## Pins

- `sarulab-speech/UTMOSv2` at revision `cc2700db57bb83ee13dc31ebe1b868c254e15d09`.
- Digest status: `pinned`.
- Verification: Retired: no QC path loads it. Its former loader verified the digest only when the file already existed and otherwise let the library download (AQ-F04).
- `weightsSource`: huggingface.co/sarulab-speech/UTMOSv2 (fusion_stage3, fold 0, seed 42); the revision is the GitHub code commit
- `configuration`: config="fusion_stage3", fold=0, seed=42, device="cpu"

| File | Bytes | Digest |
|---|---|---|
| `fold0_s42_best_model.pth` | - | SHA-256 `c8149d988e4bbf3f` |

## Execution

- Resources: canonical-host peak -; admission ceiling - (provisional); policy: retired.
- Ceiling basis: Retired; 3.6 GB peak RSS on the M2 (CM-6).
- Output identity: repository, revision, weightsSHA256, configuration. Envelope identity: peakRSSBytes.
- Legacy identifiers: evaluatorLayers: mos; cascadeLayers: utmos; guardrails: relativeUTMOSDelta, maximumMedianRelativeUTMOSRegression; sources: scripts/mos_advisory.py; frozenContracts: {'path': 'config/delivery-prompt-remediation-contract.json', 'sha256': 'e6dc278f9375d97c76fcb463cf4552ff0cf90fa81d5df690a504753f57f54634', 'fields': ['acceptance.maximumMedianRelativeUTMOSRegression'], 'reason': 'The DP-30 per-preset screen pre-registered on 2026-08-25; its execution plans and decisions bind the contract by digest, so it is frozen and never edited. Nothing reads the retired guardrail value, and promotion decisions report a legacy relativeUTMOSDelta without gating.'}.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Audit section 2.1](../../../audits/2026-09-25-audio-qc-speech-analysis-audit.md#21-license-and-compliance-urgent) and [legacy and orchestration debt](../../audio-qc-engineering.md#legacy-and-orchestration-debt): why it left every QC path; the validators that read its legacy records stay.
