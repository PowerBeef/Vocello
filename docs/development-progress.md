---
status: active
owner: backend-and-platform
reviewed: 2026-11-25
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Older checkpoints live in git history (`git log -p -- docs/development-progress.md`): commit
`3eeed981` holds October 26 through November 15, `20533a12` holds October 23 to 25, and
`a0597deb` every checkpoint before them.

## Resume now

### November 25 (App Store 3.2.0 readiness & AI safeguard plan locked — pause checkpoint): `RF-73` opened ahead of Phase 4 (`RF-71`); zero builds/tests run while Mac is busy

**Workspace & Git state:** Local `main` ahead of `origin/main` `8f84ac97` (**unpushed**; `8f84ac97`
CI, Release rehearsal, Nightly, and Swift dependency watch all passed), 0 linked worktrees, 0 active
builds/tests/benchmarks. Phase 3 (`RF-70`, `RF-54`, `RF-57`) is closed with shipped `attn` retained
unchanged for 3.2 (`f070f41a`).

**Locked App Store 3.2.0 readiness & granular AI safeguard decisions (2026-11-25, tracked in `RF-73`, `RF-42`, `RF-62`, `RF-63`, `ASR-11`, `BKL-31`, `BKL-91`):**

- **D1 (`RF-42`):** Admit the 13 eligible 8 GB+ M-series/A17 Pro iPads in portrait iPhone
  compatibility mode (remove the non-iPhone block in `IOSDeviceEligibilityPolicy.swift` and
  `scripts/ios_device_eligibility.py`; keep `TARGETED_DEVICE_FAMILY: "1"`).
- **D2 — Granular AI Safeguards (`A1`–`F1`, strictly sample-preserving):**
  - **Consent, onboarding & low-friction UX (`A1`–`A4`, `E1`, `P0-5`, `BKL-38`, `IOSExportGate`):**
    Fold the concise local AI + AudioSeal watermark (no personal IDs) + zero-tolerance Acceptable Use
    notice and Terms/Privacy links directly onto existing `IOSOnboardingFlow` Page 3 above `"Open
    Studio"` (**0 separate general-use modal sheets**; `RF-41` download alert stands alone); show **1**
    compact inline `A1` Voice Cloning consent sheet once before first Record, Import, Save, or
    Generate; **0 extra toggles after `A1`** (`A2` is a passive 1-line reminder caption on Save
    Voice/Import); render `IOSStudioCanvas` `setupMessage` as a **1-tap shortcut** opening Voice
    Brief (`BKL-38`), inline `A1` consent, or Voices/Record directly; add a **1-tap `"Export Now"`**
    button on `IOSExportPurchaseSheet` after purchasing from a take (`"Done"` from Settings);
    non-destructive Settings revocation caption (`A4`); Terms/Acceptable Use page on
    `vocello.vercel.app` linked from `Settings → About`.
  - **Watermarking & provenance (`B1`–`B4`):** Keep mandatory, fail-closed AudioSeal 16-bit PCM
    watermark (fixed non-identifying payload, all 3 modes) + `LIST/INFO` WAV provenance; defer C2PA
    to `BKL-41`; add localized watermark transparency note in `Settings → Privacy & Permissions` and
    `E1`; document open verification tools and external transcoding limits on website and Review Notes.
  - **In-app labeling & territories (`C1`–`C4`, `D4`):** No redundant `"AI-generated"` badges on
    Player or History UI (rely on mandatory `AudioSeal` + `LIST/INFO` WAV provenance, `E1`/`A1`
    advance notice, mode labels, and deployer disclosure reminder); update disclosure copy to
    jurisdiction-neutral wording in Settings and `A1`; keep **South Korea (`KR`)** enabled and
    exclude **China Mainland (`CN`)** (`147` of 175 territories on both app and export IAP).
  - **Guideline 1.2 & Age Rating (`D1`–`D4`, `RF-62`):** Add `Settings → About → Report an Issue`
    opening `vocello.vercel.app/support/#report` (zero auto-upload); localize and expand
    impersonation-intent patterns across all 10 languages (no celebrity-name list); keep spoken scripts
    unfiltered (explain user-authored local TTS in Review Notes); raise initial Age Rating from `4+`
    to **`13+`** before initial 3.2.0 submission and answer Nov 16 descriptors (`Shared Location = No`,
    `Dating and Relationships = No`).
  - **Privacy `5.1.2(i)` & Licensing `5.2` (`E2`–`E3`, `F1`):** Strengthen `website/public/privacy/index.html`
    and Review Notes (`RF-63`) to state explicitly that Hugging Face is a static read-only weight CDN
    with zero third-party AI APIs and refresh `3.1 → 3.2`; resolve `"pending-qualified-review"` in
    `config/third-party-attribution-policy.json`, strip macOS-only `Sparkle` from iOS Licenses, add
    Meta AudioSeal (`MIT`) under Models, keep `USES_THIRD_PARTY_CONTENT = true`; align macOS Settings
    copy in `RF-73` and park larger macOS UI consent sheets/badges in `BKL-91`.
- **D5 & D6 (Code, `2.5.19` binary hygiene, `BKL-31` purchase contrast, website/README):** Fix
  `IOSExportGate` loading flash + `IOSExportPurchaseSheet` contrast & link Dynamic Type (`BKL-31`
  slice under iOS 27 Liquid Glass); `#if`-strip 4,145+ lines of Release diagnostics runners + Release
  env-var reads (`TelemetryGate` / `RuntimeDebugGate`) and tighten `verify_ios_release_artifacts.py`;
  fix `errorBar` clipping/lock, wrong Settings paths, `.withoutCloneEncoders` override, drop
  `UIFileSharingEnabled`; clean up P2 copy/localization/error text and update website + `README.md`
  off `"TestFlight public beta"` / `"Price: Free"`.

**Resume next session once the Mac is quiet:**

1. **Land `RF-73` (`D1` + `A1`–`F1` + `D5` + `D6`)** in clean, `vocello-swift-review`-verified,
   sample-preserving commits on `main`, verified with `scripts/dev.sh check`, `scripts/dev.sh ios --ui`,
   and the website Playwright check.
2. **Run Phase 4 (`RF-71` — Mac/CLI 3.2.0):**
   - Quiet-Mac `benchmarks/baselines/mac-gate-bench.json` reseed (`>= 3` consecutive clean runs with
     `QWENVOICE_GATE_BENCH_SEED=1 scripts/macos_test.sh gate`, `QVOICE_LEAD_ONLY=1`) for the 3.2.0
     `"hybrid"` lineage.
   - Bump `project.yml` (`3.2.0` / build `34`), `config/third-party-attribution-policy.json`,
     `config/public-product-facts.json`, regenerate project/attributions, author
     `docs/releases/v3.2.0.md`, push `main` on maintainer go → green CI → signed `v3.2.0` tag &
     7-lane Mac promotion sitting.
3. **Run Phase 5 (`v3.2.0-ios.1` → `RF-16`):** Cut `v3.2.0-ios.1` → grouped iPhone window
   (`RF-68`/`RF-15`/`RF-17` + `RF-72` 30-take audit + 6.3-inch screenshots + `RF-66` demo video) →
   AWS Device Farm iPhone 15 Pro (`RF-65`) → authorized ASC updates (`3.2.0`, `13+`, `147`
   territories, Nov 16 descriptors, IAP attach, `RF-63` Review Notes) → `ASR-09` 24h proof → `RF-16`
   submission ahead of the Dec 20–26 holiday backlog (coordinating `RF-02` Paid Apps Active 24h+ prior).

### November 25 (Phase 3 complete — pause checkpoint): `RF-70`, `RF-54`, and `RF-57` closed; shipped `attn` retained for 3.2; resume at Phase 4 (`RF-71` Mac/CLI 3.2.0) when Mac is quiet

**Workspace & Git state:** Clean local `main` (3 commits ahead of `origin/main` `8f84ac97`,
**unpushed**; `8f84ac97` CI, Release rehearsal, Nightly, and Swift dependency watch all passed),
0 linked worktrees, 0 active subagents or background tasks. Paused before Phase 4's quiet-Mac
gate-bench reseed because the Mac was busy.

**Phase 3 closures completed (`1b228307` + this commit):**

- **Maintainer decision (2026-11-25):** Keep shipped `attn` unchanged for 3.2 and skip Experiment 3
  (Bundle B `attn-io-edge`, `+99.61 MB`), avoiding a 2.2 GB/mode user redownload and preserving
  iPhone 17 Pro cold-Clone memory headroom after Exp 1 (`D1` `REJECT`, `8f84ac97`) and Exp 2 (Bundle A
  `attn-io` `INCONCLUSIVE`, pooled 63-pair long-form error rate `+0.0331 [+0.0001, +0.0707]`,
  calibrated `RF-72` blinded dual-order audit `15–9` for `attn`, `1b228307`).
- **Closed `RF-70` (`done`):** Pack C screening completed under pre-registered `RF-57` rules with
  incumbent `attn` retained for 3.2 (`4a42d25d`, `8f84ac97`, `1b228307`).
- **Closed `RF-54` (`declined`):** Decoder 72-frame attention window (`QWENVOICE_DECODER_WINDOW=on`,
  `c4bfee76`) screened `INCONCLUSIVE` under `decoder-window-72`; unwindowed default retained per D5.
- **Closed `RF-57` (`done`):** Recorded the observed long-form QC v2 caveat in
  `docs/reference/qc.md` (phone model stops at 120 s, Whisper fixes language from first 30 s, seam
  pauses read as dropouts).

**Resume next session directly at Phase 4 (`RF-71` — Mac/CLI 3.2.0 & iOS 3.2.0 prep):**

1. **Step 4.1 — Quiet-Mac gate-bench baseline reseed (`benchmarks/baselines/mac-gate-bench.json`):**
   Currently still carries legacy `"quantization": "4-bit"` from 3.1 (`mac-gate-bench-20261114-*`).
   Once the Mac is quiet (`QVOICE_LEAD_ONLY=1`, 0 workers), run `QWENVOICE_GATE_BENCH_SEED=1
   scripts/macos_test.sh gate` for **>= 3 consecutive clean runs** on one clean commit to reseed for
   the 3.2.0 `"hybrid"` lineage (`RF-71: Reseed Mac gate-bench baseline for 3.2.0 lineage`).
2. **Step 4.2 — 3.2.0 version bump & release prep (can run even before/alongside Step 4.1):**
   - Bump `project.yml` (`MARKETING_VERSION: "3.2.0"`, `CURRENT_PROJECT_VERSION: "34"` — above
     TestFlight `v3.1.0-ios.3` build `33`) and `config/third-party-attribution-policy.json` (`"3.2.0"`),
     add `candidateRelease` (`3.2.0`, `v3.2.0`, `unpublished`) in `config/public-product-facts.json`,
     update `config/cli-contract/v1/examples/*.json` if validated against version, and run
     `./scripts/regenerate_project.sh --fast`, `scripts/attribution_manifest.py rebuild`, `scripts/dev.sh regen`.
   - Author `docs/releases/v3.2.0.md` (`check_release_notes.py v3.2.0` PASS), reconcile
     `docs/reference/app-store-listing.md` (`RF-63`, byte counts stay unchanged since `attn` stays
     shipped), check `RF-44`/`RF-52` Mac tails, and verify `scripts/dev.sh check` + `scripts/dev.sh ios --ui`.
3. **Steps 4.3–4.4 & Phase 5:** Push `main` on maintainer go → green Push CI → Mac UI smoke & release
   rehearsal → signed `v3.2.0` tag & 7-lane Mac promotion sitting (`RF-71`) → `v3.2.0-ios.1`
   TestFlight candidate → grouped iPhone window (`RF-68`/`RF-15`/`RF-17` + `RF-72` 30-take audit) →
   AWS Device Farm iPhone 15 Pro (`RF-65` Option A) → `ASR-09` → `RF-16` App Review submission.

### November 24 (Exp 2 verdict checkpoint): Pack C Exp 2 (Bundle A `attn-io`) `INCONCLUSIVE` — `attn` stays incumbent; awaiting maintainer call on Exp 3 (Bundle B `attn-io-edge`) vs keeping `attn` for 3.2

**Workspace & Git state:** Clean local `main` (2 commits ahead of `origin/main` `8f84ac97`,
**unpushed**; `8f84ac97` CI, Release rehearsal, Nightly, and Swift dependency watch all passed),
0 linked worktrees, 0 active subagents or background tasks. `build/vocello` (SHA-256
`25c6e733f7f38f15…`) and all six 3.0 4-bit/8-bit research artifacts remain in place.

**Completed Pack C Step 3.3 — Experiment 2 (Bundle A `attn-io`, `+24.12 MB`, `--stock`): DO NOT ADOPT (`attn` stays incumbent)**

- **Clone screen (`hybrid-attn-io-clone`, `pack-c-exp2-clone-seeds{16,17}`): `ADOPT` on
  non-inferiority, zero clone improvement.**
  - Fresh noise floor (`seeds16 attn` vs `seeds17 attn`, 190 paired): `speakerSimilarity −0.0057
    [−0.0119, +0.0008]`, `errorRateBetterFamily +0.0007 [−0.0078, +0.0102]`, `trailingSilenceMS
    −0.2 ms [−13.3, +12.8]` (all well inside `0.71` of margins).
  - `attn` (`190/192`) vs `attn-io` (`191/192`), 189 paired, 0 identical PCM: `speakerSimilarity
    −0.0080 [−0.0185, +0.0009]` (`0.7199 → 0.7119`), `errorRateBetterFamily +0.0007 [−0.0065,
    +0.0081]` (`0.0211 → 0.0219`), `trailingSilenceMS +2.1 ms [−9.9, +13.4]`, gross failures `3 vs 2`.
- **Long-form screen (`hybrid-attn-io`, all 6 strata Expressive, `pack-c-exp2-longform-seeds{19,20,21}`):
  `INCONCLUSIVE` (harmful direction across all 3 seed sets).**
  - Fresh noise floor (`seeds19 attn` vs `seeds20 attn`, 20 paired): `errorRateBetterFamily +0.0008
    [−0.0372, +0.0331]`, `speakerWindowSpread −0.0143 [−0.0730, +0.0497]`.
  - Completions: `attn` `64/72` (`8` refused) vs `attn-io` `68/72` (`4` refused: Korean `5/12 → 10/12`,
    Design English `12/12 → 11/12`; discordant `5 vs 1`, one-sided sign test `p = 0.1094` > `0.05`).
  - Paired `errorRateBetterFamily` regressed in **3 of 3** seed sets (`seeds19: +0.0082 [−0.0244,
    +0.0417]`; `seeds20: +0.0481 [+0.0090, +0.0956]`; `seeds21: +0.0429 [−0.0449, +0.1362]`; **pooled
    63 pairs: `0.0813 → 0.1144`, `+0.0331 [+0.0001, +0.0707]`**, CI excluding zero on the harmful side).
  - `segmentsWarned` rose in **3 of 3** seed sets (`+0.095`, `+0.286`, `+0.143`), and
    `speakerWindowSpread` reached past `+0.05` in 2 of 3 (`+0.0155 [−0.0285, +0.0593]` pooled).
  - `hybrid-attn-io-single` and `vocello bench` skipped because neither clone nor long-form cleared.
- **Calibrated `RF-72` blinded dual-order `AB`/`BA` pairwise audit (report-only, 36 pairs / 72 tasks):**
  - Independently favored incumbent **`attn` `15` wins vs `attn-io` `9` wins**:
    - Clone (`pack-c-exp2-clone-mm`, 24 pairs): **`attn` `9` vs `attn-io` `4`** (`7` ties, `4` order-inconsistent / `16.7%` flip).
    - Long-form (`pack-c-exp2-longform-mm`, 12 `seeds20` pairs): **`attn` `6` vs `attn-io` `5`** (`0` ties, `1` order-inconsistent / `8.3%` flip; caught severe hallucinated coughing/gibberish in `attn-io` across both orders).

**Next decision point (awaiting maintainer call):**

1. **Option A (Recommended):** Keep shipped `attn` unchanged for 3.2 (skip Exp 3 Bundle B `attn-io-edge`, which contains the same `io` layers that regressed Exp 2 and adds `+99.61 MB` right at the iPhone `3,662 MiB` cold Clone ceiling, avoiding a 2.2 GB user model redownload), close `RF-70`, `RF-54`, and `RF-57` cleanly per D5, and proceed directly to **Phase 4 (`RF-71` Mac/CLI 3.2.0)** and **Phase 5 (iOS 3.2.0 `v3.2.0-ios.1`)**.
2. **Option B:** Run **Experiment 3 — Bundle B (`attn-io-edge`, `+99.61 MB` vs `attn`, `--stock`, ~3.5–4.5 hr on Mac)** on fresh `clone` seed sets `18`/`19` and `long-form` seed sets `22–24` to test whether 8-bit edge-layer MLPs (`0, 1, 26, 27`) overcome the `io` mismatch and beat `attn`.

### November 23 (pause checkpoint): `RF-72` closed; Pack B (`RF-69` closed, `RF-68` Mac done); Pack C (`RF-70`) Step 3.1 landed & Exp 1 Korean `D1` `REJECT` — resume at Exp 2 (Bundle A `attn-io`)

**Workspace & Git state:** Clean local `main` (24 commits ahead of `origin/main` `67ebb3f7`, **unpushed —
awaiting explicit push authorization**), 0 linked worktrees, 0 active subagents or background tasks.
Optimized CLI `build/vocello` is built at `4a42d25d` (SHA-256 `25c6e733f7f38f15…`, includes `attn-io`
and `attn-io-edge`), and all 6 3.0 4-bit/8-bit research artifacts (`Base`, `CustomVoice`, `VoiceDesign`)
are installed in `~/Library/Application Support/QwenVoice-Research/models`.

**Completed today (`611388ac..4a42d25d` + this pause checkpoint):**

- **Phase 1 — `RF-72` (closed `done`, `611388ac..26bbfeec`):** Landed the offline, report-only
  Gemini 4 Neon multimodal audio QC complement (`scripts/qc/multimodal.py`, `scripts/qc.py multimodal`,
  `config/qc/multimodal-rubric-v1.json`, `vocello-audio-qc` skill, Antigravity `run_workflow` emitter)
  strictly outside QC v2 `SCORING_SOURCES` and Fast QC, blocking personal audio by default. Recorded
  `benchmarks/qc/multimodal-eval-v1.json`: `diction`, `delivery`, and `pairwise` are `active_advisory`
  (Q2 strict `unusable` precision `8/9 = 88.9%` vs `31%` QC v2 baseline, broad recall `11/11 = 100%`,
  clean human FA `1/30 = 3.3%`, C1 tie `12/12`, C2 win `8/8`, swap flip `1/16 = 6.25%`); static `clone`
  speaker verification remains fail-closed at `abstain_uncalibrated` (`75.0%` C4 balanced accuracy).
- **Phase 2 — Pack B (`RF-69` closed `done`; `RF-68` Mac work complete, `needs: iphone` only,
  `695717be..f54479b5`, every substantive Swift commit `Reviewed-by: vocello-swift-review`):**
  - **`RF-68` (engine/package, `574d58d8..9d572dfb`):** single `evalForReadback` error check,
    fail-closed quantization parse + `[.noUnusedKeys, .shapeMismatch]` + fused-projection summary,
    `A-08` per-encode Mimi encoder KV cache, `A-27` rectangular `[seqLen, totalLen]` decoder causal
    mask, hoisted/prewarmed `CodePredictorCompiledPlan` with lazy per-pass KV buffers and deduplicated
    cache clears, telemetry-gated `captureIntrospection` (keeping chunk timings on), package hygiene,
    narrow `A3` fixed-shape 3 KiB GPU `seenMask` with prewarm warmup (`3852e8c7`; `H2` AudioSeal
    weight caching and full speculative `A3` deferred per D2), and `compile(inputs: [weightInputs])`
    (`87d6a4b0`) eliminating a `180.2 MiB/switch` cross-thread `mlx-swift 0.32.3` `CompileCache` leak
    caught by Mac memory qualification.
  - **`RF-69` (runtime, lease, QC & delivery, `052f7fb9..efe6400f`):** closed all 6 Mac/CLI
    `EngineHostLease` / `MacEngineHostCoordinator` races, wired `unloadEpoch`, `.starting` on cold
    load, `stop()`/`B-05` `forMemoryRelief` unloads, skipped redundant post-watermark Fast QC in
    `IOSLongFormProjectRunner`, classified Carbon `-34`, wired explicit Korean long-form warnings
    across CLI/Mac/iOS, hardened outbox writes with `fsync`+`rename(2)`, landed spine `C-04`/`C-05`
    (Fast QC kept at `v10` per D1), added `.hybrid` telemetry quantization tier across
    Swift/`schema-v2`/`schema-v3`/`benchmark_history`, updated `backend-risk-spine.json` (20
    implemented), and hardened `HuggingFaceDownloader`, `SharedModelComponentStore`, and iOS versioned
    staging (`E-03`/`ER-10`).
  - **Verification:** `scripts/macos_test.sh test` PASS (`mac-test-20261123-130512`), `scripts/dev.sh ios`
    PASS, `scripts/build.sh cli` PASS, contracts & lints (`swiftlint`, `ruff`, `pyright`) 0 new findings,
    `scripts/pcm_identity.py compare` **14/14 bit-identical PCM takes** (`pre-pack-b-20261123-081930` vs
    `post-pack-b-final-20261123-181128`: host CPU `-3.56%`, `custom/short` `-2.74%` RTF / `-9.0 ms`
    first chunk, `custom/medium` `-2.33%` RTF / `-9.0 ms` first chunk), and quiet-Mac retained-memory
    qualification PASS (`mac-memory-qualification-20261123-180900-4b639d73`: `0.0 MB` cross-model
    retention, Clone cold MLX peak `-16.0 MB` to `3,749.3 MB` / `physFoot` `-373.7 MB` to `3,452.3 MB`,
    Clone retained MLX peak `-10.5 MB` to `3,084.5 MB`, warm RTF `0.28 / 0.28 / 0.30`).
- **Phase 3 — Pack C (`RF-70`) Steps 3.1 & 3.2:**
  - **Step 3.1 (`4a42d25d`, `Reviewed-by: vocello-swift-review`):** Pre-registered all 7 fresh-seed
    (`>= 16`) rules in `config/quality-screens.json`, added `.attnIO` (`"attn-io"`, 131 modules,
    `+24.12 MB` over `attn`) & `.attnIOEdge` (`"attn-io-edge"`, 143 modules, `+99.61 MB` over `attn`)
    with `validateMixedPrecisionTarget` rejecting already-hybrid targets, and fixed
    `scripts/build_hybrid_model.py` `.bias` parity & `codec_head` indexing (`53/53` Python tests PASS,
    `macos_test.sh test` PASS `mac-test-20261123-133330`).
  - **Step 3.2 — Experiment 1 (`long-form-korean-d1-attn`, shipped `hybrid-attn` Expressive, Korean
    stratum, seed sets `16–18`): DECISIVE `REJECT`** (recorded in `config/quality-screens.json`,
    retained under `build/artifacts/macos/quality-screens/pack-c-exp1-korean-d1-seeds{16,17,18}/`).
    Self-test noise floor (`seeds16 off` vs `seeds17 off`): `NOISE-FLOOR` (`2/4` vs `2/4`, `paired: 1`,
    `errorRateBetterFamily -0.0152`). `off` reproduced the defect (`5/12` generated, `7/12` refused);
    `on` (`QWENVOICE_FULL_TEXT_CONDITIONING=on`) cut refusals to `3/12` only by skipping/truncating
    `31.9–43.8 s` of Korean speech per paired project, spiking paired `errorRateBetterFamily` past
    `+0.04` on 2 of 3 seed sets (`seeds16`: `4.18% -> 19.39%` / `+0.1521` `REJECT`; `seeds17`:
    `2.66% -> 3.04%` / `+0.0038` `ADOPT`; `seeds18`: `3.83% -> 36.21%` / `+0.3238` `REJECT`, both
    Qwen3-ASR and Whisper agreeing). Korean long-form drops `D1` and keeps trailing text.
- **Documentation & instructions synced (2026-11-23):** Reconciled `AGENTS.md`, `hybrid-model.md`,
  `mlx-guide.md`, `mimi-codec-guide.md`, `tooling-and-evidence.md`, `development-workflow.md`,
  `testing-runbook.md`, `qwen3-tts-guide.md`, `release-first-execution-2026-09.md`, `quality-screens.json`,
  and `roadmap.json` / `ROADMAP.md`.

**Resume next session directly here (Pack C Step 3.3 — Experiment 2: Bundle A `attn-io`, `+24.12 MB`, `--stock`):**

1. Confirm zero active workers (`manage_subagents list`, `swarm status`) and set `QVOICE_LEAD_ONLY=1`
   on a quiet Mac. Reuse `build/vocello` (already built at `4a42d25d`, SHA `25c6e733f7f38f15…`).
2. **Experiment 2 — Bundle A (`attn-io` vs `attn`, `--stock` against 3.0 4-bit/8-bit research artifacts):**
   - **Clone screen (`hybrid-attn-io-clone`, seed set `16` + self-test noise floor `16 vs 17`):**
     `quality_screen.py plan clone --seed-set 16` (and `17` for `attn` noise floor), `run --stock --env QWENVOICE_MIXED_PRECISION=attn` vs `attn-io`, `score`, `compare --expect noise --b-run` then `compare --rule hybrid-attn-io-clone --floor`.
   - **Long-form screen (`hybrid-attn-io`, all 6 strata Expressive, seed sets `19–21` + self-test noise floor `19 vs 20`):**
     `quality_screen.py plan long-form --seed-set 19|20|21` (Expressive), `run --stock --env QWENVOICE_MIXED_PRECISION=attn` vs `attn-io`, `score`, `compare --expect noise --b-run`, then `compare --rule hybrid-attn-io`.
   - **Single screen (`hybrid-attn-io-single`, seed set `16` + noise floor `16 vs 17`):** run when
     long-form or clone clears.
   - **Speed check (`vocello bench`):** confirm median warm RTF `<= 1.05× attn`.
   - **Calibrated `RF-72` advisory audit:** blinded dual-order `AB`/`BA` pairwise audit (`scripts/qc.py multimodal`) on a sample of paired generated takes.
3. **Experiment 3 — Bundle B (`attn-io-edge`, `+99.61 MB`, `--stock`, seed sets `22–24` long-form, `18`/`19` clone/single):**
   compare against Experiment 2's winner (`hybrid-attn-io-edge`, `hybrid-attn-io-edge-clone`, `hybrid-attn-io-edge-single`, warm RTF `<= 1.08× attn`, plus iPhone `< 3,662 MiB` cold Clone memory gate per D3 if winning on Mac).
4. **Steps 3.5–3.6:** If Bundle A or B wins, build & verify bit-identity (`scripts/build_hybrid_model.py`),
   coordinate maintainer Hugging Face upload, wire receipts/catalog/attribution; close `RF-70`, `RF-54`,
   and `RF-57` per D5.
5. **Phase 4 (`RF-71` Mac/CLI 3.2.0) & Phase 5 (iOS 3.2.0 `v3.2.0-ios.1`, grouped iPhone window covering
   `RF-68`/`RF-15`/`RF-17`, AWS Device Farm `RF-65` Option A, and `RF-16`)** — coordinating with the
   maintainer at all push, tag, HF upload, UI window, and ASC boundaries.

### November 21, late night: `c0750fe7` pushed & native CI green; CI lint/test fix landed; roadmap retargeted to 3.2.0 (`RF-68`..`RF-71`)

Local `main` (`4f273cb4..c0750fe7`) was pushed to `origin/main` at the maintainer's request, both
triggered workflows completed, the small lint/test regressions were fixed locally (`65436f01`), and
the roadmap was updated per the maintainer's 2026-11-21 decision.

- **Push CI & Release Rehearsal on `c0750fe7`:**
  - **All native Xcode jobs PASSED on GA `xcode-27`:** `macOS deterministic tests` (12m09s, incl.
    Main Thread Checker, CLI identity, macOS XCUITest compile), `iOS compile check (device SDK)`
    (11m39s, incl. `VocelloiOS`, policy tests, and all 3 iOS XCUITest bundles), `macOS ThreadSanitizer
    subset` (10m04s), and `Rehearse iOS archive prerequisites` (2m55s).
  - **Fixed locally in `65436f01` (`DW-04`):** cleared 5 unused imports flagged by pinned `ruff 0.17.1`
    (`check_ios_ui_benchmark.py`, `check_ios_ui_perf.py`, `check_macos_ui_perf.py`) and updated
    `test_ios_ui_preflight.py` (signing-identity stub + `ROOT_DIR`/`lane`/`no_publish`) and
    `test_required_step_ledger.py` (`ui-build` in `ui-ios-control-audit` `optionalSteps`), which were
    the sole failures in `Repository contracts`, `Python tests (linux)` (3/2,749), and `Rehearse macOS
    package` (3/3,161). Verified locally with `ruff` (0 findings PASS) and routed `scripts/dev.sh check`
    (108/108 passed).
- **2026-11-21 Roadmap Decision (`config/roadmap.json`, `docs/ROADMAP.md`, `AGENTS.md`, `release-first-execution-2026-09.md`):**
  - **No more 3.1 TestFlight builds** and no iOS 3.1 release (Mac & CLI 3.1.0 shipped Nov 17 under
    `RF-61`; internal 3.1.0 builds 31–33 are historical/superseded).
  - **3.2.0 is the new target for the iOS App Store submission** (`v3.2.0-ios.N` candidates).
  - **Pack B & Pack C pulled ahead of 3.2:**
    - `RF-68`: Engine Pack B (part 1) — sample-preserving MLX/Metal safety, memory (`A-08`, `A-27`) &
      hot-loop performance.
    - `RF-69`: Engine Pack B (part 2) — sample-preserving runtime, Mac/CLI `EngineHostLease`, Fast QC
      & delivery hardening.
    - `RF-70` (blocked by `RF-68`): Engine Pack C — `RF-57`-screened quality upgrades (zero-weight
      Korean `D1`, Bundle A `+24.12 MB`, Bundle B `+99.62 MB`).
    - `RF-71` (blocked by `RF-68`, `RF-69`, `RF-70`): Ship Vocello and the `vocello` CLI 3.2 on the Mac.
  - `RF-12`, `RF-15`, `RF-16`, `RF-17`, `RF-62`, `RF-63` retargeted to `3.2.0` (`RF-12`, `RF-16`,
    `RF-17` blocked by `RF-68`, `RF-69`, `RF-70`); `RF-35`, `RF-41`, `RF-42` moved back to `planned`
    behind `RF-12` (0 staleness warnings; all 3 focus-lock `in-flight` slots free for `RF-68`..`RF-70`).
- **Docs, instructions & `AGENTS.md` reconciled (2026-11-21):** synced `AGENTS.md`, `ARCHITECTURE.md`,
  `native-engineering.md`, `tooling-and-evidence.md`, `development-workflow.md`, `ios-device-testing.md`,
  `telemetry-and-benchmarking.md`, `hybrid-model.md`, `ios-appstore-submission.md`,
  `app-store-listing.md`, and `.agents/plugins/vocello/skills/*` with the 15-target / 8-scheme project
  (`VocelloiOSPolicies`, warnings-as-errors on `VocelloiOSUITests` & `VocelloiOSCandidateUITests`),
  Wave 5 calibrated iOS `ui-perf` enforcement (12 scenarios, 7 enforced), wired-USB `xctrace` Metal/CPU/witness
  profiling, `RB-11` hybrid attribution rendering, and the 3.2.0 iOS submission target.
- **Next (next session):**
  1. Confirm push CI & Release rehearsal green on the pushed 2026-11-21 tip.
  2. Begin **Pack B** (`RF-68` & `RF-69`, sample-preserving, Mac-driven) in parallel or sequence,
     then run **Pack C** (`RF-70`, `RF-57`-screened Korean `D1`, Bundle A, Bundle B) before bumping to
     `3.2.0` for Mac/CLI (`RF-71`) and cutting `v3.2.0-ios.1` (`RF-12`).

### November 21, night: Wave 5 physical-iPhone 3.1.0 calibration & qualification complete (`c0750fe7`, pushed)

Physical-iPhone **Wave 5** completed on the paired iPhone 17 Pro (iOS 27.2.1, Xcode 27.2, wired USB
+ clean checkpoints) and was pushed to `origin/main` at `c0750fe7`.

- **Wave 5 On-Device Evidence & Calibrations:**
  - **`ios benchmark` (3.1 hybrid, 29/29 PASS, 0 refusals):**
    `ios-xcui-benchmark-20261121-180730-f1e8631c` (`5cc8ed43`; 10 Custom + 10 Design + 9 Clone
    with `A_warm_elderly_woman`; 4 named screenshots verified clean).
  - **`ios_device.sh memory` (3.1 hybrid, 9/9 PASS, 0 MB retained growth) + calibration:**
    `ios-memory-qualification-20261121-182637-c2b75046` (`5cc8ed43`) calibrated
    `config/memory-qualification-policy.json` (`retainedMemoryV2.calibration.ios`
    `growthLimitMB = 16.0`, `floorTiers` `floorMS = 500.0`). Warm `physFoot`: Custom `1969 MB`,
    Design `1949 MB`, Clone `2503 MB` (cold peak `3584 MB`, `2560 MB` headroom remaining —
    confirms Pack A `RB-05` `4.5 GiB` Clone gate).
  - **Wired-USB `xctrace` profiling baselines + `axiom_xcprof_analyze` validation:**
    - `metal` (`ios-metal-profile-20261122-004303-62fc2244`, `1a10801d`): `23.3 tok/s` warm,
      `1952 MB physFoot`, 142,990 captured Metal/signpost/Time Profiler rows (fixed
      `benchmarks/schema-v3.json` `profileKind` enum + `scripts/benchmark_history.py` embedded
      `time-profile` acceptance + unit test).
    - `cpu --keep-trace` (`ios-cpu-profile-20261122-010506-af2fc0e1`, `9fcfb630`): `24.4 tok/s`
      warm (`1.95×RT`), `1987 MB physFoot`, validated end-to-end with `axiom_xcprof_analyze` +
      preserved iOS dSYM (`17,997` symbolicated CPU samples; noted non-shipped
      `IOSPullableDiagnosticsMirror.syncGenerationTelemetry` at ~75% of diagnostics-runner CPU).
    - `witness` (`ios-witness-profile-20261122-010852-a0085eed`, `43371913`): `25.7 tok/s` warm
      (`2.06×RT`), `377 ms` first chunk, `1975 MB physFoot`.
    - `memory` (`ios-memory-profile-20261122-010716-e232a884` & `011044-6468584f`): captured
      Allocations + VM Tracker `.trace` cleanly over USB; publication tripped the newly tightened
      uninstrumented `500 ms` `floorTiers` unobserved-gap bound (`669.4 ms` / `789.9 ms` under
      malloc-stack instrumentation during cold load; traces retained, policy kept strict).
  - **3× counted snapshot-free `ios perf` + `AV-14` closed (`bc350530`):**
    `ios-xcui-perf-20261121-200255-00f49267`, `ios-xcui-perf-20261122-012923-b890c982`, and
    `ios-xcui-perf-20261122-014227-2dc60e89` all passed 12/12 with 100% probe coverage; derived
    `spread-v1` ceilings and enabled confirmatory enforcement in `config/ui-perf-thresholds-ios.json`,
    closing `AV-14` (`18/18` `test_check_ios_ui_perf.py` PASS).
  - **Pack A model delivery & RF-59 upgrade proofs live on device:**
    - `ios model-download --scenario queue` (`ios-xcui-model-download-20261121-201559-ff88637e`):
      **PASS (108.8s)** — `RB-06`, `RB-08`, `RB-10`, `RB-12` (prepare cancel + `Queued` relaunch
      restoration; screenshots reviewed clean).
    - `ios model-download --scenario upgrade` (`ios-xcui-model-download-20261122-012545-cdcd6211`):
      **PASS (91.5s)** — normal Update prompt + `Later` relaunch persistence + low-space Make Room
      prompt + active transfer (`10.9 MB/s`) + clean cancel (fixed `rootTab_studio` relaunch wait
      at `8eb44950`; screenshots reviewed clean).
  - **Full `ios smoke` (`ios-xcui-smoke-20261122-030658-6da29045`): 4/4 PASS (15 min):**
    `testPhysicalDeviceSmokeJourney` (518.8s, including critical memory-pressure recovery and
    visually verified `RB-11` hybrid `Additional base` / `Built from` attribution in
    `010-ios-settings-model-attribution-pro_custom-speed.png`), `testRecordThenPlayReviewsTheClip`
    (34.0s), `testStudioModesKeepTheirDockLayout` (46.3s), `testZLongFormProjectJourney` (290.7s,
    2:17 project complete).
  - **Headless `lang-bench --subset full` (`ios-lang-bench-20261122-011722-250a84c4`):**
    **23/23 `spoken_content=PASS`**, `hint_gate=PASS`, `diagnostics_fail=0` across all 10
    languages on both `qwen3-asr` and `whisper` (nearly all `0.000` WER/CER); on-device Apple
    Speech `output_gate` passed all 12 installed locales (`en-CA`, `fr-CA`, `de-DE`, `zh-CN`) and
    flagged only the 6 locales without iOS dictation packs installed (`es`, `ja`, `ru`, `pt`, `it`,
    `ko`).
  - **`ios localization` (`ios-xcui-localization-20261122-021927-fcb2d313`) + harness fixes:**
    Passed all 10 languages, Default, French-Default, AX-L (incl. Voice Models), and AX-XXXL
    Audio/About; fixed the final AX-XXXL `VocelloUISettingsReveal` short-drag stall and cached
    per-step staticText frames (`31a71e40`, `12a76ed3`, `2ecf5ceb`, `9b68d928`). An optional full
    `ios localization` re-run can confirm AX-XXXL Voice Models green in the next window.
- **Outcome:** Pushed at `c0750fe7` (see entry above); superseded for TestFlight by the 2026-11-21
  decision targeting `3.2.0`.

### November 21: iOS dev/test/bench overhaul (Waves 1–4) & Pack A release blockers (`RB-01`..`RB-12`) landed locally

Six commits landed on local `main` ahead of `origin/main` (`4f273cb4`; **not yet pushed**), bringing
iOS development, profiling, UI-perf testing, and policy modularization to parity with macOS and
resolving all twelve sample-preserving Pack A Release Blockers (`RB-01`..`RB-12`) ahead of the
physical-iPhone 3.1.0 calibration and qualification window (**Wave 5**). Packs B/C remain deferred
post-3.1 behind `RF-57`.

- **iOS Dev/Test/Bench Overhaul — Waves 1–4 (`c43f825f`, `4783d725`, `553d4e4a`, `deca64ee`,
  `DW-03`/`DW-04`/`RF-59`, Waves 2–4 `Reviewed-by: vocello-swift-review`):**
  - **Wave 1 (`c43f825f`):** aligned owned-only `-Onone` dev vs `-O` measured iOS build lanes,
    enabled `SWIFT_TREAT_WARNINGS_AS_ERRORS: YES` on `VocelloiOSUITests` and
    `VocelloiOSCandidateUITests`, and hardened CI parity.
  - **Wave 2 (`4783d725`):** brought iOS profiling, `Metal System Trace` (`os_signpost`), app-layer
    memory sampling, and benchmark history contracts to macOS parity.
  - **Wave 3 (`553d4e4a`):** overhauled `VocelloiOSPerfUITests` to snapshot-free parity, wired
    `ui_test.sh` hitch/stall gates and visual QA, and aligned iOS `ui-perf` lineage contracts.
  - **Wave 4 (`deca64ee`):** extracted static framework `VocelloiOSPolicies` (linked only by
    `VocelloiOS` and iOS/core test bundles, zero link on macOS/CLI), added hermetic RF-59 upgrade
    and attribution XCUITests, burned iOS Python pyright findings to 0, and upgraded `scripts/dev.sh`
    iOS ergonomics.
- **Engine & Hybrid Delivery Pack A — Commit A1 (`1d8397f6`, `RF-35`/`RF-59`,
  `Reviewed-by: vocello-swift-review`):** resolved `RB-01`..`RB-05` — MLX async readback safety,
  deterministic `prewarmSlot` waiting (`prewarm_slot_wait_ms`), `MLXModelLoadCoordinator` load-state
  consistency, `BG-01` background-transition generation guard + `inFlightPreparationDepth`, and
  `IOSMemoryBudgetPolicy.minimumCloneCapableProcessLimitBytes()` (`4,779 MiB`).
- **Engine & Hybrid Delivery Pack A — Commit A2 (`f269200d`, `RF-59`,
  `Reviewed-by: vocello-swift-review`):** resolved `RB-06`..`RB-12` + `runQueueScenario` assertions —
  - `RB-06`: relaunch `.queued` snapshot publication, synchronous coordinator state checks, and
    `IOSModelDownloadLedger.isCurrentArtifactFailed(modelID:artifactVersion:)` so 3.0 → 3.1
    superseded ledger entries never suppress the RF-59 Update prompt.
  - `RB-07`: `SharedStorageBackgroundActivity` (`ProcessInfo.performExpiringActivity`),
    `StorageBackgroundExpirationFlag` propagation across every `IOSBackgroundTime.hold` App Group
    `flock(LOCK_EX)` site, dedicated non-cancellation `backgroundAssertionUnavailable`, and
    expiration checks before post-tombstone reclamation.
  - `RB-08`: pure `IOSBackgroundSessionCompletionCoordinator` in `VocelloiOSPolicies` plus
    exact-once `logicalRequestID`-scoped `HuggingFaceDownloader` background task submission
    flushing (closing Race A wake-before-restore, Race B `beginDownload`→`runDownload`/Model 1→2
    handoffs, dead-task retries, and >6-file rollovers).
  - `RB-09`: immediate unreferenced shared-blob reclamation on `releaseUpdatePins` (off-actor on
    macOS, serialized via `pinReleaseTask` on iOS) + 24 h abandoned-pin fallback sweep.
  - `RB-10`: `.preparing`/`.starting` cancellation targets, `admissionSettlementWaiters` teardown
    sync before deletion, and pre-existing ledger tombstoning before discarding staging.
  - `RB-11`: extracted `IOSAttributionManifest` into `VocelloiOSPolicies` and rendered hybrid
    `additionalBases` and `builtFrom` provenance in `OpenSourceLicensesScreen`.
  - `RB-12`: subtracted verified shared-component bytes from Make Room space estimates, added typed
    `ModelUpdateFailureClassifiable` (`ENOSPC`/`EDQUOT`/Carbon `-34`), gated Make Room consent on
    `afterMakingRoom == .startUpdate`, and added `runQueueScenario` RB-06/RB-10 XCUITest checks.
- **Verification on `f269200d`:** `scripts/dev.sh lint` PASS (35 paths privacy scan, pyright 0 new,
  strict SwiftLint 0 warnings/errors), 39/39 contract validators PASS, 44 Python tests PASS,
  `./scripts/macos_test.sh test` PASS (`VocelloCoreTests` + `Qwen3RuntimeTests`), `scripts/dev.sh
  ios` PASS (`VocelloiOS` + iOS executable scan + `VocelloiOSLogicTests`), `scripts/dev.sh ios --ui`
  PASS (all 3 iOS XCUITest bundles), `scripts/dev.sh build` PASS (`Vocello.app`), and
  `./scripts/build.sh cli --version` PASS (`vocello 3.1.0`).
- **Next:** push these local `main` commits when explicitly requested, watch push CI on `xcode-27`,
  and then execute **Wave 5** in a single announced physical-iPhone window (iPhone Mirroring quit,
  `QVOICE_LEAD_ONLY=1`): 3× iOS `ui-perf` calibrations + threshold calibration, `model-management`
  (queue/relaunch + upgrade Make Room), `profile --kind metal`, and the iOS 3.1.0 candidate
  qualification/TestFlight tag (`v3.1.0-ios.4`).

### November 20, night: Antigravity harness Phases A, B & C complete on local `main`

Phases A, B and C of the Antigravity harness & engineering-velocity upgrade landed on local `main`
(ahead of `origin/main` `670f7e77`; **not yet pushed**), closing five authorized backlog items
(`BKL-63`, `BKL-74`, `BKL-79`, `BKL-87`, `BKL-90`) with zero audio-sample changes and zero
product-binary regressions.

- **Phase A — Harness safety, CI blind spots & workflow kit (`0e207be0`..`f5b1879f`, closes `BKL-63`,
  `BKL-74`, `BKL-87`, `BKL-90`):** fixed Sparkle incremental `CodeSign` race + macOS/iOS build-log
  mirroring (live macOS smoke `macos-xcui-smoke-20261120-202030-03d22d24` and perf
  `macos-xcui-perf-20261120-223253-e83975d8` 12/12 PASS); upgraded irreversible external/destructive
  commands & MCP writes to uncacheable `"force_ask"` with `PostInvocation` drift reminders,
  non-looping `Stop` whitespace guard, in-process `agent_guard` and Antigravity worktree leases;
  gated `ios_control_audit.py validate` in `contract_gate.py`; fixed `nightly.yml` and
  `release-rehearsal.yml` `report` triggers (`always() && !cancelled()`); added `.agents/workflows/`
  (`swift_adversarial_review.py`, `xcuitest_visual_qa.py`, `debt_burndown_pipeline.py`,
  `qc_experiment_synthesizer.py`).
- **Phase B — Lint burndown, Swift 6 hardening, security & perf harness (`f466500e`..`81b0dbf8`,
  `aa97fb2e`, closes `BKL-79`):**
  - Burned **Ruff `44 → 0`** (`f466500e`) and **Pyright `789 → 81`** across 72 Python files via two
    3-worker parallel `share`-worktree waves (`08c70744`, `aa97fb2e`; 0 `# type: ignore`; 3,149
    pytest passed).
  - Hardened `Packages/VocelloQwen3Core` (`cc305197`, `Reviewed-by: vocello-swift-review`):
    `swift-tools-version: 6.2`, `.treatAllWarnings(as: .error)` on 4/5 targets (`MLXAudioTTS`
    documented as waiting on upstream `mlx-swift` `MLXArray: Sendable`), SwiftLint expanded to
    `Packages/VocelloQwen3Core/` (0/0) + `no_if_debug` rule, pure-Swift parameterized Swift Testing
    suite (`Qwen3PropertyInvariantTests`, 9 `@Test` suites); audited all 164 `try?` sites in
    `Sources/` (zero silent data-loss sites).
  - Hardened `HuggingFaceDownloader` (`1251fcc4`, `Reviewed-by: vocello-swift-review`, closes
    `BKL-79`) to fail closed when any planned/installed file lacks a valid 64-hex SHA-256 or
    disagrees between `files` and `installedFiles`, with zero-request/zero-staging tests.
  - Eliminated XCUITest accessibility snapshot walks in `test05DeliveryMenu()` (`81b0dbf8`, `BKL-77`)
    using window-anchored coordinate clicks + keyboard, exposed `actionHitchTimeMSPerS` /
    `queryHitchTimeMSPerS`, bumped `("ui-perf", "macos")` lineage to v3 (`e073bbb8`), ran 3 clean
    canonical calibrations (`8f412666`, `8b059da3`, `b6cfbcce`: `[59.446, 55.426, 53.901]` ms/s,
    median `55.426` vs `84.168`), recalibrated `config/ui-perf-thresholds.json` (`72.5 ms/s`,
    `130 ms`), added `delivery-menu` to `enforce`, and closed **`BKL-77`** (`4974d4e9`).
- **Phase C — Metal profiling, `VocelloSharedPolicies` modularization, Xcode 27.2 CI cutover &
  playbook (`2aea00c9`, `91f5eae6`):** added `macos_test.sh profile --kind metal` (`Metal System
  Trace` + `os_signpost`) across trace retention and benchmark history contracts; extracted pure
  multiplatform static framework `VocelloSharedPolicies` (`91f5eae6`, `Reviewed-by:
  vocello-swift-review`) compiling 7 runtime/Studio/ownership/retry policy files once instead of
  4–5x across 5 targets (macOS, iOS, CLI and all 3 UI test bundles verified green; push CI
  `44853701944` green); cut over `config/toolchain.json` (`Xcode 27.2` / `Swift 6.4.2`) and all 6
  macOS GitHub workflows (`ci.yml`, `nightly.yml`, `promote-release.yml`, `release-rehearsal.yml`,
  `release.yml`, `security.yml`) from `macos-26` to GA `xcode-27` (`DW-04`, matching local
  `Xcode 27.2` build `27B52`); documented the Repeatable Innovation Playbook in
  `docs/reference/development-workflow.md`.
- **Next:** push the `BKL-77` calibration + `DW-04` Xcode 27.2 cutover commits when requested,
  observe the first `xcode-27` push CI run, and resume iOS 3.1.0 candidate work (`RF-12`/`RF-15`/
  `RF-35`–`RF-42`) in the next iPhone window.

### November 20: Antigravity harness takeover

The repository-owned agent harness moved from Claude Code (`.claude/`, `CLAUDE.md`,
`website/CLAUDE.md`) to Antigravity (`AGENTS.md`, `website/AGENTS.md`, `.agents/hooks.json`,
`.agents/plugins/vocello/` and `scripts/hooks/agy_hook_adapter.py`) under `RF-67`, with zero Swift
or product-binary changes. Pushed through `670f7e77` with CI green (`44831811307`). `main` stays on
the iOS 3.1.0 TestFlight candidate track (`v3.1.0-ios.3`, `focusLock` active; `RF-35`, `RF-41`,
`RF-42` remain in flight awaiting an iPhone window).

- **Live verification (2026-11-20):** Antigravity loaded `AGENTS.md`, all six `vocello-*` skills and
  both read-only subagents (`vocello-swift-review`, `vocello-xcresult-triage`). Live `PreToolUse`
  probes denied `git push --force --dry-run origin main`, `edit_file` on `docs/ROADMAP.md`,
  `mobilebuildmcp:list_sims` and `cua-driver_cua-driver:list_apps`, while allowing
  `git status --short --branch` and `mobilebuildmcp:list_schemes`. `RF-67` is closed.

### November 17: Vocello 3.1.0 is public on the Mac

The maintainer uploaded the promotion manifest to the v3.1.0 draft and dispatched **Promote verified
release** from the tag (run 44036811898, approved on the `release` environment). Every step passed,
and at 07:17 UTC the release went public as the latest: 13 assets, and `releases/latest`'s
`appcast.xml` now resolves to v3.1.0, so Sparkle offers it. Two stray drafts that a release-edit
link had created on the phone were deleted first. `main` was pushed through `f99b5c33` with CI and
the release rehearsal green.

The post-promotion refresh is committed on local `main` (`ac173582`): the six promotion records,
and the README chart, performance art and website pooled over the two build-31 records through
`0b6bc26b` (0.29 to 0.41 warm RTF).

The published, notarized 3.1.0 CLI then passed `cli_package.py qualify` on this Mac: Built-in
English, French Voice Design and Clone (a Vocello-generated reference) each with a strict QC pass
and EOS, the two-item batch, cancellation (exit 130, cleanup acknowledged, no output) and the error
exits. Its report stays untracked under `build/artifacts/macos/release`. RF-61 is closed. The 3.1
website is live; its pooled performance numbers deploy with the next push of `main`.

### November 16, night: the follow-up release's Mac backlog, first wave

At the maintainer's request (work for a follow-up release, Mac-only, no lanes on the screen), the
roadmap gained a `needs` tag (mac, keyboard, iphone) on every open item and the first wave of
Mac-only backlog fixes landed on `main` with tests; the routed check, the full macOS deterministic
suite, the CLI, the iPhone compiles and the UI-test bundles pass.

- **Closed:** BKL-18, 20, 21, 22, 24, 25, 26, 32, 37, 46, 47, 48, 58, 64, 66, 70 and 73; DA-14;
  RF-64, superseded by RF-63 (iPhone Settings already has a Help & Support row).
- **Engine-remediation parts done:** B-02 (BKL-73), B-12 (`_exit` in the CLI's forced exit), C-13
  (the QC observer above 102.4 kHz) and BKL-01 (control-token-only scripts have nothing to speak).
- **Fixed, waiting on a run:** BKL-33 and BKL-19 on the next macOS smoke, BKL-28 on the marketing
  lane, BKL-23 on a production Mac language bench, BKL-50 on the next Linux CI run, BKL-60 on the
  phone.
