---
status: historical
owner: backend-mlx
summary: Delivery-control audit (2026-08-04) — full-codebase analysis plus a 21-agent primary-source research sweep over the DP-1..DP-10 delivery program. Pinned point-in-time decision report; findings, adjudications, and ranked recommendations as they stood at capture.
contentDigest: sha256:e171bdcd3e0f3377681728dc66b5b9c960a1d40788f3547a3aca879dec84d6cb
---
# Delivery-control audit — analysis, external research, and recommendations (2026-08-04)

> Commissioned after the DP-1..DP-10 delivery program ended in a roster cut, the intensity-control
> retirement, and a maintainer verdict of "these attempts have gone wrong." Method: three parallel
> codebase-analysis passes over the delivery pipeline, harness, and evidence store; then a
> 21-agent web-research sweep (13 research questions, 8 adversarial verifications of the local
> record's load-bearing claims, ~2.3M tokens, 723 tool calls, primary sources only), including a
> live permutation-null simulation mirroring `scripts/delivery_separability.py` exactly. Evidence
> tiers reuse the prompting guide's vocabulary: OFFICIAL / RESEARCH / MEASURED-HERE / COMMUNITY /
> UNVERIFIED. This is a pinned snapshot; where it contradicts earlier prose, this report is the
> corrected record and the earlier prose is cited as history.

## 1. Verdict

**What went wrong is smaller than it feels, and what the project has is better than it thinks.**
The delivery program built genuinely good instruments and detected a real phenomenon that the
entire field has since been found to share — but it over-read two specific numbers, never ran the
two human-calibration instruments it built, shipped one state-sync defect that plausibly
contaminated the maintainer's own blind listening, and left its strongest measured control lever
unproductized. In detail:

1. **The central positive result is real and decisively so.** The 10-way separability UAR 0.311
   survives an adversarial permutation-null attack: the label-exchangeable null for the exact
   shipped procedure has mean 0.1001, SD 0.0242, 95th percentile 0.139 — the observed value is
   8.7 SD above chance, permutation p < 0.001, stable across ridge 0.01–1.0. The instruction
   channel demonstrably steers prosody in cell-identifiable ways. This measurement also appears
   to be the **first quantified valence-collapse evidence on the open Qwen3-TTS 1.7B weights
   anywhere** — nobody else has published a per-emotion confusion analysis for this model family.

2. **The two numbers the roster cut rested on do not survive.** The high-arousal-cluster figure
   ("UAR 0.278 vs 0.250 chance = 1.11×") is an ordinary null draw — permutation p = 0.28, with
   28% of pure-noise runs beating it — and the test is underpowered (80%-power minimum detectable
   effect ≈ UAR 0.39), so real within-cluster separability up to ~1.5× chance cannot be excluded.
   The honest phrasing is "no detectable separability," never "1.11× chance." And the
   excited/dramatic "below the chance floor at 0.056 recall" claim fails completely: the exact
   binomial CI is [0.001, 0.27] (contains the floor, and 0.25), a pure null puts ~48% of cells at
   or below 1/18, and selecting the two lowest cells post hoc makes their recall a minimum order
   statistic that carries **zero information** about those presets specifically. The cut may
   still be right as a *product* decision — see §5 — but the stated statistical justification is
   void.

3. **The causal story must be corrected.** The "arousal is ~91% classifiable, valence ~55%"
   figures are untraceable — no paper reports them, and they are the only untiered
   citation-shaped claim in the prompting guide. The real literature says valence-through-prosody
   is a **~3× bottleneck, not a wall** (acoustics explain R² 0.58 of arousal vs 0.17 of valence,
   Sauter 2010; CCC .658 vs .248 for a lexically-blind model, Wagner 2023), carried by cues the
   instruction channel doesn't reach well — spectral balance, voice quality, smile-formants, and
   above all **nonverbal vocalizations** — while modern "acoustic" models that appear to solve
   valence are actually reading the words. Humans decode 8 emotions at 72% from prosody alone on
   a fixed neutral sentence (RAVDESS, 247 raters), so "the acoustic space does not carry the
   distinction" is false as stated. The supportable claim is narrower: *this checkpoint's
   text-instruction channel, measured with a linear discriminant over prosody deltas, moves
   essentially one arousal-shaped axis* — which matches what the whole field measures for
   instruction-driven emotion (best purpose-built open system: ~1.7× chance; independent
   Qwen3-TTS emotion accuracy: 50–58%; IndexTTS-2's own text path scores below its
   reference-audio path on its own benchmark).

4. **The despair signal has three identified contaminants.** (a) macOS silently ships the
   `.normal` tier — a state-sync defect, not a decision — so the aborted 2026-08-02 blind A/B, if
   run through the macOS app, auditioned the weaker tier while the listener believed it was
   strong. (b) The free-identification and 2AFC instruments built to answer "what do I actually
   hear?" never ran; the one human session that exists *falsifies* the metric's
   "interchangeable" verdicts (5/6 heard as different, exact binomial p ≈ 0.002) precisely in the
   region the roster decisions consumed. (c) Expectations were uncalibrated: human listeners
   identify emotion from voice alone at only **40.9%** on six-way forced choice over *professional
   actors* (CREMA-D, 2,443 raters). A TTS preset at 40% human identification would be at parity
   with human actors, not failing.

**Three moves, in order:**

- **Move 1 — Fix, then listen (half a day).** Fix the macOS `.normal` defect and harness-evidence
  defects, then run the one ~30-minute structured listening session using the instruments already
  built, with a mixed key (presets at both tiers + clone-transfer clips + repeats) and
  pre-registered decision rules (§7). This single session adjudicates the instrument, the
  attractor claim, and the clone-path superiority at once.
- **Move 2 — Ship the strong lever (days).** Productize "design once, then clone": per-emotion
  reference clips conditioning the clone path's in-context mechanism — the only lever with
  published listener evidence in modern TTS (58–62% voice-only human accuracy vs 70.8% for human
  actors), the officially sanctioned Qwen workflow, and the strongest local measurement (5/6 SER
  top-emotion match). Fix the silent x-vector fallback that discards prosody transfer when a
  transcript is missing.
- **Move 3 — Reframe the weak lever honestly (hours).** Keep the 8 instruct presets as
  arousal/voice-quality "delivery hints" with stochastic-with-retry UX and pinned seeds — the
  market norm even at the top (ElevenLabs sells free regenerations; Hume returns two candidates
  per call; OpenAI shipped no seed at all) — and route valence through the text itself
  (script-decoration experiment, §6 R5). Vocello can uniquely offer true seed reproducibility,
  which no cloud vendor provides.

## 2. Every load-bearing claim, and the instrument it stands on

| # | Claim | Instrument | Post-audit verdict |
|---|---|---|---|
| C1 | Presets move prosody hard (paired effect 6.5–9.5) | analyzer v3 paired deltas, 18 seeds | **Holds.** Replicated across DP-3/4/5/6/10; direction win-rates ≥ 0.85. |
| C2 | 10-way separability UAR 0.311 vs 0.100 chance | 23-feature ridge-LDA, leave-one-seed-out | **Holds decisively** (permutation p < 0.001, z = 8.7; 95% CI ≈ [0.24, 0.39]). |
| C3 | High-arousal cluster ≈ one output ("1.11× chance") | same, 4-cell refit | **Falls as phrased.** p = 0.28; underpowered (MDE ≈ 0.39). Correct statement: *no detectable separability*, CI [0.18, 0.40]. |
| C4 | excited/dramatic below chance (0.056) → cut | per-cell recall, n=18 | **Falls completely.** CI [0.001, 0.27]; minimum-order-statistic selection artifact; the number carries no information about these cells. |
| C5 | Wording is not the lever (DP-3/4/5/6 nulls) | Wilcoxon+BH feature counts; separability | **Holds directionally, weakened.** "Surviving features" measures perturbation, not adherence (no external precedent for the metric); DP-3 confounded length with concreteness — external evidence supports *concreteness* (APS ≥ DSD > RP), not length. |
| C6 | Intensity tiers don't separate (ratio 0.997) → selector retired | 19-seed matrix + 1 listener datapoint | **"No ladder" holds; the attractor claim ("strong sounds angry") remains unmeasured** — the 2AFC built for it never ran. And macOS never actually shipped strong (F7). |
| C7 | The metric tracks hearing (ρ = 0.515) | one session, ~18 judged pairs | **Overclaimed.** n-of-1 × ~18 pairs is one to two orders below validation grade (COSMIN, P.808, BS.1534 norms); the CI [0.06, 0.79] is *uninformative* about magnitude, and the close-bucket data affirmatively falsifies the interchangeability threshold (5/6, p ≈ 0.002). |
| C8 | Clone ICL transfers emotion (5/6 SER, ECAPA 0.81–0.87) | pretrained SER + ECAPA, n=6 | **Holds as relative evidence, strengthened externally.** Same-instrument contrast (clone 5/6 vs preset 0.29) survives the SER-transfer critique; ECAPA 0.81–0.87 is unambiguous same-speaker (default verify threshold 0.25; community operating points 0.6–0.75). External: reference conditioning is the only lever with published listener evidence. Caveat: n=6, absolute rates optimistic, never human-confirmed. |
| C9 | The ceiling is the model's acoustic space (91%/55%) | inference + uncited figures | **Falls.** Figures untraceable; RAVDESS/Banse–Scherer show prosody carries valence for humans; the honest claim is channel-specific, not medium-specific. Residual pins: 4-bit quantization (open, prior ~25–40%), single neutral text, single speaker. |

Sampling configuration is **exonerated**: every distribution-shaping parameter (T 0.9, top_p 1.0,
top_k 50, repetition 1.05, subtalker 0.9/1.0/50, talker-only penalty scope) exactly matches the
three checkpoints' generation_config.json and the official inference code; the sole delta
(max_new_tokens 2048 vs the config's 8192) matches Qwen's own published evaluation protocol and is
an unreachable length cap for these takes. The codec think/nothink language-prefill IDs were also
audited this session: the shipped checkpoint configs carry codec_think_id 2154 / nothink 2155 /
think_bos 2156 / think_eos 2157 explicitly, and the Swift port decodes exactly those keys — no
drift against upstream, whose 4202-series values are Python class defaults the checkpoint
overrides for both runtimes.

## 3. Findings

**F1 — The calibration gap is the root cause of the crisis.** The project built the two
instruments that answer the actual product question — free-identification ("what emotion do you
hear?") and 2AFC discrimination with an angry-attractor design, both in
`scripts/delivery_identification_check.py` — verified them against simulated data, and never ran
either on real audio. Every roster and intensity decision therefore rests on the acoustic
classifier alone. Its only human validation session supports, per the standards literature, no
more than "a positive association probably exists" — while its close-bucket data *contradicts*
the interchangeability verdicts the decisions consumed. The repo's own scripts predicted this:
"'the gate failed' has never been evidence a preset is wrong."

**F2 — The statistics under the cuts were never computed.** No scorer computes a chance floor
(all floors are hand-stated prose); no permutation null was ever run; `minimum_cell_recall 0.50`
is cell-count-independent; per-cell recalls at n=18 carry ±0.20-wide CIs that were never printed.
The adversarial re-analysis (mirrored procedure, 1000-iteration nulls) upgrades C2 and demolishes
C3/C4 as stated — see §2. A design detail deserves credit: leave-one-seed-out with one take per
cell per fold is *exact stratification*, which the 2025 literature shows fully neutralizes LOOCV
distributional bias — the simulated null lands on theoretical chance to three decimals. The
design was sound; nobody computed the null's spread. One trap to close: the standalone
`scripts/delivery_separability.py --sidecar` path derives its fold key from the per-take
generation ID, silently degenerating grouped CV into leave-one-take-out; only
`scripts/delivery_matrix_report.py` re-keys folds by run. The DP-10 analysis merged sidecars
through the standalone path, so its stated "grouped by seed" guarantee is not what executed
(numerically immaterial here — the null is statistically identical — but it voids a documented
invariant).

**F3 — The evidence base cannot be re-analyzed.** The bench writes one fixed filename per cell,
so DP-10's 18 seeds overwrote each other on disk — one seed per cell survives — and the 31
delivery benchmark records were deliberately discarded as dirty-source. DP-3..DP-10's numbers
survive as prose only. Combined with sequential experiments, thresholds tuned on the deciding
data, and no confirmation set, the honest classification of DP-1..DP-10 is **exploratory**. Any
decision-bearing claim needs one preregistered fresh-seed confirmation run.

**F4 — A shipped defect sits under the ear evidence.** macOS silently sends the `.normal` tier:
`Sources/Views/Components/EmotionPickerView.swift` declares `.strong` as its default, but its
`syncSelectionFromText()` walks presets × tiers in order, the Neutral draft default
(`Sources/Models/GenerationDrafts.swift`) matches Neutral's identical `.normal` string first, and
every subsequent preset pick emits the `.normal` copy. iOS is unaffected. DP-8's decision was
ship-strong-everywhere, and DP-3 measured strong at nearly twice normal's recognisability (0.278
vs 0.157 mean recall). Consequence: a macOS-based blind listening session auditioned the weaker
tier under the belief it was hearing the stronger one. Smaller leftovers: the CLI error text in
`Sources/VocelloCLI/BenchCommand.swift` still offers the deleted `subtle` tier and defaults bare
`--delivery happy` to `.normal`; dead intensity plumbing threads through
`Sources/iOS/Sheets/IOSBottomSheets.swift` and `Sources/iOSSupport/Models/GenerationDrafts.swift`;
a macOS UI-test comment asserts the strong-tier behavior the app doesn't have
(`Tests/VocelloMacUITests/VocelloMacMarketingCaptureUITests.swift`).

**F5 — The model family, not the integration, is the common factor.** No third party has
published the specific valence-collapse measurement, but everything around it corroborates:
Alibaba's own report shows Response-Precision only ~61 on InstructTTSEval for this checkpoint and
publishes no per-emotion evaluation at all; an independent study measured hosted-era Qwen3-TTS
emotion accuracy at 49.98–58.08% despite MOS 4.3; community reports uniformly describe
instruction-emotion as audible-but-coarse and non-deterministic; the most popular community
"emotional Qwen3-TTS" tool abandons instructions entirely and fakes emotion by modulating
sampling parameters; the hosted stack ships a server-side instruction-*rewriting* knob; and the
ecosystem's collective answer — the announced Qwen3-TTS-25Hz-1.7B-VoiceEditing checkpoint, the
only family member with both Voice Clone and Instruction Following in the tech report's Table 1 —
remains unreleased seven months after being promised. Field-wide, instruction-driven categorical
emotion is weak everywhere it is measured: the best purpose-built open system reaches ~1.7×
chance on a 4-way SER recall, and IndexTTS-2's own natural-language path (EMOS 3.79) scores below
its reference-audio path (4.22) *in its own paper* — same model, same vocoder, same medium; the
delta is the control channel.

**F6 — External-validity pins remain under every conclusion.** All DP sweeps ran on the **4-bit**
Speed artifact (upstream's adherence numbers are bf16; the LLM quantization literature shows
instruction-following and long-tail conditional behavior degrade at 4-bit in the 1–2B class
before aggregate metrics move — answer "flips" up to 13.6% at ≤2% aggregate change — and no
published quality measurement exists for any quantized codec-LM TTS; adversarial prior that
quantization is a major contributor: ~25–40%). All sweeps used one semantically neutral sentence —
and the field's own evaluations show **text is the valence channel** (CosyVoice's emotion table:
happy scores 1.00 with *no instruction at all* when the text is emotion-congruent; SER
transformers' valence success is demonstrably lexical). All sweeps used one speaker and English
instructions. Two pins were closed by the sweep: sampling defaults match upstream exactly (V7),
and the queued Chinese-instruction experiment lost its evidential basis — Table 8's +5.7 APS
compares disjoint language-matched benchmark subsets, the sibling checkpoint reverses the
direction, and the metrics closest to delivery presets (DSD/RP) show no Chinese advantage.

**F7 — The judge landscape shifted under the program, mostly in its favor.** 2026 research
formally discredits pretrained SER classifiers *and* emotion-embedding cosine similarity on
codec-LM output: emotion2vec drops 99.64% → 15.31% on synthesized TESS (verified in the primary
paper — and the mechanism is autoregressive codec-token prediction, i.e. exactly this
architecture; the vocoder is exonerated at ~1.5 pp), and embedding-cosine metrics score *below
chance* under distractors ("The False Resonance"). Consequence: the bespoke paired-delta
classifier — text-controlled, seed-paired, deterministic, fitted in-domain — is *more* defensible
than off-the-shelf SER, not less. The only instruments with validated near-human agreement are
audio-LLM judges with decomposed binary rubrics and paired protocols (Gemini-class; Spearman
0.76–0.90 vs humans across InstructTTSEval / EmergentTTS-Eval / MINT-Bench), none of which fit an
8 GB local machine (the one audio-LLM that fits is the documented outlier-*bad* judge in the
EmergentTTS ablation). One nuance cuts against a local reading: the clone-vs-preset contrast
(5/6 vs 0.29 aggregate agreement) used the *same* pretrained SER on the same engine, so it
survives the transfer critique as relative evidence — the presets express emotion far more weakly
than the clone path — even though the absolute 0.29 is uninterpretable alone.

**F8 — The strongest lever is unshipped, and prior art says how to ship it.** Clone ICL mode
places the reference clip's full codec-token sequence in-context; the model continues from the
reference's actual prosody. Locally measured: 5/6 SER top-emotion match, ECAPA 0.814–0.871
against 0.10/0.39 negative controls. Externally: reference-audio conditioning is the top-ranked
lever with independent evidence (InstructTTSEval's reference-audio oracle averages 84.3, above
every open-weights instruct system and above Gemini-pro; the one controlled listener study of
modern TTS shows reference-conditioned systems reach 58–62% voice-only human accuracy against
70.8% for human actors); "Voice Design then Clone" is the officially sanctioned Qwen workflow;
and per-emotion reference banks exist in shipped products (IndexTTS-2's separate emotion-
reference input with a ≤0.6 strength recommendation; GPT-SoVITS's per-emotion reference manager;
ElevenLabs' one-style-per-clone guidance). Known pitfalls, all with evidence and mitigations:
identity gates must compare take ↔ *matching-emotion* reference (cross-emotion same-speaker
verification is measurably worse — a naive neutral-enrollment gate false-alarms exactly on the
presets that work); curate references at moderate intensity, not peak (overshoot evidence
converges on ~0.6 of full strength); require ≥10 s clean clips with deterministic QC; cache
conditioning per (voice, emotion). One product bug blocks it today: a reference without a
transcript silently degrades to x-vector-only — identity without prosody — with no UI
explanation.

**F9 — Tags are off the table; text decoration is the untested valence channel.** Bracketed or
parenthesized tags are synthesized as literal words on all three shipped checkpoints (third-party
confirmed; the [angry]-style vocabulary belongs to the hosted qwen-audio-3.0 family only), and
every codec-LM that honors tags trained them in explicitly — zero-shot tag adoption does not
exist, and Vocello cannot fine-tune. What does work in-text: punctuation prosody (measured
locally: exclamation and question marks carry matching prosody; ellipses are read as text), and —
officially claimed but unmeasured — text semantics ("adaptively adjusts tone, rhythm, and
emotional expression... based on instructions *and text semantics*"). Spontaneous laughter is
in-distribution (a known hallucination complaint upstream), so onomatopoeic and interjection
rewriting is mechanistically plausible. Given the DP program proved instruction wording is
saturated while never touching the script text, preset-driven script decoration is the cheapest
untested lever pointed directly at valence.

**F10 — What replicated and must be kept.** Presets move prosody with large direction-correct
effects; `sad` and `fearful` land as their SER categories (p = 0.93/0.99); the diction-append
parity defect was found and permanently gated; fail-closed audio QC caught real dropouts; the
paired same-seed design is exactly the control the text-dominance literature demands (DP-6's
"the contradiction is textual, not acoustic" independently rediscovers a published finding); the
underpowered-fit refusal and aliased-cell detection are the right instincts; the analyzer-v3
feature set already contains most of the valence-cue block the literature prescribes (HNR, CPP,
alpha ratio, Hammarberg, spectral flux, centroid — missing only H1–H2 and a formant/smile
proxy). This program's measurement culture is an asset. The failure was narrower than it felt:
two over-read numbers, one unrun calibration session, one shipped state bug.

## 4. Alternative explanations, adjudicated

| H | Hypothesis | Verdict after the sweep | Decisive check remaining |
|---|---|---|---|
| H1 | Instrument insensitivity to valence cues | **Partially supported.** Linear discriminants over prosody features are the instrument class the literature shows fails on valence (ρ .37-class); but analyzer v3 already includes most spectral/voice-quality cues, and the 10-way result proves real sensitivity. The ceiling-vs-floor question stays open until humans are scored on the same takes. | The listening session (R2); optionally re-score a fresh matrix with SER-embedding features under the same CV. |
| H2 | Neutral-text confound suppresses valence | **Supported externally.** Text is the demonstrated valence channel field-wide; every published emotional-TTS eval uses emotion-congruent text — the experiment Vocello needs (instruction-driven emotion on neutral text, per-emotion confusion) has never been published by anyone. | Text-decoration experiment (R5) plus one emotion-congruent-text arm. |
| H3 | Harness plumbing defects | **Weakened to residual.** Instructions demonstrably reach the model (effect sizes; community reproduction); sampling and think-prefill audited clean. Residual: per-take prompt echo has never been asserted. | Prompt-echo assertion in the harness (R1), then one regenerated matrix. |
| H4 | 4-bit quantization degrades adherence | **Open, prior ~25–40%.** Right model size class and behavior class per the LLM literature; zero direct TTS evidence either way; the clone path proves the 4-bit acoustic space *renders* emotion, so damage would be in the instruction-conditioning pathway. | Nearly free: rerun the matrix on the shipped 8-bit Quality artifact (R4); bf16 one-off (~4.5–5 GB headless) only if 8-bit shifts. |
| H5 | Forking paths / no confirmation set | **Confirmed as an attenuator.** DP-1..10 reclassified exploratory (F3). | Preregistered fresh-seed confirmation (R4). |
| H6 | English instructions underperform Chinese | **Refuted as evidenced.** Table 8 does not license cross-lingual instruction gains; deprioritize. | None — drop the experiment. |
| H7 | Temperature/seed variance drowns valence cues | **Open, modest.** Same-seed pairing already controls most; effect sizes show instruction dominates noise on arousal. | Optional T≈0.6 / best-of-N arm inside R4. |
| H8 | Wrong lever, right model | **Strongly supported.** The full lever ranking (reference audio > disentangled vectors > instruct text > tags > exaggeration) plus upstream's own design-then-clone blessing plus the local 5/6. | Clone clips in the R2 answer key confirm with human ears. |
| H9 | "It sounds fine, actually" / expectations miscalibrated | **Partially supported.** The macOS defect (F4) plus the 40.9% CREMA-D human anchor mean the despair reading was contaminated and uncalibrated. Some presets provably land (sad, fearful). | R1 then R2. |
| H10 | Small-n statistics under the cell cuts | **Confirmed.** See §2 C3/C4. | Computed floors + permutation p + FDR on the regenerated matrix (R4). |
| H11 | Valence is a physics ceiling of the medium | **Refuted as stated; survives narrowed.** A ~3× bottleneck concentrated in cues this control channel doesn't move; not a wall (RAVDESS 72%; EMIS 58–62% via reference conditioning). Also: the high-arousal cluster was never a valence contrast (excited ≈ happy variant; dramatic is a register; surprised is valence-ambiguous) — the discriminating probe is a 2-way happy-vs-angry run, which was never done. | happy-vs-angry 2-way in R4. |

The conjunction that best explains everything observed: **H8 × H2 × (H1 or H4)** — the program
measured the weak lever exhaustively, on text that suppresses the target dimension, with an
instrument (or a quantization) that may under-report what remains — while the strong lever sat
measured-but-unshipped.

## 5. Decision review

- **Roster cut 10 → 8: SUSTAIN as a product decision; the stated justification is retired.**
  "No detectable separability within the high-arousal cluster" is true and sufficient product
  grounds ("a control indistinguishable from its neighbour is not a control"), and the listener
  complaint independently points the same way. But "below chance" was never demonstrated, and the
  do-not-reintroduce note's *statistical* rationale is void. `surprised` (recall 0.222, CI wide)
  is in the same evidentiary state as the cut presets were. Confirm on the R4 fresh-seed matrix
  before treating "8" as settled; do not reinstate on wording alone (that part stands).
- **Intensity-selector retirement: KEEP the UI decision; REOPEN the evidence.** "Tiers do not
  separate from each other" (ratio 0.997) stands. "At strong it all sounds angry" — the claim
  that emotionally drove the retirement — was never measured; the attractor 2AFC exists, coded
  and tested, and belongs in the R2 session. Ship-strong-everywhere: sustain the intent, fix the
  macOS defect that quietly reversed it.
- **DP-3's "long copy wins": WEAKEN to "acoustically concrete copy wins."** The external axis
  with evidence is concreteness/abstraction (APS ≥ DSD > RP on this exact checkpoint), not
  length; the local A/B confounded the two, and "surviving features" counts perturbation, not
  adherence. Do not spend further effort on instruction register either way.
- **Autonomous-QA policy: KEEP, with one amendment.** Listening remains annotation, never a gate.
  The amendment: *instrument calibration is not take-grading*. A once-per-instrument human
  session that fixes the meaning of the machine's scale is what makes autonomous QA trustworthy —
  and both calibration instruments already exist. Every roster decision consumed verdicts from
  the one region of the metric the only human data contradicts; that is the precise cost of the
  session never running.
- **The "delivery gates aren't ground truth" lesson: PROMOTE it from memory to mechanism.** The
  fearful case (best recall 0.500, passes the directional gate 1/18) plus the derived-expectation
  circularity the repo already documented mean gate pass-rates must never again feed promotion
  or roster decisions without a separability-class instrument beside them.

## 6. Recommendations, ranked

**R1 — Fix the found defects and harden the harness (~half a day).**
macOS `.normal` state-sync bug (one-line class of fix in `EmotionPickerView`); surface the
clone-transcript requirement instead of silently degrading to x-vector-only; CLI `subtle`/tier
leftovers; dead intensity plumbing; stale 10-preset claims in
`docs/reference/qwen3-tts-prompting-guide.md`, `docs/qwen_tone.md`,
`docs/reference/qwen3-tts-guide.md`, `docs/reference/macos-app-guide.md`, and the outdated F4 claim in
`docs/reference/delivery-fidelity-report-2026-08-01.md`. Harness: label-scoped bench output
directories (stop overwriting evidence); per-take final-instruct prompt echo in sidecars;
computed chance floors and a permutation-null band in `scripts/delivery_separability.py`; an
n-aware (Wilson) recall criterion replacing the fixed 0.50 bar; fix the standalone-CLI fold-key
degeneration (F2); exploratory-vs-confirmatory labels on records.

**R2 — The calibration session (~30 min listening + ~1–2 h generation/setup).** Blind,
script-randomized, pre-registered:
*Block A* — 8-way forced-choice identification, 12 clips per preset (96 trials, ~14 min):
pooled above-chance bar ≥ 24/96 at the 1/8 floor; per-preset ≥ 5/12 (α ≈ .04); build the
confusion matrix and its arousal-collapsed 3-way form. Calibrate against the 40.9% human-actor
anchor, not against 100%. Mix in clone-transfer clips as additional key rows (adjudicates H8).
*Block B* — targeted 2AFC, 24–25 trials per contrast (~13 min): happy-vs-surprised (the
surviving within-cluster pair) and the angry-attractor design already coded; pass ≥ 17/24. A null
detects 0.75 but not 0.65 — record that limit. Optional add-on when wanted: a 20–30 rater
Prolific panel on the same ~40 clips (~$100–140, same-day) meets or beats the 11–24-listener
norm of 2025–26 expressive-TTS papers.

**R3 — Productize design-then-clone per-emotion reference banks (days, after R2 confirms clone
clips land for a human ear).** Per the F8 checklist: VoiceDesign-generated (or user-recorded)
styled reference per emotion per voice; ICL always (transcript required — make the UI say so);
moderate-intensity curation; per-clip deterministic QC; identity gate against the
matching-emotion reference plus a separate laxer neutral-reference bound; multiple takes per
emotion with nearest-to-neutral-centroid selection; conditioning cached per (voice, emotion).
This is the one lever that raises the product ceiling, and it composes with the shipped model
set — no new model, no new memory cost at rest.

**R4 — Re-measure on solid statistics (one bench overnight + half a day analysis).** Regenerate
one 8-preset matrix (≥18 fresh seeds) with R1's retention and prompt echo, then: per-cell
permutation p-values with FDR; pairwise centroid distances with bootstrap CIs (higher power per
seed than the 4-way UAR); the 2-way happy-vs-angry probe (the actual valence test, never run);
the same sweep on the **8-bit Quality artifact** (nearly free, and the highest-information
quantization check); optionally a T≈0.6/best-of-3 arm. Only after this does "8 presets" become a
confirmed number rather than an exploratory one.

**R5 — Text-decoration experiment (cheap; the untested valence lever).** Preset-scoped script
rewriting scored by the existing pipeline: exclamation marks and sentence splits (measured
prosody channel), emotive interjections ("Ugh," / "Wow!" / "Oh no." — never ellipses, never
bracketed tags), one onomatopoeic-laughter arm ("Haha!") with QC watching for hallucinated extra
laughter, and one emotion-congruent-text arm to bound H2. If interjections move valence-adjacent
features where instructions could not, the preset concept gets a second, honest channel: presets
that *suggest text edits* rather than only whispering to the model.

**R6 — Honest-UX reframing (hours, copy + small UI).** Presets become "delivery hints"; the
picker copy stops promising emotional identity; regenerate-with-new-seed plus pin-this-seed
become first-class (the market's institutionalized norm — and local fixed-seed reproducibility
is a genuine differentiator no cloud vendor offers). Cartesia's own docs state the DP-6 finding
as a product constraint ("emotion tags... only work when the emotion is consistent with the
transcript") — copy that framing.

**R7 — Judges (after R2 provides a human anchor; never before).** Keep the bespoke paired-delta
classifier as the deterministic gate — post-2026 literature makes it *more* defensible than any
pretrained SER on this architecture. Optionally add the audeering arousal axis as a paired-delta
advisory only (0.66 GB, CPU; CC-BY-NC research license — acceptable only as a never-shipped
dev-side diagnostic, flag before adopting; emotion2vec+ is the fallback with its own license
check). Never adopt embedding-cosine similarity in any form. Optionally add a non-gating,
dev-time-only cloud audit lane (Gemini-class judge, decomposed binary rubrics, paired
instructed-vs-neutral prompts) with the same policy status as human listening: annotation
evidence, never a gate, absolute scores never compared across judge versions.

**R8 — Watch list and research tier.** (a) **Qwen3-TTS-25Hz-1.7B-VoiceEditing** — the family's
own clone+instruct answer, promised, unreleased; if it ships, re-evaluate immediately (budget a
new decoder port: DiT + BigVGAN, higher decode cost). (b) **CosyVoice 3 0.5B** (Apache-2.0)
combines clone+instruct in one call *today* and has community MLX 4-bit ports at ~1.25 GB —
worth a contained spike only if VoiceEditing stalls and R3 underdelivers; instruct quality on
cloned voices is README-prose, not benchmarked. (c) **Activation steering** (EmoSteer-class,
training-free, continuous intensity) is uniquely available to a project that owns its runtime —
research-tier, genuinely novel if it works on this checkpoint. (d) A bounded DSP "delivery trim"
(rate ±10–15%, tilt, ±50–100 cents) is honest and machine-verifiable as a *softer/bigger* knob —
but the validated DSP literature fails exactly on happy-cluster intensity, so never market it as
emotion intensity. (e) bf16 one-off A/B only if the 8-bit arm in R4 moves.

**Do not do:** LoRA/SFT emotion fine-tuning (the official pipeline cannot express an emotion or
instruction label; the only rigorous lineage result needed 244 h and found naive full SFT triples
WER; every usable English emotional corpus is non-commercially licensed — there is no clean
training set for a shippable model). Model swap on control grounds (nothing that fits 8 GB/MLX
controls emotion better than what R3 unlocks; IndexTTS-2 fails footprint, speed, and license).
Inline tags on current checkpoints (synthesized literally). Further instruction-wording
experiments (five ablations, all null — the channel is saturated).

## 7. Week-one runbook

1. **Day 1 morning:** R1 defect fixes + harness hardening; deterministic gates green.
2. **Day 1 afternoon:** generate the R2 clip set (fresh seeds, strong tier actually shipping,
   clone-transfer rows included); run the 30-minute session; score with the existing tools.
3. **Day 2:** kick off the R4 regenerated matrix (4-bit + 8-bit arms) overnight; analysis next
   morning with computed nulls.
4. **Decision gate (end of week):**
   - Humans identify clone-transfer clips ≫ instruct presets → build R3; demote presets to
     hints (R6); R5 as the follow-up valence channel.
   - Humans identify presets near the 40% actor anchor → the crisis was instrument-and-defect
     driven; keep the roster, ship R6 copy, continue R4-grade measurement discipline.
   - 8-bit materially beats 4-bit → quantization is implicated; run bf16 confirm; consider
     Quality-tier default for delivery-sensitive generation.
   - Everything fails with humans too → full R6 reframe; the instruct path is decoration; R3
     remains the emotion mechanism.

## Appendix A — instrument-hardening spec

1. Bench WAV retention: label-scoped output directories or seed-suffixed filenames, governed as
   scratch under the build-output policy; sweeps must never overwrite their own evidence again.
2. Prompt-echo provenance: sidecars record the exact final instruct string per take; the harness
   asserts non-empty echo when a delivery was requested.
3. Computed floors: `scripts/delivery_separability.py` emits 1/len(cells) and a
   200-iteration permutation-null band (mean/p95) beside every UAR; refuses "below chance"
   phrasing for any cell whose Wilson interval touches the floor.
4. n-aware recall bar: replace `minimum_cell_recall 0.50` with a Wilson-lower-bound criterion
   against the computed floor.
5. Fold-key fix: the standalone sidecar path groups folds by run/seed the way
   `scripts/delivery_matrix_report.py` already does, restoring the documented guarantee.
6. Exploratory/confirmatory labels on every published record; decision-bearing claims require
   one preregistered fresh-seed run.
7. Keep unchanged: underpowered-fit refusal, aliased-cell detection, fail-closed audio QC,
   same-seed pairing, BH correction.

## Appendix B — key sources

Local: `scripts/delivery_separability.py`, `scripts/delivery_identification_check.py`,
`scripts/separability_listening_check.py`, `scripts/emotion_advisory.py`,
`scripts/delivery_matrix_report.py`, `scripts/prosody_profile.py`,
`Sources/QwenVoiceCore/EmotionPreset.swift`, `Sources/QwenVoiceCore/GenerationSemantics.swift`,
[`qwen3-tts-prompting-guide.md`](qwen3-tts-prompting-guide.md),
[`delivery-fidelity-report-2026-08-01.md`](delivery-fidelity-report-2026-08-01.md). The
permutation-null simulation scripts and the 21 per-question research reports are session
artifacts (untracked); their load-bearing numbers are reproduced above with citations.

External (primary, all opened during the sweep unless noted):
- Qwen3-TTS Technical Report — arXiv 2601.15621 (Table 1 capability matrix incl. the unreleased
  25Hz VoiceEditing row; Table 8 InstructTTSEval at bf16; no emotion evaluation anywhere).
- QwenLM/Qwen3-TTS issue #25 (collaborator: Base does not support instruct; VoiceEditing "will
  support both cloning and instruct"); discussions #218/#231/#238/#248; official inference code
  (ChatML instruct turn; clone API has no instruct parameter; 0.6B silently nulls instruct).
- On the Emotion Understanding of Synthesized Speech — ACL 2026, arXiv 2603.16483 (emotion2vec
  99.64 → 15.31 on synthesized TESS; AR codec-token prediction is the dominant cause; SER stays
  near chance even on human-verified emotional synthetic speech).
- The False Resonance — arXiv 2604.26347 (emotion-embedding cosine metrics unreliable to
  below-chance under distractors).
- InstructTTSEval — arXiv 2506.16381 (APS/DSD/RP; Gemini judge, ~79% human agreement;
  reference-audio oracle 84.3 above all open instruct systems). EmergentTTS-Eval — arXiv
  2505.23009, NeurIPS 2025 (judge–human Spearman 0.76–0.90; Qwen2.5-Omni the outlier-bad judge).
  MINT-Bench — arXiv 2604.17958.
- Wagner et al., IEEE TPAMI 2023 — arXiv 2203.07378 (valence CCC .248 acoustics-only vs .635 via
  implicit text; frozen-transformer synthetic-speech proof). Sauter et al. 2010 (arousal R² .58
  vs valence .17). Livingstone & Russo 2018, RAVDESS (72% 8-way from prosody on neutral text).
  Bänziger & Scherer 2005 (contour-shape null). Gobl & Ní Chasaide 2003 (voice quality signals
  mild states; happy/sad worst). Juslin & Laukka 2003.
- EMIS / emotionally incongruent speech — arXiv 2510.25054 (reference-conditioned TTS 58–62%
  voice-only human accuracy vs 70.8% human actors; SLMs read the text, chance on acoustics).
- FunAudioLLM/CosyVoice — arXiv 2407.04051 (emotion-congruent text saturates happy at 1.00 with
  no instruction); CosyVoice 2 — arXiv 2412.10117 (trained-in [laughter]/[breath]/<strong>
  vocabulary); CosyVoice 3 — arXiv 2505.17589; Fun-CosyVoice3-0.5B (Apache-2.0, clone+instruct
  in one call, community MLX 4-bit ≈ 1.25 GB).
- IndexTTS-2 — arXiv 2506.21619 (reference-audio EMOS 4.22 vs text-path 3.79; emo_alpha ≤ 0.6
  guidance; non-commercial-without-authorization license; MLX ports exist but ~3–4.7 GB and
  RTF ≈ 1.3 on M2 Max). EmoVoice — arXiv 2504.12867 (field-wide instruct-emotion recall table).
  EmoCtrl-TTS/ELaTE — arXiv 2407.12229 (nonverbal conditioning, not more emotional data, moved
  listener-perceived emotion). EmoSteer-TTS — arXiv 2508.03543 (training-free activation
  steering). CSP-FT — arXiv 2501.14273 (partial fine-tuning 244 h; naive full SFT triples WER).
- Combrisson & Jerbi 2015; Noirhomme et al. 2014; Varoquaux 2018; Austin, Pe'er & Korem 2025
  (small-sample CV statistics; exact stratification resolves LOOCV bias). CREMA-D — Cao et al.
  2014 (human voice-only emotion ID 40.9%). ITU-T P.808 / ITU-R BS.1534-3 / Naderi & Cutler 2020
  (listening-test standards). Kiritchenko & Mohammad 2017 (best-worst scaling).
- ElevenLabs v3 docs and blog (non-determinism documented; two free regenerations; tag-spoken-
  aloud failure mode); Hume Octave docs (num_generations 2; description Octave-1-only); Simon
  Willison 2025-03-20 (gpt-4o-mini-tts instruction non-determinism); Cartesia Sonic-3 docs
  ("guidance rather than strict adjustments"; emotion must be consistent with the transcript);
  MiniMax Speech-02 — arXiv 2505.07916.
- Blaizzy/mlx-audio and model-repo API data for every footprint/RTF figure in R8; Blaizzy
  Qwen3-TTS multi-precision benchmark gist (speed/memory only — no quality data exists);
  quantization behavior literature: arXiv 2409.11055, 2407.09141 ("Accuracy is Not All You
  Need"), 2407.03211, 2505.02214.
