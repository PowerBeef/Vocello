---
status: active
owner: backend-mlx
reviewed: 2026-11-25
summary: Vocello's hybrid (mixed-precision) Qwen3-TTS model, RF-55 — the recipe and why, how it is built from the two 3.0 artifacts, the identity proof, the evidence that chose it, how it was delivered, and what one model means for the backend.
sourceOfTruth:
  - scripts/build_hybrid_model.py
  - config/quality-screens.json
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSLoading.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3StreamingMemoryTuning.swift
---

# Hybrid model (RF-55)

Each mode (Built-in Voice, Voice Design, Voice Cloning) has one model: the `attn` hybrid, a
mixed-precision artifact that replaced the two 3.0 packages, Speed (4-bit) and Quality (8-bit), and
with them the Speed/Quality selector (RF-59). The maintainer decided on 2026-11-12 that a custom
model may ship if it beats the stock artifacts at a similar footprint, accepting up to 20% more
generation time. This guide records the model the screens chose, how it is built, and how it was
delivered.

**Status (2026-11-25).** `attn` is the single model (`hybrid-single-model`): every rule it was
screened by is ADOPT, and it has 176 MB more weights than Speed. In the formal speed lane its median
real-time factor on the M6 is 0.303, against 0.279 for Speed and 0.412 for Quality: about 9% more
generation time than Speed and about 27% less than Quality (per cell, 4 to 6% more than Speed; §4).
It beats Speed in every screen and does not match Quality everywhere (§4, Known limits). The three
artifacts were published on 2026-11-13 and the contract, catalog and apps moved to them the same day
(§5, §6). iPhone qualification, Pack B/C outcomes, and the final 3.2 status are recorded at the end of §6.

## 1. The recipe: `attn`

Every tensor of the 4-bit artifact, except the talker's attention projections, which come from the
8-bit artifact of the same conversion:

| Component | Precision | Source |
| --- | --- | --- |
| Talker attention, `model.layers.{0..27}.self_attn.{q,k,v,o}_proj` | 8-bit affine, group 64 | 8-bit artifact |
| Talker MLP, `model.layers.N.mlp.{gate,up,down}_proj` | 4-bit affine, group 64 | 4-bit artifact |
| Code predictor (every tensor) | 4-bit affine, group 64 | 4-bit artifact |
| Talker text embedding | 8-bit (both tiers already) | 4-bit artifact |
| Speech tokenizer (codec) | fp32, Qwen's release | shared, byte-identical |
| Base speaker encoder | float | 4-bit artifact |

That is 112 modules (28 layers × 4) per mode: 1.51 GB of model weights against Speed's 1.33 GB and
Quality's 2.10 GB (+176 MB and +768 MB), about 2.23 GB per artifact with the codec and marking.

**Why attention, and why not the code predictor.** A frame reads the talker's layers once (about
0.79 GB at 4 bits) and the code predictor's 15 times (44 MB × 15, about 0.68 GB), and on Apple
silicon about half of any growth in bytes read shows up as time. The ceiling probe showed precision
causes the East Asian long-form refusals: the all-8-bit model generated 31 of 32 Chinese and Japanese
projects the 4-bit model refused 21 of. Probes over 24 East Asian projects then ranked the recipes:
Speed 11, `down` 8, `mlp` 14, `attn` 17, `attn-down` 19, Quality 22. The 8-bit code predictor alone did
not rescue Korean long-form (`long-form-korean-code-predictor-8bit`: NOT SHOWN, 15 of 16 refused either
way) and costs about 20% on a GPU-bound frame, so it stays at 4 bits. A recipe keeps q/k/v and gate/up at
equal precision, so the fused projections (RF-46) stay fused.

## 2. Building it

```sh
python3 scripts/build_hybrid_model.py build --recipe attn --out build/artifacts/macos/hybrid-models/attn
python3 scripts/build_hybrid_model.py self-test
```

- **Inputs are the 3.0 packages.** The builder reads them from the research folder
  (`~/Library/Application Support/QwenVoice-Research/models`, `--models` otherwise) through the last
  two-package contract (`Tests/Fixtures/two-package-model-contract.json`), since the shipped one
  names only the hybrids and the app's first verified hybrid removes every 3.0 folder from its own
  models folder.
- **Inputs are verified.** Each mode's 4-bit and 8-bit folders must match their integrity
  record (size and SHA-256 of every file), and that record must name the contract's repository and
  revision. Anything else is refused; nothing is requantized.
- **Output is deterministic.** One `model.safetensors` per mode, tensors in sorted key order with an
  8-byte-padded header, so the same inputs give the same digest. `config.json` gains a per-layer
  `quantization` entry (`{group_size: 64, bits: 8, mode: affine}`) for each selected module, in the path
  form the loader reads (`model.layers.N.self_attn.q_proj`). The index and a README are regenerated;
  every other required file is the 4-bit artifact's own (hard-linked).
- **Admission without a bypass.** Each built folder carries its own `.qwenvoice-model-integrity.json`,
  computed from its files, and the build writes a development contract (`qwenvoice_contract.hybrid-attn.json`)
  naming the three folders. `vocello --manifest <contract>` with a data directory whose `models` holds
  the build loads them through the normal verified path.
- **Naming rules the runtime enforces** (found by the first build, now in the builder and its tests):
  - the revision must be 40 lowercase hex characters (`ContractBackedModelRegistry`); a local build's
    revision is the SHA-1 of its file list, a content identity that changes with any byte;
  - the folder and the repository must both name Qwen3-TTS (`Qwen3TTSRuntimeProfile`); a local build's
    repository is `local/<folder>`. **A published name must keep "Qwen3-TTS" in it.**
- **The diagnostic key.** `QWENVOICE_MIXED_PRECISION=<recipe>` (a diagnostics build with
  `QWENVOICE_DEBUG=1`) takes the recipe's tensors from the installed 8-bit sibling at load so a
  recipe can be screened before anything is built. It needs both 3.0 siblings installed (Mac-only)
  and `validateMixedPrecisionTarget` refuses to overlay onto an already-hybrid checkpoint. Since
  `4a42d25d` (`RF-70`), the recipes include Pack C's `attn-io` (131 modules, `+24.12 MB` over `attn`:
  `attn` plus `text_projection`, `codec_head`, `small_to_mtp_projection`, and all 15 code-predictor
  `lm_head`s) and `attn-io-edge` (143 modules, `+99.61 MB` over `attn`: `attn-io` plus edge talker
  layers `0, 1, 26, 27` MLPs), and `scripts/build_hybrid_model.py` copies and verifies optional
  `.bias` tensors alongside `.weight`/`.scales`/`.biases` for non-layer I/O projections.

## 3. Identity proof

A built artifact loaded normally, with no key, must reproduce the key's takes exactly. At the
campaign's executable (`4ef80685`, preserved), the built `attn` artifacts gave:

- the clone screen's seed set 3: 192 of 192 takes PCM-identical to arm `attn`, with the same durations
  and code counts;
- the long-form screen's seed set 13: 21 of 21 generated projects PCM-identical, and the same 3 refused.

So every screened number below holds for the built artifact, not only for the key.

## 4. Evidence

Rules were recorded before their takes (`config/quality-screens.json`, where each rule's `result` holds
every number); each screen's arms ran at one build with fixed seeds, the clone and long-form arms at
`4ef80685` with nothing else running, the single-take arms at `734e3766` (no timing is read from them).
Margins: speaker similarity 0.05, error rate 0.04, window spread 0.05, trailing silence 40 ms. Every
verdict below was read by hand against its rule's decision text.

| Screen | Rule | Verdict | Detail |
| --- | --- | --- | --- |
| Clone, seed set 3 (192 takes, six languages) | `hybrid-attn-vs-speed` | ADOPT | similarity −0.002 [−0.014, +0.009]; error rate +0.007 [−0.006, +0.022]; gross failures 3 against 1 |
| Clone, seed set 3 | `hybrid-attn-vs-quality` | ADOPT | similarity **−0.026 [−0.039, −0.014]**, inside the margin; error rate +0.009 [−0.004, +0.025] |
| Long-form, seed sets 13–15 (72 projects, Expressive) | `hybrid-attn-long-form` | ADOPT | generated 65 of 72 (Speed 56, Quality 68); against Speed 11 gained, 2 lost (sign test p = 0.011); no stratum below Speed (Chinese 11, Japanese 12, Korean 6 of 12; Speed 9, 9, 3; Quality 12, 11, 9); no failure class Speed lacks (dropout, slow delivery); error rate against Speed −0.082, −0.053, −0.069 per seed set, against Quality **+0.031, +0.070, +0.035**, each interval excluding zero, none wholly past +0.04 |
| Single takes, seed set 1 (144 takes: Built-in Voice in five languages, Voice Design in English) | `hybrid-attn-single-vs-speed` | ADOPT | better than Speed: error rate −0.016 [−0.029, −0.005], window spread −0.036 [−0.051, −0.022], takes 1.9 s shorter; no take refused (Speed 2 gross failures, `attn` 0); noise floor inside 0.71 of each margin |
| Single takes, seed set 1 | `hybrid-attn-single-vs-quality` | ADOPT | inside both margins: error rate +0.007 [+0.000, +0.015], window spread +0.010 [+0.005, +0.016] |
| Choice | `hybrid-single-model` | `attn` | both candidates qualify (three ADOPT rules, ×1.07 at most against the 1.20 ceiling, weights under 560 MB); `attn` has the fewest added weights, and `attn-down` was no better on clones (+0.004 [−0.008, +0.016] against `attn`) and generated 2 fewer long-form projects, at twice the added weights |

**Cost on the M6** (campaign arms, engine real-time factor, wall over audio):

| | Clone takes | Long-form segments | Added weights | MLX peak, clone takes |
| --- | --- | --- | --- | --- |
| Speed | 0.476 | 0.281 | — | 3,597 MB |
| `attn` | 0.499 (×1.05) | 0.297 (×1.06) | 176 MB | 3,765 MB (+168) |
| Quality | 0.610 (×1.28) | 0.390 (×1.39) | 768 MB | 4,330 MB (+733) |

**The formal speed lane** (`scripts/pcm_identity.py`, 2026-11-14 at `9236f175`, lead only, load 1.8
to 3.1, thermal nominal): four captures in alternation, the 3.0 Speed and Quality packages
(`capture --stock --variants speed,quality`) then the installed hybrid, twice; three modes, short,
medium and long, two warm takes per cell (36 warm takes per model). Median engine real-time factor
(wall over audio): Speed 0.279, `attn` 0.303, Quality 0.412. Per cell, `attn` takes ×1.04 and ×1.06
of Speed's time (the two rounds' medians; Built-in Voice ×1.04, Voice Design ×1.05, Voice Cloning
×1.03 pooled) and ×0.72 of Quality's, as the campaign measured. Short clone takes, where a frame's
fixed cost dominates, run at Speed's pace.

**Memory on the Mac** (2026-11-14, `scripts/macos_test.sh memory`, PASS on both runs): on the M6 at
`27af0c0e` (`mac-memory-qualification-20261114-174519-39bd0268`) the MLX peak is 2,227 MB for Built-in
Voice, 2,621 MB for Voice Design and 3,765 MB for Voice Cloning's first take (3,095 MB after), with no
growth within a mode; the calibration's bounds are unchanged and now cite this run. On the emulated
8 GB floor (`QWENVOICE_SIMULATED_PHYSICAL_MEMORY_GB=8`, `…-174644-2e88d57a`, exploratory) the highest
footprint is 3,264 MB, against the floor's guarded band of 4,505 MB (55% of 8 GiB) and critical band
of 5,898 MB, and the MLX peak is 69% of its 5,461 MB Metal working set (critical at 85%): the Mac's
bands hold unchanged. A cold load takes 767 to 886 ms (Speed's record of 2026-10-20: 710 to 812 ms)
and the prewarm about 160 ms, so the idle-unload timings stand as they are.

**Known limits: `attn` beats Speed and does not match Quality.**
- **Clone likeness stays at Speed's level.** `attn` does not recover Quality's speaker-similarity
  advantage on clones (−0.026 against Quality, inside the 0.05 margin).
- **Long-form accuracy sits between the two.** The better ASR family's error rate per seed set is 0.12
  to 0.15 on Speed, 0.05 to 0.10 on `attn` and about 0.03 on Quality; the voice's spread across a
  project's windows follows (0.34 to 0.40, 0.23 to 0.25, 0.16). The rule's margin allows it. The gap
  is measured by machine screens, not heard: nobody has listened.
- **Korean long-form still refuses half its projects** (6 of 12), against Quality's 3 of 12. The
  maintainer chose on 2026-11-13 to document it and warn before such a project starts (RF-60;
  [qwen3-tts-guide.md §11.2](qwen3-tts-guide.md#112-vocellos-known-limitations)), not a richer recipe.
- **iPhone memory and performance (measured on iPhone 17 Pro; 8 GB phones still unmeasured under
  entitlement).** Wave 5 measured shipped `attn` on the canonical iPhone 17 Pro (`5cc8ed43`, §6):
  UI benchmark 29/29 PASS and retained memory 9/9 PASS with 0 MB retained growth (warm Custom
  1,969 MB, Design 1,949 MB, Clone 2,503 MB / 3,584 MB cold peak). Smaller 8 GB phones (e.g.
  iPhone 15 Pro) remain unmeasured with the entitlement (estimated ~+0.18 GB peak and up to ~+12%
  time where memory bandwidth bounds a frame).

## 5. Delivery (the maintainer's decisions are marked ★)

1. ★ **Publish three artifacts**, one per mode, under names that keep "Qwen3-TTS" (proposed:
   `<owner>/Qwen3-TTS-12Hz-1.7B-<mode>-hybrid-attn`, the build's folder names). `--publish-as <owner>`
   writes the published card (licence, both sources at their revisions, the recipe, AudioSeal's MIT
   licence); the weights are byte-identical to a development build's. The upload runs from the
   maintainer's terminal; the dot-files are local install records and stay behind:

   ```sh
   python3 scripts/build_hybrid_model.py build --recipe attn --publish-as <owner> \
     --out build/artifacts/macos/hybrid-models/attn-publish
   for mode in CustomVoice VoiceDesign Base; do
     hf upload "<owner>/Qwen3-TTS-12Hz-1.7B-$mode-hybrid-attn" \
       "build/artifacts/macos/hybrid-models/attn-publish/Qwen3-TTS-12Hz-1.7B-$mode-hybrid-attn" . \
       --repo-type model --no-private --exclude ".*" --commit-message "Vocello hybrid attn (RF-59)"
   done
   ```

   Publication gives each a 40-character Hugging Face revision (`hf models info <repo>`).

   **Published 2026-11-13** at the maintainer's request, public, each repository's 14 files equal to
   the local build (sizes and SHA-256; the small files by Git blob id):

   | Mode | Repository | Revision |
   |---|---|---|
   | Built-in Voice | `PowerBeef02/Qwen3-TTS-12Hz-1.7B-CustomVoice-hybrid-attn` | `c36e22eddb74ed1ae3c9f054b961b1173f7c093f` |
   | Voice Design | `PowerBeef02/Qwen3-TTS-12Hz-1.7B-VoiceDesign-hybrid-attn` | `6bcae41e75db1312816efae9792661a7e70ba75e` |
   | Voice Cloning | `PowerBeef02/Qwen3-TTS-12Hz-1.7B-Base-hybrid-attn` | `5af70b5c61199b060152d80f5b232d7aa1da9618` |
2. **Receipts:** each file's exact size and SHA-256 at that revision in the bundled iPhone catalog
   (`Sources/Resources/qwenvoice_ios_model_catalog.json`), which supplies the receipts of a model both
   platforms ship; `config/model-artifact-receipts.json` takes only a Mac-only artifact's. Then
   `python3 scripts/model_catalog_contract.py rebuild` and `validate --require-complete`. The speech
   tokenizer files are byte-identical to the shipped ones, so the shared-component identity holds.
3. **iPhone evidence:** a farm build whose catalog names the published artifact, through
   `scripts/farm_smoke.sh` on BrowserStack App Automate (★ the maintainer runs and pays), or the paired
   phone in an announced window. Farm results are exploratory (re-signed without
   `increased-memory-limit`, heat uncontrolled).
4. **Migration:** keep installed Speed and Quality models until the hybrid is installed and verified,
   then reclaim their space; History keeps every take's recorded variant.

## 6. One model: what specialising the backend means

§4 passed on 2026-11-12. On 2026-11-13 the maintainer confirmed it, with the Quality gap above in
view: `attn` replaces both Speed and Quality, and the selector goes (RF-59). Its scope:

- the catalog goes from six artifacts to three, with receipts and the regenerated catalog;
- the Mac and CLI `--variant quality` is accepted with a notice and resolves to the hybrid;
- memory bands in `NativeMemoryPolicyResolver` re-derived from the hybrid's measured peak, and prewarm
  and idle-unload timings re-measured;
- `config/public-product-facts.json` and the website copy;
- benchmark baselines reseeded as a new lineage; the Mac gate bench reseeded.

**Landed on 2026-11-13, after publication:**

- **The contract.** Each mode keeps one variant, `speed`, on both platforms, and its top-level
  artifact is the hybrid too, so no fallback can reach an 8-bit artifact. The id and kind stay `speed`
  because six places treat a variant's id and kind as one string, and every Speed-only gate (the
  iPhone's preferred variant, the memory-qualification pins, `check_ios_catalog.sh`) keeps holding.
  The receipts live in the bundled iPhone catalog; the production catalog holds three artifacts.
- **Retired folders.** Each model lists the Speed and Quality folders it replaced. They are removed
  through the shared component store, every mode's at once, as soon as any mode's model verifies:
  the Mac after its digest pass, the iPhone at launch, `vocello models install` after an install. No
  current model reads them, so a mode whose new model is never installed does not keep its old one
  (maintainer decision 2026-11-13). Until then the legacy cleanup leaves the 8-bit folders alone.
- **Model update for 3.0 users.** The modes an earlier build installed are recorded before any
  folder goes (`.qwenvoice-model-update.json`) and read "Update required", not "Not installed".
  The Mac starts their update on its own on an unmetered network, with a banner over every
  destination and "Update in Settings" on Studio's button; the iPhone asks once (total size,
  networks; on a nearly full phone the earlier models go first, their shared blobs pinned) and
  resumes at later launches. A failed attempt is recorded in the ledger (its class: space,
  verification, network) and waits for the user's Update or Retry; the Mac checks free space first
  and, short of it, offers to remove the earlier models before updating. Cancel, the Mac's Not Now
  and the iPhone's Later stop it until the
  user taps Update, and nothing asks again; a done note says how much space the earlier models
  freed.
- **The selector.** A mode with one model shows no Speed/Quality switch, no "Prefer lower-memory
  models" toggle, and a package row that reads Model. `--variant quality`, `models use … quality` and
  `models prefer-lower-memory` parse, warn `variant_retired` and change nothing.
- **Tooling.** Since `efe6400f` (`RF-69`), the runtime (`ModelQuantization.hybrid`) and benchmark
  tooling (`schema-v2.json`, `schema-v3.json`, `publish_benchmark_history.py`, `benchmark_history.py`)
  classify any checkpoint carrying per-layer `quantization` entries alongside top-level `quantization`
  as `"hybrid"` rather than `"4-bit"`, and quality promotion's `quality-generation` capability applies
  nowhere.

**iPhone qualification & Pack B/C outcomes (2026-11-25):** Wave 5 measured the shipped `attn` hybrid on
the canonical iPhone 17 Pro (`5cc8ed43`: UI benchmark 29/29 PASS in `f1e8631c`, retained memory 9/9
PASS with 0 MB retained growth in `c2b75046` — warm Custom 1,969 MB, Design 1,949 MB, Clone 2,503 MB /
3,584 MB cold peak; `cloneCapableMinimumProcessLimitBytes` aligned to 4,779 MiB in `1d8397f6`).
`config/public-product-facts.json`, the README and the website moved to the one model with the 3.1
Mac/CLI publication (RF-61). RF-58 (one take variation, Expressive) landed first. Pack B (`RF-68` Mac
work & `RF-69`) landed bit-identical on the Mac (14/14 PCM takes, quiet-Mac retained memory
`mac-memory-qualification-20261123-180900-4b639d73`: `0.0 MB` cross-model leak, Clone cold MLX peak
`3,749.3 MB` / `3,084.5 MB` retained). Under Pack C (`RF-70`), Experiment 1 (`long-form-korean-d1-attn`,
full-text conditioning `D1` on shipped `hybrid-attn`) was decisively `REJECT`ed on 2026-11-23 (2/3
seed sets jumped `+0.152` and `+0.324` in paired error rate from 32–44 s of skipped text), and
Experiment 2 (Bundle A `attn-io`, `+24.12 MB`) finished `INCONCLUSIVE` on 2026-11-24 (`attn` stays
incumbent: clone non-inferiority `ADOPT` with `speakerSimilarity −0.0080`, long-form error rate
regressed in all 3 seed sets with pooled 63-pair `+0.0331 [+0.0001, +0.0707]` and discordant
completions `5 vs 1` sign test `p = 0.1094`; calibrated `RF-72` blinded dual-order audit independently
favored `attn` `15–9`). On 2026-11-24 (`f070f41a`), the maintainer closed `RF-70` (along with
`RF-54` declined and `RF-57` done) without running Bundle B (`attn-io-edge`), retaining the shipped
`attn` hybrid artifacts unchanged for the 3.2 release and 3.2.0 iOS App Store submission.

## 7. Licence and attribution

The hybrid is a derivative of Qwen/Qwen3-TTS (Apache-2.0). Each one was built by
`scripts/build_hybrid_model.py` from two of Vocello's own 3.0 artifacts, with no requantization, as
its published model card says: every tensor of the 4-bit artifact, except the talker's attention
projections (`q_proj`, `k_proj`, `v_proj`, `o_proj` in its 28 layers), taken from the 8-bit one. Each
3.0 artifact is in turn mlx-community's conversion of the Qwen checkpoint at a pinned revision, with
one tensor changed (the text embedding quantized to 8 bits) and Meta's AudioSeal generator added.

| Hybrid (revision) | 4-bit parent (revision) | 8-bit parent (revision) | mlx-community bases (4-bit, 8-bit revisions) |
| --- | --- | --- | --- |
| `…-CustomVoice-hybrid-attn` (`c36e22ed`) | `PowerBeef02/…-CustomVoice-4bit` (`29c4b746`) | `…-CustomVoice-8bit` (`50c40b22`) | `f35faf19`, `41d3337e` |
| `…-VoiceDesign-hybrid-attn` (`6bcae41e`) | `…-VoiceDesign-4bit` (`62f2646e`) | `…-VoiceDesign-8bit` (`bb56faf7`) | `5c390979`, `f90d6177` |
| `…-Base-hybrid-attn` (`5af70b5c`) | `…-Base-4bit` (`47ab65f7`) | `…-Base-8bit` (`f63ea141`) | `37e955a1`, `e7dd0585` |

The marking generator inside each artifact is Meta's AudioSeal (MIT), unchanged. The attribution
manifest (`scripts/attribution_manifest.py rebuild`) follows the catalog and
`config/third-party-attribution-policy.json`, whose entry for each hybrid names this lineage at full
40-character revisions:

- `baseRepo` and `baseRevision`: the mlx-community 4-bit conversion, which supplied every tensor but
  the attention projections;
- `additionalBases`: the mlx-community 8-bit conversion, with what it contributed (the talker's
  attention projections);
- `builtFrom`: the two Vocello 3.0 artifacts the builder read.

The manifest carries the same fields for each model, and the tool refuses an entry whose base or
parent is not pinned to an exact revision, or that carries no `redistributionDecision`. Since
`b896fce1` (`RF-73`, 2026-11-25), `config/third-party-attribution-policy.json` records
`redistributionDecision: "attested-maintainer-asr04-2026-11-01"` for all three hybrids as well as
for the bundled Meta AudioSeal (`MIT`, `facebook/audioseal`) auxiliary watermark generator weights
(`auxiliaryModelWeights`, verified across all three model catalogs). Since `f269200d` (Pack A
`RB-11`, extracted into `VocelloiOSPolicies` and visually verified on iPhone 17 Pro in `6da29045`),
the iPhone's Open Source Licenses screen renders `baseRepo`/`baseRevision`, `additionalBases` (the
8-bit parent), and `builtFrom` lineage directly from the bundled manifest.
