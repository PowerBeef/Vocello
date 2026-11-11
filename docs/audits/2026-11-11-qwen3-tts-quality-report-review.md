---
status: active
owner: backend-mlx
reviewed: 2026-11-11
summary: Counter-verification of an outside model-written report on the Qwen3-TTS integration - which of its claims hold in the code, the records and upstream, three new measurements (encoder rotary convention, 4-bit against 8-bit, mixed precision), and what follows for the parked engine-remediation items.
sourceOfTruth:
  - Packages/VocelloQwen3Core/Sources/MLXAudioCodecs/Mimi/Transformer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSSpeechTokenizer.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSVoiceClonePrompt.swift
  - Sources/QwenVoiceCore/NativeCloneSupport.swift
  - docs/audits/2026-10-16-engine-runtime-audit.md
  - docs/audits/2026-10-17-qwen3-tts-model-research.md
  - docs/reference/qwen3-tts-guide.md
  - config/roadmap.json
---
# Review of an outside report on the Qwen3-TTS integration

The maintainer asked a newly released Qwen model to audit Vocello's Qwen3-TTS 1.7B integration from
our reviewed documents, then asked for a detailed counter-verification of what it wrote. This is that
counter-verification. It is a report only: no product code, model artifact, roadmap item or
dependency changed.

## 1. Verdict

- **The report is a careful cross-reading of our own documents, not model insight.** Nothing in it
  rests on knowledge of the weights or of Qwen's training. Its value is the way it joins findings
  that our documents keep apart.
- **Its facts about our code hold.** All 14 code claims checked are true or partly true at
  `f4edb60a`. Its figures from our measurement records are quoted correctly, with a few misdated or
  stretched (section 6).
- **Its ranking does not hold.** Its first finding, the encoder's rotary convention (A-02), is a
  real divergence, and measured here for the first time it changes nothing detectable in the output
  (section 4.1). Calling it critical was an inference; our own guide says the effect was unmeasured.
- **Several upstream citations it leans on are weaker than stated, and the weakness is ours.** The
  report repeated readings of upstream issues that our October audits wrote down. Three of them do
  not say what our documents say they say (section 5).
- **One finding gains ground.** Its seventh finding says quantization precision may cost clone
  fidelity and proposes an 8-bit code predictor inside the 4-bit model. Measured here, the 8-bit
  model matches the reference speaker better than the 4-bit one by 0.025 in speaker similarity, and
  an 8-bit code predictor alone recovers 0.010 of that for 56 MB (sections 4.2 and 4.3). That is the
  only recommendation in the report with a measured benefit behind it, and it is a small one whose
  speed cost is not measured.
- **Nothing in it is a release blocker** under the focus lock's definition. Every sample-changing
  recommendation belongs to the parked engine-remediation items, where most are already recorded.

## 2. How this was checked

- **Code.** Each claim about the clone path, the codec and the artifacts was checked against the
  current source, not against the documents that describe it.
- **Records.** Each quoted number was traced to its measurement record, with its date, build and
  what it was measured on.
- **Upstream.** Each cited issue, pull request, commit, source line and paper was fetched and read:
  QwenLM/Qwen3-TTS at `022e286b`, Hugging Face transformers' Mimi, Kyutai's moshi, mlx-audio,
  mlx-audio-swift, MLX, vLLM-Omni, and the three papers.
- **Measurements.** Three experiments ran on the Mac with tools already installed: the reference
  PyTorch encoder (transformers 5.2.0), the Python port of the model (mlx-audio 0.5.7, which carries
  the rotary fix), and the QC harness's speaker embedder (ReDimNet2+) and Whisper large-v3. Nothing
  was downloaded and no Swift code was changed. Nobody listened.

## 3. The ten findings

| # | The report's finding | What holds | What does not | Standing |
|---|---|---|---|---|
| 1 | The encoder's rotary convention is wrong (A-02), "critical" for clones | The divergence is real: Hugging Face permutes the q and k weights for split-half rotary, Qwen runs that code, and our encoder applies the adjacent-pair form. Our stored codes match the reference's 31% of the time | No effect on output was detectable in 96 paired clones: speaker similarity +0.004 (95% interval -0.003 to +0.011), identical word error rate, same lengths | Fix for parity when ER-04 opens; expect no audible change |
| 2 | Streamed clones decode from a cold decoder (A-04, D5) | True for every Studio clone take; the non-streamed path already decodes the reference first | The upstream evidence for audible harm (issue 219) was retracted by its author. The link to the half-precision codec's onset burst is a guess | Worth one screen with the half-precision codec re-test, because that is where the payoff is |
| 3 | Partial transcripts are accepted (G-01); "audio only" still uses the stored transcript (G-02) | Both true in the code. G-02 is a correctness bug: the user's explicit choice is overridden | "Proven upstream" is one user, one clip, three takes | Best first fixes after the submission |
| 4 | Half a second of zeros after a hard-stopped reference is "the documented echo trigger" (A-12, G-07) | The padding, the abrupt endings and the wrong comment are all in the code | Issue 341 says nothing about abrupt endings. It reports the output starting with the reference transcript's last words | Fix the comment; screen the padding only with a versioned audio preparation (G-13) |
| 5 | The long-form decision against full-text conditioning (D1) is stale | The chronology is right: the screen ran on 2026-10-16, before the subtalker fix of 2026-10-19, and was never repeated | The default variation never failed in either layout; the full-text arm was under its own minimum size; D1 has measured costs on single takes | A cheap re-screen, already open under ER-03; needs transcription scoring to show anything |
| 6 | Undetected language falls back to English for Built-in Voice (D6) | True, and never screened | The loss of dialect ids is narrow: only when detection fails on text that is not mostly Han | A cheap screen under ER-05; the switch exists |
| 7 | The 4-bit code predictor may cost fidelity; build a 4-bit model with an 8-bit code predictor | Precision does cost clone similarity: all 8-bit beats all 4-bit by 0.025, and the 8-bit code predictor alone gives +0.010 for 56 MB | Issue 43 is about half-precision crashes, not 4-bit quality. The gain is under the report's own +0.02 rule, and the code predictor runs 15 times per frame, so its speed cost matters | The one proposal with a measured benefit; measure its speed before anything else |
| 8 | Enrollment quality gates never fire (G-08 to G-11) | True on every point | Nothing | Low-cost fixes after the submission |
| 9 | Expose pace, energy, pitch and volume instead of emotion labels | The evidence it cites is quoted correctly | That these dimensions separate is assumed. Our own result is that presets move prosody along one axis | A separability bench first; no interface work before it |
| 10 | Listen to a fixed corpus each release | The QC v2 outcome is quoted correctly | It contradicts the standing decision that nobody listens, and QC v2 already tried calibrating detectors on 39 blind judgments without success | Not actionable unless the decision changes |

## 4. New measurements

All three use the same design: 4 references (the fixture voice's recording and three generated
takes with known scripts), 4 English scripts of 9 to 29 words, 3 seeds, the sampling defaults
(0.9, top-k 50, top-p 1.0, repetition penalty 1.05), the Base model through the Python port. Speaker
similarity is ReDimNet2+ against the reference recording; words are scored with Whisper large-v3.

### 4.1 The encoder's rotary convention (A-02)

- **Our encoder does apply the wrong convention.** The fixture voice's stored prompt, made by the
  Swift encoder, matches a PyTorch emulation of the adjacent-pair rotary on 96.8% of codes and on
  100% of the first codebook. It matches the reference encoder on 31.2%.
- **The two conventions disagree on most codes.** Over 8 clips the codes agree on a median 34%
  (30 to 52%), and the first codebook on 31% (19 to 51%). The Python port gives the same figures as
  PyTorch.
- **Both sets of codes describe the audio equally well.** Decoded with the Qwen decoder, the
  reference codes sit 0.411 from the input in log-mel distance and ours 0.429. Speaker similarity to
  the input is 0.983 against 0.981. Our stored fixture codes decode at 0.979.
- **Clones do not change measurably.** 48 pairs on the 4-bit model: similarity 0.832 with the
  reference convention against 0.826 with ours. 48 pairs on the 8-bit model: 0.856 against 0.854.
  Pooled, +0.004 with a 95% interval of -0.003 to +0.011, and the reference convention was higher in
  exactly 48 of 96 pairs. Word error rate was 0.0125 in every arm, no take ended in more than 0.6 s
  of silence, and lengths differed by 0.06 s.
- **By the outside report's own rule** (adopt at +0.02 similarity) the fix would not be adopted.

What this does not cover: other languages, cross-language references, noisy or phone recordings,
targets longer than 10 s, and the Swift runtime itself. A wrong convention could matter more where
the reference is already far from clean speech. The code-parity experiment in ER-04's gate still
has to run in Swift.

### 4.2 4-bit against 8-bit

The same takes, paired by reference, script, seed and convention: the 8-bit Base model's clones
match the reference speaker better, 0.855 against 0.829. The difference is +0.026 (95% interval
+0.019 to +0.033, 96 pairs). Word error rate is the same. This is the first measurement here that
quantization costs clone identity, and it is seven times the size of the rotary effect's point
estimate. On the 48 pairs that use the reference convention it is +0.025 (+0.016 to +0.034), and the
8-bit model is higher in 41 of 48.

### 4.3 Where the loss sits: mixed precision

The two models were loaded together and their code predictors swapped in memory, so each half's
precision can be judged alone. Same references, scripts and seeds; 48 takes per row; the difference
is against the all-4-bit row.

| Talker | Code predictor | Speaker similarity | Difference (95% interval) | Size of the two parts |
|---|---|---|---|---|
| 4-bit | 4-bit | 0.832 | | 1,144 + 189 MB |
| 4-bit | 8-bit | 0.842 | +0.010 (+0.002 to +0.019) | 1,144 + 245 MB |
| 8-bit | 4-bit | 0.839 | +0.007 (-0.001 to +0.015) | 1,856 + 189 MB |
| 8-bit | 8-bit | 0.856 | +0.025 (+0.016 to +0.034) | 1,856 + 245 MB |

- **Both halves contribute, about equally.** The two mixed rows do not differ from each other
  (-0.004, interval -0.012 to +0.005), and each is below the all-8-bit row.
- **The code predictor is the cheap half.** Raising it to 8 bits adds 56 MB and gives +0.010. Raising
  the talker adds 712 MB and gives +0.007 on its own.
- **Word error rate, lengths and endings are the same in every row** (0.0125, no take above 0.2, no
  trailing silence over 0.5 s).
- **Not measured:** speed. The code predictor runs 15 passes per frame, and the 8-bit model is 46 to
  57% slower than the 4-bit one on the M6 as a whole. How much of that is the code predictor decides
  whether this is affordable on an iPhone 15 Pro, which is already slower than real time.
- The local model files confirm the report's count: 51 quantized code-predictor modules in both
  tiers.

## 5. Citations that do not hold

These readings are in our October audits and guides; the outside report repeated them.

- **QwenLM issue 341, "the documented echo trigger".** It reports clones that begin with the last
  words of the reference transcript, on the official PyTorch code at full precision. It verifies
  that the trim arithmetic is exact and supposes the model runs past the reference boundary. It
  never mentions a reference that ends abruptly, and no maintainer answered. One commenter fixed one
  voice of six by cutting its last phrase. G-07's tie to this issue is our own inference.
- **QwenLM issue 219, cold-decoder distortion.** It concerns a non-streamed Built-in Voice take, and
  its author withdrew the cause in the thread: the WAV was clean and the fault was an MP3 encoder's
  delay.
- **QwenLM issue 80, "about 20% wrong speaker across languages".** The 20% comes from one user in an
  all-English setup on vLLM-Omni. The cross-language remark is a separate, unquantified line.
- **mlx-audio issue 921, partial transcripts "proven" to loop.** One user, one clip, one text: three
  degenerate takes of three on official PyTorch with a transcript covering about 6 s of a 10 s clip,
  and five normal takes of five with the full transcript. A credible mechanism, not a proof.
- **mlx-audio commit `6549fc2` as the rotary fix.** It is the commit that added the encoder, with the
  correct setting from the start. Nothing in it measures the rotary setting's effect.
- **MLX pull request 4710 and the reload leak.** It closed unmerged. A maintainer pointed to pull
  request 4453, merged 2026-09-11. The pinned MLX core is 0.32.2, released 2026-08-25, so that fix is
  not in our pin. It arrives with a pin move, which needs authorization, not by porting
  mlx-audio-swift's pull request 286.
- **vLLM-Omni pull request 5041, trimming the reference's leading silence.** It closed unmerged after
  its author's own rebenchmark found no gain.
- **The technical report.** It does not say its instruction scores were measured without the
  language "thinking" pattern. Its short and long word error rates come from different model variants
  and test sets, so they do not show that long takes are 2 to 3 times worse.
- **QwenLM issue 43, precision of the code predictor.** A collaborator does say it is "extremely
  sensitive to precision". The context is half-precision assertion failures on CUDA, not a quality
  comparison of quantized weights.

Citations that do hold: the reference decodes the reference codes before the generated ones and
cuts them off (source lines 612 to 631); it pads nothing before encoding; the decoder's config sets a
72-frame window on all 8 layers; the Base model takes no instruction (issue 25); design-then-clone is
the documented route to a reusable designed voice; Hugging Face's conversion permutes the q and k
weights, so split-half rotary is correct for the shipped encoder weights; mlx-audio-swift's main
branch still has the wrong convention.

## 6. Statements that are out of date or stretched

- **"TF32 measurement pending" (its 9.3).** Done on 2026-11-11: marked takes read 0.998 to 1.0 on
  the Mac and 0.999 to 1.0 on the iPhone 17 Pro, payload exact. That phone's chip is one TF32
  applies to.
- **"30 s idle unload on the iPhone".** It is 120 s since `eb0775f0`, so reloads are rarer and the
  leak in section 5 matters less than the report assumes.
- **"Fast QC rejects 10 s of terminal silence".** Fast QC fails at 1.2 s, or 2.0 s with a declared
  pause or 45 s of content. Ten seconds is the long-form screen's definition of a runaway ending.
- **"The 300-unit budget was chosen when Consistent was broken".** It was set on 2026-07-23 from a
  97 s segment with a 2 s gap. The record names no variation.
- **"Emotion reference banks" as an app feature.** The app groups saved voices by name. Nothing is
  bundled, and the builder was retired on 2026-10-01.
- **"angry.strong recall fell from 0.31 to 0.00".** True as recorded, for a cell that no longer
  ships.
- **Register figures of 2.4, 3.1 and 1.1 semitones (QC-06).** They exist only in a roadmap gate's
  text; no measurement record was found.
- **"Never matches a Studio take" (G-12).** A CLI prompt differs from a Studio prompt only when the
  stored transcript holds newlines, tabs or repeated spaces. Our prompting guide carries the same
  overstatement.

## 7. The report's new proposals

- **Decoder priming plus a half-precision codec re-test.** Sound as one screen. The half-precision
  burst did need the streaming decoder's first chunk, so priming could remove its cause. The payoff
  is 234 MB on the iPhone. The recorded reopen condition for the half-precision codec is a decoder
  precision fix or a per-platform measurement; priming is neither, so this needs the maintainer's
  word to reopen.
- **An in-loop silence watchdog.** Sound in principle: a take with many seconds of trailing silence
  fails Fast QC anyway, so stopping it early cannot change an accepted take. It saves up to about a
  minute of compute per runaway take. ICA-15 already holds the constraint that a take is never
  trimmed or silently regenerated.
- **Continuing long-form from the first segment's audio ("self-ICL").** Not as described. Cloning
  from codes and a transcript is a Base-model capability. Built-in Voice and Voice Design segments
  would have to switch to the Base model after the first one, which drops delivery instructions and
  loads a second model, on a phone that holds one. The existing design-then-clone route is the same
  idea without the switch mid-project.
- **Dimension controls (pace, energy, pitch, volume).** A hypothesis. Our own result (DP-10) is that
  the presets move prosody along one arousal axis, so four controls may collapse into one. A
  separability bench on the delivery harness would settle it before any interface exists.
- **Per-speaker preset variants.** DP-26 measured speaker as a factor and rejected the candidate
  copy. A matrix scored by an acoustic classifier would repeat a known trap: angry and fearful
  separate acoustically and are not recognized by ear.
- **Number normalization and splitting at language changes.** Reasonable candidates with no
  measurement here, and upstream's evidence is single unanswered reports. Each is a new planner
  feature.
- **A mixed-precision Speed model.** Supported by section 4.3 as far as a pre-screen can: +0.010
  similarity for 56 MB. It would still be a new artifact with new receipts, a new catalog entry and
  a 2 GB download for every iPhone user, so its speed cost and a Swift measurement come first.
- **A fixed listening corpus.** Declined by the standing decision of 2026-10-13. The machine
  equivalent already exists in pieces: fixed-seed sample digests, the paired speaker-similarity and
  transcription screen used in section 4, and the watermark reading.

## 8. Recommendations

Nothing here should enter the release plan. In order, for when the engine-remediation items resume:

1. **Fix what overrides the user or lets bad input through, with no sample change for good input:**
   "audio only" honoured (G-02), the enrollment checks run on the original audio and shown to the
   user (G-08 to G-11), a coverage check on recognized transcripts (G-01), and the padding comment
   (A-12).
2. **Follow the precision result.** Measure the speed of an 8-bit code predictor under the 4-bit
   talker first, on the Mac and in the host-bound stand-in. If it is affordable, repeat section 4.3
   in Swift with more voices and languages. Only then weigh a new artifact against its cost: new
   receipts, a new catalog entry and a 2 GB download for every iPhone user.
3. **Run the two screens whose switches already exist:** full-text conditioning for long-form
   segments (D1) and the Auto fallback (D6). For D1, add transcription scoring, a Japanese stratum
   and a Voice Design stratum, because its recorded costs are there, and size both arms above the
   rule's minimum.
4. **Screen decoder priming together with the half-precision codec,** if the maintainer reopens that
   decision.
5. **Fix the rotary convention with the version bump (A-02, G-03) for parity,** expecting no audible
   change. The reason to do it is that every later comparison with the reference starts from the
   same codes, and that mlx-audio-swift may fix it upstream. Its cost is one rebuild of every saved
   voice.
6. **Leave the decoder window (A-03) where PA-16 has it.**

Use the method of section 4 as the pre-screen for these: the Python port with the QC models answers
"does this parity fix change anything" in about twenty minutes, before any Swift work.

Not recommended: dimension controls before a separability bench; continuing long-form from segment
audio; porting mlx-audio-swift's leak patch; treating the rotary fix as the first month's work.

## 9. Corrections owed to our documents

Listed, not made:

- `docs/audits/2026-10-16-engine-runtime-audit.md` (G-07) and `docs/reference/qwen3-tts-guide.md`
  section 11.1: issue 341 is not an abrupt-ending trigger; issue 219 was withdrawn; issue 80's 20%
  is same-language.
- `docs/reference/qwen3-tts-prompting-guide.md`: the same three, "3 of 3" for mlx-audio 921 without
  its sample of one clip, and "never matches" for G-12.
- `docs/audits/2026-10-17-qwen3-tts-model-research.md` and `docs/reference/mlx-guide.md`: the leak's
  upstream fix is MLX pull request 4453, not 4710, and it is not in the pinned core.
- `docs/reference/mimi-codec-guide.md` section 2.2: "unmeasured" can now cite section 4.1. Its line
  references into `Qwen3TTS.swift` predate the file split of `76fa18e7`, as do several in the two
  guides.
- PA-16's gate still asks for the encoder's 250-frame window, which the codec guide and the research
  say not to add.
- QC-06's gate quotes register figures with no record behind them.
- `Qwen3TTSVoiceClonePrompt.swift` lines 19 to 22 still claim the padding matches upstream.

## 10. Limits

- The measurements ran in the Python port, in English, on clean references, with one identity
  measure and no listening. They are a pre-screen, not a qualification.
- The pairs in sections 4.2 and 4.3 share seeds but not samples, since precision changes the sampling
  path; the comparison is of distributions. A similarity change of 0.01 has no listening result
  behind it, here or anywhere in our records.
- The report's list of where we match the reference (chat template, sampler order, end-of-speech
  handling) was not re-verified.
- Upstream items were read as they stood on 2026-11-11.
