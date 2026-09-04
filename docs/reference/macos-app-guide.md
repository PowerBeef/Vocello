---
status: active
owner: macos
reviewed: 2026-09-04
summary: Consolidated macOS app map — screens, elements, and options, and how XCUITest addresses each through the stable accessibility surface.
sourceOfTruth:
  - Sources/Views
  - Sources/ContentView.swift
  - Sources/SharedSupport/Services/ReferenceTranscriptionReviewState.swift
  - Sources/Services/MacStudioGenerationRequestFactory.swift
---
# Vocello for Mac — app guide + test-driving reference

A consolidated map of the Vocello macOS app: what every screen/element/option does and how
XCUITest addresses it (identifier → action → expected). Use this to maintain the smoke and
benchmark tests and stable accessibility surface.

> **Where this fits:** the canonical "macOS app + driving" reference. Running the tests
> lives in [`macos-testing.md`](macos-testing.md); the engine/XPC internals live in
> [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the iOS counterpart is
> [`ios-app-guide.md`](ios-app-guide.md).

---

## 1. Overview

A `NavigationSplitView` with a **sidebar** (6 items) + a detail pane. The engine runs
**out-of-process in an XPC service** — the app talks to it over XPC; the service can crash
or retire independently.

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

### Semantic state surfaces

XCUITest inspects the real accessibility state. Destination containers use `screen_*`, primary
controls expose stable identifiers, and `{mode}_readiness` values report `ready=true/false`.
Tests assert these visible production surfaces directly.

### Built-in Voice (`sidebar_customVoice` → `screen_customVoice`)

| Element | Identifier |
|---|---|
| Speaker picker | `customVoice_speakerPicker` (visible menu; selected speaker is its accessibility value) |
| Language picker | `customVoice_languageSetup` |
| Delivery (tone) | `customVoice_toneSpeed` row; the menu itself is `customVoice_tonePicker`, sectioned since DP-14 into "Distinct deliveries" (Neutral/Calm/Whisper/Sad), "Directional hints" (Happy/Angry/Fearful/Surprised), and Custom; selecting a hint shows the advisory caption `customVoice_hintAdvisory` |
| Script editor | `textInput_textEditor` / `textInput_charCount` |
| Generate CTA | `textInput_generateButton` |
| Cancel | `textInput_cancelButton` |
| Batch | `textInput_batchButton` |
| Pinned seed chip | `textInput_seedPinChip` beside Generate while a seed is pinned (DP-15); `textInput_seedUnpin` clears it back to fresh-seed-per-take. Shared across all three modes |

### Voice Design (`sidebar_voiceDesign` → `screen_voiceDesign`)

| Element | Identifier |
|---|---|
| Voice brief field | `voiceDesign_voiceDescriptionField` (visible field; current brief is its accessibility value) |
| Brief starters | `voiceDesign_briefStarter_<n>` |
| Brief char count | `voiceDesign_briefCharCount` |
| Language + delivery | `voiceDesign_toneSpeed` / `voiceDesign_languageSetup`; delivery menu `voiceDesign_tonePicker` with the same DP-14 sectioning and `voiceDesign_hintAdvisory` caption as Custom |
| Save voice | `voiceDesign_saveVoiceButton` / `voiceDesign_saveVoiceCompleted` |
| Script + CTAs | `textInput_*` (shared) |

### Voice Cloning (`sidebar_voiceCloning` → `screen_voiceCloning`)

| Element | Identifier |
|---|---|
| Reference picker | `voiceCloning_savedVoicePicker` (saved voices menu). Standalone voices list as `<name> · transcript` / `<name> · audio only`; emotion-bank members collapse into one persona row labeled `<persona> · voice bank` (`VoiceBankCatalog` naming convention; [emotion-reference-banks.md](emotion-reference-banks.md)) |
| Bank delivery menu | `voiceCloning_bankDeliveryPicker` — visible only while a bank member is selected; lists Neutral (the persona's base) plus its curated emotion variants and swaps the concrete member voice through the ordinary selection path |
| Import | `voiceCloning_importButton` |
| Record | `voiceCloning_recordReferenceButton` |
| Active reference | `voiceCloning_activeReference` / `voiceCloning_referenceWarning` |
| Transcript (optional) | `voiceCloning_transcriptInput`; blank selects genuine audio-only x-vector conditioning |
| Record clip sheet | `recordClip_record` / `_stop` / `_retake` / `_use` / `_cancel` / `_timer` |
| Script + CTAs | `textInput_*` (shared) |

### History (`sidebar_history` → `screen_history`)

| Element | Identifier |
|---|---|
| Search | `history_searchField` (toolbar) |
| Sort | `history_sortPicker` (menu) |
| Clear | `history_clearMenu` → `history_clearKeepFiles` / `history_clearDeleteFiles` |
| Row | `historyRow_<genID>` / `historyRow_play_<genID>` / `historyRow_saveAs_<genID>` / `historyRow_delete_<genID>` |
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
| Row | `voicesRow_<voiceID>` / `voicesRow_play_<voiceID>` / `voicesRow_use_<voiceID>` / `voicesRow_delete_<voiceID>` |
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
versioned XPC candidate command and never selects a later Clone output language. Clone Auto follows
the target script; an explicit output language always wins. Voice Design uses the same target-text
language boundary.

### Settings (`sidebar_settings` → `screen_settings`)

| Element | Identifier |
|---|---|
| Model summary | `settings_modelDownloadsSummary` |
| Mode row | `settings_mode_<mode>` |
| Package row | `settings_package_<modelID>` / `settings_packageStatus_<modelID>` |
| Download / cancel / repair / update | `settings_download_<id>` / `settings_cancel_<id>` / `settings_repair_<id>` / `settings_update_<id>` / `settings_manage_<id>` |
| Auto-play | `preferences_autoPlayToggle` |
| Variation | `settings_generationVariation` (segmented: Expressive/Balanced/Consistent) |
| Clone consent | `voiceCloning_consentAcknowledgment`; persistent and required before Clone Generate |
| Output dir | `preferences_outputDirectory` / `preferences_browseButton` / `preferences_openFinderButton` |
| Version label | tap 7× → toggles `QWENVOICE_DEBUG` mode |

### Sidebar player + engine status

| Element | Identifier |
|---|---|
| Player bar | `sidebarPlayer_bar` / `sidebarPlayer_playPause` / `sidebarPlayer_waveform` / `sidebarPlayer_time` / `sidebarPlayer_dismiss` |
| Live badge | `sidebarPlayer_liveBadge` / `sidebarPlayer_liveProgress` |
| Engine status | `sidebar_backendStatus_idle` / `_standby` / `_starting` / `_active` / `_error` / `_crashed` |

### Batch generation

| Element | Identifier |
|---|---|
| Segmentation | `batch_segmentationMode` |
| Editor | `batch_textEditor` |
| Generate all | `batch_generateAllButton` / `batch_cancelButton` / `batch_doneButton` |
| Item status | `batch_itemStatusList` / `batch_regenerateSegment_<index>` (long-form, per accepted segment) |
| Long-form resume | `batch_resumeLongFormButton` (shown when a stopped project has reusable takes) |
| Delivery summary | `batch_deliverySummary` |

Every item — line-separated and long-form — is an ordinary sequential streaming take (mandatory
engine Fast QC, streaming telemetry, live preview). Long-form additionally plans segments, joins
them into one WAV, and lands a single project row in History.
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
Settings → Voice Models shows per-mode packages. Download via `settings_download_<id>`;
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
| `scripts/macos_test.sh test` | Core, XPC transport, and runtime tests; no UI driving |
| `scripts/ui_test.sh macos smoke` | Seven ordered focused journeys (navigation/readiness, completed generation + History, mid-generation cancellation, virtual-mic recording, library surfaces, three-segment long-form project, two-line batch) with named screenshots and automatic on-failure desktop + element-tree evidence |
| `scripts/ui_test.sh macos benchmark` | UI-driven generation matrix plus merged telemetry proof |
| `scripts/ui_test.sh macos perf` | Nine scripted frame-health scenarios (`VocelloMacPerfUITests`) with the in-app 500 ms display-link probe, gated by `scripts/check_macos_ui_perf.py` against warn-only ceilings in `config/ui-perf-thresholds.json`; a canonical-hardware PASS publishes a `ui-perf` registry record → [`macos-ui-refresh-2026-08.md`](macos-ui-refresh-2026-08.md) |

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
- **XPC service retirement** — the engine may be idle/retired; a generation auto-relaunches
  it. The `sidebar_backendStatus_*` markers reflect the state.
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
