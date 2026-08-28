---
status: active
owner: ios
summary: Compact iOS screen and accessibility-identifier map for physical-device XCUITest — states, stable identifiers, and expectations per screen.
sourceOfTruth:
  - Sources/iOS
  - Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift
---
# iOS UI reference

This is the compact screen and accessibility map for physical-device Vocello UI tests. XCUITest is
the sole autonomous driver and runs on a paired physical iPhone; the iOS Simulator is unsupported.

Related sources:

- [`ios-app-guide.md`](ios-app-guide.md) — architecture and implementation map.
- [`ios-device-testing.md`](ios-device-testing.md) — physical-device lanes and gates.
- [`testing-runbook.md`](testing-runbook.md) — shared smoke/benchmark policy.

## Navigation hierarchy

Vocello opens on the Studio tab in Custom mode. The root tabs are:

| Surface | Purpose | Stable identifier family |
| --- | --- | --- |
| Studio | Custom, Design, and Clone generation | `rootTab_studio`, `generateSection_*`, `studio_*`, `studioChip_*`, `textInput_*` |
| Voices | Saved voices and built-in speakers | `rootTab_voices`, `screen_voices`, `voicesRow_*` |
| History | Generated takes, playback, export, deletion | `rootTab_history`, `historyModeFilter*`, `historyRow_*` |
| Player sheet | Full-screen playback with karaoke transcript and scrubber (opens from a History row) | `iosPlayer_*` (`_close`, `_playPause`, `_scrubber`, `_download` — labeled "Share"; `_save` renders only when a caller supplies a distinct save handler, and `_transcript`) |
| Settings | Models, preferences, clone consent, storage, permissions, About | `rootTab_settings`, `iosSettings_*`, `iosModel*`, `voiceCloning_consentAcknowledgment` |

The Studio selector changes the composer in place. Cold launch selects Custom mode; explicit
handoffs may change the in-session Studio mode.

## Studio states

### Built-in Voice

- Script editor and count: `textInput_textEditor`, `textInput_lengthCount`.
- Voice, delivery, language, and variation controls.
- Generate: `textInput_generateButton`.
- Inline progress and completed player.

Generate remains unavailable until the script and Custom model are ready. Smoke requires the
completed player and matching History row; the benchmark validator adds readable-audio and exact
telemetry evidence per take.

Scripts above the 900-character single-take limit route to a long-form project (all three modes):
the helper line narrates per-segment progress, the dock's Cancel stops the whole run, and a
stopped project with reusable takes exposes `longform_resumeChip`, and a completed in-session
project exposes `iosLongForm_segmentsChip` (a setup-row chip whose confirmation-dialog items,
`iosLongForm_regenerateSegment_<index>`, regenerate one segment with a fresh recorded seed and
reassemble the joined output; device acceptance pending). The completed project surfaces
the joined output as the inline player item.

### Voice Design

Design requires a voice brief, entered directly or from a starter, before generation. The benchmark
lane exercises Design when that mode is selected; the minimal smoke only verifies the mode is
navigable before performing its single Custom generation. A missing Design model must present the
install state instead of Generate.

### Voice Cloning

Clone requires a reference clip from a saved voice, the physical-device recording flow
(`referenceClip_recordNewClip`), or direct Files import (`referenceClip_importAudioFile`) of WAV,
MP3, AIFF, or M4A. Direct import always enters the permanent Saved Voice enrollment pipeline; it
does not create a session-only reference. A neighboring `.txt` sidecar wins, otherwise the existing
on-device transcriber runs automatically and reports through `saveVoice_transcriptionStatus`.
Save stays disabled until editable text exists or the user explicitly selects
`saveVoice_useAudioOnlyButton`; a delayed recognizer result cannot overwrite a manual edit.
Successful enrollment selects the exact new voice in `studioChip_reference` and begins ordinary
Clone priming. Automated smoke and benchmark tests use a prepared non-PII saved reference.
Recording, Files-picker import, and permission enrollment are separate explicit product-acceptance
scenarios. The genuine visible
`voiceCloning_consentAcknowledgment` control lives in Settings; Clone reads that persistent choice
and keeps Generate disabled until it is enabled. A transcript is optional: supplied text selects
transcript-backed conditioning, while an empty transcript selects the distinct audio-only x-vector
path.

Emotion reference banks (DP-16) surface in Clone as a persona with a delivery choice: when the
selected saved voice belongs to a bank, the reference chip shows the persona name and a Delivery
chip appears (`studioChip_bankDelivery`) opening a member sheet whose rows are
`bankDeliveryRow_<voiceID>` (Neutral is the persona's base; each emotion row is that delivery's
verified reference voice). Selection applies the concrete member voice through the ordinary
saved-voice path. The delivery preset sheet elsewhere in Studio is sectioned per DP-14 (Distinct
deliveries / Directional hints) with the hints advisory as its footer
(`deliveryPickerSheet_hintAdvisory`). While a sampling seed is pinned (DP-15), every Studio mode
shows a Seed chip (`studioChip_seedPin`) whose tap offers the unpin confirmation.

## Voices and History

Voices exposes saved rows (`voicesRow_saved_*`; a bank member's caption reads
"Voice bank · <Delivery>" while standalone voices read "Cloned reference"), built-in speakers,
separate row and preview actions, search, filters, and one visible Save a New Voice action: `voices_saveNewVoice` records a
reference with the microphone, or imports one from Files ("Import audio file",
`voices_importAudioFile`, restored 2026-08-15 — WAV/MP3/AIFF/M4A; audio files opened from the
Files app route through the same flow via `RootView.onOpenURL`).
`saveVoice_nameField`, `saveVoice_transcriptEditor`, `saveVoice_transcriptionStatus`, the conditional
`saveVoice_useAudioOnlyButton`, and `saveVoice_saveButton` complete enrollment. A saved voice hands off to Studio Clone; a built-in speaker hands off to Studio
Custom. Benchmark-fixture enrollment is script-owned via
`scripts/ios_device.sh enroll-clone-fixture`.

History supports search, mode filtering, sorting, playback, export, saving a take as a voice, and
deletion. A row whose take recorded a sampling seed offers "Pin seed N for new takes" in its
overflow menu (`historyRowPinSeed_<id>`, DP-15): pinning lands in that take's Studio mode with the
Seed chip visible. Long-form projects group as one joined row plus a per-segment disclosure
(`history_longFormSegmentsToggle_<digest8>`); search flattens the grouping, and orphan segments
(no joined output yet) stay visible as ordinary rows. A typed database failure presents
`historyRetryButton` rather than an empty list and keeps destructive actions disabled until a
successful read. Destructive History actions are outside the minimal smoke and benchmark lanes.

## Settings

iOS Settings is a title-free landing surface (`screen_settings`); the selected tab-dock item is the
sole location indicator. Its order is Audio, Models & Files, Accessibility, Privacy, and About.
Compact solid groups reuse the app canvas, eyebrow headings, headline/caption row hierarchy, tinted
utility tiles, panel stroke, spacing grid, and shared dock clearance established by Voices and
History. Neutral controls use the Settings silver accent; model and Clone semantics retain their
mode colors. The Audio group owns a semantic `Toggle` with custom compact switch chrome and the Take
variation menu picker. Models & Files summarizes model
readiness as `N of 3 ready` through `iosSettings_voiceModelsRow` and keeps the Saved outputs value
multi-line. Accessibility owns the app-level Reduce Motion and Reduce Transparency switches.
Privacy owns clone consent, disclosure guidance, the Privacy Policy, Permissions (explicitly
labeled as opening iOS Settings), and `iosSettings_supportRow`, which opens the contract-owned
unauthenticated support page. About contains `iosSettings_openSourceRow`, Source Code, and the compact
version/build row; there is no oversized logo footer. Open Source & Licenses pushes
`screen_openSourceLicenses`, with stable component/model rows and a 44-point
`iosSettings_openSourceBackButton`; attribution details expose their complete bundled license text
and governed source link without requiring network access.

`iosSettings_voiceModelsRow` pushes `screen_voiceModels`, whose compact
`iosSettings_voiceModelsBackButton` is the only Settings-specific contextual header. iOS has one
Speed model for each generation mode. The destination combines `N of 3 ready` with managed model
bytes in `iosSettings_storageRow`, then gives every model one non-color-dependent text-and-symbol
status and only the lifecycle actions valid for its current state. At ordinary text sizes a sole
Install, Retry, Cancel, or Remove action sits beside the compact model summary; Update/Remove,
Repair/Remove, and accessibility sizes reflow below it with 44-point targets. Installed and
update-available models expose `iosModelDelete_<id>` without an overflow-menu discovery step and
retain the named confirmation. `iosModelStatus_<id>` reads `Ready` when usable. The installation
bar renders exact durable logical catalog-byte progress while transfer is incomplete, reserving a
visible trailing rail segment so a 99% rounded capsule cannot look finished. Transfer completion,
verification, and installation replace the bar with named indeterminate activity; only `Ready` is
terminal. Restored percentage, bytes, speed, and ETA are reconciled from the same presentation
value. Normal smoke and benchmark lanes do not install or delete models; they visibly assert that
Custom, Design, and Clone Speed are ready before generation.

Settings also owns the persistent Clone consent row
`voiceCloning_consentAcknowledgment` under Settings → Privacy. Smoke and benchmark enable it through that visible row when
needed so Clone acceptance starts from an explicit consent state; this preference intentionally
remains enabled for later testing. The benchmark may temporarily enable Auto-play and restores its
prior value. System permission enrollment is attended setup.

## Sheets and accessibility

Important transient surfaces include voice and clone-reference pickers, the Design brief editor,
delivery/language controls, the player, History actions, model confirmations, and system pickers.

All controls used by autonomous tests retain stable `accessibilityIdentifier` values. Tests use
condition-based waits and assert the visible enabled/readiness/completion state needed by the active
scenario. Named screenshots are attached at important states and failures; labels and coordinates
are not selector fallbacks. VoiceOver, Dynamic Type, Reduce Motion, and Reduce Transparency remain
product accessibility requirements, but are not claimed as coverage of the minimal lanes.

## Test routing

| Goal | Command |
| --- | --- |
| Device/environment readiness | `scripts/ios_device.sh preflight` |
| Physical-device UI regression | `scripts/ui_test.sh ios smoke` |
| Full UI generation matrix | `scripts/ui_test.sh ios benchmark` |
| UI frame-health scenarios | `scripts/ui_test.sh ios perf` |
| Physical-device deterministic/runtime diagnostic | `scripts/ios_device.sh gate` |

Never use an iOS Simulator, Simulator Browser, alternate desktop/mobile UI driver, or committed
coordinate table.
