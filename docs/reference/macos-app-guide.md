---
status: active
owner: macos
reviewed: 2026-09-12
summary: Consolidated macOS app map — screens, elements, and options, and how XCUITest addresses each through the stable accessibility surface.
sourceOfTruth:
  - Sources/Views
  - Sources/ContentView.swift
  - Sources/SharedSupport/Services/ReferenceTranscriptionReviewState.swift
  - Sources/Services/MacStudioGenerationRequestFactory.swift
  - Sources/Models/ScriptTextState.swift
---
# Vocello for Mac — app guide + test-driving reference

A consolidated map of the Vocello macOS app: what every screen/element/option does and how
XCUITest addresses it (identifier → action → expected). Use this to maintain the smoke and
benchmark tests and stable accessibility surface.

> **Where this fits:** the canonical "macOS app + driving" reference. Running the tests
> lives in [`macos-testing.md`](macos-testing.md); the engine internals live in
> [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the iOS counterpart is
> [`ios-app-guide.md`](ios-app-guide.md).

---

## 1. Overview

A `NavigationSplitView` with a **sidebar** (6 items) + a detail pane. The engine runs
**in-process** (since 2026-09-15) on the same `TTSEngineStore` the iOS app uses; an engine
fault takes the app down with it, so crash deltas stay part of every lane's verdict.

The shell (since 2026-09-15, CONV-11) is the iOS design on the desktop: the brand lockup on
top of the sidebar, **Studio** and **Library** sections plus Settings as rows with mode-tinted
glyph tiles (`sidebarSection_generate`, `sidebarSection_library`), the selected row a tint-glass
pill, a mode whose model is missing dimmed with an "Install in Settings" caption, and the inline
player card and engine status strip pinned in the sidebar footer. Dark-only. Window minimum
720×560, default 880×640 (`MacShellMetrics`).

| Sidebar | Identifier | Shortcut |
|---------|------------|----------|
| Built-in Voice | `sidebar_customVoice` | Cmd+1 |
| Voice Design | `sidebar_voiceDesign` | Cmd+2 |
| Voice Cloning | `sidebar_voiceCloning` | Cmd+3 |
| History | `sidebar_history` | Cmd+4 |
| Saved Voices | `sidebar_voices` | Cmd+5 |
| Settings | `sidebar_settings` | Cmd+6 (labeled "Models" in the Navigate menu, opens the unified Settings/Models surface) |

Three generation modes (Custom / Design / Clone) — same engine contract as iOS, but macOS
has **both Speed (4-bit) and Quality (8-bit)** variants.

---

## 2. Screen-by-screen element + identifier map

The shared macOS script editor materializes native UTF-8 once per AppKit edit using
`ScriptTextState`, without normalizing or trimming text. Its coordinator compares the last
synchronized snapshot and refreshes its binding on updates; a native edit's binding echo does
not rewrite the text view. This avoids repeated foreign-NSString comparisons while preserving
the exact request text. Language, seed and delivery resolution remain in the existing request
factory/engine, not the editor.

### Semantic state surfaces

XCUITest inspects the real accessibility state. Destination containers use `screen_*`, primary
controls expose stable identifiers, and `{mode}_readiness` values report `ready=true` or `ready=false`.
Tests assert these visible production surfaces directly.

### Studio composition

The three Studio screens are one canvas (`MacStudioCanvas`) arranged for a desktop: the composer
on top, taking every point the rest of the column does not (a six-line floor, scrolling past its
height), then the meta line (mode, readiness, Clear, counter) flush below it, one row of setup
chips, and the dock. Nothing trails the dock: the script is the flexible element, so a taller
window grows the writing surface rather than the space under the button. The dock holds the full-width Generate button with
the square Batch button (`textInput_batchButton`) at its right end, the generating bar, the error bar
that retries when clicked, or the player card, and never falls below 64 pt. The column caps at
780 pt. One mode-tinted wash (`VocelloModeBackdrop`, shared with iOS) is painted behind the whole
window by `ContentView`, tinted by the selected destination, and the title bar is transparent over
it with no visible title. There is no title row — the sidebar names the mode, as the phone's capsule
does — so the desktop's Speed/Quality switch (`<prefix>_speedVariantButton`,
`<prefix>_qualityVariantButton`, `<prefix>_heavyBadge`) lives in the window toolbar. Below roughly
the window's 880 pt minimum the four ordinary setup chips stay on one row; a fifth (an
emotion-bank delivery) or a sixth (a pinned seed) wraps below about 1040 pt rather than squeezing.

### Built-in Voice (`sidebar_customVoice` → `screen_customVoice`)

| Element | Identifier |
|---|---|
| Speaker chip | `customVoice_speakerPicker` (menu anchored to the chip; the selected speaker is its accessibility value; "Recommended for your script" section from the detected language) inside `customVoice_voiceSetup` |
| Language chip | `customVoice_languagePicker` inside `customVoice_languageSetup`; native-speaker hint `customVoice_languageHint` |
| Delivery chip | `delivery_tonePicker` inside `customVoice_toneSpeed`, sectioned since DP-14 into "Distinct deliveries" (Neutral/Calm/Whisper/Sad), "Directional hints" (Happy/Angry/Fearful/Surprised) and Custom; a hint shows `delivery_hintAdvisory`, Custom shows the field `delivery_toneField` (duration advisory `delivery_durationAdvisory`); `customVoice_deliveryUnsupported` when the package has no delivery control |
| Script editor | `textInput_textEditor` / `textInput_charCount` (reads "96 / 900" against the shared script ceiling; its spoken value stays "N characters") / `textInput_clearButton` / `textInput_modeMetaLabel` |
| Readiness | `customVoice_readiness` (value "Ready" or "Waiting"), one caption after the mode label in the meta line, where the phone puts it |
| Generate CTA | `textInput_generateButton`; error bar `textInput_generationError` retries |
| Generating | `textInput_generatingBar` with `textInput_cancelButton`; once audio streams, the player card `studio_livePreview_card` carries the same cancel |
| Completed take | `studio_inlinePlayer_generation_<id>`: a result row, not a player — the take's identity plus `studio_inlinePlayer_retry`, `studio_inlinePlayer_saveAs`, `studio_inlinePlayer_reveal` and `studio_inlinePlayer_dismiss` (confirmed by `studio_inlinePlayer_dismissConfirm`). It carries no waveform, clock, scrubber or play/pause: playback of a finished take belongs to the sidebar footer card, which is reachable from every destination (maintainer decision 2026-09-16) |
| Batch | `textInput_batchButton` chip (opens the batch sheet) |
| Pinned seed chip | `textInput_seedPinChip` while a seed is pinned (DP-15); its confirmation's `textInput_seedUnpin` clears it back to fresh-seed-per-take. Shared across all three modes |

### Voice Design (`sidebar_voiceDesign` → `screen_voiceDesign`)

| Element | Identifier |
|---|---|
| Voice brief | inline editor `voiceDesign_voiceDescriptionField` inside `voiceDesign_voiceSetup` (the brief is the container's accessibility value); starters menu `voiceDesign_briefStarters` with `voiceDesign_briefStarter_<n>`; count `voiceDesign_briefCharCount` |
| Delivery chip | `delivery_tonePicker` inside `voiceDesign_toneSpeed` (same sections, `delivery_hintAdvisory`, `delivery_toneField` as Built-in Voice) |
| Language chip | `voiceDesign_languagePicker` inside `voiceDesign_languageSetup` |
| Readiness | `voiceDesign_readiness` (value "Ready" or "Waiting") |
| Save voice | `voiceDesign_saveVoiceButton` beside the readiness line after a take; `voiceDesign_saveVoiceCompleted` once saved |
| Script + CTAs + dock | `textInput_*` and `studio_inlinePlayer_*` (shared) |

### Voice Cloning (`sidebar_voiceCloning` → `screen_voiceCloning`)

| Element | Identifier |
|---|---|
| Reference chip | `voiceCloning_savedVoicePicker` inside `voiceCloning_voiceSetup`: a menu of the saved voices (standalone voices as `<name> · transcript` / `<name> · audio only`; emotion-bank members collapse into one persona row, see [emotion-reference-banks.md](emotion-reference-banks.md)) plus Import, Record and Clear; the selected voice is its accessibility value |
| Bank delivery chip | `voiceCloning_bankDeliveryPicker`, visible only while a bank member is selected; lists Neutral (the persona's base) plus its curated emotion variants and swaps the concrete member |
| Import / Record chips | `voiceCloning_importButton` (Import or Replace) / `voiceCloning_recordReferenceButton`; audio files can also be dropped on the screen |
| Language chip | `voiceCloning_languagePicker` inside `voiceCloning_languageSetup` |
| Active reference | `voiceCloning_activeReference` (file name, detail or `voiceCloning_referenceWarning` chip, Clear) under the chips; `voiceCloning_consentNotice` above it |
| Warnings | `voiceCloning_savedVoicesWarning` (+ `voiceCloning_savedVoicesRetry`) / `voiceCloning_transcriptWarning` / `voiceCloning_dropWarning` (a dropped file of an unsupported type; the dock error bar is reserved for takes) |
| Transcript (optional) | `voiceCloning_transcriptInput` inside `voiceCloning_transcriptField`, shown once a reference exists; blank selects genuine audio-only x-vector conditioning; `voiceCloning_transcriptionUnavailable` explains a missing auto-fill |
| Consent | `voiceCloning_inlineConsent` (one-time, same key as the Settings toggle) |
| Readiness | `voiceCloning_readiness` (value "Ready" or "Waiting") |
| Record clip sheet | `recordClip_record` / `_stop` / `_retake` / `_use` / `_cancel` / `_timer` / `_levelMeter` |
| Script + CTAs + dock | `textInput_*` and `studio_inlinePlayer_*` (shared) |

### History (`sidebar_history` → `screen_history`)

| Element | Identifier |
|---|---|
| Search | `history_searchField` (toolbar) |
| Sort | `history_sortPicker` (menu); date sections (Today, Yesterday, Previous 7 days, Previous 30 days, Earlier) appear only under the newest-first sort |
| Clear | `history_clearMenu` → `history_clearKeepFiles` / `history_clearDeleteFiles` |
| Mode filter | `history_modeFilter` → `history_modeFilter_all` / `_custom` / `_design` / `_clone` chips |
| Row | `historyRow_<genID>` card: `historyRow_play_<genID>` (the thumbnail tile) / `historyRow_saveVoice_<genID>` (clone and design takes) / `historyRow_saveAs_<genID>` / `historyRow_delete_<genID>` |
| Pin seed | `history_pinSeedButton` in the row context menu (only for rows with a recorded seed, DP-15): pins the take's seed into its mode's draft and switches to that mode; the composer then shows the pinned-seed chip |
| Long-form project | joined row plus `history_longFormSegmentsToggle_<digest8>` disclosure over the per-segment map; segments collapse under the project, flatten during search, and orphans stay visible |
| Degraded database state | `history_errorState`; destructive actions stay disabled until a later reload/read succeeds |
| Pending-history recovery | `historyRecovery_banner` with `historyRecovery_retry`, `historyRecovery_reveal`, and `historyRecovery_export` |

Database failures are typed and fail closed: an unavailable store is not shown as empty History.
Published single takes are queued before their idempotent database write when storage permits. Startup and History
entry retry pending writes; if recovery still needs attention, the visible banner can retry,
reveal the local outputs folder, or export the pending audio. Clear-all records a resumable
database-first transaction before removing pending entries or files.
If enqueue itself fails, `historyUnqueued_banner` appears above the main content with
`historyUnqueued_retry` and `historyUnqueued_export`. Audio remains playable; the exact retry
record is app-session memory only until safely queued. No storage failure is reported as failed
synthesis, and clear-all refuses to discard unqueued records. Export before quitting if retry fails.

Corrupt long-form journals leave unrelated standalone clips readable while project rows and writes
remain gated. Export Recovery Files retains bounded journals for repair with a private-text/path
warning; it does not repair or delete them.

### Saved Voices (`sidebar_voices` → `screen_voices`)

| Element | Identifier |
|---|---|
| Enroll | `voices_enrollButton` (toolbar) |
| Row | `voicesRow_<voiceID>` (name) / `voicesRow_<voiceID>_transcriptStatus` (badge) / `voicesRow_<voiceID>_qualityWarning` (chip, opens the popover with `voicesRow_<voiceID>_replaceReference`) / `voicesRow_play_<voiceID>` / `voicesRow_use_<voiceID>` / `voicesRow_delete_<voiceID>`; rows lay out from the List width and the action cluster width, never their own rendered width |
| Enrollment sheet | `voicesEnroll_nameField` / `_audioPathField` / `_browseButton` / `_recordButton` / `_transcriptField` / `_transcriptionStatus` / `_referenceLanguagePicker` / `_useAudioOnlyButton` / `_confirmButton` / `_cancelButton` |

Confirm prepares a private candidate first. A clean candidate commits immediately; a warned
candidate commits only on Keep, while Discard, Cancel, and outside dismissal discard it. Editing a
voice supplies replacement intent to the same transaction, so the old assets remain recoverable
until the new audio crosses the publication boundary. Row deletion stops a matching preview before
the engine atomically removes that voice's audio, transcript, and prepared prompt artifacts.
Voice-bank siblings are independent and never cascade.

Imported and recorded references use the same operation-generation transcription-review policy as
iPhone. Save stays disabled until on-device transcription resolves; a delayed recognizer result
cannot overwrite edited text. If recognition cannot provide text, the user must enter a transcript
or choose **Use audio only** explicitly. Transcript-backed enrollment also requires a separately
confirmed reference language. That language is persisted as reference metadata through the
`enrollmentMetadata` overload and never selects a later Clone output language. Clone Auto follows
the target script; an explicit output language always wins. Voice Design uses the same target-text
language boundary.

### Settings (`sidebar_settings` → `screen_settings`)

| Element | Identifier |
|---|---|
| Model summary | `settings_modelDownloadsSummary`; recommended setup `settings_downloadRecommendedModels` / `settings_cancelRecommendedSetup` / `settings_recommendedSetupProgress` |
| Mode row | `settings_mode_<mode>` (scrolled to and flashed when a disabled sidebar mode redirects here) |
| Package row | `settings_package_<modelID>` / `settings_packageBadge_<modelID>` (Recommended or Heavy) / `settings_packageStatus_<modelID>` / `settings_downloadProgress_<modelID>` |
| Download / cancel / repair / update | `settings_download_<id>` / `settings_cancel_<id>` / `settings_repair_<id>` / `settings_update_<id>` / `settings_manage_<id>` (AppKit menu: Reveal in Finder, Delete Model) |
| App language | `settings_appLanguage` (menu: System Default plus the bundle's languages; `MacInterfaceLanguage` owns the selection in `AppDefaults.store` and feeds it to `MacInterfaceText`; smoke test05 reads System Default) |
| Auto-play | `preferences_autoPlayToggle` |
| Variation | `settings_generationVariation` (segmented: Expressive/Balanced/Consistent) |
| Prefer lower-memory models | `settings_preferSpeedEverywhere` |
| Clone consent | `voiceCloning_consentAcknowledgment`; persistent and required before Clone Generate; deliberately the last section |
| Output dir | `preferences_outputDirectory` / `preferences_browseButton` / `preferences_outputResetButton` / `preferences_outputDirectoryWarning` / `preferences_outputDirectoryIssue` / `preferences_openFinderButton` |
| Version label | read-only `version (build)` caption in the Application data row (beside `preferences_openFinderButton`); the runtime debug gate is a launch environment (`QWENVOICE_DEBUG=1`, internal-diagnostics builds only), not an in-app toggle |

### Sidebar player + engine status

| Element | Identifier |
|---|---|
| Player card | `sidebarPlayer_bar` / `sidebarPlayer_playPause` (value `play` / `pause`) / `sidebarPlayer_waveform` / `sidebarPlayer_time` / `sidebarPlayer_dismiss` / `sidebarPlayer_error` |
| Live badge | `sidebarPlayer_liveBadge` / `sidebarPlayer_liveStatus` / `sidebarPlayer_liveProgress` |
| Engine status strip | `sidebar_generationStatus` > `sidebar_backendStatus` > `sidebar_backendStatus_idle` / `_standby` / `_starting` / `_active` / `_error` (+ `_dismiss`) / `_crashed` |

### Batch generation

| Element | Identifier |
|---|---|
| Segmentation | `batch_segmentationMode` |
| Editor | `batch_textEditor` |
| Generate all | `batch_generateAllButton` / `batch_cancelButton` / `batch_doneButton` |
| Item status | `batch_itemStatusList` / `batch_regenerateSegment_<index>` (long-form, per accepted segment) |
| Long-form resume | `batch_resumeLongFormButton` (shown when a stopped project has reusable takes) |
| Delivery summary | `batch_deliverySummary` |

The sheet (`MacBatchGenerationSheet`) only projects two runners owned by `MacAppModel`: a
line-by-line batch runs on `MacLineBatchRunner`, one ordinary Studio take per line on the shared
`IOSSingleTakeGenerationExecutor` with `MacStudioSingleTakeGenerationHooks` (timeline, live preview,
History append, telemetry merge); a long-form project runs on the shared iOS
`IOSLongFormCoordinator` / `IOSLongFormProjectRunner` with `MacStudioLongFormPlatformHooks`. Both run
under the mode's `StudioGenerationCoordinator`, so the canvas behind the sheet locks and shows the
live card exactly as during a single take, and the batch uses the Settings Speed/Quality variant.
Every item — line-separated and long-form — is an ordinary sequential streaming take (mandatory
engine Fast QC, streaming telemetry, live preview). Long-form additionally plans segments, joins
them into one WAV, and lands a single project row in History. Resume and per-segment regeneration
follow the iOS semantics — resume after a stopped project, regenerate after a completed one — and
survive closing the sheet because the coordinator lives on the shell model; a reopened sheet starts
a line batch blank.
Segments are saved individually to History before continuing and remain exportable/deletable
after abandoning a draft or relaunching. Segment completion is not project acceptance.
Both initial completion and segment replacement await the shared `LongFormHistoryAcceptanceStore`:
QC-checked unique candidate WAVs, throwing manifest serialization, atomic manifest replacement,
and one journaled SQLite transaction. Failed replacement preserves the previous accepted project;
recovery runs before History reads/writes. Superseded joined outputs retain individually deletable
History rows rather than becoming unowned WAVs. Unchanged segments retain their QC, effective seeds,
and generation identities. Old manifest-v4 files remain readable; this adds no cross-launch
generation-resume feature. A joined-row commit reloads the complete History project.

---

## 3. Model download management

macOS has **both Speed (4-bit) and Quality (8-bit)** variants (unlike iOS Speed-only).
Settings → Model downloads shows per-mode packages. Download via `settings_download_<id>`;
cancel via `settings_cancel_<id>`; repair via `settings_repair_<id>`; a complete install whose files no longer match the pinned catalog identity shows **Update available** with `settings_update_<id>` (the same authenticated download path repairs it in place).

The shared foreground downloader distinguishes queued, waiting for connectivity, downloading,
retrying, verifying, installing, and cancelling. Active transfer shows bytes, smoothed speed, ETA,
and a separate 20-second no-progress indication. Transient failures retry up to three times; Retry
preserves verified files, while explicit Cancel discards that package's staged data. Every terminal
foreground path invalidates its URLSession after ordered durable-stage/terminal processing. Bounded
progress ingress still emits the exact final byte count. Details: [`model-delivery.md`](model-delivery.md).

The Studio's Generate CTA (`textInput_generateButton`) appears only when the mode's model
is installed — otherwise the app prompts to download from Settings.

---

## 4. What each option means

Same engine as iOS. See [`ios-app-guide.md`](ios-app-guide.md) §4 for the full reference
(modes, 9 speakers + native languages, 8 delivery presets, custom
tone, 10 languages, reproducible takes). macOS adds the **Quality (8-bit)** variant for
higher-fidelity output.

---

## 5. Driving the macOS UI like a human

### Test infrastructure (XCUITest)

`VocelloMacUITests` is the sole autonomous macOS frontend driver. It launches its configured
Vocello test host, uses the shared UI automation support, and re-queries stable accessibility state
before and after each logical action. There is no hidden test-marker surface.

The shell harness owns deterministic proof and evidence:

| Lane | Purpose |
|------|---------|
| `scripts/macos_test.sh test` | Core and runtime tests; no UI driving |
| `scripts/ui_test.sh macos smoke` | Seven ordered focused journeys (navigation/readiness, completed generation + History, mid-generation cancellation, virtual-mic recording, library surfaces, three-segment long-form project, two-line batch) with named screenshots and automatic on-failure desktop + element-tree evidence |
| `scripts/ui_test.sh macos benchmark` | UI-driven generation matrix plus merged telemetry proof |
| `scripts/ui_test.sh macos perf` | Nine scripted frame-health scenarios (`VocelloMacPerfUITests`) with the in-app 500 ms display-link probe, gated by `scripts/check_macos_ui_perf.py` against warn-only ceilings in `config/ui-perf-thresholds.json`; a canonical-hardware PASS publishes a `ui-perf` record under `benchmarks/runs/ui-perf/` (see [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md); the August 2026 refresh that introduced the lane is recorded historically in [`macos-ui-refresh-2026-08.md`](macos-ui-refresh-2026-08.md)) |

### macOS-specific patterns (vs iOS)

- **NavigationSplitView sidebar** — not a tab bar. Use `sidebar_*` identifiers or Cmd+1..6,
  then re-observe the real destination identifier such as `screen_customVoice`.
- **Menus + popovers** — sort pickers, model "Manage" menus, language/delivery pickers use
  macOS menus (NSMenu), not iOS-style sheets. Re-observe after opening before selecting.
- **Keyboard shortcuts** — Cmd+1..6 for sidebar (Cmd+6 is labeled "Models" in the Navigate menu but opens the unified Settings/Models surface); Cmd+, for the Settings window.
- **File pickers** — reference import uses NSOpenPanel. Import is product functionality but is not
  part of the minimal smoke or benchmark lane.
- **Screenshots** — attach named screenshots at important states and on failures; do not use
  coordinates as a control-selection fallback.

### Canonical flow

1. Launch → observe `sidebar_customVoice` and `screen_customVoice`.
2. Navigate by `sidebar_<mode>` → re-observe the destination screen identifier.
3. Compose through `textInput_textEditor` → re-observe the changed semantic value/state.
4. Generate through `textInput_generateButton` → observe `sidebarPlayer_bar`, then assert the
   matching History/WAV/typed-probe evidence.
5. History: `sidebar_history` → `historyRow_play_<id>`.
6. Settings: `sidebar_settings` → `settings_download_<id>`.

### Gotchas

- **Menu items** — if a future scenario needs an item that lacks a stable identifier, add one before
  automating it. Label-only selection is not a fallback.
- **NSOpenPanel** — system-picker interaction belongs to an explicit import scenario. Do not use
  coordinates, hidden mocks, or AppleScript as frontend proof.
- **Idle unload** — the engine may have unloaded its model while idle; the first generation
  reloads it. The `sidebar_backendStatus_*` markers reflect the state.
- **First responder** — after navigating, the text editor may need one explicit action before
  typing; re-observe instead of assuming focus.

---

## 6. Identifier gaps

macOS controls not currently targeted by the minimal smoke/benchmark lanes:
- Individual delivery/language menu items.
- Model "Manage" popover menu items.
- Per-segment long-form controls beyond the batch journeys (`batch_regenerateSegment_<index>` and
  `batch_resumeLongFormButton` exist but are not yet exercised by the minimal lanes).
- The History "Reveal in Finder" context menu item (the pin-seed item carries
  `history_pinSeedButton`).

Add stable identifiers before extending autonomous coverage to these controls; do not introduce
label-only or coordinate-based selectors.
