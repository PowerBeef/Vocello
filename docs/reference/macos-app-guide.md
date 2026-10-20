---
status: active
owner: macos
reviewed: 2026-10-20
summary: Consolidated macOS app map — screens, elements, and options, and how XCUITest addresses each through the stable accessibility surface — plus macOS permissions (TCC), code signing and the dev loop, the UI test runner's grants, and permissions_doctor.sh diagnosis (§7).
sourceOfTruth:
  - Sources/Views
  - Sources/ContentView.swift
  - Sources/SharedSupport/Services/ReferenceTranscriptionReviewState.swift
  - Sources/Services/MacStudioGenerationRequestFactory.swift
  - Sources/Models/ScriptTextState.swift
  - scripts/permissions_doctor.sh
  - scripts/lib/dev_signing.sh
  - scripts/ui_test.sh
  - Sources/QwenVoice.entitlements
  - Tests/VocelloMacUITests/VocelloUIWindowFrame.swift
  - config/runtime-debug-knobs.json
---
# Vocello for Mac — app guide + test-driving reference

A consolidated map of the Vocello macOS app: what every screen/element/option does and how
XCUITest addresses it (identifier → action → expected). Use this to maintain the smoke and
benchmark tests and stable accessibility surface.

> **Where this fits:** the canonical "macOS app + driving" reference, including permissions,
> signing and TCC ([§7](#7-macos-permissions-tcc)). Running the tests lives in
> [`macos-testing.md`](macos-testing.md); the engine internals live in
> [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the iOS counterpart is
> [`ios-app-guide.md`](ios-app-guide.md).

---

## 1. Overview

A `NavigationSplitView` with a **sidebar** (Studio, Voices, History, Settings) + a detail pane. The engine runs
**in-process** (since 2026-09-15) on the same `TTSEngineStore` the iOS app uses; an engine
fault takes the app down with it, so crash deltas stay part of every lane's verdict.

The September 18 shell adapts the approved iOS navigation: four sidebar destinations, with
Built-in, Design and Clone inside Studio's shared mode selector. Studio resumes its last mode.
A missing model leaves the Studio accessible with its Install action. All three Studio modes keep
the active take's transport inline; the sidebar carries playback on other destinations. Dark-only.
Window minimum and default dimensions are owned by `MacShellMetrics`; UI acceptance measures
actual reachable sizes rather than treating those constants as proof of fit.

| Control | Identifier | Shortcut |
|---------|------------|----------|
| Studio destination | `sidebar_studio` | Mode shortcuts below |
| Built-in mode segment | `sidebar_customVoice` | Cmd+1 |
| Design mode segment | `sidebar_voiceDesign` | Cmd+2 |
| Clone mode segment | `sidebar_voiceCloning` | Cmd+3 |
| History destination | `sidebar_history` | Cmd+4 |
| Voices destination | `sidebar_voices` | Cmd+5 |
| Settings destination | `sidebar_settings` | Cmd+6 |
| History search field | `history_searchField` | Cmd+F (opens History) |
| Stop: cancels a running take, otherwise stops playback | Playback menu | Cmd+. |

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
controls expose stable identifiers, and `{mode}_readiness` values report `Ready` or `Waiting`.
Tests assert these visible production surfaces directly.

### Studio composition

Both platforms use `VocelloStudioLayout` for the composer, setup and dock. The Mac adapter
supplies its AppKit text editor, native menus/popovers, batch action and file actions. The editor
fills remaining height; metadata, setup chips and dock retain their natural sizes.
All three modes share a column capped at `MacStudioMetrics.composerMaxWidth`. The mode selector aligns with the active column.

The dock holds Generate and Batch while idle, progress/cancellation while preparing, and the
inline player once live audio or a completed take is available. All three modes replace the
idle action row with the completed player; Retry, Save As, Reveal and Dismiss remain on that card.
Design additionally offers Save as Voice when its completed take still matches the current draft.
The shared backdrop and per-mode accents follow iOS. Speed/Quality remain in the window toolbar;
setup chips wrap when the actual available width cannot fit them.

### Built-in Voice (`sidebar_customVoice` → `screen_customVoice`)

| Element | Identifier |
|---|---|
| Speaker chip | `customVoice_speakerPicker` (menu anchored to the chip; the selected speaker is its accessibility value; "Recommended for your script" section from the detected language) inside `customVoice_voiceSetup` |
| Language chip | `customVoice_languagePicker` inside `customVoice_languageSetup`; native-speaker hint `customVoice_languageHint` |
| Delivery chip | `delivery_tonePicker` inside `customVoice_toneSpeed`, sectioned since DP-14 into "Distinct deliveries" (Neutral/Calm/Whisper/Sad), "Directional hints" (Happy/Angry/Fearful/Surprised) and Custom; a hint shows `delivery_hintAdvisory`, Custom shows the field `delivery_toneField` (duration advisory `delivery_durationAdvisory`); the chip writes the draft's `DeliveryInputState` as the iPhone controls do, so one selection sends one instruction on both apps and a blank Custom tone sends none (P02-07); `customVoice_deliveryUnsupported` when the package has no delivery control |
| Script editor | `textInput_textEditor` / `textInput_longFormIndicator` (localized Long-form above 900 characters, a CJK character counting three, or Line-by-line while explicitly selected; absent for ordinary short drafts) / `textInput_clearButton` / `textInput_modeMetaLabel` |
| Readiness | `customVoice_readiness` (value "Ready" or "Waiting"), one caption after the mode label in the meta line, where the phone puts it |
| Generate CTA | `textInput_generateButton`; error bar `textInput_generationError` retries |
| Generating | `textInput_generatingBar` with `textInput_cancelButton`; once audio streams, the player card `studio_livePreview_card` carries the same cancel |
| Live preview | `studio_livePreview_card`, with `studio_livePreview_playPause`, `studio_livePreview_scrubber`, `studio_livePreview_badge` and `textInput_cancelButton` |
| Completed take | `studio_inlinePlayer_generation_<id>` carries the inline waveform, `studio_inlinePlayer_playPause`, `studio_inlinePlayer_scrubber`, `studio_inlinePlayer_retry`, `studio_inlinePlayer_saveAs`, `studio_inlinePlayer_reveal` and `studio_inlinePlayer_dismiss` (confirmed by `studio_inlinePlayer_dismissConfirm`). All three modes suppress duplicate sidebar transport while their displayed take owns audio. |
| Batch | `textInput_batchButton` line-by-line toggle (grey off, tinted and selected on; Generate opens the matching workflow) |
| Pinned seed chip | `textInput_seedPinChip` while a seed is pinned (DP-15); its confirmation's `textInput_seedUnpin` clears it back to fresh-seed-per-take. Shared across all three modes |

### Voice Design (`sidebar_voiceDesign` → `screen_voiceDesign`)

| Element | Identifier |
|---|---|
| Voice brief | `studioChip_voiceBrief` opens the native popover `voiceDesign_voiceSetup`; its editor keeps `voiceDesign_voiceDescriptionField`. Starting points: `voiceDesign_briefStarters` / `voiceDesign_briefStarter_<n>`; count: `voiceDesign_briefCharCount`; Done: `voiceBrief_confirm`. Edits bind directly to the draft. |
| Delivery chip | `delivery_tonePicker` inside `voiceDesign_toneSpeed` (same sections, `delivery_hintAdvisory`, `delivery_toneField` as Built-in Voice) |
| Language chip | `voiceDesign_languagePicker` inside `voiceDesign_languageSetup` |
| Readiness | `voiceDesign_readiness` (value "Ready" or "Waiting") |
| Save voice | `voiceDesign_saveVoiceButton` inside the completed player; `voiceDesign_saveVoiceCompleted` below setup once saved. Cancelling the enrollment sheet preserves the take and save action. |
| Script + CTAs + dock | `textInput_*` and `studio_inlinePlayer_*` (shared) |

### Voice Cloning (`sidebar_voiceCloning` → `screen_voiceCloning`)

| Element | Identifier |
|---|---|
| Reference chip | `studioChip_reference` inside `voiceCloning_voiceSetup` opens `voiceCloning_referencePanel`; its `voiceCloning_savedVoicePicker` menu lists saved voices (standalone voices as `<name> · transcript` / `<name> · audio only`; emotion-bank members collapse into one persona row, see [emotion-reference-banks.md](emotion-reference-banks.md)) plus Clear; the selected voice is its accessibility value |
| Bank delivery chip | `voiceCloning_bankDeliveryPicker`, visible only while a bank member is selected; lists Neutral (the persona's base) plus its curated emotion variants and swaps the concrete member |
| Reference panel actions | `voiceCloning_importButton` / `voiceCloning_recordReferenceButton`, plus `cloneReference_confirm` to close; audio files can also be dropped on the screen |
| Language chip | `voiceCloning_languagePicker` inside `voiceCloning_languageSetup` |
| Active reference | `voiceCloning_activeReference` (file name, detail or `voiceCloning_referenceWarning` chip, Clear) inside the reference panel; `voiceCloning_consentNotice` remains on the canvas |
| Warnings | `voiceCloning_savedVoicesWarning` (+ `voiceCloning_savedVoicesRetry`) / `voiceCloning_transcriptWarning` / `voiceCloning_dropWarning` (a dropped file of an unsupported type; the dock error bar is reserved for takes) |
| Transcript (optional) | `voiceCloning_transcriptInput` inside `voiceCloning_transcriptField`, in the reference panel once a reference exists; blank selects genuine audio-only x-vector conditioning; `voiceCloning_transcriptionUnavailable` explains a missing auto-fill |
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
| Pending-history recovery | `historyRecovery_banner` with `historyRecovery_retry`, `historyRecovery_reveal`, and `historyRecovery_export`; a confirmed `historyRecovery_discard` sets aside records that cannot be verified (A2-02) or long-form recovery data Retry cannot resolve (F-16) |
| Paging | `history_showMoreButton` below the list loads the next 500 entries (AUD-05); sort, filter and search reach the whole archive through `GenerationHistoryPageQuery` with the list's own predicate, and run in memory while the whole archive is loaded |

Database failures are typed and fail closed: an unavailable store is not shown as empty History.
Published single takes are queued before their idempotent database write when storage permits. Startup and History
entry retry pending writes; if recovery still needs attention, the visible banner can retry,
reveal the local outputs folder, or export the pending audio. Clear-all records a resumable
database-first transaction before removing pending entries or files. Audio a clear or a single
delete could not remove is reported, counted by the same banner and retried on every reconcile
(AUD-05). The banner states one notice shared with iOS (`GenerationHistoryRecoverySnapshot.notice`):
a clear that did not finish has its own copy and Retry resumes it, no count is ever zero, and a
removal list that could not be read is reported until Retry from it discards the list without
deleting the audio it named (PA-30).
If enqueue itself fails, `historyUnqueued_banner` appears above the main content with
`historyUnqueued_retry` and `historyUnqueued_export`. Audio remains playable; the exact retry
record is app-session memory only until safely queued. No storage failure is reported as failed
synthesis, and clear-all refuses to discard unqueued records. Export before quitting if retry fails.

Corrupt long-form journals leave unrelated standalone clips readable while project rows and writes
remain gated. Export Recovery Files retains bounded journals for repair with a private-text/path
warning; it does not repair or delete them.

History date headings render as transparent List rows (`history_sectionHeading_<bucket>`),
without native pinned-header material or section rules. Search still renders a flat result list.

### Saved Voices (`sidebar_voices` → `screen_voices`)

| Element | Identifier |
|---|---|
| Enroll | `voices_enrollButton` (toolbar) |
| States | `voices_loadingState` / `voices_emptyState` (also while the engine starts) / `voices_errorState` with `voices_retryButton`. When a state card is the whole screen, SwiftUI exposes it under `screen_voices` and its own identifier does not resolve, so lanes tell the states apart by the status strip (`sidebar_backendStatus_<state>`), the loading indicator and `voices_retryButton`. The cards keep a minimum width so the window's minimum-size pass cannot stretch the window off screen (BKL-15) |
| Row | `voicesRow_<voiceID>` (name) / `voicesRow_<voiceID>_transcriptStatus` (metadata) / `voicesRow_<voiceID>_qualityWarning` (compact icon, opens the popover with `voicesRow_<voiceID>_replaceReference`) / `voicesRow_play_<voiceID>` / `voicesRow_use_<voiceID>` / `voicesRow_more_<voiceID>` (native MenuButton containing `voicesRow_delete_<voiceID>`); a 32-point avatar, two-line metadata and compact actions share one horizontal row |
| Enrollment sheet | `voicesEnroll_nameField` / `_audioPathField` / `_browseButton` / `_recordButton` / `_transcriptField` / `_transcriptionStatus` / `_referenceLanguagePicker` / `_useAudioOnlyButton` / `_confirmButton` / `_cancelButton`; `voicesEnroll_inlineConsent` (one-time, same key as the Settings toggle) shows while consent is off and Confirm stays disabled until it is recorded |

Confirm prepares a private candidate first. A clean candidate commits immediately; a warned
candidate commits only on Keep, while Discard, Cancel, and outside dismissal discard it, including a
candidate a save was still staging when the sheet closed (F-01). Editing a
voice supplies replacement intent to the same transaction, so the old assets remain recoverable
until the new audio crosses the publication boundary. Row deletion stops a matching preview before
the engine atomically removes that voice's audio, transcript, and prepared prompt artifacts.
Voice-bank siblings are independent and never cascade. As on iPhone, Delete waits while a take, a
line batch or a long-form project runs, since a Clone line batch or long-form project reads the
voice again for every line or segment, and a retained long-form project that reads the deleted
voice can no longer resume or regenerate a segment (`MacSavedVoiceDeletion`, BKL-13).

Imported and recorded references use the same operation-generation transcription-review policy as
iPhone. Save stays disabled until on-device transcription resolves; a delayed recognizer result
cannot overwrite edited text. If recognition cannot provide text, the user must enter a transcript
or choose **Use audio only** explicitly. Transcript-backed enrollment also requires a separately
confirmed reference language. That language is persisted as reference metadata through the
`enrollmentMetadata` overload and never selects a later Clone output language. Clone Auto follows
the target script; an explicit output language always wins. Voice Design uses the same target-text
language boundary.

### Settings (`sidebar_settings` → `screen_settings`)

The overview groups Audio, App Language and Models & Files, with Voice Cloning in a separate
consent destination. Shared `VocelloSettingsGroup` and `VocelloSettingsNavigationRow` provide the
same quiet surfaces as iOS, with desktop typography. The sidebar and Cmd+, window host the same
screen. Audio owns playback/variation; Models & Files owns memory preference, model management
and storage. Studio installation links open Models & Files and focus the requested mode.
Category buttons use `settings_category_<audio|appLanguage|modelsFiles|cloning>`; detail headings
use `settings_detail_<category>`, and `settings_backButton` returns to the overview.

| Element | Identifier |
|---|---|
| Model summary | `settings_modelDownloadsSummary`; recommended setup `settings_downloadRecommendedModels` / `settings_cancelRecommendedSetup` / `settings_recommendedSetupProgress` |
| Mode row | `settings_mode_<mode>` (scrolled to and flashed from a Studio installation link) |
| Package row | `settings_package_<modelID>` / `settings_packageBadge_<modelID>` (Recommended or Heavy) / `settings_packageStatus_<modelID>` / `settings_downloadProgress_<modelID>` |
| Download / cancel / repair / update | `settings_download_<id>` / `settings_cancel_<id>` / `settings_repair_<id>` / `settings_update_<id>` / `settings_manage_<id>` (AppKit menu: Reveal in Finder, Delete Model) |
| App language | `settings_appLanguage` (menu: System Default plus the bundle's languages; `MacInterfaceLanguage` owns the selection in `AppDefaults.store` and feeds it to `MacInterfaceText`; smoke test05 reads English, which beginSession selects through this control) |
| Auto-play | `preferences_autoPlayToggle` |
| Variation | `settings_generationVariation` (segmented: Expressive/Balanced/Consistent) |
| Prefer lower-memory models | `settings_preferSpeedEverywhere` |
| Clone consent | `voiceCloning_consentAcknowledgment`; persistent and required before Clone Generate; in the Voice Cloning detail page |
| Output dir | `preferences_outputDirectory` / `preferences_browseButton` / `preferences_outputResetButton` / `preferences_outputDirectoryWarning` / `preferences_outputDirectoryIssue` / `preferences_openFinderButton` |
| Version label | read-only `version (build)` caption in the Application data row (beside `preferences_openFinderButton`); the runtime debug gate is a launch environment (`QWENVOICE_DEBUG=1`, internal-diagnostics builds only), not an in-app toggle |

### Sidebar player + engine status

The compact global player places transport and title above a slim waveform. It follows the
playing audio's mode color (saved references use the Voices tint), independently of navigation.
Studio owns transport only for its displayed playing take. On other destinations, or while
another take plays, the global player lives in the sidebar; hiding the sidebar moves the same
card into the detail footer, preserving its identifiers. No duplicate transport is shown.

Closing the global preview or explicitly choosing other audio revokes automatic playback for
that entire generation operation, including later batch lines and long-form segments. Generation
can still complete and save to History. Starting a new generation grants playback ownership again.
Pausing the preview (or starting a reference recording) holds it the same way until Play: no
chunk, final-file handoff or later item of the operation starts on its own, and Play resumes the
paused item, then the items waiting behind it. Within one operation each item's preview plays to
its end, live tail and final file, before the next item's starts; the next items' chunks wait in
memory. Past about five minutes of waiting audio a newly waiting item stops buffering its preview
and keeps only its result, so a line still plays from its file at its turn.
Internal segment cleanup preserves the joined-output handoff. Studio result errors belong only to
the file that failed; a stale card cannot display or control another clip's failure.

| Element | Identifier |
|---|---|
| Player card | `sidebarPlayer_bar` / `sidebarPlayer_playPause` (value `play` / `pause`) / `sidebarPlayer_waveform` / `sidebarPlayer_time` / `sidebarPlayer_dismiss` / `sidebarPlayer_error` |
| Live badge | `sidebarPlayer_liveBadge` / `sidebarPlayer_liveStatus` / `sidebarPlayer_liveProgress` |
| Engine status strip | `sidebar_generationStatus` > `sidebar_backendStatus` > `sidebar_backendStatus_idle` / `_standby` / `_starting` / `_active` / `_error` (+ `_dismiss`) / `_crashed` |

### Batch generation

Generate automatically selects long-form above the shared 900-character threshold (a Han, kana
or Hangul character counts three, `SingleTakeScriptBudget`). The
line-by-line toggle overrides both single-take and long-form routing in all three Studio modes.
Switching it off restores automatic routing. The batch sheet receives the current script and
selected segmentation, with its existing review, Generate all, cancel and recovery actions.

| Element | Identifier |
|---|---|
| Segmentation | `batch_segmentationMode` (read-only mode selected in Studio) |
| Editor | `batch_textEditor` |
| Generate all | `batch_generateAllButton` / `batch_cancelButton` / `batch_doneButton` |
| Item status | `batch_itemStatusList` / `batch_regenerateSegment_<index>` (long-form, per accepted segment) / `batch_errorLine` (the attempt's failure, a rejected replacement included) |
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
recovery runs before History reads/writes. Superseded joined outputs, and segment takes a
regeneration replaced, retain individually deletable History rows rather than becoming unowned WAVs. Unchanged segments retain their QC, effective seeds,
and generation identities. Old manifest-v4 files remain readable; this adds no cross-launch
generation-resume feature. A joined-row commit reloads the complete History project.

---

## 3. Model download management

macOS has **both Speed (4-bit) and Quality (8-bit)** variants (unlike iOS Speed-only).
Settings → Models & Files → Model downloads shows per-mode packages. Download via `settings_download_<id>`;
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
| `scripts/ui_test.sh macos smoke` | Fifteen ordered focused journeys, `test00`–`test14` in `VocelloMacSmokeUITests` and its `+Acceptance` extension (window sizes + Cmd+, Settings scene, navigation/readiness, completed generation + History with played-audio capture, mid-generation cancellation, virtual-mic recording, library surfaces, long-form project (two planned segments by default; `--long-form-segments 2`–`12` scales it for local evidence), two-line batch, Design brief + completed player, Clone reference + completed player, missing-model Studio install links, generation error + recovery, cross-language Studio content, long-form recovery Discard, Saved Voices empty and error states; `--scenario layout\|studio-content\|generation-errors\|design-enrollment\|clone-reference\|long-form\|line-batch\|long-form-recovery\|saved-voices-states` runs one) with named screenshots and automatic on-failure desktop + element-tree evidence |
| `scripts/ui_test.sh macos benchmark` | UI-driven generation matrix plus merged telemetry proof |
| `scripts/ui_test.sh macos perf` | Eleven scripted frame-health scenarios (`VocelloMacPerfUITests`) with the in-app 500 ms display-link probe, gated by `scripts/check_macos_ui_perf.py` against warn-only ceilings in `config/ui-perf-thresholds.json`; a canonical-hardware PASS publishes a `ui-perf` record under `benchmarks/runs/ui-perf/` (see [`telemetry-and-benchmarking.md`](telemetry-and-benchmarking.md); the August 2026 refresh that introduced the lane is recorded historically in [`macos-ui-refresh-2026-08.md`](../audits/2026-08-04-macos-ui-refresh.md)) |
| `scripts/ui_test.sh macos marketing` | Product image refresh (`VocelloMacMarketingCaptureUITests.test00_WebsiteRefresh`, `--scenario models` for the Model Downloads image): two demo takes and one saved designed voice through visible controls at a 1040×680 window, captures attached for export; `evidenceClass: marketing-assets`, never acceptance or benchmark evidence |

### macOS-specific patterns (vs iOS)

- **NavigationSplitView sidebar** — not a tab bar. Use `sidebar_*` identifiers or Cmd+1..6,
  then re-observe the real destination identifier such as `screen_customVoice`.
- **Menus + popovers** — sort pickers, model "Manage" menus, language/delivery pickers use
  macOS menus (NSMenu), not iOS-style sheets. Re-observe after opening before selecting.
- **Keyboard shortcuts** — Cmd+1..6 for sidebar (Cmd+6 is the Navigate menu's Settings item; the Navigate commands wait while a line batch or long-form project runs, since leaving its Studio screen would close its sheet); Cmd+F opens History with its search field focused; Cmd+. cancels a running take (single take, line batch or long-form project) and otherwise stops playback; Cmd+, for the Settings window.
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
  reloads it. The `sidebar_backendStatus_*` markers reflect the state. Every Mac tier unloads
  after idle (2 min up to 10 GB of RAM, 10 min up to 24 GB, 30 min above) and trims on kernel
  pressure. Entering Studio or generating warms the engine; History, Voices and Settings never
  do, so browsing cannot keep the weights resident. The longer high-memory window trades a cold
  first take after a long pause for fewer reloads; see
  [`../ARCHITECTURE.md`](../ARCHITECTURE.md#45-memory-policy).
- **First responder** — after navigating, the text editor may need one explicit action before
  typing; re-observe instead of assuming focus.

---

## 6. Identifier gaps

macOS controls not currently targeted by the minimal smoke/benchmark lanes:
- Individual delivery/language menu items.
- Model "Manage" popover menu items.
- `batch_resumeLongFormButton` exists but is not yet exercised by the minimal lanes; the long-form
  journey only asserts its absence after a clean run, then regenerates segment 0 through
  `batch_regenerateSegment_0` (F-16).
- The History "Reveal in Finder" context menu item (the pin-seed item carries
  `history_pinSeedButton`).

Add stable identifiers before extending autonomous coverage to these controls; do not introduce
label-only or coordinate-based selectors.

---

## 7. macOS permissions (TCC)

How Vocello meets macOS privacy permissions: why the project used to fight TCC constantly, how
stable signing fixed it, what end users experience, and how to diagnose problems. Diagnose anything
permission-related with **`scripts/permissions_doctor.sh`**.

### The TCC model (why this was ever a problem)

macOS TCC (Transparency, Consent & Control) keys every permission grant to the
app's **bundle ID + code-signing identity** (designated requirement). Two
identities matter:

- **Ad-hoc signatures** (`codesign -s -`) have no certificate, so their
  designated requirement is pinned to the binary's **CDHash — which changes on
  every rebuild**. To TCC, every rebuild is a brand-new app: grants are
  invalidated, prompts re-appear (sometimes while another window has focus, so
  they're easy to dismiss by accident — a stray keystroke answers them
  "Don't Allow"), and denials stick.
- **Certificate signatures** (Apple Development / Developer ID) anchor the
  designated requirement to the *certificate*, which is stable across
  rebuilds. Grant once, keep forever.

This project's local builds were ad-hoc for a long time — the root cause of
the recurring permission pain.

### How each build flavor is signed

| Build | Identity | Hardened runtime | TCC stability |
|---|---|---|---|
| `build.sh build`/`run` (dev) | auto-detected **Apple Development** cert (fallback: ad-hoc + warning) | OFF (lldb-friendly; matches old ad-hoc behavior) | **Stable** — grants survive rebuilds |
| `release.sh` (default) | ad-hoc, re-signed from scratch | ON (`--options runtime`) | n/a (packaging check only) |
| `release.sh --signing-mode developer-id` / CI | **Developer ID Application** | ON | **Stable** for end users |

- Dev identity resolution (`scripts/lib/dev_signing.sh`):
  `QWENVOICE_DEV_SIGNING_IDENTITY` env (verbatim; `"-"` forces ad-hoc) → first
  `Apple Development` identity in the keychain → ad-hoc with a warning.
  Nothing is hardcoded; get a certificate via Xcode → Settings → Accounts →
  Manage Certificates.
- The resolved identity is fingerprinted inside the managed shared-package cache at
  `build/cache/xcode/source-packages/.qwenvoice-cache/dev-signing-identity`;
  changing it forces a fresh sign + restage, and `build.sh` asserts the app
  ended up signed as expected.
- The dev-signed app and the shipped (Developer ID) app have different
  designated requirements, so the installed release prompts once on its own —
  expected.
- First signing with a new certificate may show a keychain prompt
  ("codesign wants to sign…") — choose **Always Allow**.
- Switching ad-hoc → certificate leaves stale TCC rows behind; reset once:
  `scripts/permissions_doctor.sh --reset-tcc` (then grant on next launch).
- **System Audio Recording for the UI test runner.** `scripts/ui_test.sh macos benchmark` and the
  smoke lane's completed-generation journey (`test02`, PC-02) tap the app's own audio output from
  `VocelloMacUITests-Runner` (`com.qwenvoice.app.uitests.xctrunner`, usage string in `project.yml`).
  Xcode signs that runner sandboxed, which would block the tap and the capture files, so both lanes
  re-sign it without entitlements after the build, with the same Apple Development identity
  `build.sh` uses (ad hoc only when none is installed). On macOS 26
  creating a process tap never prompts (an ungranted runner receives silence), so add the runner
  once by hand under System Settings → Privacy & Security → Screen & System Audio Recording →
  *System Audio Recording Only* (plus button, Cmd+Shift+G,
  `build/cache/xcode/macos-optimized/Build/Products/Release/VocelloMacUITests-Runner.app`, the
  optimized UI-lane cache; the pane asks for the login password) **after** a benchmark or smoke lane
  has re-signed it. On macOS 27 the first captured
  take raises « VocelloMacUITests-Runner souhaite enregistrer le contenu audio système »: click
  **Autoriser** once while the lane runs, so the grant attaches to the re-signed runner (a grant
  added in System Settings before that binds to whatever build is on disk). An identity-signed
  grant survives rebuilds; an ad-hoc one binds to a single code hash and needs redoing after
  every rebuild. The prompt blocks the runner until it is answered, so an unattended benchmark
  lane arms capture only when it can: `QVOICE_MAC_BENCH_PLAYBACK_CAPTURE=auto` (default) skips
  capture when the TCC database shows no grant, `off` always skips it, `on` always arms it.
  Unarmed, the takes pace and play out the same and the record carries no capture evidence. The
  smoke lane has no such switch: its one capture is always armed, and its `ui-preflight` warns when
  the runner has no System Audio Recording decision.
  Reset with `tccutil reset AudioCapture com.qwenvoice.app.uitests.xctrunner`.
  Every macOS lane also verifies the runner's signature before launching it and re-signs it in
  place when a build interrupted between Xcode's Info.plist rewrite and its CodeSign step left
  it invalid (launchd otherwise refuses to spawn it: "Runningboard has returned error 5" with
  zero tests executed); the repair drops the UI-build fingerprint so the next lane rebuilds it.
- **UI-lane builds are ad-hoc signed** (`scripts/ui_test.sh` builds with
  `CODE_SIGN_IDENTITY="-"`), so they never match the dev identity's TCC grant: any *real*
  microphone request from a lane-built app prompts fresh, and answering it re-keys the row to that
  build's throwaway identity (the next real-mic use of the dev-signed app may then prompt once —
  grant it; stable signing keeps it). In practice lane builds only reach the real-mic path when the
  virtual-microphone fixture is broken, which the smoke suite asserts explicitly. Speech
  Recognition has no such fixture: on 2026-10-18 the smoke journey `test08` asked for it at its
  save-voice step after a lane rebuild, and the unanswered dialog covered the window, so `test12`,
  `test13` and `test14` failed on controls that were not hittable until a human answered it
  (BKL-19, parked). The lane's
  advisory `ui-preflight` checks TCC row existence per bundle id and cannot see this identity
  mismatch.

### Permission map (which process touches what)

| Permission | macOS app | `vocello` CLI |
|---|---|---|
| Microphone (`NSMicrophoneUsageDescription`, `device.audio-input` entitlement) | record reference clips (`ReferenceClipRecorder`) | — |
| Speech recognition (`NSSpeechRecognitionUsageDescription`) | on-device transcript auto-fill (`VoiceClipTranscriber`, `requiresOnDeviceRecognition` always) | — |
| Files & Folders | `NSOpenPanel`/`NSSavePanel` (user intent ⇒ no extra prompt); writing to a **persisted** custom output dir in the Desktop, Documents or Downloads folder prompts once per folder category | app-support folders only |
| Everything else (contacts, photos, location, automation, screen) | not used | not used |

The app process is the TCC client for everything; the CLI never triggers prompts.

### OS gates beyond TCC

- **Siri gate (speech):** on macOS, `SFSpeechRecognizer` authorization is
  **auto-denied without ever showing a prompt while Siri is disabled**. The UI
  detects this (`VoiceClipTranscriber.availability()` → `.siriDisabled`) and
  shows "Auto-transcription needs Siri enabled" with an Open Siri Settings
  button. Recovery: enable Siri, then allow the app under Privacy & Security →
  Speech Recognition (reset the denied row first if needed).
- **On-device speech models:** transcription only covers languages whose
  dictation model is installed; missing models degrade silently to "no
  transcript" by design.
- **In-process caching:** a process that was denied keeps that answer until
  relaunch (`requestAuthorization` won't re-prompt). The UI re-checks
  `authorizationStatus` on every app activation, so a grant made in System
  Settings applies without relaunching.

### User-facing permission UX inventory

- **Record sheet** (`MacRecordVoiceSheet`): mic-denied alert + status
  label with an Open System Settings (Privacy → Microphone) path; a
  "No microphone detected" state when there's no input device; permission
  state refreshes on app activation.
- **Enroll sheet** (`MacSavedVoiceSheet`): transcript section shows
  "Transcribing on-device…" while running and a denied/Siri-disabled caption
  with a direct System Settings button otherwise; retries the auto-fill when
  access is granted mid-session.
- **Voice Cloning**: same unavailability hint near the transcript field for
  fresh-file imports; clears + retries on activation.
- **Settings → Models & Files (Storage section)**: warning badge + caption when the configured output
  folder is missing/unwritable; generation transparently falls back to the
  default outputs folder (`AudioService.makeOutputPath`) so audio is never lost.

### Troubleshooting

1. Run `scripts/permissions_doctor.sh` — it reports the build's signing
   identity + designated requirement (flags rebuild-unstable ad-hoc), decoded
   TCC rows, available certificates, mic hardware, on-device speech locales,
   and the Siri gate.
2. Permission prompts re-appearing every rebuild ⇒ the build fell back to
   ad-hoc (no Apple Development cert, or `QWENVOICE_DEV_SIGNING_IDENTITY="-"`).
3. A permission seems granted but the app behaves denied ⇒ relaunch (the
   process cached an earlier denial), or the row predates an identity switch —
   `scripts/permissions_doctor.sh --reset-tcc` and re-grant.
4. Transcript never auto-fills ⇒ check the caption in the enroll sheet; if
   none, the language's on-device model may not be installed (doctor lists
   locales).
5. Reading the TCC database from a terminal needs Full Disk Access for that
   terminal; the doctor degrades gracefully without it.

### XCUITest setup (separate from mic/speech TCC)

The lanes themselves are [§5](#5-driving-the-macos-ui-like-a-human)'s. XCUITest drives the app
through macOS Automation Mode. On a Mac where turning it on needs
authentication (`automationmodetool` prints "requires user authentication"), an unattended lane
times out "enabling automation mode" after its build. Once per machine, run
`sudo automationmodetool enable-automationmode-without-authentication`. The login session must
also stay unlocked for the whole run. The lane's `ui-preflight` step refuses both conditions before
building.

#### Accessibility, for pinning the window to a width (UIF-06)

macOS XCUITest has no window-resize API, so the layout survey
(`VocelloMacMarketingCaptureUITests.test04`/`test05`) pins the window through the accessibility API
instead — `VocelloUIWindowFrame` writes `kAXPositionAttribute` and `kAXSizeAttribute` on the app's
main window. That needs the **runner**, not the app, to hold the Accessibility grant, and macOS
never prompts for it from a test process: without it every accessibility call returns
`kAXErrorAPIDisabled` (-25211) and the survey skips rather than photographing an unknown width and
labelling it 720.

Grant it once, the same way as the
[System Audio Recording grant](#how-each-build-flavor-is-signed):

1. Build the runner and let the lane re-sign it, or re-sign it directly with the Apple Development
   identity — the grant binds to the designated requirement, so a stable identity survives rebuilds
   while an ad-hoc signature does not.
2. System Settings → Privacy & Security → Accessibility → **+**, then add
   `build/cache/xcode/macos-optimized/Build/Products/Release/VocelloMacUITests-Runner.app` and enable it.

`VocelloUIWindowFrame.diagnosis()` reports which of the three failure modes applies (untrusted
runner, no running process, or an accessibility error on a process that was found), and every
survey run prints it as `WINDOW_FRAME diagnosis:`.

### Virtual microphone (registered debug knob)

`QWENVOICE_FAKE_MIC_WAV` is a registered input-substitution knob
(`config/runtime-debug-knobs.json`) available only in an internal diagnostics build with
`QWENVOICE_DEBUG`. When both are set and
the path points at a readable audio file, `ReferenceClipRecorder` simulates capture: elapsed time
and level-meter values come from the clip's real amplitude envelope, auto-stop fires at clip end or
the 20 s cap, and stop-and-save delivers a copy of the clip — so the record→review→enroll flow runs
end to end with no input hardware and no mic TCC prompt. The recording XCUITest journey uses this
knob with a synthesized speech-like clip; the flow it drives is the genuine visible recording sheet,
and it deliberately cancels at the review stage — accepting a clip starts transcript auto-fill,
whose speech-recognition TCC dialog only a human may answer (see
[Manual testing / TCC caveat](#manual-testing--tcc-caveat)).
Unavailable in distributed builds: process environment cannot grant the compile capability.

### Manual testing / TCC caveat

TCC permission dialogs require a **human** to answer; UI tests must stop before a permission-
sensitive scenario when the grant is absent. After a permission reset, answer the prompt and
verify the outcome with `scripts/permissions_doctor.sh` (or the TCC query). With stable dev signing
this is a once-per-machine event.
