---
status: active
owner: backend-mlx
reviewed: 2026-09-25
summary: Audit of the audio QC and speech-analysis harness (51 findings, AQ-F01 to AQ-F51) with a staged registry-driven target pipeline, a listener-free qualification protocol, a license-cleared judge panel for the Mac mini M6, and the proposed roadmap plan audio-qc-audit-2026-09 (items AQ-01 to AQ-09).
sourceOfTruth:
  - config/roadmap.json
  - docs/reference/audio-qc-engineering.md
  - config/prosody-holdout-policy.json
  - config/delivery-evaluator-v2-candidates.json
  - config/delivery-evaluator-v2-contract.json
  - scripts/lib/language_metrics.py
  - scripts/lib/audio_qc.py
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/GenerationQualityComposition.swift
  - .claude/rules/release.md
---
# Audio QC and speech-analysis harness audit (2026-09-25)

Read-only audit of Vocello's audio QC and speech-analysis harness: the Swift Fast QC, the recognizers
and language verdicts, prosody and delivery measurement, speaker similarity, the advisory neural
judges, the resource supervisor and the calibration tooling. It asks one question: can this harness
judge audio accurately and autonomously, with no human ear, on the Mac mini M6?

**Method.** Four research passes: an inventory of `main`; recognizers, language ID and alignment;
quality, speaker, prosody, emotion and artifact judges; and meta-evaluation and target architecture.
This document synthesizes them. Every repository citation was re-checked at `f157be4c`. The
inventory was taken at `35265730`. Since then the BT-05 wave 9 changes have landed on `main`: WER v2,
per-channel consensus, seed identity v2, clustered click events, the #39 cell verdict, the #41
uncalibrated composition, the #103 matched controls, the #102 candidate recovery rule and the #106
noise tool. This audit describes `main` as it is now. No model, benchmark, device or native build ran
and nothing was downloaded. Every M6 time and memory figure is marked *est.* and must be measured
before a contract relies on it.

**Identifiers.** Findings are `AQ-Fnn`. Proposed roadmap items are `AQ-nn`. Findings of the sibling
audit (`docs/audits/2026-09-25-benchmark-telemetry-audit.md`) are cited as `#n`. License tiers
are set by the terms of both the weights and the training data. **A**: permissive weights, and
training data whose terms allow commercial use (or no learned weights at all). **B**: permissive
weights, but the training data includes scraped web audio or corpora whose rights stay with the
original owners, with no explicit non-commercial (NC) term (for example Whisper's web data,
Parakeet's Granary/YODAS, VoxLingua107, VoxCeleb). **C**: NC weights, or training data under an
explicit NC or research-only term (for example NISQA's corpus, SOMOS, GigaSpeech, RAVDESS, the
CC BY-NC-SA pitch benchmark), which disqualifies the judge.

---

## 1. Executive summary

### Verdict

Rebuild the harness as one staged, registry-driven pipeline, and put a **qualification engine** at its
center. Keep the parts that work. Today the harness measures a great deal, but it has **never
measured its own accuracy**. No detector has a per-take false-alarm or detection rate, and the
qualification machinery that exists has never qualified anything. Three judges in use are
NC-licensed or NC-trained, while the registry and a docstring describe two of them as permissive.
Much of the design is a workaround for an
8 GB host that is no longer the canonical Mac.

The target:

- **Stage 0** stays the Swift Fast QC inside the engine. It remains the only product publication
  gate.
- **Stages 1 and 2** run deterministic DSP and pinned neural judges after the generator exits, in
  parallel within a measured M6 memory budget.
- **Stage 3** is a pure composer. It emits `pass`, `warn`, `fail`, `abstain`, `uncalibrated` or
  `unavailable`, and every verdict names its detector, its judges and a calibration record.
- **Ground truth comes from construction, not listening.** It is built from PCM injection,
  codec-domain injection through the production decoder, controlled generation, and three tiers of
  clean controls. Operating-point statistics decide what a detector may claim.

**Keep** Fast QC's fail bounds and its bounded, file-bound design; the quality registry's terminal and
codec gates; the two-family consensus rule, now per channel; `language_metrics.py` as the single
metric module; the supervisor, analysis cache and FIR resampler; the holdout validator, generalized;
playback capture; Apple Speech as the on-device family and repeatability check; and every legacy
record, unchanged.

### Top 10 problems

1. **License.** NISQA's weights are CC BY-NC-SA 4.0, yet the registry records "MIT" and
   `commercialUseCompatible: true`. UTMOSv2 and the SER advisory were trained on NC data. UTMOS is
   still a promotion guardrail. (AQ-F01 to AQ-F03)
2. **No measured accuracy.** No detector has a per-take false-alarm rate (FAR) or true-positive rate
   (TPR). Only PASS and WARN takes are ever published. The approved external label catalog is empty.
   The only prosody calibration used 2 + 2 clips. (AQ-F07, AQ-F33)
3. **No qualified wrong-language detector, and no two-family record.** Apple's language check is
   transcript consistency on a locked recognizer. Whisper heard the negative control, which may be
   anglicized, as English (p = 0.893). None of the 7 committed language records is two-family. (AQ-F13, AQ-F29)
4. **whisper-small is a weak sole Mac witness.** The harness tables around it cover 6 of 10 languages (`language_metrics.py:47-54`), its CJK CER sits near
   the gate, it reads only the first 30 s for language ID, and it runs one greedy pass. (AQ-F14,
   AQ-F27)
5. **Fast QC is amplitude-only, and the engine's own failure signals are ignored.** Run-ons only
   warn, repeats and voice breaks go unmeasured, and the maintainer found the onset break by ear.
   The engine's seams, token loops and EOS state are never recorded. (AQ-F08, AQ-F09)
6. **Normalization would change verdicts.** Korean is decomposed to jamo and scored by WER, Chinese
   has no traditional-to-simplified folding, and digits are never reconciled. (AQ-F21 to AQ-F23)
7. **Signal detectors mis-scale.** The per-sample click fraction fails 3 of 45 professional
   clips (CREMA-D and Thorsten, under QC v6; flagged signal observations, not confirmed audible clicks), and a fixed 0.001 silence floor reads whispered speech as dropout. (AQ-F10, AQ-F11)
8. **Prosody and identity measurands are biased or uncalibrated.** The HNR proxy reads 0.5-13 dB on
   noiseless sines, and the ECAPA bands were never calibrated. (AQ-F16, AQ-F17)
9. **8 GB-era rules make adoption impossible and waste the M6.** Contracts demand 8 GB runs that the
   M6-bound qualifier refuses. The rules allow one analyzer host-wide and one launch per clip, with a
   recovery wait of up to 15 s. (AQ-F40 to AQ-F43)
10. **Verdict logic and documentation are scattered.** Five lanes compose verdicts separately.
    Accuracy is stated in prose inside a 1,057-line decision log. (AQ-F46, AQ-F50)

### Top 5 things to do first

1. **Correct the license registry now and quarantine NISQA, UTMOSv2 and the SER** (AQ-F01 to
   AQ-F04). Code-only. Correcting the registry needs no decision; retiring the judges is decision 1.
2. **Normalization v2** (AQ-F21 to AQ-F26): Korean syllable CER, the extra Latin folds, bracket
   safety, recognizer-tag stripping and a corpus lint, with Swift parity. Code-only. OpenCC,
   cn2an, num2words and fugashi follow once their pins are authorized.
3. **Build the qualification engine** (AQ-F07, AQ-F33 to AQ-F37): statistics, the T1 injector
   catalog with shams, composer goldens and the policy file. Then run "measure the present" on the
   current judges over procedural fixtures. Code-only.
4. **Judge registry M0, then the pipeline's worker model** (AQ-F40, AQ-F42, AQ-F47): license tiers,
   the output/envelope identity split, and "two clean canonical-host runs" in place of the
   impossible 8 GB wording; then one worker per model per run in place of one launch per clip.
   Code-only.
5. **Engine introspection telemetry** (AQ-F09, AQ-F49): codec-token n-gram cycles, the EOS
   trajectory, an entropy summary and seam indices, recorded as additive observational fields that
   do not bump the QC algorithm version. Code-only.

---

## 2. Findings

Column key:

- **Sev.** is high, medium or low.
- **Dec.** says whether a maintainer decision is needed (section 9).
- Line numbers are at `f157be4c`.
- "Est." marks an estimate.
- Detector classes (A-J), injector ids (SIG-\*, CNT-\*, COD-\*, GEN-\*), label tiers (T1-T6) and
  populations (N1-N3, P1-P4) are defined in section 5.

### 2.1 License and compliance (urgent)

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F01 | NISQA | The registry declares "MIT (NISQA model code and released weights)" and `commercialUseCompatible: true`. Upstream licenses `nisqa.tar` under CC BY-NC-SA 4.0; only the code is MIT. The torchmetrics port downloads the same `nisqa.tar`. | The only license gate trusts the field, so an NC model is admitted. Its MOS 3.81 warn floor screens both sides of the cascade and fed the DP-31 French pilot's "advisory NISQA" comparison. | `config/delivery-evaluator-v2-candidates.json:164-171, :204-205`; gate: `scripts/prepare_delivery_compact_model_config.py:73`, `scripts/delivery_compact_model_adapter.py:66`, `scripts/delivery_evaluator.py:447`; `scripts/run_local_delivery_cascade.py:487-488`; roadmap DP-31 notes; [NISQA README](https://github.com/gabrielmittag/NISQA); [torchmetrics nisqa.py](https://github.com/Lightning-AI/torchmetrics/blob/master/src/torchmetrics/functional/audio/nisqa.py) | high | Record `commercialUseCompatible: false` and tier C now. Retire NISQA from QC and cascade paths. | y (retire); n (correct) |
| AQ-F02 | UTMOSv2 | The weights are carded MIT, but training used SOMOS (CC BY-NC-SA 4.0) and Blizzard samples that may not be redistributed (per the Blizzard Challenge terms page). The repository records neither. | A promotion guardrail depends on it: `relativeUTMOSDelta ≥ −0.10` in the promotion decision and the DP-32 gate. Its peak RSS was 3.6 GB on the M2 (CM-6). | `scripts/mos_advisory.py:17-27, :47-55`; `scripts/delivery_promotion_decision.py:184-186`; `config/roadmap-archive.json:605` (3.6 GB); roadmap DP-32 gate; [UTMOSv2 datasets](https://github.com/sarulab-speech/UTMOSv2/blob/main/docs/datasets.md); [VMC22 data](https://zenodo.org/records/10691660) | high | Retire it from QC. Replace the guardrail with a qualified relative-quality column (section 4.6), or drop it. | y |
| AQ-F03 | SER | The advisory SER's docstring says "permissively licensed". The checkpoint was trained on RAVDESS (CC BY-NC-SA 4.0), TESS (CC BY-NC-ND 4.0) and SAVEE (research use). It also resamples with `np.interp`, which aliases above 8 kHz, and runs outside the supervisor. | It is the scorer that admits emotion reference-bank candidates (SER top-1 must match the target), and it runs as the clone lane's third analyzer. | `scripts/emotion_advisory.py:4, :39, :165, :175-178`; `scripts/build_emotion_reference_bank.py:23-28`; `scripts/clone_fidelity_lane.py:11, :266-271`; [model card](https://huggingface.co/firdhokk/speech-emotion-recognition-with-facebook-wav2vec2-large-xlsr-53); [RAVDESS](https://zenodo.org/records/1188976) | high | Retire it. Bank selection uses the paired arousal and prosody deltas plus the owned probe (section 4.7). | y |
| AQ-F04 | Provenance | Judges outside the governed registry carry no license or training-data record. UTMOSv2 checks its digest only if the file already exists and otherwise lets the library download. The SER loads by `revision=` with no digest. ECAPA records only its source and revision. | Evaluation can depend on unverified bytes and undeclared data. The registry's offline-after-acquisition rule does not reach these judges. | `scripts/mos_advisory.py:24, :126-136`; `scripts/emotion_advisory.py:175-178`; `scripts/clone_speaker_similarity.py:40, :128` | medium | One registry for every judge (section 3.2). Loads are offline-only, and the digest is verified before each load. | n |
| AQ-F05 | Tiers | No policy classifies judges by the terms of their training data. Under the tiers above, SwiftF0 (trained on the CC BY-NC-SA 4.0 pitch benchmark), Distill-MOS (NISQA corpus, non-commercial research) and WavLM-SV (GigaSpeech pretraining, non-commercial research only) are tier C despite permissive weights, while Whisper, Parakeet, the VoxLingua107 ECAPA and the VoxCeleb-trained speaker models (ECAPA, CAM++, ResNet293) are tier B (scraped audio, rights with the owners, no explicit NC term). | Without a recorded tier per judge, the recognizers, the LID witness and every speaker judge can be neither adopted nor refused on a recorded basis. | [GigaSpeech terms](https://huggingface.co/datasets/speechcolab/gigaspeech); [SwiftF0 training data](https://github.com/lars76/swift-f0-training); [NISQA corpus](https://github.com/gabrielmittag/NISQA/wiki/NISQA-Corpus); [WeSpeaker pretrained](https://github.com/wenet-e2e/wespeaker/blob/master/docs/pretrained.md); [VoxLingua107](https://bark.phon.ioc.ee/voxlingua107/) | high | Record a tier per judge from its weights and data terms; exclude tier C; adopt tier B for internal, never-shipped evaluation only by decision 2. | y |
| AQ-F06 | Traps | Likely next picks carry NC or copyleft terms: MMS-LID, MMS-FA and the torchaudio VoxPopuli aligners (CC BY-NC 4.0), zhconv (GPL-2.0+), pykakasi (GPL-3.0), soynlp (GPL-3.0, pulled in by `qwen-asr`), mHuBERT-147 (TTSDS2, CC BY-NC-SA 4.0), VERSA (wraps NC models), JSUT and JVS audio (NC). | One convenient import would reintroduce an AQ-F01-class problem. | [MMS_FA](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.MMS_FA.html); [VoxPopuli FR](https://docs.pytorch.org/audio/stable/generated/torchaudio.pipelines.VOXPOPULI_ASR_BASE_10K_FR.html); [mHuBERT-147](https://huggingface.co/utter-project/mHuBERT-147); [JSUT](https://sites.google.com/site/shinnosuketakamichi/publication/jsut) | medium | Keep an exclusion list in the registry (section 4.9). A test refuses any excluded id or package. | n |

### 2.2 Measurement accuracy

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F07 | All detectors | No detector has a measured per-take FAR or TPR. Only PASS and WARN records are published, so no fail example is tracked. The external label catalog is empty. The only prosody calibration record used 2 + 2 clips (TPR 0.5). | Every threshold's error rate is unknown, and a regression in a judge is invisible. | `.claude/rules/release.md:82-84`; `config/prosody-holdout-policy.json:16`; record `prosody-calibration-20260712-200718-54aa4b5d`; `docs/reference/audio-qc-engineering.md:827-828` (3,778 committed takes) | high | Build the qualification engine and meta-evaluation records (sections 5 and 3.6). | n |
| AQ-F08 | Fast QC scope | Every Fast QC measure reads amplitude or waveform shape. Run-ons only warn, and no fail bound qualified. Repeats inside a normal-length take, voice breaks, mispronunciation and codec timbre go unmeasured. The maintainer heard a clone voice break "for the first moments" after every gate passed. | Content and timbre defects reach History. | `docs/reference/audio-qc-engineering.md:778-812`; `docs/development-progress.md:924-930`; `Sources/QwenVoiceCore/GenerationOutputAdapter.swift:3021` | high | Add engine introspection (AQ-F09), then the class B, C, E and I detectors (section 5.7). Run-on fail comes from content evidence. | n |
| AQ-F09 | Engine signals | The engine knows its chunk seams, codec tokens and EOS state, but records no token-cycle, entropy or EOS-trajectory summary. Per-token entropy correlates with CER (Pearson 0.636). RF-06's 2,048-code no-EOS collapse and ICA-15's over-continuation surface only as silence. | The cheapest and strongest hallucination priors are discarded. | Roadmap RF-06, ICA-06 and ICA-15 notes; [arXiv 2508.15442](https://arxiv.org/html/2508.15442); `Sources/VocelloCLI/BenchCodecReplay.swift:94` (verified trace) | high | Add Stage 0 introspection fields, additive and observational. Validate them under class I. | n |
| AQ-F10 | Clicks | The click bound is a per-sample fraction (fail > 0.5%, warn > 0.05%), so its tolerance grows with take length. It failed 3 of 45 professional clips (CREMA-D plus Thorsten, under QC v6); the doc calls these flags signal observations, not confirmed audible clicks or a measured false-positive rate (`docs/reference/audio-qc-engineering.md:145-148`). Clustered events per second are recorded but observational. | A seam regression of 1-10 clamps per second passes, while professional speech fails. | `Sources/QwenVoiceCore/GenerationOutputAdapter.swift:2898-2899, :2997-2998`; `docs/reference/audio-qc-engineering.md:145-148, :814-830` | medium | Qualify a per-second event bound (class A, SIG-CLICK, N1 and N2). The current bound stays until then. | n |
| AQ-F11 | Silence floor | Silence is a fixed absolute floor of 0.001, with no noise-floor adaptation. Whisper-adjacent takes fell to the dropout detector (5 of 24). Loudness never reaches history: `QC_METRIC_MAP` omits `rmsDBFS`, peak and hot samples. | Breathy or whispered delivery false-fails, and level regressions go unseen. | `Sources/QwenVoiceCore/GenerationOutputAdapter.swift:1001, :2897`; `config/roadmap-archive.json:1017`; `scripts/lib/audio_qc.py:26-46` | medium | Adaptive noise floor with WADA-SNR; BS.1770 loudness and true peak; publish level metrics. | n |
| AQ-F12 | Onset cluster | The 150-250 ms plosive-onset step cluster (11 of 88 takes) was judged "not a QC defect" because NISQA could not separate it (AUC 0.54). | An unqualified, NC-licensed judge closed a measured artifact. | `docs/reference/audio-qc-engineering.md:758-774` | medium | Re-open it under class A (natural-onset negatives) and class E (onset identity delta). | n |
| AQ-F13 | Language ID | Apple's language pass is `NLLanguageRecognizer` over the transcript of a locale-locked recognizer. An English-locked whisper heard the negative control, which may be anglicized (the matrix note says the model still speaks French), as English (p = 0.893). Per-channel consensus now declares the negative control an accuracy control only. | No lane has a qualified detector for a wrong-language take; content failure catches it only indirectly. | `scripts/lib/language_metrics.py:62-71, :405-415`; `Sources/SharedSupport/Services/VoiceClipTranscriber.swift:617-620`; roadmap AV-08 notes | high | Two audio-LID witnesses (section 4.2) and GEN-XLANG positives. The Apple check becomes auxiliary. | n |
| AQ-F14 | Mac ASR | whisper-small is the only Mac witness. Its CJK CER "sits close to" the 0.15 gate. Language ID reads the first 30 s only. Decoding is one greedy pass with no word timing. | Content verdicts rest on one weak recognizer. Long takes are language-judged by their opening. | `docs/reference/language-bench.md:321`; `scripts/independent_asr_worker.py:98-101, :112-114`; `scripts/lib/language_metrics.py:80` | high | Two-family panels per language (section 4.1), after a dual run. | n |
| AQ-F15 | Omissions | A 2-4 word skip passes the 15% gate on 17-32-unit scripts; the longest-deletion run only warns. Edge coverage never proves the interior. | Skipped phrases pass. | `scripts/lib/language_metrics.py:39-43`; roadmap VLR-07 gate | medium | Project each transcript onto the aligned reference words; class B deletion detector. | n |
| AQ-F16 | Prosody | The HNR proxy reads 0.51, 6.99 and 13.29 dB on noiseless sines. Praat and the analyzer disagree on pitch by more than 600 cents in 62 frames and on voicing in 298. F0 is limited to 70-400 Hz, and syllable rate is an envelope proxy. | Voice-quality and rate features are not trustworthy measurands. | `docs/reference/audio-qc-engineering.md:566, :625-626`; [Praat harmonicity](https://www.fon.hum.uva.nl/praat/manual/Sound__To_Harmonicity__ac____.html) | medium | SwiftF0, window-corrected HNR and aligner-based rate, validated against oracle ladders (section 4.4). | n |
| AQ-F17 | Identity | The ECAPA bands (≥ 0.60 strong, ≥ 0.45 acceptable) are uncalibrated. Only one speaker family exists. Nothing detects windowed drift or an onset break. No clone-identity record exists. #103 set the default to eight gender-matched controls, and cross-clone negatives run only for voices the operator names; no run has used either yet. | Clone and voice consistency cannot be gated. | `scripts/clone_speaker_similarity.py:62-63, :207`; `scripts/clone_fidelity_lane.py:14-27, :98`; [VoxSim](https://arxiv.org/pdf/2407.18505) | medium | Two SV families, window, onset and seam deltas, and splice-injection calibration (sections 4.3 and 5). | y (tier B) |
| AQ-F18 | MOS | Reference-free MOS has no per-take validity on clean TTS: best pairwise accuracy 0.528 against a 0.764 human ceiling, and a duration baseline ties it. In TTSDS2, NISQA scores ρ −0.14. Yet NISQA and UTMOS feed comparisons and guardrails. | Advisory numbers read as quality evidence. | [arXiv 2609.13150](https://arxiv.org/html/2609.13150); [TTSDS2](https://arxiv.org/html/2506.19441v1); `scripts/delivery_promotion_decision.py:186` | medium | Neural quality stays relative and advisory, with duration as a covariate (section 4.6). | n |
| AQ-F19 | Delivery | Acoustic happy/angry separation depends on tier and arm: DP-22 found normal-tier angry-vs-happy separable (UAR 0.765, p = 0.007, 4-bit arm) but null at the strong tier (0.531) and in the 8-bit arm; semantic valence is not autonomously measurable. #39 and #40 landed a cell verdict and stratified features, but no semantic delivery claim is autonomously measurable. | "Delivery adherence" can overclaim. | `config/roadmap-archive.json:1083`; roadmap DP-28 notes | medium | Gate only the paired, speaker-normalized arousal and prosody contrast at cell level (class H). | n |
| AQ-F20 | Determinism | No judge has a recorded determinism class. MLX GPU repeatability was never measured. Whisper is required to pass once, and SenseVoice is pinned at q8. | A transcript flip between identical runs is indistinguishable from a regression. | `scripts/lib/language_metrics.py:80`; `config/delivery-evaluator-v2-candidates.json:14-18` (q8 GGUF) | low | Determinism classes D0, D1 and D2 plus canary acceptance (section 5.8). | n |

### 2.3 Normalization

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F21 | Korean | Non-CJK text goes through NFKD, which decomposes Hangul syllables into conjoining jamo. `CHARACTER_ERROR_LANGUAGES` holds only zh and ja, so Korean would be WER-scored over inconsistent eojeol spacing. The multilingual TTS evaluations surveyed (for example CV3-Eval) score Korean by character error rate. | The first Korean cell would be mis-scored. | `scripts/lib/language_metrics.py:57, :122-133`; [CV3-Eval run_wer.py](https://github.com/QwenAudio/CV3-Eval/blob/main/utils/run_wer.py) | high | NFC syllable CER, space-insensitive; jamo CER as a diagnostic. | n |
| AQ-F22 | Chinese | There is no traditional-to-simplified folding, and Whisper often emits traditional characters. Seed-TTS uses zhconv, which is GPL. | Correct zh takes pay CER for orthography. | `scripts/lib/language_metrics.py:122-133`; [Seed-TTS run_wer.py](https://github.com/BytedanceSpeech/seed-tts-eval/blob/main/run_wer.py) | medium | OpenCC `t2s` (Apache-2.0) on both sides. | n |
| AQ-F23 | Digits | Nothing reconciles digits with spelled numbers, while Whisper, Parakeet and SenseVoice with ITN emit digits. | Spurious substitutions. | `scripts/lib/language_metrics.py:122-140` | medium | Keep digits out of gated scripts with a corpus lint; verbalize both sides for diagnostics (num2words, LGPL-2.1; cn2an, MIT). | n |
| AQ-F24 | Latin folds | NFKD cannot fold ß, æ, œ, ø or ł. Recognizer tags such as SenseVoice `<\|…\|>` are not stripped. | Correct takes pay WER, for example "Straßen" against "Strassen". | `scripts/lib/language_metrics.py:129-133` | low | Add an `ADDITIONAL_DIACRITICS` map and tag stripping. | n |
| AQ-F25 | Trap | Whisper's `BasicTextNormalizer` and `EnglishTextNormalizer` delete bracketed text and fillers. Qwen3-TTS speaks parenthesized words, and fillers are defects. | Adopting them as-is would hide babble and delete reference words. | [Whisper basic.py](https://github.com/openai/whisper/blob/main/whisper/normalizers/basic.py) | low | Never delete bracket contents; count fillers. | n |
| AQ-F26 | Japanese | Surface CER charges orthographic variants (今日 against きょう, kanji against kana numerals). | Small, systematic CER inflation. | `scripts/lib/language_metrics.py:57` | low | Add a kana-reading CER diagnostic (fugashi with unidic-lite; not pykakasi). | n |

### 2.4 Coverage: languages and modes

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F27 | Languages | The product supports 10 languages, but the language tables cover 6. Italian, Korean, Portuguese and Russian fail closed, and the corpus has 6 scripts. | 40% of product languages are unverified. | `scripts/lib/language_metrics.py:45-54`; `config/language-bench-corpus.json` (6 languages); [Qwen3-TTS report](https://arxiv.org/html/2601.15621) | high | 10-language panels, normalization and script pool (sections 4.1 and 6). | n |
| AQ-F28 | Sampling | The corpus has one script per language. The matrix has 19 cells, with a quick subset of 7. Seed identity v2 has landed, but coverage is still one script and a few seeds per cell. | Per-language claims have no statistical footing. | `config/language-bench-matrix.json` (19 cells); `config/language-bench-corpus.json` (v2); roadmap AV-08 gate | medium | Script pool of CC0 Common Voice sentences with human controls (section 5.3). | n |
| AQ-F29 | Two families | 7 language records hold 73 takes. Whisper evidence is EN/FR quick only. No record is two-family, and the Apple side of the negative control was never measured. | Consensus, the core language rule, has never run on committed evidence. | `benchmarks/runs/language/` (7 records); roadmap AV-08 notes | high | M6 panel qualification, then two-family lanes (consent-bound). | n |
| AQ-F30 | Delivery | 902 delivery takes in 108 records are all from the M2, all Custom and all medium length. | Design, Clone, short and long deliveries, and the M6, are unmeasured. | Offline count over `benchmarks/runs/` (takes carrying `delivery*` metrics: 902 in 108 records, all `mac-mini-m2-8gb`, `custom`, `medium`); `docs/audits/2026-09-25-benchmark-telemetry-audit.md:82` | medium | Class H cells across modes and lengths on the M6. | n |
| AQ-F31 | Long form and phonation | The seam jump is a warn-only advisory at 4,096 PCM16 units. No long-form content judge exists. Language ID reads 30 s. Whisper phonation has no QC posture. | Long-form collapse and whisper delivery rest on silence heuristics. | `Sources/QwenVoiceCore/LongFormAssembly.swift:132-135`; `scripts/independent_asr_worker.py:112-114`; `docs/reference/emotion-reference-banks.md:119` | medium | Classes J and C with segment-wise alignment; phonation-aware scope and abstention. | n |
| AQ-F32 | Human controls | No script-matched human recording exists for any gated script. In differential ASR testing, 21-34% of "ASR failures" on TTS audio were TTS defects, and attribution needed human recordings of the same text. | A content failure cannot be attributed to the recognizer or the take. | [Lau et al., ISSTA 2023](https://arxiv.org/abs/2305.17445); `config/language-bench-corpus.json` | medium | CC0 Common Voice script pool with human recordings and codec resynthesis (N1, N2). | y (downloads) |

### 2.5 Calibration and self-validation

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F33 | Authority | The threshold authority defines no operating points. Its 60/60/60 Wilson floor can support FAR ≤ 0.10 only; FAR ≤ 1% needs 299 independent negatives at zero errors. It has no label tiers, no in-domain requirement, no cross-mechanism check and no automatic de-qualification. | No fail bound can ever qualify, which the speaking-rate screen showed. | `docs/reference/audio-qc-engineering.md:798-812, :844-860, :874-880`; `config/prosody-holdout-policy.json:4-13` | high | Keep the five rules verbatim and add A1-A10 (section 5.6). | y |
| AQ-F34 | Evidence kinds | `controlled-pcm` supports only `unchanged` and `mute-interval`. There are no shams, no codec-domain injection and no controlled generation, and no token-cap or EOS-suppression knob is registered. | Positives cannot be produced for most defect classes. | `docs/reference/audio-qc-engineering.md:1009-1014`; `config/runtime-debug-knobs.json` (groups list no such key) | medium | T1 catalog, T2 codec replay mode, T3 knobs (section 5.2). | n |
| AQ-F35 | Independence | Consensus treats families as independent by name. Parakeet's training labels are Whisper pseudo-labels (Granary). Paraformer and SenseVoice share a company. Qwen3-ASR and the aligner share the generator's lab. The speaker models all train on VoxCeleb. | "Two families agree" can overstate evidence. | `scripts/lib/language_metrics.py:376-396`; [Granary](https://arxiv.org/html/2505.13404v1); [Qwen3-ASR report](https://arxiv.org/html/2601.21337v1) | medium | An error-correlation audit before any consensus rule gates. Same-lab judges do not vote. | y |
| AQ-F36 | Regression | No judge canary exists and no metamorphic test runs on audio. Unit suites use synthetic tones, which prove implementation, not accuracy. | A judge change can move verdicts unnoticed. | `docs/reference/audio-qc-engineering.md:215-223` | medium | CI goldens plus a consent-bound judge canary (section 5.8). | n |
| AQ-F37 | Retention | Failing evidence never becomes tracked data, and retained failure bundles were lost in the 2026-09-11 host cleanup. | Positive controls cannot be rebuilt. | `.claude/rules/release.md:82-84`; roadmap VLR-07 notes | medium | Meta-evaluation records hold failing fixtures as digests plus regeneration recipes. | n |
| AQ-F38 | Rule tension | release.md turns a heard defect into a Swift measurement "that fails the offending takes". The authority keeps every boundary until a change qualifies, so v7 and v8 both ended warn-only. | The two rules are unsatisfiable together. | `.claude/rules/release.md:123-125`; `docs/reference/audio-qc-engineering.md:846-860` | medium | A heard defect enters as a shadow detector with the heard takes as positives, and fails once qualified (A9). | y |
| AQ-F39 | Vocabulary | Swift outcomes are `pass`, `warning`, `fail`, `unavailable` and `uncalibrated`. Python consensus says `inconclusive`. Neither side has a distinct `abstain`, and several advisory columns (NISQA floor, ECAPA bands) have no status at all. | Out-of-scope and disagreement cases blur with infrastructure failure. | `Sources/QwenVoiceCore/GenerationQualityReport.swift:9-19`; `Sources/QwenVoiceCore/GenerationQualityComposition.swift:197-203`; `scripts/lib/language_metrics.py:376-396` | low | Add `.abstained` (section 3.3). | y (decision 7) |

### 2.6 Constraints from the 8 GB era

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F40 | Adoption | Adoption requires "two-clean-eight-gib-host-runs" or "measured-eight-gigabyte-memory-compatibility", while the qualifier refuses any host but the canonical M6. | As written, no candidate can be adopted. | `config/delivery-evaluator-v2-candidates.json:226`; `config/delivery-evaluator-v2-contract.json:114`; `config/delivery-experiment-contract.json:213`; `scripts/qualify_delivery_compact_models.py:37-58`; `config/public-product-facts.json:40-43` | high | Require "two clean canonical-host runs". The 8 GB and iPhone floors stay product constraints, not evaluator constraints. | n |
| AQ-F41 | Concurrency | One heavy process may run host-wide (a flock), under a strictly sequential subprocess policy. | The 12-core M6 runs one analyzer at a time. | `scripts/delivery_resource_supervisor.py:687-690`; `config/delivery-evaluator-v2-contract.json:7` | medium | A budgeted admission semaphore after the generator exits (section 3.4). | y |
| AQ-F42 | Launches | Compact adapters and NISQA launch one supervised process per WAV, and each launch may wait up to 15 s for recovery. Torch is capped at 4 threads and forced onto the CPU. | Model loads and waits dominate lane time. | `scripts/delivery_compact_model_adapter.py:201, :244`; `scripts/delivery_compact_model_runtime.py:106, :162`; `scripts/delivery_resource_supervisor.py:61-64` | medium | One persistent worker per model per run. Thread counts are declared per judge. | n |
| AQ-F43 | Ceilings | The 5 GiB ceiling is "sized for the 8 GB support floor". Whisper has a 2.5 GiB ceiling, so only the 244M model was ever pinned. | Model choice was capped by an obsolete budget. | `scripts/delivery_resource_supervisor.py:4-7, :57`; `scripts/independent_asr.py:74-76` | medium | Per-judge ceilings from measured M6 peaks × 1.2. | n |
| AQ-F44 | Recovery | The binding post-exit recovery rule judges a whole-host percentage. The attributed candidate rule is report-only. | Unqualified envelopes stay unattributed. | `scripts/delivery_resource_supervisor.py:554-621, :818-834`; #102 | low | Promote the child-attributed rule (BT-05 decision). | y |
| AQ-F45 | Stale text | Seven scripts and two runbooks justify serial scoring by "the 8 GB Mac" or "the canonical 8 GB Mac". | The rationale misleads M6 design. | `scripts/emotion_advisory.py:12`; `scripts/mos_advisory.py:17`; `scripts/clone_fidelity_lane.py:31`; `scripts/build_emotion_reference_bank.py:15`; `scripts/longform_carryover_probe.py:9-10`; `scripts/delivery_experiment_runner.py:6`; `scripts/delivery_evaluator.py:12`; `docs/reference/delivery-harness.md:1045-1047`; `docs/reference/testing-runbook.md:104` | low | Rewrite: the evidence-lane rule is "no evaluator beside a resident generator", and the M6 budget governs after exit. | n |

### 2.7 Architecture

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F46 | Composition | Verdicts are composed separately in the language checker and publisher, the delivery cascade, the clone lane, VLR and the bank builder. | The same judge can mean different things per lane, and no single place states what gates. | `scripts/check_language_output.py:278`; `scripts/publish_benchmark_history.py:2852, :2947`; `scripts/run_local_delivery_cascade.py:487`; `scripts/clone_fidelity_lane.py:229, :266` | medium | One registry-driven Stage 3 composer with per-lane gating sets. | n |
| AQ-F47 | Identity | The supervisor's SHA-256 is part of each compact adapter's execution identity, so any supervisor fix invalidates every prepared config and cache entry (V-12). | Envelope changes force re-computation. | `scripts/delivery_compact_model_adapter.py:113-126` | medium | Split output identity (keys caches and calibration) from envelope identity (provenance only). | n |
| AQ-F48 | Dead weight | DistilHuBERT does not transcribe and has no QC role. The fitted ridge, elastic-net and PLS heads were never calibrated and always abstain. | Code and qualification cost with no measurand. | `docs/reference/audio-qc-engineering.md:755`; roadmap DP-28 notes | low | Delete them from QC paths after M0. | n |
| AQ-F49 | Versioning | The Fast QC algorithm version is part of the gate's baseline identity, so a v9 bump forces a consent-bound re-seed of the M6 gate baseline. | New Stage 0 detectors collide with the AV-17 sequence. | `docs/reference/audio-qc-engineering.md:822-824`; `Sources/QwenVoiceCore/GenerationTelemetryRecord.swift:1086` | medium | Land fields additively; bump v9 once, with the first qualified promotion (decision 8). | y |

### 2.8 Documentation

| ID | Area | Finding | Impact | Evidence | Sev. | Fix | Dec. |
|---|---|---|---|---|---|---|---|
| AQ-F50 | Structure | The authority, pilots, decisions and operator commands share one 1,057-line living document. Its front matter says reviewed 2026-09-12, although it was edited on 2026-09-25. No per-judge page exists, and accuracy is stated only in prose. | Documentation can claim accuracy no record supports. | `docs/reference/audio-qc-engineering.md:1-26, :776-860` | medium | `docs/reference/audio-qc/` tree with generated accuracy blocks (section 3.7). | n |
| AQ-F51 | Rules text | release.md names whisper-small as "the pinned" Mac producer and describes `sensevoice` as a family id no lane produces. | Any panel change needs a rules edit in the same change. | `.claude/rules/release.md:115-123` | low | Rewrite: families come from the judge registry (decision 7). | y |

---

## 3. Target architecture

### 3.1 Stages

```
 engine generate (Swift + MLX)                                   ── product publication gate ──
 ┌──────────────────────────────────────────────────────────────┐
 │ Stage 0  inline, every take, macOS / iOS / CLI                │ Fast QC (existing fails) + v9 DSP
 │          bounded memory, bitwise (D0)                         │ (observational → warn → fail only
 └──────────────────────────────────────────────────────────────┘  when qualified) + introspection
        │ atomic WAV + receipt (+ code trace in diagnostic lanes)
        ▼ generator exits; manifest declares generationProcessExited
 ┌─────────────────────────────────────────────────────────────────────────────┐
 │ Orchestrator (Python, loads no model): manifest → canonical 16 kHz (cache L0) │
 │  ├─ Stage 1 DSP pool: loudness, SNR, bandwidth, pYIN pitch + voice quality,     │
 │  │    spectral flux, VAD, prosody v4                                          │
 │  ├─ Stage 2 GPU lane, one MLX worker at a time: ASR voter + LID →            │
 │  │    literal voter → aligner → adjudicator (inconclusive rows only)          │
 │  └─ Stage 2 CPU lane, ≤ 2 workers: Paraformer | SenseVoice-f16 | LID ECAPA | │
 │       CAM++ | ResNet293 | advisory quality                                     │
 │  every worker: one process per model per run, supervised, batch 1, declared  │
 │  threads, JSONL over stdin/stdout, exits at end of manifest                  │
 └─────────────────────────────────────────────────────────────────────────────┘
        │ measurement vectors (L1 raw → L2 metrics)
        ▼
 Stage 3 composer (pure, never cached) ◀── registries: judges · detectors · calibration records ·
        │                                   qualification policy · lane gating sets
        ▼
 Stage 4 report: private bundle (untracked) · privacy-safe record (benchmarks/) · generated docs
```

| Stage | Where and when | Determinism | Budget per 10 s take (est.) | Role |
|---|---|---|---|---|
| 0 | In the engine, every take, every platform | D0 | < 50 ms, < 20 MB | The only product publication gate |
| 1 | Mac, after exit | D0 | 0.1-0.5 s CPU | Evidence lanes |
| 2 | Mac, after exit | D0 on CPU, D1 on MLX | 3-5 s warm; loads 15-30 s once per run | Evidence lanes and release promotion |
| 3 | Mac and CI | Pure | Milliseconds | Emits every verdict |

**Placement rules.**

1. A detector moves into Stage 0 only if all of these hold:
   - it is deterministic DSP with bounded memory;
   - it is qualified (section 5.6);
   - it fits the iPhone budget.
2. Model-based judges never ship in the app, per DP-32.
3. Stages 1 and 2 never gate a user's publication. They gate evidence: records, language and clone
   lanes, and release promotion.
4. In timing and benchmark lanes, everything runs after the generator exits.

### 3.2 Registries

Five digest-bound configs, all validated in CI:

| Registry | Succeeds | Holds |
|---|---|---|
| `config/audio-qc-judges.json` | `delivery-evaluator-v2-candidates.json` | Per judge: pins (repo, revision, file SHA-256s), runtime and dependency digests, worker source digest, device, dtype, threads, batch size, determinism class, languages, license tier, training-data risk, notices, independence (vendor, architecture, label lineage, generator-lab correlation), measured envelope, output and envelope identities, canary record, status |
| `config/audio-qc-detectors.json` | Scattered rule code | Per detector: class, consumed judges with versions, metric-definition version, rule, parameters, abstain reasons, calibration records with scope, status |
| `config/audio-qc-qualification-policy.json` | `prosody-holdout-policy.json` | The five authority rules verbatim, A1-A10, operating points, label tiers, lane gating sets, drift thresholds |
| `config/audio-qc-corpora.json` | — | Per corpus subset: id, release, license, attribution, term flags (`noRehost`, `noSpeakerIdentification`, `shareAlike`), per-file SHA-256, opaque group ids, language, text digest |
| `config/audio-qc-injectors.json` | The `controlled-pcm` kinds | Injector id and version, parameter grid, sham definition, golden digests |

Judge statuses: `candidate`, `shadow`, `warn`, `gating`, `retired`, `quarantined`. `quarantined` is
new: a license or provenance problem blocks execution until a decision.

### 3.3 Verdict states and composition

| Status | Meaning | Effect in a lane that gates on the detector |
|---|---|---|
| `pass` | In scope, qualified, no defect | Contributes to pass |
| `warn` | A qualified warn operating point is exceeded, or a fail-class detector is qualified only at warn | Take `warn` |
| `fail` | A qualified fail operating point is exceeded, with the required consensus | Take `fail` |
| `abstain` | The detector ran but declined: out of scope, families disagree, repeatability disagreement, low confidence, or an unqualified text class | Take `inconclusive`: it blocks a claimed pass but is not a defect |
| `uncalibrated` | A measurement exists, but no qualified record covers this version and scope | Listed; never blocks and never counts toward pass (the #41 semantics) |
| `unavailable` | Infrastructure failure: missing model, digest drift, crash, timeout or envelope breach | Fails closed |

**Composition, per lane.** Rules are applied in order, and the first that matches decides:

1. Any gating `fail` gives `fail`.
2. Otherwise, any gating `unavailable` gives `unavailable`.
3. Otherwise, any gating `abstain` gives `inconclusive`.
4. Otherwise, any `warn` gives `warn`.
5. Otherwise, any gating `uncalibrated` gives `uncalibrated` (it ranks above `pass`, as #41 composes
   it in `GenerationQualityReport.swift:14-17`).
6. Otherwise the take passes; advisory uncalibrated detectors are listed but do not change the verdict.

**Gating sets:**

| Lane | Gating classes |
|---|---|
| Publication | Stage 0 only |
| Language bench | B, C and D |
| Clone lane | E |
| Delivery bench | H, at cell level |
| Release promotion | The union |

**Swift.** Add `.abstained` to `GenerationQualityOutcome`. It ranks 3 in required-gate contexts,
like `unavailable` and `fail`, but is reported distinctly. The existing order pass 0, uncalibrated 1,
warning 2 is unchanged (`Sources/QwenVoiceCore/GenerationQualityComposition.swift:197-203`).

### 3.4 Process and memory model on the M6

**Host.** The M6 has 12 cores (2 Super, 4 Performance, 6 Efficiency) and 16 GB of memory
(`benchmarks/hardware-profiles.json:15-39`).

**Budget.** 16 GB, minus about 4.5 GB for macOS and tooling, minus a 1.5 GB margin, leaves about
**10 GB for evaluators** (est.; the first M6 lane measures it).

**Workers.** One persistent worker per model per run loads once, warms on a fixed clip, streams the
manifest and exits, generalizing `independent_asr_worker.py`. It is never a daemon spanning runs:
source binding, memory hygiene and lane ownership of processes all forbid it. On a crash, emitted
rows are kept, the remainder is retried once in a fresh worker (recorded), and a row that crashes
twice is `unavailable`.

**Admission.** A budgeted semaphore under the existing supervisor replaces the host-wide flock. A
worker is admitted only while the sum of the registry ceilings of running workers (measured peak ×
1.2) stays within the budget.

**Unchanged for evidence lanes.** No evaluator runs while a generator is resident. A lane refuses to
start on a busy host.

| Lane | Concurrency | Threads each | Ceiling each (est.) | Contents |
|---|---|---|---|---|
| DSP pool | 4 processes | 1 | 0.3 GB | Stage 1 |
| GPU lane | 1 MLX process at a time | 2 (host side) | Whisper-L-v3 6 GiB; Qwen3-ASR 6 GiB; Parakeet 3.5 GiB; aligner 3.5 GiB | Recognizers, LID, aligner |
| CPU neural lane | ≤ 2 processes | 2-3 | Paraformer 2.5; SenseVoice 1.5; LID ECAPA 1; CAM++ 0.2; ResNet293 0.3; Audiobox 1.2; DNSMOS and SigMOS 0.25 (GiB) | CPU judges |
| Orchestrator and composer | 1 | 1 | 0.2 GB | Scheduling, cache, verdicts |

**Limits.** The worst admitted mix is Whisper-L (6) + Paraformer (2.5) + DSP (4 × 0.3) = 9.7 GB
(est.); Qwen3-ASR is admitted only beside CPU judges of 2.5 GB or less. Parallelism runs across clips
and judges, never inside a judge's numerics. Thread counts are part of each judge's output identity,
so scheduling cannot change a result. macOS offers no core pinning on Apple silicon, so placement
uses QoS classes and identity records thread counts, not cores.

**Throughput (est.).** A 19-cell language matrix takes 1-2 min of evaluation, a 300-take drift panel
about 15-35 min (est.; the lower figure is evaluation only, the upper includes generation), and a full qualification corpus (about 11,500 clips of about 6 s) 5-8 h overnight. A
threshold-only change costs no model time, because the composer re-reads cached L2 metrics.

### 3.5 Caching

| Layer | Key | Content | Invalidated by |
|---|---|---|---|
| L0 canonical | PCM SHA-256 + resampler digest (`polyphase-kaiser5-v2`) | 16 kHz PCM | Resampler change |
| L1 raw | L0 + judge **output** identity + request (locked language, reference-text digest, reference-clip digest) | Private transcript, scores, embeddings, timestamps | Output-identity change only, not envelope changes (fixes AQ-F47) |
| L2 metrics | L1 + metric-definition version (for example normalization v2) | Edit operations, rates, intervals | Metric-definition change |
| L3 verdict | Never cached | — | Recomputed from L2, the rule and the calibration record |
| Fixtures | Source digest + injector id and version + parameters + seed | Injected PCM or trace | Injector version (golden-checked) |
| Embedding banks | Reference digest + SV output identity | Voiceprints, AS-norm cohorts | SV identity change |

The cache lives under roots owned by `config/build-output-policy.json`. Writes are atomic and fail
closed. Pruning is LRU with `--keep-newest`, reusing `delivery_analysis_cache.py`, and never deletes
a whole cache.

### 3.6 Evidence schema

Tracked records hold digests, metrics and verdicts. Transcripts, alignments and paths stay in the
untracked private bundle. A per-take sketch:

```json
{"schema": "vocello.audioqc.take-evidence/1",
 "take": {"pcmSHA256": "…", "sampleRate": 24000, "durationSeconds": 8.4, "textSHA256": "…",
          "language": "fr", "mode": "custom", "voice": "aiden", "seed": 1234,
          "generator": {"artifactVersion": "…", "catalogSHA256": "…"}},
 "registries": {"judges": "sha256:…", "detectors": "sha256:…", "policy": "sha256:…"},
 "stage0": {"audioQC": {"algorithmVersion": 8, "verdict": "pass", "flags": []},
            "introspection": {"tokenCycleMax": 0, "entropyP95": 2.1, "eosTrajectory": "normal"}},
 "measurements": [{"judge": "asr.whisper-large-v3@1", "outputIdentity": "…", "status": "complete",
                   "metrics": {"errorRate": 0.031, "deletions": 1, "longestDeletionRun": 1},
                   "transcriptSHA256": "…", "wallSeconds": 1.7}],
 "verdicts": [{"detector": "content.deletion@2", "status": "pass",
               "judges": ["asr.whisper-large-v3@1", "asr.parakeet-tdt-0.6b-v3@1"],
               "calibration": {"recordSHA256": "…", "status": "warn", "inScope": true}},
              {"detector": "identity.onset-break@1", "status": "uncalibrated",
               "reasons": ["no-qualified-record"]}],
 "takeVerdict": {"lane": "language-bench", "status": "pass", "composition": "worst-of-gating/1"}}
```

Records of the kinds `qc-calibration`, `qc-canary` and `qc-drift` are tracked and hold no audio or
text. Per detector and stratum they carry confusion counts and bounds, ROC and pAUC points,
reliability bins, risk-coverage, the error-correlation matrix, corpus and injector digests, and
failed attempts. They are qualified PASS records that contain failing fixtures as data, which
resolves AQ-F37 within the evidence-retention rule. Legacy kinds gain a `qcEvidence` block only under
a new evidence contract (section 7.2).

### 3.7 Documentation structure

```
docs/reference/audio-qc/
  README.md                  pipeline, stages, verdict vocabulary, lane gating sets, how to add a judge
  qualification-policy.md    the authority (5 rules verbatim + A1-A10), label tiers, sample sizes
  corpora.md                 prose + GENERATED table from config/audio-qc-corpora.json
  injectors.md               prose + GENERATED catalog from config/audio-qc-injectors.json
  judges/<judge-id>.md       one page per judge
  meta-evaluation-report.md  GENERATED ONLY, from committed calibration/canary/drift records
docs/reference/audio-qc-engineering.md → status: historical (its authority section moves)
```

**Each judge page** covers: what it measures; how (preprocessing, decode options, normalization);
model and provenance (pins, license tier, training data, label lineage, vendor correlation);
execution (runtime, threads, dtype, determinism class, measured M6 cost, generated); operating points
(generated); measured accuracy per stratum (generated: the N1 and N2 judge floor, FAR and TPR bounds,
pAUC, ECE, abstention, worst stratum); limits (hand-written plus generated thin strata); failure
semantics; tests and canary; and a change log.

**Staleness is prevented mechanically.** `scripts/refresh_derived_artifacts.py` registers an
`audio-qc-docs` artifact whose `validate` fails when a generated block drifts. A contract test
requires a page per registry judge, an identity match between page and registry, and a qualified,
scope-covering record behind every `warn` or `gating` detector. A judge with no record prints
**UNQUALIFIED**, and the composer emits only `uncalibrated` for it.

---

## 4. Judge panel

**Every pick below:**

- runs locally;
- is pinned by revision and file SHA-256;
- runs offline after acquisition;
- processes clips at batch size 1.

Revisions and digests were read from the Hugging Face API on 2026-09-25 (`02` and `03` research). The
supporting files' SHA-256 values are computed at first fetch. Times are per 10 s take, warm, on the
M6 (est.). "Gating" means the judge may feed a gating detector once that detector qualifies; until
then its verdicts are `uncalibrated`.

### 4.1 Content and intelligibility

| Role | Model @ revision | Main file (SHA-256 prefix) | License (tier) | Runtime | Memory (est.) | Time (est.) | Status | Placement |
|---|---|---|---|---|---|---|---|---|
| Primary voter: en, de, fr, es, it, pt, ru, ja, ko; secondary for zh | `mlx-community/whisper-large-v3-mlx@49e6aa286ad60c14352c404340ded53710378a11` | `weights.npz` 3.08 GB (`05ff791c…`) | MIT / Apache-2.0 weights; scraped web training audio (B, as whisper-small today) | mlx-whisper 0.4.3, fp16, greedy, `temperature=0.0` scalar, `condition_on_previous_text=False`, no prompt, `no_speech_threshold=None`, language locked | 4-4.5 GB | 1.5-3 s | Gating after dual-run qualification | Stage 2 GPU |
| Secondary literal voter: en, de, fr, es, it, pt, ru | `mlx-community/parakeet-tdt-0.6b-v3@ed2b7e8c15f9aaa0b5772e2efb986255eaef7e15` (upstream `nvidia/parakeet-tdt-0.6b-v3@541d1f99…`) | `model.safetensors` 2.51 GB (`05e01c7f…`) | CC BY 4.0, attribution; Granary/YODAS scraped audio (B); label lineage: Whisper pseudo-labels | parakeet-mlx 0.5.2, greedy, fixed dtype, no chunking under 120 s | 1.5-2.5 GB | 0.1-0.3 s | Gating after the error-correlation (φ) audit | Stage 2 GPU |
| Primary voter: zh | `funasr/paraformer-zh@d7811ee3ac581fbcfdeb37c98c6ba674028433dc` | `model.pt` 0.88 GB (`5bba782a…`) | Apache-2.0 card; FunASR model license upstream (A, with notices) | funasr 1.4.16, torch 2.13.0 CPU, fixed threads, no hotwords or punctuation model | 1.2-1.8 GB | 0.3-0.8 s | Gating | Stage 2 CPU |
| Secondary voter: ja, ko | `FunAudioLLM/SenseVoiceSmall-GGUF@90c1c61912018b70ada0fcc024ea24aca62f2e63` | `sensevoice-small-f16.gguf` 0.47 GB (`23890396…`), replacing q8 | FunASR license v1.1 attribution and naming (A, with notices); same company as Paraformer | Existing llama.cpp runtime pin, `use_itn=False`, locked for ja/ko | < 1 GB | 0.1-0.3 s | Gating | Stage 2 CPU |
| Transitional witness | `mlx-community/whisper-small-mlx@45f39159…` (existing) | `weights.npz` (`55b6674c…`) | B | Existing worker | ~0.85 GB (measured, M2) | ~0.64 s (M2) | Legacy, until large-v3 qualifies | Stage 2 GPU |
| Adjudicator (non-voting) | `mlx-community/Qwen3-ASR-1.7B-bf16@e1f6c266914abc5a46e8756e02580f834a6cf8a7` (upstream `Qwen/Qwen3-ASR-1.7B@7278e1e7…`) | `model.safetensors` 4.08 GB (`2f080a3b…`); 8-bit alternative 2.46 GB (`bf304b00…`) | Apache-2.0 (A); **same lab as the generator** | mlx-audio 0.5.6 or mlx-qwen3-asr 0.4.4, greedy, no context string | 3.5-4 GB | 0.8-1.2 s, inconclusive rows only | Adjudicator: may corroborate a fail as `diagnostic-corroborated`, never convert a disagreement to pass | Stage 2 GPU |
| Timing instrument (non-voting) | `mlx-community/Qwen3-ForcedAligner-0.6B-bf16@53c8c0e46733eec430e4b53dd6471d0e5dee45f8` (upstream `@c7cbfc20…`) | `model.safetensors` 1.84 GB (`9d0728e1…`) | Apache-2.0 (A); same lab | mlx-audio 0.5.6; language explicit; word units for alphabetic languages, character units for zh, ja and ko; whitespace eojeol for ko (avoids soynlp) | 2-2.4 GB | 0.1-0.3 s | Supplies intervals to class B, C and F detectors that already have content consensus; never a vote | Stage 2 GPU |
| Offline calibration reference | Montreal Forced Aligner 3.4.2 | Per-language models | CC BY 4.0 models, MIT code (A) | conda-forge Kaldi | — | Once per panel | Research: measures aligner bias per language | Research |

Evidence for the picks:

- **Qwen3-ASR** reports strong accuracy across all ten languages in its own
  [report](https://arxiv.org/html/2601.21337v1) (vendor-reported). Its lab correlation keeps it non-voting.
- **Whisper large-v3 plus Paraformer-zh** is the Seed-TTS and CV3-Eval standard, and Qwen3-TTS's
  multilingual table uses Whisper large-v3
  ([Seed-TTS run_wer.py](https://github.com/BytedanceSpeech/seed-tts-eval/blob/main/run_wer.py),
  [CV3-Eval](https://github.com/QwenAudio/CV3-Eval/blob/main/utils/run_wer.py),
  [Qwen3-TTS](https://arxiv.org/html/2601.15621)).
- **Whisper large-v3 hallucinated on 40.3% of non-speech inputs**
  ([arXiv 2501.11378](https://arxiv.org/pdf/2501.11378)), so it is paired with a literal transducer
  or CTC-style voter.
- **The aligner's accuracy is vendor-reported.** Its accumulated average shift is 42.9 ms, against
  129.8 for NFA and 133.2 for WhisperX ([Qwen3-ASR card](https://huggingface.co/Qwen/Qwen3-ASR-1.7B)); the
  three averages cover 10, 7 and 5 languages respectively, so they are not directly comparable.

### 4.2 Language

| Role | Model @ revision | License (tier) | Runtime | Memory (est.) | Time (est.) | Status | Placement |
|---|---|---|---|---|---|---|---|
| Audio-LID vote 1 | `speechbrain/lang-id-voxlingua107-ecapa@0253049ae131d6a4be1c4f0d8b0ff483a0f8c8e9`, `embedding_model.ckpt` 84 MB (`ab750d5c…`), `classifier.ckpt` (`a50d9024…`) | Apache-2.0 weights; YouTube-derived VoxLingua107, copyright with the owners (B) | speechbrain 1.1.1, torch CPU, fixed threads | 0.4-0.7 GB | 0.05-0.15 s | Warn-only until calibrated per language and voice | Stage 2 CPU |
| Audio-LID vote 2 | Whisper large-v3 `detect_language`, from the same process as the voter | B | MLX | Shared | Included | Gating after calibration | Stage 2 GPU |
| Auxiliary | Parakeet output language (European); SenseVoice LID tag (CJK); Apple `NLLanguageRecognizer` on the transcript | — | — | — | — | Reported only | — |
| Adjudicator | Qwen3-ASR LID (`language=None` pass) | A, same lab | MLX | Shared | ~1 s | Non-voting | Stage 2 GPU |

**Rule.** Posteriors are restricted to the ten product languages plus an "other" mass. Pass needs
both votes to put the expected language top-1 with a calibrated margin. Long-form takes run language
ID per segment. GEN-XLANG and LNG-SWAP positives must fail on both votes.

**Caveats.** VoxLingua107 reports a 6.7% dev error, and its card warns of weaker accented speech and
a male skew ([card](https://huggingface.co/speechbrain/lang-id-voxlingua107-ecapa)). Aiden speaking
French and the Vivian and Ono Anna fixtures are therefore mandatory negatives.

### 4.3 Speaker identity and drift

| Role | Model @ revision | License (tier) | Runtime | Memory (est.) | Time (est.) | Status | Placement |
|---|---|---|---|---|---|---|---|
| Family 1 | `Wespeaker/wespeaker-voxceleb-campplus-LM@c5e01c6fcffcce160861e7e79782828320192b5c`, `voxceleb_CAM++_LM.onnx` 29.3 MB (`1068e4ac…`); Vox1-O EER 0.707% (LM), 0.659% with AS-Norm (vendor-reported) | Apache-2.0 card; VoxCeleb (B) | ONNX Runtime CPU, pinned `intra_op_num_threads` | 0.12-0.2 GB | ≤ 0.4 s with windows | Gating (decision 2) | Stage 2 CPU; beside the engine only in exploratory lanes (decision 7) |
| Family 2 | WeSpeaker ResNet293-LM (VoxCeleb), revision and ONNX digest pinned at acquisition (AQ-06). A different architecture from CAM++ but the same VoxCeleb training data, so the correlated-failure audit (section 5) must pass before the two may vote jointly. The seed-tts-eval WavLM-large SV checkpoint is excluded (tier C, GigaSpeech pretraining; section 4.9), so Vocello's SIM is not directly comparable to Qwen3-TTS's published 0.714-0.817 | Apache-2.0 card; VoxCeleb (B) | ONNX Runtime CPU, pinned threads | ~0.3 GB (est.) | ≤ 1 s (est.) | Gating (decision 2) | Stage 2 CPU |
| Continuity | `speechbrain/spkrec-ecapa-voxceleb@0f99f2d0…` (existing) | Apache-2.0 card; VoxCeleb (B) | torch CPU | 0.4-0.6 GB | 0.2-0.5 s | Shadow for one cycle, then retired | Stage 2 CPU |
| Drift features | Window embeddings (2 s windows, 0.5 s hop, voiced regions only); onset and seam identity delta = CAM++ cosine + pYIN register delta (st) + spectral-envelope Mahalanobis distance | — | DSP + ONNX | Shared | Included | Onset: warn until natural breaks are harvested | Stage 1 / 2 |

**Rules.** Fail only when both families fall below their calibrated thresholds; when they disagree,
the verdict is `abstain`, never pass. Impostors are same gender and same language first, extending
#103's gender-matched controls with language matching. Scores use AS-norm with a cohort of 200-500 embeddings, and each report
gives EER, FAR at 1% and Cllr. If tier B is refused (decision 2), identity stays advisory.

**Why a joint onset rule.** Off-the-shelf SV models correlate only 0.73-0.77 with human similarity
([VoxSim](https://arxiv.org/pdf/2407.18505)) and degrade on short windows
([ERes2NetV2](https://www.researchgate.net/publication/381158294_ERes2NetV2_Boosting_Short-Duration_Speaker_Verification_Performance_with_Computational_Efficiency)),
so embeddings alone cannot judge the first 1.5 s.

### 4.4 Pitch and prosody

| Role | Pick | License (tier) | Runtime | Memory (est.) | Time (est.) | Status | Placement |
|---|---|---|---|---|---|---|---|
| Pitch tracker | pYIN (librosa, ISC license; a probabilistic YIN with no learned weights), fixed frame and hop, the full 50-1,000 Hz range, voicing probabilities kept | Owned configuration of permissive code, no training data (A) | NumPy/librosa CPU | Bounded | ~0.2-0.5 s (est.) | Measurement; feeds class E and F | Stage 1 |
| Voice quality | NumPy reimplementation of the published Praat definitions: window-corrected autocorrelation HNR, jitter (local, RAP, PPQ5), shimmer (local, APQ3/5/11), CPPS, H1*-H2*, alpha ratio, Hammarberg index | Owned code (A) | NumPy | Bounded | 0.1-0.3 s | Measurement once oracle ladders pass (HNR ≥ 37 dB on noiseless sines, ±1 dB of Parselmouth on SNR ladders) | Stage 1 |
| Speaking rate | Aligner units per articulation-second: syllables for alphabetic languages, Hanzi, Hangul blocks, morae from a kana reading. De Jong-Wempe nuclei as a text-free cross-check | A | MLX / DSP | Shared | Included | Class C and F measurand | Stage 2 / 1 |
| Oracles (dev only) | Parselmouth (GPL-3.0, isolated process, never linked); SwiftF0 and RMVPE as research columns only (tier C training data) | — | — | — | — | Validation only | Research |

**Units.** Features are reported in speaker-normalized units: semitones against the voice's neutral
median, and z-scores against its voiceprint bank. This completes #40. SwiftF0 would be the stronger
tracker on published numbers (vendor-reported: the highest F1 of 19 trackers, tied with RMVPE, in
the [SwiftF0 paper](https://arxiv.org/abs/2508.18440), which describes the model before release 0.2.0
replaced it), but it trains on the CC BY-NC-SA 4.0
[pitch benchmark](https://github.com/lars76/pitch-benchmark), so it is tier C (section 4.9).

### 4.5 Artifacts

| Role | Pick | License | Runtime | Cost (est.) | Status | Placement |
|---|---|---|---|---|---|---|
| Stage 0 DSP (v9 candidates) | BS.1770 integrated loudness, short-term max, LRA and 4× true peak; pause-percentile noise floor plus WADA-SNR; effective bandwidth; clustered log-spectral-flux events per second; 12.5 Hz modulation index at the tokenizer frame rate; seam discontinuity z-score; self-similarity repetition stripe (≥ 600 ms, cos ≥ 0.95) | Owned (A) | Swift, inline | < 50 ms, < 20 MB per take | Observational, then warn, then fail per qualification | Stage 0 |
| Engine introspection | Codebook-0 n-gram cycles (for example an 8-gram repeated at least 3 times), per-step entropy summary (mean, p95, longest high-entropy run), EOS-probability trajectory, seam indices | Owned (A) | Swift, engine | ~0 | Loops may fail (exact); entropy and EOS warn | Stage 0 |
| Python mirror | The same DSP for offline replay and fixtures | Owned | NumPy | Bounded | Parity-tested | Stage 1 |
| Advisory screens | SigMOS DISC only (microsoft/SIG-Challenge; MIT; 48 kHz model, so band-limit caveat); DNSMOS P.835 BAK and SIG (microsoft/DNS-Challenge; CC BY 4.0). Repository commit and ONNX SHA-256 are pinned at acquisition; the research did not record them | A | ONNX CPU | 0.25 GB, 0.2 s | Advisory, after a ladder test | Stage 2 CPU |

The tokenizer runs at 12.5 Hz with 16 codebooks
([Qwen3-TTS-Tokenizer-12Hz](https://huggingface.co/Qwen/Qwen3-TTS-Tokenizer-12Hz)). BS.1770 is at
[ITU-R BS.1770](https://www.itu.int/rec/R-REC-BS.1770).

### 4.6 Quality (advisory)

| Role | Pick | License (tier) | Runtime | Memory / time (est.) | Status |
|---|---|---|---|---|---|
| Primary relative quality | `facebook/audiobox-aesthetics@9b1dd8e5df9af7216e836a98974fe3b82c56ded6`, `model.safetensors` 415.5 MB (`a5a3c241…`), pip `audiobox-aesthetics==0.0.4`. Out-of-domain system SRCC 0.813 (PQ), against 0.707 for UTMOSv2 | CC BY 4.0 (A) | torch CPU | 0.8-1.2 GB / 0.3-0.8 s | Advisory; PQ and CE as deltas against the cell baseline |
| Secondary | DNSMOS P.835 ONNX (Microsoft DNS Challenge; OVRL, SIG, BAK), pinned by file digest at acquisition (AQ-06); a screen, not a naturalness judge | CC BY 4.0 weights (A; training-data terms to confirm at acquisition) | ONNX Runtime CPU | ~0.25 GB / < 0.2 s (est.) | Advisory |
| Composite | Equal-weight z(PQ) + z(DNSMOS OVRL) − z(WER), with duration regressed out | — | Composer | — | Advisory; the only quality column eligible as a DP-31/DP-32 guardrail after a ladder test |

Neural MOS never reaches warn: no per-take validity was shown in this regime
([arXiv 2609.13150](https://arxiv.org/html/2609.13150),
[Audiobox paper](https://arxiv.org/html/2502.05139)).

### 4.7 Emotion (advisory)

| Role | Pick | License | Runtime | Cost (est.) | Status |
|---|---|---|---|---|---|
| Gated measurand | Paired, speaker-normalized arousal and prosody deltas (instructed minus neutral; same voice, seed and text), judged per cell by a sign test across seeds | Owned | Stage 1 | Negligible | Warn at cell level (class H) |
| Owned probe | L2-logistic or LDA head on mean-pooled mid-layer encoder states of the pinned Whisper encoder. Moves from whisper-small to large-v3 when that model qualifies. Trained on CREMA-D (ODbL), Thorsten-emotional (CC BY 4.0 per its Zenodo record) and JVNV (CC BY-SA 4.0); kept internal | A/B | Reuses the ASR pass | +0.1 s | Advisory, with top-2 margin abstention |
| Research judge | `mlx-community/Qwen2-Audio-7B-Instruct-4bit@c65570002626f41b4dc08b7b54f42f99f3e82e7f` pairwise A/B in both orders, scored by answer log-probabilities | Apache-2.0 (B); same lab as the generator | MLX | 7-8 GB, 3-6 s per pair | Research only, per cell; never per take |

**Scope.** Construction cannot create "angry", so autonomous qualification stops at measured
acoustic contrast. Semantic valence stays unmeasured; acoustic happy/angry separation depends on tier and arm (DP-22,
`config/roadmap-archive.json:1083`: UAR 0.765 at the normal tier in the 4-bit arm, null at the strong
tier and in the 8-bit arm).

### 4.8 Budget per take (est.)

| Configuration | Wall time | Peak memory |
|---|---|---|
| Stage 0 | < 50 ms | < 20 MB |
| After exit, serial | 3-5 s per 10 s take plus 5-15 s of loads once per run | ≤ 4.5 GB |
| After exit, admitted in parallel | GPU-bound at about 2-3.5 s per 8 s take | ≤ 10 GB |

### 4.9 Excluded, and why

| Item | Reason |
|---|---|
| NISQA v2 / NISQA-TTS | Weights CC BY-NC-SA 4.0; weak on clean TTS (TTSDS2 Table 3 correlations 0.05 to −0.64; onset-cluster AUC 0.54) |
| UTMOSv2 | SOMOS (NC-SA) and Blizzard in training; 3.6 GB; out of domain |
| `firdhokk/…-wav2vec2-large-xlsr-53` SER | Trained on RAVDESS, TESS and SAVEE (NC or research) |
| audeering dimensional; emotion2vec+; 3loi Odyssey; tiantiaf MSP-Podcast | CC BY-NC-SA or MSP-Podcast academic data; undisclosed pseudo-labels (emotion2vec+) |
| TorchAudio-SQUIM Subjective; SpeechJudge-GRM; Qwen2.5-Omni-3B; Audio Flamingo 3 | CC BY-NC, the Qwen Research License (NC) or NVIDIA NC terms |
| MMS-1B-all, MMS-LID, MMS-FA, `ctc-forced-aligner` default, torchaudio VoxPopuli aligners, Moonshine legacy non-English | CC BY-NC 4.0 or a non-commercial community license |
| mHuBERT-147 (TTSDS2 multilingual); VERSA as a suite | CC BY-NC-SA; VERSA wraps NC models without per-metric licenses and installs unpinned backends |
| SCOREQ | Weights CC BY 4.0 (Zenodo 13860326, 15739280), but trained on NISQA-corpus and other research data (tier C); reported to be gameable |
| UTMOS22 | BVCC and Blizzard training data (Blizzard samples cannot be redistributed); research column at most |
| SwiftF0 | Trained on the CC BY-NC-SA 4.0 pitch benchmark (tier C); pYIN replaces it (section 4.4) |
| Distill-MOS | Trained on NISQA-corpus (non-commercial research) and VoiceMOS labels (tier C); DNSMOS replaces it |
| WavLM-large SV (seed-tts-eval) | GigaSpeech pretraining, "only for non-commercial research" (tier C); ResNet293 replaces it as the second family, at the cost of SIM comparability with Qwen3-TTS's paper |
| Kotoba-Whisper, distil-whisper | Whisper family, so not independent; not better on read speech |
| Qwen3-Omni-30B-A3B, Qwen2-Audio as a per-take judge | Does not fit 16 GB (Omni); sampling-based D2 |
| lightning-whisper-mlx | Unmaintained since 2024-04; no license metadata |
| Cohere Transcribe | Gated click-through; no Russian (watch-list) |
| NVIDIA AmberNet | NGC terms, not a clear permissive license; needs NeMo |
| AASIST and deepfake detectors | Every output is synthetic, so the score measures detector domain, not defects |
| DistilHuBERT; ridge, EN and PLS heads | No QC measurand; never calibrated |
| Resemblyzer | Optimized for English |
| OAS alignment metric | Paper withdrawn ([2509.19852](https://arxiv.org/abs/2509.19852)) |
| zhconv, pykakasi, soynlp, nemo-text-processing / WeTextProcessing | GPL, or pynini wheels that are Linux-only |

---

## 5. Meta-evaluation and qualification protocol

**Template.** Published TTS judges are validated for ranking systems, never for per-take defect
verdicts:

- VoiceMOS and TTSDS2 validate at system level ([VoiceMOS 2024](https://arxiv.org/html/2409.07001),
  [TTSDS2](https://arxiv.org/html/2506.19441v1)).
- High inter-judge concordance is not accuracy: Kendall's W 0.97 among judges that share biases
  ([EmergentTTS-Eval](https://arxiv.org/html/2505.23009)).

Vocello therefore adopts operating-point testing from biometrics: false-alarm and false-rejection
rates (FAR, FRR) at a declared threshold, exact binomial bounds and DET curves
([BOSARIS](https://arxiv.org/pdf/1304.2865)). Labels come from construction, never from the judge.

### 5.1 Label tiers and populations

| Tier | Source | May qualify | May not qualify |
|---|---|---|---|
| T1 PCM construction | A registered injector, verified by recipe replay (source digest, injector version, parameters, seed → output digest) | TPR for that signal event; sham FAR | Perceptual severity; realism |
| T2 codec construction | A code-trace mutation decoded by the production decoder, verified by trace, recipe and decoder digests | TPR in the product's acoustic domain | LM-origin pathologies |
| T3 controlled generation | A registered knob with a certain effect: token cap, EOS suppression, L2 text with L1 pinned | Natural positives for truncation, run-on and wrong language | Any probabilistic knob (temperature, top-p) |
| T4 published labels | Corpus transcripts and metadata | Negatives for content, language and identity; SV trials | That a recording is defect-free |
| T5 cross-modal | A qualified detector of another modality and another family labels natural takes | Confirmation cohorts | Sole evidence for a new fail bound; any same-lineage label |
| T6 human annotation (optional) | The existing `speech-defects-1` protocol | As today | — |

**Populations.**

| Population | Content |
|---|---|
| N1 | Human originals: FLEURS, Common Voice and other §5.3 subsets with verified text |
| N2 | N1 resynthesized through the Qwen3-TTS tokenizer at full codebooks; FAR in domain |
| N3 | Natural Vocello takes over the script pool. With no labels, FAR ≤ f/(1 − π_max), where f is the flag rate and π_max the maximum defect prevalence |
| S | Shams: the same processing at zero magnitude |
| P1-P4 | Positives: PCM injections, codec injections, knob takes, and harvested natural failures with T5 labels |

### 5.2 Defect catalog and injection methods

Every injector is a pure function of (source, parameters, seed) with a golden digest, emits the
exact labeled interval, and has a sham. Word-aligned edits use the aligner on N1 and N2 only, where
the text is human-verified.

| ID | Defect | Method and sweep | Sham | Class |
|---|---|---|---|---|
| SIG-CLICK | Clicks | Impulses and 1-3 sample steps; 0.1-1.0 FS; 0.5-50 per s; isolated or clustered; voiced, quiet or silent placement | Identity | A |
| SIG-DROP | Dropout | Zero or −60 dB; 20-2,000 ms; interior, intra-word or at a pause; hard or 5 ms ramp | A natural pause of equal length at punctuation | A, C |
| SIG-CLIP / SIG-DC / SIG-LEVEL | Clipping, DC, level | Hard and tanh clipping 0.01-5%; DC 0.01-0.3; gain −10 to −50 dB | Gain without clipping | A |
| SIG-NOISE / SIG-BAND / SIG-CODEC / SIG-BUZZ | Noise, hum, band-limit, lossy codec, buzz | MUSAN noise at SNR 40-0 dB; hum; low-pass 8-3 kHz; Opus 6-24 kb/s and MP3 16-64 kb/s; pulse train −30 to −10 dB | Noise at 80 dB SNR; low-pass at 11.9 kHz; Opus 128 kb/s | A, G |
| SIG-SIL | Leading or terminal silence | 0.25-10 s of zeros or noise floor | 50 ms pad | A, C |
| CNT-DEL / INS / REP / SUB | Content edits | 1-5 aligned words; start, middle or end; gap 0-150 ms; same-speaker donor words | Splice-only (remove and re-insert) | B, I |
| BND-TRUNC / BND-RUNON | Boundaries | Last 1-5 words or 25-75% of the last word; append repeats, 0.5-4 s of speech or reversed speech | 20 ms fade; 300 ms room tone | C |
| IDN-SWAP / MORPH / SHIFT | Identity | Splice speaker B for 0.3-4 s at onset, middle or end (same-gender close or cross-gender); WORLD A→B morph over 1-4 s; ±2/±4 st and formant shifts | Same-speaker splice; WORLD resynthesis unmodified | E |
| PRS-OCT / BRK / RATE | Prosody | WORLD F0 ×2 or ÷2 over 50-400 ms; ±3/5/7 st steps; WSOLA 0.7-1.3× | WORLD 0 st; WSOLA 1.0× | F |
| LNG-SWAP / LNG-CS | Language | FLEURS parallel sentence in another language; L2 splices at 20-60% of the duration | Same-language swap or splice | D |
| SEAM-* | Long-form seams | Gain steps of 1-12 dB, tilt steps, 1-20 ms discontinuities | No step | J |
| COD-LOOP / SKIP / TRUNC / BABBLE | Codec (T2) | Repeat or delete 4-32 frames (0.32-2.56 s); drop the last 1-16; codes sampled from the marginals | Untouched trace | B, C, I |
| COD-SPLICE / CBLOSS / SEAM | Codec (T2) | Voice-B frames from frame k; keep codebooks 1..K for K = 1-12 of 16; ±1-3 frame seam misalignment | Same-voice splice; K = 16 | E, G, J |
| GEN-TOKCAP / NOEOS / XLANG | Generation (T3) | Cap at 50-90% of the uncapped length; suppress EOS for 6-50 frames; L2 text with L1 pinned (10 × 10 subset) | Uncapped; N = 0; matched language | C, D, I |

**T2 and T3 need new code, but no new product surface.** `BenchCodecReplay` replays only an
unmodified, digest-verified trace and requires an internal-diagnostics build with `QWENVOICE_DEBUG=1`
(`Sources/VocelloCLI/BenchCodecReplay.swift:51-68, :94`); a mutation-recipe replay mode must be
added. GEN-TOKCAP and GEN-NOEOS need registered knobs under the release-only rules;
`config/runtime-debug-knobs.json` lists none today.

**Abstention fixtures** must never return `pass`: silence, noise, music, square waves and NaN-bearing
PCM; clips under 1 s and takes of 60 s or more; whisper phonation, shouting and extreme F0;
repeated-word scripts and tongue twisters; brackets, digits and CJK text with embedded Latin;
explicit long pauses; and a mismatched script and voice.

**Procedural fixtures** (tones, glottal-pulse vowels, formant sequences, and seeded noise from
`PCG64.random_raw()` bytes) are generated in tests. No WAV is committed.

### 5.3 Clean-clip tiers and corpora

Corpus terms were read on 2026-09-25. Rows marked (verify) must be re-read at acquisition.

| Language | Primary read speech (N1) | TTS-grade or expressive | Notes |
|---|---|---|---|
| en | FLEURS en_us (CC BY 4.0); Common Voice (CC0); MLS (CC BY 4.0) | LibriTTS-R, VCTK (CC BY 4.0); CREMA-D (ODbL/DbCL); speechocean762 (CC BY 4.0, accented negative) | — |
| de | FLEURS; Common Voice; MLS | Thorsten (CC0) and Thorsten-21.06-emotional (CC BY 4.0 per its Zenodo record; ends may be cut off early, and clips are denoised and trimmed per `audio-qc-engineering.md:118-122`, so it is unsuitable as a class C or silence negative); HUI (CC0) | Whisper negatives for AQ-F11 come from the unedited Thorsten set |
| fr | FLEURS; Common Voice; MLS | SIWIS (CC BY 4.0); CSS10 | — |
| es | FLEURS es_419; Common Voice; MLS | CSS10; M-AILABS; OpenSLR 71-76 (CC BY-SA 4.0, internal only) | — |
| it | FLEURS; Common Voice; MLS | M-AILABS | — |
| pt | FLEURS pt_br; Common Voice; MLS | — | Record pt-BR against pt-PT per clip |
| ru | FLEURS; Common Voice | CSS10; M-AILABS | RUSLAN (NC) excluded; Golos (verify) |
| zh | FLEURS cmn; Common Voice zh-CN; AISHELL-1 (Apache-2.0) | AISHELL-3 (Apache-2.0, 218 speakers); THCHS-30 | NC Chinese sets excluded |
| ja | FLEURS; Common Voice | Kokoro and CSS10 (LibriVox public domain); JVNV (CC BY-SA 4.0) | JSUT and JVS excluded (NC audio) |
| ko | FLEURS; Common Voice; Zeroth-Korean (CC BY 4.0) | — | KSS (verify) and KsponSpeech excluded |
| Noise and RIR | MUSAN noise subset (CC BY 4.0, verify per track); RIRS_NOISES (Apache-2.0) | — | Injection sources |

**Terms for Common Voice.** Its terms forbid speaker identification, and re-hosting is treated as
not allowed until a primary source confirms otherwise (unconfirmed); and it is now
distributed through the Mozilla Data Collective. Its sentence corpus is CC0.

**Script pool.** The committed pool is CC0 Common Voice validated sentences, so every gated script
has a human recording (N1) and its codec resynthesis (N2). A per-language hard-case pool follows the
400-sentence seed-tts test-hard design. Digits and abbreviations go to a separate diagnostic pool.
The existing `config/language-bench-corpus.json` stays as a legacy cohort.

**What is committed.**

- **In Git:** manifests, recipes, CC0 texts, recorded measurement vectors, and the privacy-safe
  meta-evaluation records.
- **Never in Git:** human audio, and transcripts of fetched corpora.

Sources: [FLEURS](https://huggingface.co/datasets/google/fleurs),
[Common Voice MDC](https://mozilladatacollective.com/datasets?q=common+voice),
[MLS](https://huggingface.co/datasets/facebook/multilingual_librispeech),
[AISHELL-3](https://www.openslr.org/93/), [Zeroth](https://www.openslr.org/40/),
[Thorsten emotional](https://www.openslr.org/110/),
[JVNV](https://sites.google.com/site/shinnosuketakamichi/research-topics/jvnv_corpus),
[CREMA-D](https://github.com/CheyneyComputerScience/CREMA-D), [MUSAN](https://www.openslr.org/17/),
[JVS](https://sites.google.com/site/shinnosuketakamichi/research-topics/jvs_corpus).

### 5.4 Sample sizes

The table gives the minimum number of independent units for which the one-sided 95% Clopper-Pearson
(CP) upper bound on an error rate meets the target, with k errors observed. The same table sizes miss
rates, since TPR ≥ 1 − target.

| Target | k = 0 | k = 1 | k = 2 | k = 5 | Wilson two-sided, k = 0 |
|---|---|---|---|---|---|
| 0.20 | 14 | 22 | 30 | 50 | 16 |
| 0.10 | 29 | 46 | 61 | 103 | 35 |
| 0.05 | 59 | 93 | 124 | 208 | 73 |
| 0.02 | 149 | 236 | 313 | 523 | 189 |
| 0.01 | 299 | 473 | 628 | 1,049 | 381 |

These match the repository's Wilson figures: 0/60 gives 0.0602
(`docs/reference/audio-qc-engineering.md:874-878`).

**Independence and multiplicity.** The unit of independence is the source family, not the clip:
crops, injections and resyntheses of one utterance are one family, and one script × voice × seed is
one Vocello family, deduplicated by PCM digest. Intervals use a cluster bootstrap over families
(B = 2,000, fixed seed). Per-language claims are per stratum; a simultaneous ten-language claim uses
Bonferroni, which raises the k = 0 FAR ≤ 5% requirement from 59 to 104 per language. The worst
stratum is always reported.

### 5.5 Threshold derivation

1. **Split.** Calibration and confirmation cohorts are disjoint by family, speaker and script. No
   feature is extracted from the confirmation cohort before the plan's digest is committed.
2. **Neyman-Pearson from negatives only.** τ is the ⌈(n + 1)(1 − α)⌉-th order statistic of clean N2
   calibration scores, the split-conformal quantile. It guarantees a marginal FAR ≤ α
   ([Bates et al.](https://arxiv.org/abs/2104.08279)).
3. **Multi-parameter rules use Learn-then-Test** with a pre-ordered grid
   ([2110.01052](https://arxiv.org/abs/2110.01052)).
4. **TPR is measured, never optimized.** It must hold on two independent construction mechanisms,
   confirmed on the one the threshold was not fitted on. This is the structural defense against
   over-fitting to injections.
5. **Stratify only for a reason declared in advance** (for example, CER against WER languages, or
   units relative to the voice's F0). A missed stratum becomes a scope exclusion, not a new
   threshold.
6. **Confirm once.** Publish the record, including failed attempts; there is no silent retry.

**Where each threshold lives.** Stage 0 constants stay in Swift, and a Swift-side test asserts that
they equal the current calibration record for that algorithm version (never a Python reader of Swift
source, per release.md and dd28519e). Stage 1 and 2 parameters live
in the detector registry, bound to a record digest.

**Re-derivation always writes a new record.** Triggers: a judge identity change (de-qualify, canary,
re-qualify); a generator artifact change (drift panel, then new N2 and N3 FAR on an alarm); a
metric-definition change; a scope extension; an injector change (TPR only).

### 5.6 Additions to the threshold authority

The five rules at `docs/reference/audio-qc-engineering.md:853-860` stay verbatim. They move to
`qualification-policy.md` and to the policy file. The additions:

- **A1 Scope-bound status.** A detector gates only inside the scope of a qualified record
  (languages, modes, length class, F0 band, phonation). Outside it, the verdict is
  `abstain (out-of-scope)`.
- **A2 In-domain FAR.** FAR must be confirmed on N2 and bounded on N3. N1 alone never qualifies
  `fail`.
- **A3 Cross-mechanism TPR.** The TPR bound must hold on at least two construction mechanisms, one of
  them not used for fitting.
- **A4 Shams.** Every processed-positive family has a matched sham. A sham FAR that departs from the
  N2 FAR beyond interval overlap refuses the detector.
- **A5 Pre-registration.** The rule, grid, α, strata and split are committed by digest before the
  confirmation cohort is scored. Confirmation runs once, with no top-ups.
- **A6 No same-lineage labels.** T5 labels never come from a judge that shares family, vendor
  lineage or label lineage with a consumed judge. This generalizes `detectorSelfLabelsAllowed: false`
  (`config/prosody-holdout-policy.json:21`).
- **A7 Automatic de-qualification.** Any change to a consumed judge's output identity, the metric
  definition or the rule reverts the detector to `shadow`. The registry enforces this by digest.
- **A8 Status-specific operating points.** Fail is stricter than warn. See the table below.
- **A9 Heard defects.** A defect the maintainer hears enters Stage 0 or 1 as a shadow detector with a
  test, and the heard takes become P4 positives. It fails takes once it qualifies under A1-A8. This
  reconciles release.md with the authority (AQ-F38).
- **A10 Legacy bounds.** Existing Fast QC fail bounds stay, labeled `legacy-unqualified`, with their
  measured FAR and TPR reported from M1 onward. A bound is replaced only by a qualified successor,
  never removed on evidence of weakness alone.

| Status | FAR bound (CP 95%) | TPR bound (CP 95%) | Clean abstention | Minimum units |
|---|---|---|---|---|
| warn | ≤ 0.10 pooled, ≤ 0.20 per language | ≥ 0.70 on severe defects | ≤ 10% | The existing 60 calibration / 60 good / 60 bad, with ≥ 3 speakers, scripts and languages |
| fail | ≤ 0.01 pooled and ≤ 0.05 per language on N2; N3 flag-rate bound ≤ 0.05 | ≥ 0.90 severe and ≥ 0.70 moderate, on two mechanisms | ≤ 5% | 1,240 N2 negatives (124 per language) + 60 N3 per language + 60 positives per subtype × severity × mechanism |
| shadow / uncalibrated | — | — | — | Recorded; never blocks; never counts as pass |

**Physical events may qualify on T1 alone:** non-finite samples, digital silence, clipping above full
scale, and DC. For these the event is the defect. Every perceptual or content claim needs A2 and A3.

### 5.7 Protocol per detector class

| Class | Detectors | Construction | Negatives | Maximum status |
|---|---|---|---|---|
| A signal | Fast QC flags, loudness, noise floor, bandwidth, spectral flux, modulation, seams, onset bursts | T1 (+ T2 for spectral) | N1 including whisper and expressive speech, N2, N3 | fail |
| B content | Deletion, insertion, substitution, repetition, babble; per-reference-word projection; `longestDeletionRun` | T1 + T2 | N1 and N2 of the script pool; the per-language judge floor published | fail (deletion, repetition); warn (substitution) |
| C boundary | Truncation and run-on: aligner last word against file end (after content consensus), voter tail edits, hard-cut energy, EOS trajectory | T1 + T2 + T3 + P4 (the v8 run-ons) | N2; N3 including slow Design takes | fail. This class, not duration alone, qualifies a run-on fail (`audio-qc-engineering.md:803-812`) |
| D language | Two audio-LID votes, margin | T1 (FLEURS parallel) + T3 | N1 and N2 including accented speech (speechocean762, VCTK), N3 cross-lingual voices | fail (whole clip); warn (code-switch under 40%) |
| E identity | Whole-take SIM, window drift, onset and seam delta | T1 + T2 | Same-speaker expressive speech; same-speaker splice shams | fail (clone mismatch; swaps ≥ 1 s); warn (onset) |
| F prosody | Pitch breaks, octave jumps, creak | T1 via WORLD, after tracker validation | Expressive N1; WORLD 0 st sham | warn |
| G quality | DSP band-limit and modulation; neural columns | Ladders + T2 codebook loss | N2 | warn (DSP); advisory (neural) |
| H delivery | Paired arousal and prosody contrast per cell | Actor labels (CREMA-D, Thorsten, JVNV) | Engine neutral seeds | warn at cell level |
| I introspection | Token loops (exact); entropy and EOS | T2 loops; T3 | N3 | fail (loops); warn (entropy, EOS) |
| J long form | Seam z-score, seam identity delta, seam jump | T1 + T2 | N3 long form | warn, then fail when qualified |

Every class also reports the error-correlation φ between consensus partners and their joint-miss
rate, the partial AUC (pAUC) over FAR 0-5%, the expected calibration error (ECE) where probabilities
feed abstention, risk-coverage and the worst stratum. A consensus rule does not gate until its φ audit is recorded.

### 5.8 Regression canaries

| Tier | Runs models? | Consent | Catches |
|---|---|---|---|
| CI-py (every push) | No | None | Injector goldens; canonicalizer goldens; composer goldens (recorded vectors → exact verdicts); statistics goldens (CP, Wilson, cluster bootstrap, conformal, Learn-then-Test); schema checks; registry integrity; `refresh_derived_artifacts.py validate` |
| CI-swift (existing `macos_test.sh test`) | No | None | Stage 0 flags on procedural T1 fixtures with exact counts, extending `AudioQCStepBurstTests` to every flag; Swift constants equal to the current record |
| Judge canary | Yes | Explicit request | About 120 pinned clips (procedural, N1/N2 public, frozen N3) plus metamorphic relations. D0 judges must match bitwise. D1 judges must match exactly on discrete outputs and within ε on scores. D2 judges are never eligible |
| Qualification run | Yes | Explicit request | The section 5.7 protocol for changed judges and detectors |
| Drift panel | Yes | Explicit request | 300 takes per generator artifact (10 languages × 3 voices × 5 scripts × 2 seeds; est. 15-35 min, see section 3.4). Compared by KS, PSI and CUSUM against calibration; an alarm opens a review and never moves a threshold |

**Metamorphic relations.** Gain ±6 dB, the 24→16→24 kHz round trip, ±150 ms padding, polarity and
−90 dBFS dither leave verdicts unchanged. Self-concatenation must fire repetition, and reversed audio
must fail or abstain. Silence or noise in place of speech must yield no text; any text is a
hallucination event. A text swap and a wrong expected language must fail. WSOLA at 0.95 or 1.05×
scales rate by 1/speed. SV scores are symmetric. Scores rise monotonically with severity
(Spearman ≥ 0.9).

**Registry integrity (CI).** Every `warn` or `gating` judge needs a canary record whose output
identity equals the registry's, plus a matching calibration record, or CI fails.
`scripts/dev.sh check` names "judge canary required" when a judge's worker, config or pins change.
Canary goldens bind the host profile, so an M2 result is never compared with an M6 golden.

### 5.9 How a judge or detector gains and loses gating status

| Transition | Requires |
|---|---|
| → `candidate` | Registry entry with pins, license tier A (or B under decision 2), independence fields, exclusion-list pass |
| candidate → `shadow` | Two clean M6 resource runs (measured peak RSS and footprint, recovery, no swap growth), determinism class measured, canary record matching its output identity |
| shadow → `warn` | A qualified calibration record at the warn operating point for its declared scope (A1-A8) |
| warn → `gating` | A fail-level record on two mechanisms (A3), shams (A4), φ audit for consensus partners, N3 bound (A2) |
| any → `shadow` | Output-identity, metric or rule change (A7); canary mismatch; confirmed judge drift |
| any → `quarantined` | License or terms change, or digest drift at acquisition. Execution stops until a decision |
| any → `retired` | Superseded by a qualified successor, or maintainer decision. Validators needed to read legacy records are kept |

---

## 6. Normalization plan per language

**Common to all ten languages.** Normalization v2 lives in `language_metrics.py`, with Swift parity
for the in-app verdict. The host re-scores every recognition (`scripts/check_language_output.py:278`,
`scripts/publish_benchmark_history.py:2852-2947`), so Python is authoritative for published records.
The steps:

- NFKC, then casefold. Korean uses NFC; see its row.
- Map Unicode P\* and S\* to spaces, keeping intra-word apostrophes for en, fr and it.
- Collapse whitespace.
- Strip recognizer tags (SenseVoice `<|…|>`).
- **Never delete bracket contents.** Delete only the bracket characters.
- For Latin and Cyrillic text, the primary metric keeps today's fold (NFKD, then drop `Mn` marks)
  and adds the `ADDITIONAL_DIACRITICS` map (ß→ss, æ→ae, œ→oe, ø→o, ł→l).
- Count fillers; never erase them.
- Keep WER v2 (segmentation-aware) as the word metric, as today, and report a space-free CER as a
  secondary metric everywhere.
- A corpus lint keeps digits, symbols, abbreviations and parentheses out of gated scripts.

Normalization is part of every content detector's identity. Changing it bumps the metric-definition
version (L2 cache) and the language kinds' measurement version, and re-qualifies consumers.

| Lang | Primary metric | Language-specific steps | Diagnostics | Voters | Notes |
|---|---|---|---|---|---|
| en | WER v2 | British/American map from Whisper `english.json`, without its bracket or filler steps | Verbalized-digit WER (num2words) | Whisper-L-v3 / Parakeet | — |
| de | WER v2 | ß→ss; compounds handled by WER v2 plus space-free CER | Diacritic-preserving WER (umlauts) | Whisper-L-v3 / Parakeet | German compounds motivated WER v2 (#43) |
| fr | WER v2 | Apostrophe joins elisions (l', d', qu'); œ→oe | Diacritic-preserving WER | Whisper-L-v3 / Parakeet | Accent leakage from `aiden` is a D-class negative |
| es | WER v2 | ¿ and ¡ as punctuation; ñ folds (symmetric, documented) | Diacritic-preserving WER | Whisper-L-v3 / Parakeet | — |
| it | WER v2 | Apostrophe elisions kept intra-word | Diacritic-preserving WER | Whisper-L-v3 / Parakeet | Aligner AAS is highest for it (75.5 ms, vendor) |
| pt | WER v2 | ç and ã fold; record the variant (pt-BR or pt-PT) | Diacritic-preserving WER | Whisper-L-v3 / Parakeet | Parakeet trained on European Portuguese; check which variant Qwen3-TTS speaks |
| ru | WER v2 | ё→е and й→и folds (symmetric, documented); Cyrillic only | Latin-script transcript flagged as a language signal | Whisper-L-v3 / Parakeet | Digits inflect by case and gender, so keep them out |
| zh | CER, space-insensitive | OpenCC `t2s` on both sides; Arabic digits → Chinese numerals with cn2an | — | Paraformer-zh / Whisper-L-v3 | Never zhconv (GPL) |
| ja | CER, space-insensitive, NFKC (dakuten kept) | Digits → kanji numerals (num2words `ja`) | Kana-reading CER (fugashi + unidic-lite) | Whisper-L-v3 / SenseVoice-f16 | Never pykakasi (GPL); the reading CER inherits MeCab errors |
| ko | Syllable CER, NFC, space-insensitive | Hangul blocks as units (not NFKD jamo) | Jamo CER | Whisper-L-v3 / SenseVoice-f16 | Sino-Korean against native numerals is ambiguous, so keep digits out; never soynlp |

**New dependencies.** Four Python dependencies need maintainer-authorized pins: opencc 1.4.2
(Apache-2.0), cn2an 0.5.24 (MIT), num2words 0.5.14 (LGPL-2.1, internal tooling, to be listed in the
notices policy), and fugashi 1.5.2 with unidic-lite 1.0.8 (MIT/BSD).

**Swift.** For the in-app zh verdict, Swift may use ICU's `Hant-Hans` transform, with a parity
fixture that lists known OpenCC divergences.

---

## 7. Keep, fix, replace or delete

### 7.1 Per component

| Current component | Verdict | Action |
|---|---|---|
| Swift Fast QC v8 (`GenerationOutputAdapter.swift`) | **Keep + fix** | Stays the only product gate, with its fail bounds (A10). Add the v9 DSP and introspection fields (additive, observational); procedural tests for every flag; qualify a per-second click bound and an adaptive floor. The run-on fail comes from class C. |
| Quality registry gates; clone leading-silence gate | Keep | — |
| Long-form seam jump | Fix | Calibrate with SEAM-\* and COD-SEAM; warn until qualified |
| `scripts/lib/audio_qc.py` | Keep + fix | Publish `rmsDBFS`, peak, hot samples, trailing silence and loudness (V-10) |
| Apple Speech verifier (iPhone) | **Keep + fix** | Keep it as the on-device family, and its 3 passes as repeatability. Its language judgement becomes auxiliary; Mac audio LID over the pulled WAV decides language. Measure the Apple side of the control. |
| whisper-small MLX | **Replace after dual run** | Keep the worker, offline and supervisor pattern. The dual run on the existing matrix records every flip (McNemar). |
| `language_metrics.py` and the language verdicts | **Keep + fix** | Keep the per-channel consensus and WER v2. Add normalization v2, 10 languages, the CV script pool and multi-seed, multi-voice cells. |
| `analyze_prosody.py` v3 | **Fix** | Host for pYIN, window-corrected HNR and speaker-normalized units |
| `prosody_quality_gate.py` flags | **Replace** | Monotone, rushed and flat have no defect definition (1 flag in 902 takes). Class F and C detectors replace them; the flags are deleted unless re-defined and qualified. |
| `delivery_quality_gate.py` | Keep + fix | Class H, cell level only (#39 landed) |
| Holdout, calibration, separability tooling | **Keep + generalize** | `prosody_holdout_validation.py` becomes the qualification engine (CP bounds, cluster bootstrap, conformal thresholds, Learn-then-Test, tiers T1-T6) |
| Delivery evaluator v2 cascade | **Fold in** | Its layering (deterministic first, neural serial, native receipt wins) becomes the section 3 pipeline |
| DistilHuBERT; ridge, elastic-net and PLS heads | **Delete from QC** | No measurand; never calibrated |
| SenseVoice q8 | **Replace** | f16, as the ja/ko voter |
| NISQA | **Delete** | Tier C; weak |
| `delivery_resource_supervisor.py` | **Keep + fix** | Child-attributed recovery; per-judge M6 ceilings; admission semaphore; identity split; canonical-host adoption wording |
| ECAPA clone similarity | **Fix → shadow → retire** | Re-derive with hard impostors and AS-norm; CAM++ and ResNet293 (both tier B, decision 2) succeed it |
| Clone prosody fidelity, VLR, reference banks | Keep (research) | Feed fixtures and classes E and H. Bank selection drops the SER. |
| SER advisory; UTMOSv2 advisory | **Delete** | Tier C; replaced by the probe and by Audiobox/DNSMOS |
| Playback capture (UI fail gate) | Keep | Physically defined, D0 |
| `clip_quality_screen.py` | Fold in | Its separation statistics become class G ladders |
| Analysis cache, FIR resampler | **Keep + generalize** | L0-L2 cache and canonicalizer |
| Long-form probe, failure topology, speech-asset check | Keep | Research, report and prerequisite roles |

### 7.2 Migration that keeps legacy evidence valid

| Phase | Content | Verdict impact | Lineage |
|---|---|---|---|
| M0 Describe | Registries describe the current judges as they are (`asr.whisper-small@1`, `asr.apple-speech-consensus@2`, `fastqc@8`, `prosody@3`), with calibration `legacy-unqualified`, and map legacy identity fields to registry ids | None | No record changes |
| M1 Measure the present | Qualification engine, injectors, canary; classes A-F run against the current judges, report-only | None | New `qc-calibration` kind. Legacy judges gain accuracy **context** in the generated report only |
| M2 Normalization v2 | Section 6 | Language verdicts may move | Measurement-version bump for the language kinds |
| M3 Shadow | New judges run beside legacy ones; flip analysis; M6 resource qualification | New verdicts `uncalibrated` | New fields under a new evidence contract, so a new comparison key. Legacy keys stay byte-identical |
| M4 Qualify and promote | Per detector: pre-register, calibrate, confirm once, promote | Lane gating sets switch | Each promotion bumps the evidence contract; `benchmarks/HISTORY.md` marks the boundary |
| M5 Swift v9 | Qualified Stage 0 additions; algorithm version 9; consent-bound gate re-seed | Product gate changes only by qualified change | The algorithm version is part of the gate identity |
| M6 Retire | Legacy judges `retired`; NISQA, UTMOSv2, SER, DistilHuBERT and heads removed from QC paths | — | Only the validators needed to read legacy records remain |

**Lineage rules.** Records are never rewritten. A change to what a kind measures bumps its
measurement version (`scripts/lib/lineage_identity.py`). A change to the judge set, detector versions
or calibration set enters the key through the evidence contract, so legacy and new records never
share a comparison key (`.claude/rules/release.md:87-98`). Legacy verdicts are re-interpreted only in
the generated report's "legacy judge accuracy" section.

---

## 8. Recommended sequence

### 8.1 Phases

Labels: **code-only**; **downloads** (maintainer-authorized model, corpus or package acquisition);
**consent-bound** (a model, benchmark or device lane run on explicit request in the lead session).
Effort is engineer-days (est.). Agents may run phases with non-overlapping files in parallel
worktrees. In the tables of sections 8 and 10, `Fnn` abbreviates finding `AQ-Fnn`.

| Phase | Label | Content | Findings | Effort (est.) |
|---|---|---|---|---|
| P0 License correction | code-only | Correct NISQA to tier C with `commercialUseCompatible: false`; record UTMOSv2, SER and ECAPA provenance; mark NISQA, UTMOSv2 and SER `quarantined`; exclusion-list test. The NISQA correction is decision 1 (it stops NISQA in the cascade); provenance records that change no gate are not. | F01-F06 | 1 |
| P1 Registry M0 and identity | code-only | `audio-qc-judges.json` describing today's judges; output/envelope identity split; "two clean canonical-host runs" wording; stale 8 GB text rewritten | F40, F43, F45, F47 | 3-4 |
| P2a Normalization v2 (no new packages) | code-only | Korean syllable CER, NFKC and casefold, extra folds, tag stripping, bracket safety, space-free CER, corpus lint, fixtures, Swift parity | F21, F24-F26 | 3 |
| P2b Normalization v2 (packages) | downloads, then code-only | OpenCC, cn2an, num2words, fugashi and unidic-lite pins | F22, F23, F26 | 1-2 |
| P3 Qualification engine | code-only | Statistics, T1 injectors with shams, metamorphic relations on recorded vectors, composer goldens, policy file draft (A1-A10), `qc-calibration` kind; M1 over procedural fixtures and committed records | F07, F33, F34, F36-F39 | 12-15 |
| P4 Stage 0 observational | code-only | v9 DSP fields and engine introspection, additive to QC v8 like the click events | F08-F12, F49 | 8-10 |
| P5 Pipeline | code-only | Orchestrator, persistent workers, admission semaphore, L0-L2 cache, evidence schema, private bundle, report generator, corpus fetcher with digest verification | F41, F42, F44, F46, F48 | 12-15 |
| P6 Documentation | code-only | `docs/reference/audio-qc/` skeleton, judge pages, generated blocks, contract test; `audio-qc-engineering.md` to historical | F50, F51 | 4-5 |
| P7 Acquisition | downloads | Judges about 13.5 GB (est.): large-v3 3.08, Parakeet 2.51, Qwen3-ASR 4.08, aligner 1.84, Paraformer 0.88, SenseVoice f16 0.47, ResNet293 ~0.1 (est.), Audiobox 0.42, the rest < 0.2. Corpus subsets 3-8 GB (est.): ten-language N1 subsets, Thorsten-emotional (748 MB, already retained per `audio-qc-engineering.md:191-192`), MUSAN noise, RIRs | F29, F32 | Maintainer 0.5-1 |
| P8 First M6 session | consent-bound | Per-judge two-run resource qualification; determinism repeats (D1 → D0); M1 on N1; whisper-small against large-v3 dual run on the existing matrix | F14, F20, F29 | 1 session (est. 3-5 h) |
| P9 T2 and T3 | code-only, then consent-bound | Codec mutation replay mode; token-cap and EOS knobs (registered, release-only); N2 resynthesis lane | F09, F34 | 8-10 + 1 session |
| P10 Qualification | consent-bound | Classes A, B, C and D first; then E, I and J; F, G and H to warn. Promotion per record | F07, F13, F15-F17 | Several overnight sessions (est. 5-8 h each) |
| P11 Swift v9 and retirement | code-only, then consent-bound | Qualified Stage 0 promotions; version 9; gate re-seed; M6 retirement | F49 | 3 + 1 session |

**Total effort (est.).** About 55-70 engineer-days of code, one acquisition step, and four to six
consent-bound sessions.

**Order constraints.** P0 comes first. P3 comes before any promotion. P4 and P11 respect the AV-17
gate re-seed (decision 8). P8 needs P1, P5 and P7.

### 8.2 What can start immediately, without any decision

- **P0's provenance records** that change no gate or execution path (UTMOSv2, SER and ECAPA
  provenance, the exclusion-list test). The NISQA correction and the retirements are decision 1.
- **P1 without the adoption wording**, which is decision 7.
- **P2a.**
- **P3 through M1** on procedural fixtures and committed records, with A1-A10 written as a draft
  policy and without `.abstained`; both bind only after decision 7.
- **P4 as additive observational fields** that keep QC v8, which is valid under either option of
  decision 8.
- **P5 without the admission semaphore and the recovery rule** (decision 9), and **P6 without the
  release.md rewrite** (decision 7).

None of these runs a model, a lane or a download.

---

## 9. Maintainer decisions required

1. **License posture.** Correcting the registry is itself this decision: marking NISQA
   `commercialUseCompatible: false` makes `prepare_delivery_compact_model_config.py:73` and
   `delivery_compact_model_adapter.py:66` refuse it, so NISQA stops running in the delivery cascade
   (`run_local_delivery_cascade.py:485-488`); `quarantined` also blocks execution. (a) Correct the
   registry and retire NISQA, UTMOSv2 and the SER from every QC path; (b) correct the registry but
   keep them as NC-labeled research columns outside any gate, guardrail or selection, which needs new
   code to let a tier-C candidate run; (c) status quo, which keeps a mislabeled registry. DP-32's
   `relativeUTMOSDelta` guardrail then uses the qualified composite of section 4.6 or is dropped.
   **Recommend (a)**, with the composite as the guardrail once it passes its ladder test.
2. **Tier-B weights** (scraped training audio, rights with the owners, no explicit NC term): Whisper
   large-v3 and today's whisper-small, Parakeet v3, the VoxLingua107 ECAPA, and the VoxCeleb-trained
   CAM++, ResNet293 and ECAPA. (a) Accept tier B for internal evaluation that never ships, recorded
   per judge; (b) accept it for recognizers and LID but refuse the speaker models, so identity stays
   advisory; (c) refuse tier B, which removes every Mac recognizer (including today's whisper-small)
   and LID vote 1, leaving only Apple Speech on the iPhone, so Mac content and language verdicts
   become unavailable. **Recommend (a).** Tier C (SwiftF0, Distill-MOS, WavLM-SV, NISQA, UTMOSv2,
   the SER) stays excluded under every option. Two VoxCeleb speaker families carry a correlated-error
   risk that the section 5 audit must bound before they vote jointly.
3. **Same-lab judges** (Qwen3-ASR and Qwen3-ForcedAligner). (a) Non-voting: the adjudicator only
   corroborates, the aligner only supplies intervals, and neither provides T5 labels; (b) let
   Qwen3-ASR vote for Korean only, with `vendorCorrelatedWithGenerator: true` and the other voter
   required to agree; (c) exclude both. **Recommend (a).**
4. **Downloads:** models of about 13.5 GB (est.), corpus subsets of 3-8 GB (est.) under per-corpus
   terms (Common Voice: no speaker identification, re-hosting treated as not allowed; ODbL and CC BY-SA material kept
   internal), and four Python packages. (a) The full panel at once; (b) staged: the six current
   languages' corpora with the European and zh panels first, then it, pt, ru and ko; (c) none,
   leaving only procedural fixtures and N3, with the warn ceiling everywhere. **Recommend (b).**
5. **Gating bar.** (a) Warn at the existing 60/60/60 floor (FAR ≤ 0.10); fail at CP FAR ≤ 1% pooled
   and ≤ 5% per language on N2 (1,240 N2 + 600 N3 negatives; 60 positives per subtype × severity ×
   mechanism); (b) a lighter fail bar for evidence-lane gating only: FAR ≤ 2% pooled (149 at
   k = 0) and ≤ 10% per language; (c) one bar for both statuses. **Recommend (a) for any
   product-affecting fail, with (b) acceptable for evidence lanes.** New claims use one-sided
   Clopper-Pearson; Wilson stays for legacy records.
6. **Apple Speech on the iPhone.** (a) Keep it as the on-device family and repeatability check, make
   its language channel auxiliary, let Mac audio LID over the pulled WAV decide language, and
   measure the Apple side of the control; (b) retire it from verdicts, so only Mac panels judge
   pulled WAVs; (c) status quo. **Recommend (a).** The modern `DictationTranscriber` migration is
   optional and separate.
7. **Threshold-authority and rule changes.** Adopt A1-A10 into
   `config/audio-qc-qualification-policy.json` and move the authority to
   `docs/reference/audio-qc/qualification-policy.md`. Rewrite release.md:115-125 so recognizer
   families come from the judge registry, whisper-small is no longer "the" Mac producer, the
   SenseVoice sentence is updated and the heard-defect rule reads as A9. Replace the adoption
   wording with "two clean canonical-host runs". Add Swift `.abstained`. Optionally, let CPU judges
   with a ceiling of 1 GiB or less run beside the engine. **Recommend adopting all of these, with the
   optional concurrency limited to exploratory lanes;** evidence lanes keep the strict after-exit
   rule.
8. **QC algorithm-version timing.** The M6 gate baseline was seeded at `qcAlgorithmVersion` 8
   (AV-17 step 1, ce66096c; `benchmarks/baselines/mac-gate-bench.json`), and the gate identity binds
   that version, so any bump to v9 needs another seeded re-seed (three runs on one clean commit).
   (a) Keep v8, land Stage 0 additions as additive observational fields, and bump to v9 once, with
   the first qualified promotion and a planned re-seed; (b) bump to v9 as soon as Stage 0 lands and
   re-seed then. **Recommend (a).**
9. **Resource admission and the recovery rule** (AQ-F41, AQ-F44). (a) Replace the host-wide flock
   with a budgeted admission semaphore after the generator exits (about 10 GB, est.), and promote the
   child-attributed post-exit recovery rule to binding once M6 evidence supports it; (b) keep the
   flock and the whole-host rule. **Recommend (a).**

---

## 10. Proposed roadmap items

New plan `audio-qc-audit-2026-09`, owner `backend-mlx`, authority this document.

**Goal:** make the audio QC and speech-analysis harness measure its own accuracy and judge audio
autonomously on the M6. It rests on license-cleared pinned judges, construction-labeled
qualification and one staged pipeline, and never rewrites legacy evidence.

| Item | Title | Scope (findings) | Gate | Depends on | Label |
|---|---|---|---|---|---|
| AQ-01 | License-clean judge registry | F01-F06, F40, F43, F45, F47; P0, P1 | No non-retired judge is tier C or unknown; NISQA, UTMOSv2 and SER are retired or quarantined per decision 1; every judge loads offline after digest verification; the adoption wording names the canonical host; output and envelope identities are split with an offline replay showing no cache invalidation on a supervisor-only change | Decision 1 (retirement only); decision 2 for tier-B entries | code-only |
| AQ-02 | Normalization v2 and ten-language coverage | F21-F28, F32; P2a, P2b | Per-language fixtures pass in Python and Swift parity; Korean scores by syllable CER; the corpus lint refuses digits and brackets in gated scripts; the CC0 script pool covers all 10 languages with manifests; the language kinds' measurement version is bumped with legacy keys unchanged | Package pins (decision 4) | code-only + downloads |
| AQ-03 | Qualification engine and injector catalog | F07, F33, F34, F36-F39; P3 | CI goldens for injectors, statistics and composer; the policy file with A1-A10 validates; the first generated meta-evaluation report (M1) quantifies Fast QC v8 flags on procedural and committed evidence; the Swift `.abstained` outcome is tested | Decision 7 (binding) | code-only |
| AQ-04 | Stage 0 observational DSP and engine introspection | F08-F12, F49; P4 | Every new field has procedural T1 tests with exact expected values; fields are additive to QC v8 with no verdict change; the Python mirror matches Swift on fixtures | Decision 8 | code-only |
| AQ-05 | Staged pipeline, workers and admission | F41, F42, F44, F46, F48; P5 | One worker per model per run; the admission semaphore enforces registry ceilings; an L0-L2 cache replay reproduces current cascade and language verdicts exactly; the evidence schema and private bundle validate; DistilHuBERT and heads are removed from QC paths | AQ-01; decision 9 | code-only |
| AQ-06 | Judge panel acquisition and M6 qualification | F13, F14, F20, F29; P7, P8 | Each panel judge has two clean M6 resource runs, a measured determinism class and a canary record; the whisper-small against large-v3 dual run publishes its flip analysis; judges reach `shadow` | AQ-01, AQ-05; decisions 2-4 | downloads + consent-bound |
| AQ-07 | Detector qualification and lane gating sets | F07, F10, F13, F15, F17, F29-F31; P9, P10 | Calibration records meeting A8 for classes A-D (then E, I, J) in declared scopes; φ audits recorded; the language bench gates on B, C and D and publishes two-family records; the clone lane gates on E | AQ-02, AQ-03, AQ-06; decision 5 | code-only + consent-bound |
| AQ-08 | Prosody, delivery and advisory quality rebuild | F16, F18, F19; section 4.4-4.7 | pYIN and HNR pass the oracle ladders; prosody flags are replaced by class F detectors; class H warns at cell level only; the Audiobox and DNSMOS composite passes its ladder test; the DP-31/DP-32 guardrails cite only qualified judges | AQ-03, AQ-06 | code-only + consent-bound |
| AQ-09 | Audio QC documentation and generated accuracy report | F50, F51; P6, P11 docs | The `docs/reference/audio-qc/` tree exists with one page per registry judge; `refresh_derived_artifacts.py validate` covers the generated blocks; the contract test refuses a gating detector without a scope-covering record; `audio-qc-engineering.md` is historical; release.md is updated per decision 7 | AQ-01, AQ-03 | code-only |

**Overlap with existing items.**

| Existing | Relation | Recommendation |
|---|---|---|
| BT-05 | Code landed in waves 8-9. Open, per its notes: consented runs (lang-bench, delivery sweep, prosody calibration, clone lane, gate noise runs, bounds cohort) and AV-17(5); the notes already expect this audit to supersede parts | Let BT-05 close on its live-proof runs (lang-bench, delivery sweep, gate noise, AV-17(5)). Move the bounds cohort (speaking-rate and click fail bounds, #10 and #85), the prosody calibration and the clone-lane band calibration (#103) to AQ-07 by note, where they become class C, A, F and E qualifications. |
| DP-28 | The layered evaluator, abstaining heads, serial 8 GB envelopes | **Supersede** by AQ-08 (`supersededBy`; `legacyIds` on AQ-08). The pipeline itself is AQ-05. |
| DP-29 | Corpus structure and fluent review of zh, ja and ko scripts | Keep. AQ-02 reuses its leakage validators. CC0 Common Voice sentences may offer review provenance; the maintainer decides whether that satisfies "fluent review". |
| DP-31 / DP-32 | Frozen holdout and promotion guardrails naming UTMOS and SIM | Keep. Add `blockedBy` AQ-07 and AQ-08. Replace the UTMOS guardrail per decision 1. |
| AV-07 | Prosody threshold validation and click recalibration | **Supersede** by AQ-07, with `legacyIds` AV-07. Its prosody part becomes class F, and its click part class A. |
| AV-08 | Multilingual qualification; whisper-small's 8 GB qualification; the first two-family iOS record | Keep it parked for the iPhone record. Rewrite its gate to cite the AQ-06 panel. The whisper-small 8 GB clause becomes historical. |
| RF-06, ICA-06, ICA-15, VLR-07 | Product audio defects | Keep. AQ-04 introspection (EOS trajectory, token cycles) and the AQ-07 class C, I and J detectors give them instruments. GEN-NOEOS and GEN-TOKCAP reproduce their failure shapes. VLR-07's "edge coverage only" caveat is resolved by aligner interior coverage once qualified. |

---

## 11. Risks

| Risk | How it shows | Mitigation | Residual |
|---|---|---|---|
| Correlated judges | Parakeet's labels are Whisper pseudo-labels; Paraformer and SenseVoice share a company; the SV families all train on VoxCeleb; the aligner and adjudicator share the generator's lab | φ and joint-miss audit before any consensus gates; same-lab judges do not vote; A6 | Shared blind spots on Qwen-specific mispronunciation stay invisible until P4 harvests them |
| Injected defects unlike real ones | Detectors learn splice or vocoder traces | T2 decoder-domain injection, T3 knobs, shams (A4), cross-mechanism TPR (A3), P4 harvest | Subtle LM-origin mispronunciation: substitution stays warn |
| Over-fitting thresholds | High injected TPR, poor real TPR; threshold creep | Thresholds from negatives only; TPR never optimized; pre-registration; confirm once | Negatives can over-fit the corpus mix; the drift panel watches it |
| Human corpus label noise | Misreads in FLEURS or Common Voice inflate FAR | Judge-independent metadata filters (up-votes ≥ 2, down-votes 0); report FAR before and after filtering | A conservative floor of genuine corpus errors |
| Domain gap | Human FAR does not transfer to TTS | N2 resynthesis, N3 bound (A2) | Product prosody appears only in N3. If N2 raises the judge floor, the codec is itself reported |
| Goodhart pressure | Prompt, seed or bank selection tuned against the gating judges | Promotion needs an independent family unused in selection (`delivery_promotion_decision.py` schema 2); composite quality; per-release natural-failure rates | All-family blind spots |
| MLX nondeterminism and repo churn | Transcripts flip across runs; mlx-community re-uploads (2026-04-12) | D1 class with abstention on repeatability disagreement; revision and SHA pins; one-time parity against upstream weights | Cross-host comparison invalid by design |
| License and terms drift | Cards mislabel weights (NISQA); corpora change distribution (Common Voice) | Tier and risk fields; re-check at every pin change; quarantine status | Legal interpretation of tier B and ODbL/SA stays a maintainer call |
| Over-abstention | Strict scope and consensus make lanes mostly `inconclusive` | Coverage floors (A8); risk-coverage reporting; scope growth by qualification | Early phases honestly report "unmeasured" |
| Consent friction and cost | Overnight qualification needs explicit requests | Incremental cache; threshold-only changes cost no model time; a small drift panel | The first full qualification is a large one-time lane |
| Dependency weight | torch, funasr, speechbrain, mlx-audio, parakeet-mlx, onnxruntime and a separate Python MLX pin | Pinned per judge in the registry; evaluators never ship; a Python MLX pin separate from the engine's Swift MLX pins | Upgrade churn in tooling |
| Privacy | Voices are biometric; transcripts can leak into records | No human audio or transcripts in Git; opaque group ids; digests and metrics only; home-path stripping | — |
| Existing click-bound debt | The v8 click bound flags professional speech (unconfirmed as audible) | M1 measures it; the successor qualifies under A1-A10 | The legacy bound stays until then (A10) |
