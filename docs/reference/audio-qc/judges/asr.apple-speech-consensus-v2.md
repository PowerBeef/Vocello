# `asr.apple-speech-consensus@2`

<!-- BEGIN GENERATED audio-qc-docs:facts (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
Registry entry `asr.apple-speech-consensus@2` in [config/audio-qc-judges.json](../../../../config/audio-qc-judges.json).

**Measures.** iPhone recognizer family 'apple-speech': three locale-locked on-device passes (repeatability of one recognizer) plus a transcript language-consistency check.

| Status | Calibration | Kind | Family | Votes | Ships | Stage | Determinism |
|---|---|---|---|---|---|---|---|
| `gating` | legacy-unqualified | platform | apple-speech | yes | yes | 2 (device) | unmeasured |

`gating`: Feeds a verdict that can fail a take or a lane.

## Provenance

- License tier **A** (undisclosed-vendor-licensed): Permissive weights, and training data whose terms allow commercial use, or no learned weights at all. Commercial use compatible: yes.
- Weights: Apple platform framework used under the Apple Developer Program License Agreement; no weights are redistributed
- Code: Apple platform framework
- Training data: Undisclosed and vendor-owned; the vendor licenses commercial use of the framework
- Tier basis: vendor-licensed platform service; nothing is redistributed
- Independence: vendor Apple; architecture on-device Speech framework recognizer (undisclosed); training data undisclosed; label lineage undisclosed; correlated with the generator's lab: no.
- Sources: <https://developer.apple.com/documentation/speech>

## Pins

- Framework: Speech (SFSpeechRecognizer, on-device) and NaturalLanguage (NLLanguageRecognizer).
- Digest status: `platform-managed`.
- Verification: The operating system owns the model; each record carries the OS build that ran it.

## Execution

- Stage 2; lane device; not orchestrated.
- Note: Runs inside the iPhone app; the orchestrator reads its channel verdicts from the diagnostics sentinels.
- Resources: canonical-host peak -; admission ceiling - (provisional); policy: product memory contract.
- Ceiling basis: In-app; bounded by the product's memory budget.
- Output identity: osBuild, deviceProfile, locale, onDeviceRecognition, passCount, verdictAlgorithmVersion. Envelope identity: diagnosticsRunnerSource.
- Legacy identifiers: modelFamilies: apple-speech; sources: Sources/SharedSupport/Services/VoiceClipTranscriber.swift.
<!-- END GENERATED audio-qc-docs:facts -->

<!-- BEGIN GENERATED audio-qc-docs:accuracy (scripts/audio_qc_docs.py regen; edit its sources, not this block) -->
## Canary and accuracy

- No canary record.

**UNQUALIFIED.** No registered detector consumes this judge, so no accuracy is claimed for it.
<!-- END GENERATED audio-qc-docs:accuracy -->

## See also

- [Language and naturalness remain separate](../../audio-qc-engineering.md#language-and-naturalness-remain-separate): the iPhone family and its repeatability check (decision 6).
