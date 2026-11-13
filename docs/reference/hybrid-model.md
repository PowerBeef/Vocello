---
status: active
owner: backend-mlx
reviewed: 2026-11-12
summary: Vocello's hybrid (mixed-precision) Qwen3-TTS model, RF-55 — the recipe and why, how it is built from the two shipped artifacts, the identity proof, the evidence that chose it, how it would be delivered, and what one model means for the backend.
sourceOfTruth:
  - scripts/build_hybrid_model.py
  - config/quality-screens.json
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3TTSLoading.swift
  - Packages/VocelloQwen3Core/Sources/MLXAudioTTS/Models/Qwen3TTS/Qwen3StreamingMemoryTuning.swift
---

# Hybrid model (RF-55)

Vocello ships each mode (Built-in Voice, Voice Design, Voice Clone) as two MLX conversions of the
same Qwen3-TTS checkpoint: Speed, 4-bit, and Quality, 8-bit. The maintainer decided on 2026-11-12
that a custom model may ship if it beats the stock artifacts at a similar footprint, accepting up to
20% more generation time. If it is right, one model replaces the Speed/Quality selector. This guide
records the candidate the screens chose, how it is built, and what it would take to ship.

**Status (2026-11-12).** `attn` is the single-model candidate (`hybrid-single-model`): every rule it
was screened by is ADOPT, at about 5% more generation time and 176 MB more weights than Speed. It beats
Speed in every screen and does not match Quality everywhere (§4, Known limits). Left before it can
ship: the iPhone's memory and speed, and the maintainer's decisions on publication, hosting and the
selector's removal. Nothing ships from this guide.

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
- **The diagnostic key.** `QWENVOICE_MIXED_PRECISION=attn` (a diagnostics build with `QWENVOICE_DEBUG=1`)
  takes the same tensors from the installed 8-bit sibling at load, so a recipe can be screened before
  anything is built. It needs both siblings installed, so it is Mac-only.

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

The formal speed lane (`scripts/pcm_identity.py`, quiet host, lead only) is still owed: the hybrid
installed in the debug root for one capture, `capture --stock` (the 3.0 Speed packages from the
research folder) for its baseline.

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
- **The iPhone is unmeasured.** Expected on the iPhone 15 Pro: peak about Speed's 2.5 GB plus 0.18 GB,
  and up to the byte growth in time (about +12%) where memory bandwidth bounds a frame. Measure before
  publication (§5).

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
2. **Receipts:** each file's exact size and SHA-256 at that revision in
   `config/model-artifact-receipts.json` (and the iPhone catalog for the iPhone's artifacts), then
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
  resumes at later launches. Cancel, the Mac's Not Now and the iPhone's Later stop it until the
  user taps Update, and nothing asks again; a done note says how much space the earlier models
  freed.
- **The selector.** A mode with one model shows no Speed/Quality switch, no "Prefer lower-memory
  models" toggle, and a package row that reads Model. `--variant quality`, `models use … quality` and
  `models prefer-lower-memory` parse, warn `variant_retired` and change nothing.
- **Tooling.** The publisher reads a hybrid's quantization as the runtime does (4-bit, its config's
  top-level bits), and quality promotion's `quality-generation` capability applies nowhere.

**Left:** the iPhone's memory and speed, the formal speed lane, the memory bands and benchmark
baselines from those measurements, and `config/public-product-facts.json`, the README and the website
with the release that ships the change. RF-58 (one take variation, Expressive) landed first.

## 7. Licence and attribution

The hybrid is a derivative of Qwen/Qwen3-TTS (Apache-2.0), assembled from Vocello's own MLX
conversions; its model card says so and names the recipe. The marking generator inside each artifact
is Meta's AudioSeal (MIT), unchanged. The attribution manifest (`scripts/attribution_manifest.py
rebuild`) follows the catalog.
