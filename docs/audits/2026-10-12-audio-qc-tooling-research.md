---
status: active
owner: backend-and-platform
reviewed: 2026-10-12
summary: Survey of tools, models, dependencies, MCP servers, plugins and skills for catching the voice-clip defects the QC harness keeps missing; root causes, verified generator divergences, a layered strategy and a phased recommendation. Research only, no implementation.
sourceOfTruth:
  - docs/reference/qc.md
  - config/qc/protocol.json
  - config/qc/models.json
  - config/qc/runtimes/mlx.txt
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTS.swift
  - Sources/QwenVoiceCore/GenerationSemantics.swift
  - config/roadmap.json
---
# Audio QC tooling research: what would catch the defects the harness misses

**Research date:** October 12, 2026. **Repository baseline:**
`73ee6c3ea4058534607d883161b82807a8b2e041`.

For months the audio QC harness has missed defects the maintainer hears immediately. It has gone
through Fast QC v1–v8, the Gemini/`agy` "ear", a DSP prosody gate, NISQA, QC v1 / Stage 0 with
12 shadow judges, and the QC v2 rebuild. QC v2 has been report-only since October 6, and RF-14, the
3.0 take-quality decision, is still open.

The maintainer asked for an exhaustive search for tools, dependencies, MCP servers, plugins and skills
that would solve the problem for good, and for a report with recommendations. This is that report. It
recommends only: no code, model, download, listening or roadmap-scope change accompanies it.

**Method.** Four strands ran in parallel:

1. The repository history: `docs/reference/qc.md`, the six 2026-10-10 audits, the roadmap and git
   history.
2. Detection models, judges, toolkits and industry practice: arXiv, Hugging Face, GitHub and vendor
   docs.
3. Prevention: the Qwen3-TTS reference code and upstream issues, compared with Vocello's engine.
4. Claude Code tooling and human-evaluation infrastructure: MCP servers, plugins, skills, Artifacts,
   labeling services and Apple frameworks.

The D1, D2, D3 and D6 code citations were re-checked at the baseline. Other items cite their sources.

This report complements the [2026-10-10 research](2026-10-10-automatic-audio-quality-research.md) and
does not repeat it. That report already covers MOS predictors, SpeechJudge, UTMOSv2, ECAPA/WavLM-SV,
MFA and Learn-then-Test.

**Defect codes used below:**

| Code | Defect |
|---|---|
| C0 | Content: skip, hallucination, truncation, run-on, long gap |
| C1 | Whispered or devoiced syllable |
| C2 | False start or repeated fragment |
| C3 | Inserted vowel, over-linked liaison, mispronunciation |
| C4 | Anglophone accent in French |
| C5 | Clone pitch, register or identity drift |
| C6 | Delivery, emotion or pacing that misses the request |

## TL;DR

1. **No single tool, model, MCP server or plugin solves this.**
   - The research up to October 2026 agrees with Vocello's own history. MOS predictors and audio-LLM
     judges match humans when ranking *whole systems*. They are unreliable on *defects within a
     single clip*, judged one dimension at a time (Beyond Naturalness, EmergentTTS-Eval).
   - No published benchmark shows an audio LLM detecting skips, repeats or single-syllable defects.
   - The durable fix is a closed loop: prevent, gate gross errors, learn the subtle detectors from
     labels, and keep the ear as the authority.
2. **The blocker is ground truth, not tooling.**
   - There are 40 label rows in total.
   - The 11 takes confirmed unusable carry no defect class. Only fr-0101--dylan has timed defect spans.
   - No clone has ever been confirmed by ear.
   - Every confirmed take was Speed 4-bit, Expressive, on CC0 scripts.
   - The protocol also merges defects that need different detectors: "mispronunciation **or accent**"
     and "stutter **or missing syllable**".
3. **The ASR checks have a documented blind spot.**
   - An August 2026 audit (preprint, Chinese news) found that Qwen3-ASR-1.7B, one of Vocello's two ASR
     families, wrote the *expected* text over 40 of 97 confirmed TTS errors. A non-autoregressive
     recognizer did so for 2.
   - This matches Vocello's note that ASR "turned stutters and mispronunciations into plausible words".
   - The fix is a recognizer from another family with a weak language-model prior, plus phone checks
     constrained by the intended text.
4. **The cheapest likely gain is prevention.** The shipping engine diverges from Qwen's reference in
   four verified ways, and PA-16 adds a fifth problem:
   - Custom and Design use streaming text conditioning, which upstream measured at +16.7%
     speaking-rate acceleration.
   - The EOS logit is put back after the sampling filters.
   - Sampling runs on logits that are never cast to float32.
   - Custom falls back to *English* when language detection is ambiguous.
   - PA-16: the codec decoder never applies its sliding window, so output drifts after about 6 s.

   Each can be put behind a flag and judged by blind listening.
5. **Most of the detection stack is already installed.**
   - The pinned `mlx-audio` 0.5.7 in the QC environment ships Parakeet, Qwen3-ForcedAligner, Canary,
     Voxtral and Granite.
   - FCPE, SwiftF0, ReDimNet2+, ZIPA and wav2vec2-espeak are installed.
   - Missing are two model downloads, some in-house code, and labels.
6. **Claude cannot hear audio.**
   - The right Claude Code integration is a thin project skill over `scripts/qc.py`. It renders
     spectrogram, F0 and alignment images that Claude reads and explains, without issuing verdicts.
   - Every third-party audio MCP server found is small, unlicensed or cloud-only. They are patterns,
     not dependencies.
7. **Make listening cheap.**
   - A phone-first listening lab: tap to mark a span, pick a class, compare two takes A/B.
   - Optional paid native-French listeners: about **$290 for 400 takes rated twice** on Prolific.
   - Active learning to pick what gets labeled, and Learn-then-Test qualification on a protected panel.
8. **A free in-app second witness.**
   - Apple's on-device `SpeechTranscriber` (iOS and macOS 26+, the deployment target) returns
     per-word confidence and time ranges.
   - The apps still use the older `SFSpeechRecognizer`.

## 1. Why the harness keeps missing defects

### 1.1 What was tried

| When (2026) | Approach | Outcome |
|---|---|---|
| May | Gemini/Antigravity review; Fast QC v1 with `agy` as "the ear" | Retired Jun 14–15: verdicts flipped on byte-identical audio, and it hung |
| Jun–Aug | DSP prosody gate; delivery and clone program; 146-trial blind test (DP-12) | Angry recognized 0/11; happy vs angry at chance |
| Sep 6 | Decision: "human listening is no longer required" | Undone by events |
| Sep 14 | NISQA | Retired: non-commercial weights |
| Sep 25–Oct 1 | QC v1 / Stage 0 (AQ-01..09): 12 shadow judges, injected defects | Abandoned. It "missed defects the maintainer heard at once", and the injected defects did not carry the real defect |
| Oct 1–2 | QC v2 with Gemma 4 and Qwen2.5-Omni judges | Removed in the Oct 2 "lean cut"; the cloud audio LLM was "useless for defect detection" |
| Oct 5–6 | 106-clip batch, then 39 blind confirmations | Flags were right 9 of 29 times (31%). 2 of 5 unflagged decisive controls were unusable. QC v2 made report-only |
| Oct 10 | CTC/DSP candidates (phonation, fragment, boundary) | Overlap with Dylan's whisper IoU 0.474, false start 0.75; acceptable clips also get nominated |

Precision of each detector on the confirmations:

| Detector | Precision |
|---|---|
| content.phoneme | 6/15 |
| content.asr | 5/12 |
| language.wrong | 3/7 |
| boundary.cutoff | 3/7 |
| prosody.rate | 2/4 |
| pause.anomalous | 1/4 |
| signal.artifacts | 0/4 |

Gross failures were caught: a run-on and a 0.039 s-per-unit truncation each drew five flags. Subtle
defects drew zero to two.

### 1.2 Root causes

1. **No defect-class or time-span truth.** QC-06 already says that future automation needs both.
   TL;DR 2 covers the taxonomy problem.
2. **The defects sit inside the human range.**
   - Clip-level statistics (rate, pitch SD, pause totals) cannot see one bad syllable.
   - Those same statistics flag accent and pacing that the maintainer accepts. That one cause explains
     both the misses and the false alarms.
3. **The recognizers normalize defects away.**
   - Recognizers with a strong language-model prior rewrite bad readings into the expected text
     ([2608.10606](https://arxiv.org/abs/2608.10606)).
   - Selecting and evaluating with the same ASR family inflates results
     ([2607.08256](https://arxiv.org/abs/2607.08256)).
4. **Requiring consensus erased single-witness evidence.** If detectors must agree, a defect that only
   one sensor can perceive is suppressed. Example: a phone recognizer hearing an inserted vowel.
5. **Natural French looks defective.**
   - Continental French devoices phrase-final high vowels /i y u/ (Fónagy 1989; Dalola & Bridwell,
     ICPhS 2019).
   - A whisper detector without that exemption flags natural speech. This likely explains part of the
     October 10 false nominations.
6. **The judges were set up to fail.** They were non-deterministic (`agy`) and unqualified, and they
   were asked for clip verdicts on defects that no benchmark shows they can detect.
7. **Synthetic injection measured the injector.** Qualifying against injected defects proved nothing
   about real ones.
8. **The generator causes some defects systematically** (D1, D6, PA-16 below). QC should not be the
   only defense against them.
9. **Free signals go unused.**
   - The engine records talker entropy and EOS probability (AQ-04, `introspectionScalars`), codebook-0
     cycles and repeated runs, but no gate reads them.
   - Fast QC v8 has no lower or upper bound on take length or pace.
   - Long-form joins have no identity check.

## 2. Strategy: five layers, with the ear last and authoritative

```
L1 prevent → L2 gate gross errors → L3 detect subtle (learned, per class) → L4 triage judges → L5 ear
                (deterministic)          (report-only until qualified)        (dev-time only)   (labels feed L2–L4)
```

| Layer | What it does |
|---|---|
| **L1 Prevent** | Fix the generator divergences, qualify clone references, verbalize numbers, offer native-French voices. |
| **L2 Gross gate** | High precision and cheap: duration and pace bounds, a cross-family ASR round trip, aligner coverage, introspection guards. It can fail a take, and the product's answer is a visible Regenerate. |
| **L3 Subtle detectors** | Phone verification against the intended text, per-vowel phonation, worst-window speaker similarity and register, then span classifiers trained on Vocello's own labels. Report-only until a class qualifies. |
| **L4 Triage** | Gemini or Qwen3-Omni, pairwise with anchors, at development time only, never as a gate. |
| **L5 Ear** | A phone-first listening lab produces class and span labels. Detectors qualify with Learn-then-Test on a protected panel, the method chosen on October 10. |

## 3. Findings by area

Verdicts are **Adopt**, **Pilot** (test against labels), **Watch** and **Reject**. Every QC model needs a
commercial-use license (`config/qc/models.json`).

### 3.1 Prevention (generator side)

**D1 — streaming text conditioning.** Action: **Adopt** behind a flag; blind A/B test.
- **Finding:** Streaming generation defaults to `.streamingTrailingText` (`Qwen3TTS.swift:3258`).
  Only the quality-first paths pass `.fullTextNonStreaming` (`:2512`, `:2574`, `:2638`).
- **Evidence:**
  - Qwen's wrappers default to `non_streaming_mode=True`.
  - Streaming text measured +16.7% speaking-rate acceleration
    ([Qwen3-TTS #239](https://github.com/QwenLM/Qwen3-TTS/issues/239)).
  - Upstream fixes: [mlx-audio-swift #270](https://github.com/Blaizzy/mlx-audio-swift/pull/270) and
    [Qwen3-TTS #362](https://github.com/QwenLM/Qwen3-TTS/pull/362).

**D2 — EOS logit kept through filtering.** Action: A/B test that counts truncations and run-ons in each
arm.
- **Finding:** The EOS logit is saved before top-k/top-p/min-p and restored afterwards
  (`Qwen3TTS.swift:5210`, `:5310`).
- **Evidence:** Neither Qwen's reference nor mlx-audio Python does this.
- **Trade-off:** It prevents run-ons, but a low-probability EOS can cut words off (compare
  [#181](https://github.com/QwenLM/Qwen3-TTS/issues/181), last words cut).

**D3 — no float32 cast before sampling.** Action: **Adopt**, with a parity fixture.
- **Finding:** The sampler (near `Qwen3TTS.swift:5150`) works on logits in model precision, likely
  bf16. Only the AQ-04 introspection casts to float32.
- **Evidence:** The Hugging Face reference casts to float32 before sampling.

**D5 — ICL decode history.** Action: parity fixture against the reference.
- **Finding:** Clone (ICL) decode history differs from the reference. This comes from the prevention
  research and was not re-checked.

**D6 — English fallback for Custom.** Action: fall back to Auto, and count how often the French corpus
hits this path.
- **Finding:** When `NLLanguageRecognizer` is ambiguous, `qwenLanguageHint` returns English for
  Custom (`GenerationSemantics.swift:859`), while Design and Clone fall back to Auto. An English tag
  also appends "Native English pronunciation…" (near `:801`).
- **Evidence:** An explicit, correct language outperforms Auto, and a wrong tag pushes the accent. How
  often French scripts hit this path is unmeasured.

**PA-16 — codec sliding windows.** Action: implement to the existing PA-16 gate.
- **Finding:** The decoder never applies its 72-frame window, so output drifts after about 6 s. The
  encoder ignores its 250-frame window for references over 10 s.
- **Evidence:** ENG-01 audit, confirmed 2026-09-22.

**P1 — clone references.** Action: qualify references (10–20 s, full transcript, trimmed tail, same
language as the script), with a UI warning.
- **Evidence:**
  - The reference tail echoes at the start of the take
    ([#341](https://github.com/QwenLM/Qwen3-TTS/issues/341)).
  - A partial `ref_text` collapses ICL
    ([mlx-audio #921](https://github.com/Blaizzy/mlx-audio/issues/921)).
  - About 20% of takes come out in the wrong speaker's voice when the reference is in another language
    ([#80](https://github.com/QwenLM/Qwen3-TTS/issues/80)).

**P2 — accent leakage.** Action: native-French voices made through Voice Design → Clone, and a French
diction line that mirrors the English one.
- **Evidence:** [#134](https://github.com/QwenLM/Qwen3-TTS/issues/134),
  [#359](https://github.com/QwenLM/Qwen3-TTS/issues/359),
  [discussion #230](https://github.com/QwenLM/Qwen3-TTS/discussions/230) (French with a "strong
  english accent"), [#288](https://github.com/QwenLM/Qwen3-TTS/discussions/288).
- No built-in speaker is a native French speaker. Dylan is Beijing Chinese.

**P3 — numbers.** Action: spell numbers out in the target language before synthesis.
- **Evidence:** Numbers are read in the wrong language or as noise
  ([#68](https://github.com/QwenLM/Qwen3-TTS/issues/68),
  [#151](https://github.com/QwenLM/Qwen3-TTS/issues/151),
  [#305](https://github.com/QwenLM/Qwen3-TTS/issues/305)).

**P4 — sampling.** Action: a small sweep, judged by blind listening.
- **Finding:** The sampling values match the official defaults, and the subtalker inherits them. The
  `QWENVOICE_SUBTALKER_TEMP` and `QWENVOICE_TALKER_MINP` knobs exist in
  `config/runtime-debug-knobs.json`.

**P5 — quantization.** Action: run the Speed-vs-Quality defect study that was never run; consider a
mixed-precision Speed tier.
- **Finding:** The Speed tier quantizes the codec and code-predictor heads to 4-bit.
- **Evidence:** 4-bit and 8-bit WER are similar in English ([soniqo](https://soniqo.audio/benchmarks)).
  No study covers accent or artifacts.

**P6 — LACI.** Action: **Pilot**, reimplemented in the MLX loop.
- **Finding:** [LACI](https://arxiv.org/abs/2609.16989) watches Qwen3-TTS's own alignment heads.
  Detecting pacing problems and rolling back cut catastrophic long-form failures from 26% to under 1%.
- **Evidence:** The effect is small under 500 words. The code is not released.

**P7 — Best-of-N.** Action: an explicit, user-visible mode only (a decision).
- **Finding:** Generate N takes and pick one using ASR plus speaker similarity.
- **Evidence:**
  - Llasa's WER dropped from 12.13 to 5.24.
  - ASR self-verification gets catastrophic failures near zero with N = 2–4
    ([2606.18323](https://arxiv.org/abs/2606.18323)).
  - The ASR that selects must come from a different family than the ASR that evaluates.

**P8 — French LoRA or DPO.** Action: **Watch** (long term).
- **Evidence:** Fix the official fine-tuning bugs first
  ([#371](https://github.com/QwenLM/Qwen3-TTS/issues/371),
  [#337](https://github.com/QwenLM/Qwen3-TTS/issues/337)).

### 3.2 Recognition, alignment and content (C0, C2)

**Parakeet-TDT-0.6B-v3: Adopt-candidate.**
- **What it adds:** a third ASR family with a weak language-model prior (a transducer). It covers 25
  European languages and gives word timestamps. French WER is 5.15 on FLEURS and 4.97 on MLS.
- **License:** CC-BY-4.0.
- **On the Mac:** already in the pinned mlx-audio; also available as `parakeet-mlx` (Apache-2.0).
- **Plan:** a new QC runner. It also re-transcribes flagged spans in isolation.

**Whisper large-v3 per-word `probability` (already installed): Adopt as a span feature.**
- **What it adds:** it localizes low-confidence words with no new model.
- **License:** MIT.
- **On the Mac:** mlx-whisper.

**Qwen3-ForcedAligner-0.6B: Adopt-candidate as the timing backbone.**
- **What it adds:** word and character timestamps for audio up to 5 min, in 11 languages including
  French. The vendor reports a 42.9 ms timing error.
- **License:** Apache-2.0.
- **On the Mac:** already in the pinned mlx-audio.
- **Limit:** it force-fits any text, so it cannot detect a mismatch.

**ctc-segmentation: Pilot.**
- **What it adds:** a windowed confidence that the audio matches the text.
- **License:** Apache-2.0.
- **On the Mac:** PyTorch on CPU, with a French CTC model under Apache-2.0
  (`jonatasgrosman/wav2vec2-large-xlsr-53-french`).

**Kyutai `stt-1b-en_fr`: Pilot as an alternate.**
- **What it adds:** a cheap English/French ASR family with semantic VAD.
- **License:** weights CC-BY-4.0, code MIT.
- **On the Mac:** an MLX checkpoint exists; word timestamps through MLX are unverified.

**Canary-1B-v2, Voxtral, Granite Speech 4.1 and Nemotron 3.5: Watch.**
- **License:** CC-BY-4.0, Apache-2.0, Apache-2.0 and OpenMDW, respectively.
- **On the Mac:** their model families ship in the pinned mlx-audio; exact versions are unverified.
- **Risk:** their LLM-style decoders may mask errors the same way Qwen3-ASR does.

**Meta Omnilingual ASR (CTC): Pilot.**
- **What it adds:** CTC emissions under a commercial license.
- **License:** Apache-2.0.
- **On the Mac:** fairseq2 installs on macOS. French support is unconfirmed.

**CrisperWhisper 2.0 "Verbatimize": Pilot only with a commercial license.**
- **What it adds:** given the intended text, it inserts only the disfluencies actually present, which
  makes it a direct C2 detector. The vendor reports an F1 of 87.8.
- **License:** non-commercial. A commercial license is sold separately.
- **On the Mac:** PyTorch or CT2.

**Rejected for non-commercial licenses** (CC-BY-NC or NC-SA):
- WhisperX's default French aligner.
- torchaudio `MMS_FA`.
- The ctc-forced-aligner default model.
- FrWhisper.
- CrisperWhisper v1.
- SQUIM subjective.
- Vox-Profile.

torchaudio's CTC alignment APIs are also removed in 2.9.

### 3.3 Liaison, inserted vowels and mispronunciation (C3); dysfluency (C2)

**The detection survey's first recommendation: an in-house phone verifier constrained by the intended
text.**

- **Approach:**
  - Segmentation-free goodness of pronunciation (GOP-SF, [2507.16838](https://arxiv.org/abs/2507.16838)).
  - WFST-style repeat and insert arcs ([Dysfluent WFST](https://arxiv.org/abs/2505.16351)). The
    repository has no license, so reimplement it rather than vendor it.
- **Inputs:** the installed wav2vec2-xlsr-espeak and ZIPA posteriors.
- **French-specific:** a lattice that marks obligatory, optional and forbidden liaisons and optional
  schwa, so legitimate variants are not flagged.
- **What it catches:** inserted vowels, over-linking, repeats and false starts, measured against the
  *intended* text. That is exactly where ASR built around a language model fails.

**Cloud phoneme scoring for French.** Only two off-the-shelf French phoneme scorers exist:
- **Azure Pronunciation Assessment:** fr-FR and fr-CA at the phoneme level; prosody is en-US only.
- **Speechace:** fr-FR and fr-CA at the word, syllable and phoneme level; zero retention can be agreed
  by contract.

Neither has been tested on TTS. **Pilot**, at development time only, if cloud use is allowed.

**Rejected:**
- SSDM 2.0: no code.
- YOLO-Stutter: unlicensed checkpoints, English only.
- Stutter-Solver: the repository is gone.

### 3.4 Whispered or devoiced syllables (C1)

- **Method (Adopt):**
  1. Align with Qwen3-ForcedAligner or phone CTC.
  2. Measure each vowel's periodicity with the installed FCPE or SwiftF0 (PENN, MIT, if needed),
     plus HNR and CPP.
  3. Flag low-periodicity vowels inside a phrase.
  4. **Exempt phrase-final /i y u/.**
- **PANNs `Cnn14_DecisionLevelMax` (Pilot).** MIT code, CC-BY-4.0 weights. Gives a frame-by-frame
  AudioSet "Whispering" score as a second opinion. Not validated inside voiced speech.
- **ParaSpeechCLAP (Pilot once the weights' license is confirmed).** MIT code; the weights' license is
  unstated. Gives a coarse "whispered" style score.

### 3.5 Clone identity, pitch and register (C5)

- **Two methods (Adopt):**
  - Worst-window speaker similarity, using LACI's wSIM (8 s windows, 4 s stride, keep the minimum)
    with the installed ReDimNet2+.
  - Register: compare the clone's log-F0 median and range with the reference, in semitones.
- **Label clones first.** No failing clone pair has ever been supplied.
- **Diarization as a drift flag (Pilot).** pyannote community-1 (CC-BY-4.0, gated) or Sortformer v2.1
  (NVIDIA license, trained on English).
- Identity scores do not capture accent ([2604.01562](https://arxiv.org/abs/2604.01562)).

### 3.6 Accent (C4)

- **No commercially licensed classifier exists for native French vs English-accented French.**
  - CommonAccent has no French model.
  - Vox-Profile is English-only and non-commercial.
  - The release status of the LREC 2026 French regional classifier is unclear.
- **Probe bundle (Pilot):**
  - The French posterior from the VoxLingua107 ECAPA language-ID model (Apache-2.0). Its model card
    warns that accented speech degrades it, which is exactly the signal wanted here.
  - Formant contrasts /y/–/u/ and /o/–/ɔ/, VOT, /ʁ/ and rhythm variability, following an SFU thesis on
    English-speaking learners of French.
  - Native-centroid probes in the style of PSP over XLS-R layer 9
    ([2604.25476](https://arxiv.org/abs/2604.25476), MIT).
- **Validate against labels before setting any threshold.** Formants and posteriorgrams failed to
  separate accents in [2508.07426](https://arxiv.org/abs/2508.07426).
- **Prevention (P2, D6) beats detection for accent.**

### 3.7 Delivery and emotion (C6), and audio-LLM judges

**Gemini 3.x (cloud).** Pilot at development time only, for C6 and C4: pairwise comparisons with anchor
clips. Never a gate for C0–C3.
- Audio costs 32 tokens per second, about $0.0014–0.0038 per minute. Answers can cite MM:SS
  timestamps.
- On English voice-style following it agreed with humans at r = 0.640, against 0.596 between humans
  ([2506.05984](https://arxiv.org/abs/2506.05984)).
- Its timestamps are weak: about 31 mIoU on TAG-Bench.

**Qwen3-Omni-30B-A3B.** Pilot on a Mac with 32 GB or more; otherwise Watch.
- Apache-2.0, accepts French audio, runs in mlx-vlm.
- The 4-bit model is 21.8 GB, hence the 32 GB minimum.

**Gemma 4 / 3n, Phi-4-mm and Nemotron 3 Nano Omni.** Watch. They run in mlx-vlm, but their ability to
judge tone and delivery is undocumented.

**Step-Audio 2, Kimi-Audio, MiDashengLM and MiMo-Audio.** Reject. They focus on English and Chinese,
and most have no MLX port.

**Cautions:**
- Counterfactual audits show that success on contrastive tests overstates a judge's reliability
  ([2608.06718](https://arxiv.org/abs/2608.06718)).
- [Beyond Naturalness](https://arxiv.org/abs/2608.09930) found MOS predictors and audio LLMs unreliable
  one dimension at a time. Human agreement there was alpha 0.71–0.77.
- [Vox-Evaluator](https://arxiv.org/abs/2510.20210) (localize error spans, then mask and regenerate) has
  the right shape for Vocello, but its code is not released. **Watch.**

### 3.8 Toolkits

VERSA (Apache-2.0, 90+ metrics), Amphion, Audiobox Aesthetics, SQUIM objective, SHEET and CV3-Eval (which
includes a French cloning subset) are worth watching for convenience only. None of them targets C1–C6.
`scripts/qc` is already the right harness.

### 3.9 Industry practice

- ElevenLabs advertises automatic mispronunciation and artifact checks with auto-regeneration. This
  could not be verified on their live pages.
- Hume TADA counts a CER above 0.15 as a hallucination.
- Amazon research has used pronunciation-error detectors on synthetic speech
  ([2209.06265](https://arxiv.org/abs/2209.06265)).
- Deepgram, Cartesia and Artificial Analysis use human panels.

No vendor publishes automated, defect-level TTS QC at scale. The working pattern is a round-trip gate for
gross errors, visible regeneration, and humans for subtle defects.

### 3.10 Claude Code: MCP servers, plugins and skills

**Constraint: Claude cannot take audio input.** It accepts only text, images and documents. Every
integration therefore takes one of two routes:
- turn audio into evidence Claude can read: features, transcripts, or **images** of the spectrogram, F0
  and alignment (the Read tool displays images);
- route the audio to a model that can hear it.

| Item | What it is | License | Verdict |
|---|---|---|---|
| voice-analysis-mcp 0.1.0 | Local faster-whisper plus librosa spectrogram, prosody and quality tools | Unknown | Pattern only. Vocello's runners are stronger |
| audio-analysis-mcp (zachswift615) | Small local analysis server | Unknown | Pattern only |
| [Claudio](https://pypi.org/project/claudio/) 0.2.3 | Gemini-backed `listen_to_audio` / `ask_about_audio` | None | Reject as a dependency; a good pattern |
| [gemini-audio-upload](https://glama.ai/mcp/servers/unscene/gemini-audio-upload) | Uploads audio to Gemini | — | Pattern for L4, if cloud use is allowed |
| mcp_video_recognition, [Whissle](https://mcpservers.org/servers/WhissleAI/whissle-mcp), Deepgram MCP | Cloud ASR and video wrappers | — | Reject: cloud-only, nothing QC-specific |
| [parakeet-mlx skill](https://mcp.directory/skills/parakeet-mlx) (openclaw/skills) | Local Parakeet v3 transcription | — | Pattern. Integrate Parakeet as a QC runner instead |
| [Hugging Face MCP](https://huggingface.co/docs/hub/en/hf-mcp-server) | Hub search, Spaces as tools, Jobs | — | For model discovery only; enable when needed. Spaces and Jobs upload audio, so they need consent |
| Praat MCP | — | — | None exists. HNR and CPP are easy to write in-house. Parselmouth is GPL; keep it in the venv only, like espeak-ng |
| Plugins | No marketplace plugin targets TTS QC | — | Already useful: axiom (Apple Speech, Create ML), context7, and Claude in Chrome / chrome-devtools for testing the listening page (never for judging audio) |

**Recommendation: no new MCP server.**
- Add a **`/vocello-qc-review` skill**, built with skill-creator in the existing `.claude/skills/vocello-*`
  pattern. For a take or run, it:
  1. runs `qc.py` in report-only mode;
  2. renders evidence PNGs: waveform and spectrogram with word and phone alignment, F0 against the
     reference, per-vowel periodicity, entropy and codebook-cycle traces, and the flagged spans;
  3. has Claude read and explain the images;
  4. queues the take for listening.
- The skill never issues a verdict: Claude's reading of spectrograms is unqualified.
- An MCP server earns its place only for opt-in Gemini triage, or for exposing labels to a claude.ai
  page.

### 3.11 Listening, labeling and crowdsourcing: fixing the label shortage

**Listening lab.** Extend the existing local label page, `scripts/qc/label.py`. It already stores
severity and start/end times per class and has keyboard shortcuts. Make it phone-first:
- a large play button;
- **tap to mark a span while listening**;
- a class picker;
- a **pairwise A/B mode** for the prevention experiments.

**Protocol v2** (`config/qc/protocol.json`) needs classes that map one-to-one onto detector families:
- split "mispronunciation or accent" into liaison/insertion (C3) and accent (C4);
- split "stutter or missing syllable" into false start/repeat (C2) and skip (C0);
- add pacing, delivery mismatch and clone register (C6, C5).

**Hosting** (a decision). Two options:
- **(a) Local, reached over Tailscale (recommended).** Clips and labels never leave the maintainer's
  machines, consistent with keeping labels under `build/private/qc`. This needs the Tailscale app.
- **(b) A private claude.ai Artifact.**
  - Labels live in its `db` under per-user paths. Clips are published files (FLAC). Claude reads the
    labels through ArtifactData.
  - It works from anywhere and can invite other raters.
  - It is an external write. Use it only for built-in and Design voices on CC0 scripts, never for
    clone references of real people.

**Paid listeners** (a decision):
- Prolific recommends £9 / $12 per hour and adds a 42.8% fee for non-academic studies.
- Estimate: 400 takes × 2 native-French raters × about 75 s ≈ 17 hours ≈ **$290**. Add about 20% for
  gold clips.
- Experts and crowd workers agree poorly on pronunciation labels (ETS study). Use the crowd for "any
  defect, and where?" and for A/B preference. Keep the fine-grained class taxonomy for the maintainer
  or one trained native rater.
- Podonos (at most $0.22 per rating) suits only MOS or preference calibration.

**Fallback tools:**
- webMUSHRA or the Web Audio Evaluation Toolbox for formal MUSHRA or ABX tests.
- Label Studio (Apache-2.0), which labels regions on a spectrogram.

**Active learning.** Queue first:
- takes where detectors disagree or sit near a threshold;
- cells that have never been labeled: clones, Quality 8-bit, the Balanced and Consistent presets,
  English.

Keep about 25% as a **protected panel** that is never used for tuning.

### 3.12 In-app safety net (Apple)

- **`SpeechAnalyzer` / `SpeechTranscriber`** (iOS and macOS 26+) runs on-device.
  `ResultAttributeOption.audioTimeRange` and `.transcriptionConfidence` give per-word timing and
  confidence.
  - Today the apps use `SFSpeechRecognizer` (`VoiceClipTranscriber.swift`).
  - English accuracy is below Whisper turbo. French is unbenchmarked: check `supportedLocales` at
    runtime.
  - Assets come through AssetInventory, with a cap of about two analyzers.
  - Recommended use: a free second witness in Fast QC, flagging low-confidence words, missing words and
    word-duration anomalies.
- **Create ML `MLSoundClassifier`** could become an in-app C1/C2 detector trained on labeled windows,
  once the labels exist.

## 4. Recommended stack

| Layer | Components | New dependency or download |
|---|---|---|
| L1 | D1/D2/D3/D6 fixes, PA-16, clone-reference qualification, number verbalization, French voices and diction line | None |
| L2 | Too-short/too-fast bound (folded into QC-08's Fast QC v9); introspection guards (entropy, codebook-0 cycles, EOS margin); Parakeet v3 round trip plus span re-transcription; aligner coverage; Whisper per-word probability; in-app SpeechTranscriber | Weights only: `parakeet-tdt-0.6b-v3` and `Qwen3-ForcedAligner-0.6B`, 0.6B parameters each (about 1.2 GB at bf16). mlx-audio 0.5.7 is already pinned |
| L3 | GOP-SF plus WFST phone verifier with a French liaison lattice; phonation with the phrase-final exemption; wSIM and register; ctc-segmentation; LACI pacing; then trained span classifiers | ctc-segmentation (Apache-2.0) and one French CTC model (Apache-2.0) |
| L4 | Gemini pairwise triage | API key and consent (opt-in) |
| L5 | Listening lab, protocol v2, `/vocello-qc-review`, optional paid raters, Learn-then-Test | Tailscale or an Artifact (decision) |

## 5. Recommended phases

Each phase ends with a measurement, either on the labeled panel or by blind listening. **None has
started.**

**Phase 0 — labels and plumbing.** Local; no downloads.
- Protocol v2 and the phone-first label page (tap to mark, A/B).
- The maintainer replays the 11 unusable confirmations (about 15 minutes) to give each a class and a
  span.
- Surface the recorded introspection in the QC report, report-only.
- Fold the too-short/too-fast bound into QC-08.
- Measure: how many labels have a class.

**Phase 1 — prevention A/B.**
- Register D1, D2, D3 and D6 as knobs in `config/runtime-debug-knobs.json`, with defaults unchanged.
- Generate fixed-seed pairs on French and English CC0 scripts, with built-in and Design voices, at
  Speed and at Quality.
- The maintainer runs a blind A/B in the lab. A default flips only after it wins the listening test,
  per RF-14.
- Then PA-16 to its gate, clone-reference qualification and number verbalization.
- Measure: preference rate and defect counts per class and per arm.

**Phase 2 — grow the panel.**
- Label 300–500 takes, stratified across mode, tier, preset, language and clones.
- Set up the active-learning queue and the protected panel; optionally add paid raters.
- Measure: inter-rater agreement (Krippendorff's alpha) and prevalence per class.

**Phase 3 — detectors.**
- Parakeet and aligner runners (once the download is authorized), the phone verifier, phonation,
  wSIM/register, ctc-segmentation and LACI pacing.
- Report precision and recall per class on the development split.
- Set thresholds with Learn-then-Test on the protected panel.
- A class joins the strict gate only once it meets a pre-registered bound, for example recall ≥ 0.8 at
  precision ≥ 0.5. Set the bound together with RF-14.

**Phase 4 — tooling.**
- The `/vocello-qc-review` skill.
- Optional Gemini triage, gated on cloud consent.
- Recalibrate as labels accumulate.

**Phase 5 — product.**
- A visible Regenerate when a take fails L2.
- An optional explicit Best-of-N.
- Long-form LACI monitoring.
- SpeechTranscriber as Fast QC's second witness.

RF-14 can be decided after Phase 1, with a measured defect rate. It does not need to wait for Phases
3–5.

## 6. Decisions required before each phase

| # | Decision | Recommendation |
|---|---|---|
| 1 | Cloud use at development time (Gemini triage; Azure or Speechace for French scoring) | Yes, opt-in, with built-in and Design voices on CC0 scripts only |
| 2 | Where to host the listening lab | Local plus Tailscale, or a private Artifact if other raters will join |
| 3 | Paid native-French raters (about $290 for 400 takes rated twice) | Yes, after Phase 0 proves the page |
| 4 | Best-of-N | Keep "no hidden best-of-N"; allow an explicit, visible mode later |
| 5 | Downloads: Parakeet v3 and Qwen3-ForcedAligner (about 1.2 GB each), registered in `config/qc/models.json` | Yes, at Phase 3 |

## 7. Do not repeat

- Another MOS predictor or general audio LLM as a gate.
- Requiring detectors to agree before flagging. Keep single-witness evidence and qualify each class.
- Qualifying on injected defects.
- WER from an ASR built around a language model as a pronunciation check.
- Non-commercial models: NISQA, CrisperWhisper, MMS_FA, WhisperX's French default.
- Letting Claude judge audio from transcripts or images.
- Tuning on the protected panel.

## Sources

**Failure evidence**
- [2608.10606](https://arxiv.org/abs/2608.10606): ASR masking TTS errors.
- [2607.08256](https://arxiv.org/abs/2607.08256): cross-family verification.
- EmergentTTS-Eval (NeurIPS 2025).
- [Beyond Naturalness](https://arxiv.org/abs/2608.09930).
- [2608.06718](https://arxiv.org/abs/2608.06718): judge counterfactuals.
- [Dalola & Bridwell 2019](https://assta.org/proceedings/ICPhS2019Microsite/pdf/full-paper_456.pdf): French devoicing.

**Generator**
- [LACI](https://arxiv.org/abs/2609.16989).
- GOAT (EMNLP 2025).
- [2606.18323](https://arxiv.org/abs/2606.18323).
- The Qwen3-TTS issues and pull requests linked in section 3.1.
- [mlx-audio-swift #270](https://github.com/Blaizzy/mlx-audio-swift/pull/270).
- [soniqo benchmarks](https://soniqo.audio/benchmarks).

**Recognition and alignment**
- [Parakeet v3](https://huggingface.co/nvidia/parakeet-tdt-0.6b-v3)
- [parakeet-mlx](https://github.com/senstella/parakeet-mlx)
- [mlx-audio](https://github.com/Blaizzy/mlx-audio)
- [Qwen3-ForcedAligner](https://huggingface.co/Qwen/Qwen3-ForcedAligner-0.6B)
- [ctc-segmentation](https://github.com/lumaku/ctc-segmentation)
- [Omnilingual ASR](https://github.com/facebookresearch/omnilingual-asr)
- [Kyutai stt-1b-en_fr](https://huggingface.co/kyutai/stt-1b-en_fr)
- [CrisperWhisper 2.0](https://huggingface.co/nyralabs/CrisperWhisper2.0_large)
- [Apple SpeechTranscriber result options](https://developer.apple.com/documentation/speech/speechtranscriber/resultattributeoption)

**Pronunciation and dysfluency**
- [GOP-SF](https://arxiv.org/abs/2507.16838)
- [Dysfluent WFST](https://arxiv.org/abs/2505.16351)
- [Amazon, 2209.06265](https://arxiv.org/abs/2209.06265)

**Voice and accent**
- [PENN](https://github.com/interactiveaudiolab/penn)
- [PANNs weights](https://zenodo.org/records/3987831)
- [ParaSpeechCLAP](https://github.com/ajd12342/paraspeechclap)
- [2604.01562](https://arxiv.org/abs/2604.01562)
- [PSP](https://arxiv.org/abs/2604.25476)
- [2508.07426](https://arxiv.org/abs/2508.07426)
- [SFU thesis](https://summit.sfu.ca/item/6952)

**Judges**
- [Chiang et al.](https://arxiv.org/abs/2506.05984)
- [Vox-Evaluator](https://arxiv.org/abs/2510.20210)

**Claude ecosystem**
- [Claudio](https://pypi.org/project/claudio/)
- [gemini-audio-upload](https://glama.ai/mcp/servers/unscene/gemini-audio-upload)
- [Whissle MCP](https://mcpservers.org/servers/WhissleAI/whissle-mcp)
- [parakeet-mlx skill](https://mcp.directory/skills/parakeet-mlx)
- [Hugging Face MCP](https://huggingface.co/docs/hub/en/hf-mcp-server)

**Labeling**
- Prolific [study cost](https://researcher-help.prolific.com/en/articles/445129-study-cost) and
  [reward guidance](https://researcher-help.prolific.com/en/articles/445266-deciding-on-a-reward)
- [Label Studio spectrogram labeling](https://labelstud.io/learning-center/how-to-build-a-labeling-tool-for-sound-event-detection-with-spectrogram)

**Not verified**
- ElevenLabs' auto-regeneration claims.
- Whether NeMo gives word confidence for TDT models.
- Kyutai's French WER, and its timestamps through MLX.
- Apple SpeechTranscriber's French accuracy.
- Omnilingual ASR's French support.
- The licenses of the ParaSpeechCLAP and YOLO-Stutter weights.
- A release of the LACI code.
- Any accuracy figure for an audio LLM detecting single-syllable defects.
