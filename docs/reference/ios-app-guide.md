---
status: active
owner: ios
reviewed: 2026-09-10
summary: Consolidated iPhone app map — every screen, element, and option from the user view, and how XCUITest drives each via stable identifiers on the paired physical device.
sourceOfTruth:
  - Sources/iOS
  - Sources/iOSSupport/Services/IOSDeviceEligibilityPolicy.swift
  - Sources/SharedSupport/Services/ReferenceTranscriptionReviewState.swift
  - Sources/SharedSupport/Services/VoiceClipTranscriber.swift
  - Sources/QwenVoiceCore/GenerationSemantics.swift
  - Tests/VocelloiOSUITests/VocelloiOSUITestCase.swift
---
# Vocello for iPhone — app guide + test-driving reference

## iOS export purchase

Generation, listening, internal History and voice enrollment remain free. One iOS non-consumable
unlocks outward Design/Clone audio export. Built-in exports remain free; macOS and CLI are unchanged.
The approved product and USD 19.99 US-base/automatic-regional price schedule exist in App Store
Connect. Product metadata/availability and physical purchase acceptance remain pending under
RF-13/RF-02/RF-12; this is not an available or reviewed purchase.

This is the official iOS app's export purchase, not a restriction on the MIT-licensed source.
Self-built forks may change the checks; they do not acquire an official Apple entitlement by doing
so. No licensing server or obfuscation is planned to prevent source modification. Keep public product
configuration separate from private developer credentials as described in the
[security boundary](../../SECURITY.md#open-source-purchase-boundary). Unmodified self-builds are not
promised live purchase support under a different signing identity; use the isolated test fixture only
through the governed test route, never a shipping unlock or production credential copied from the maintainer.

- Studio Save/Download, expanded-player Share, History/segment export and optional Files folder
  copying use the **finished output's mode**, never the current Studio selection. Unknown generated
  modes require unlock. Internal storage and playback never consult the entitlement.
- Settings → **Design & Clone Export** (`iosSettings_exportPurchaseRow`) opens purchase options.
  `exportPurchase_buy` displays the StoreKit-localized one-time price; `exportPurchase_reload` handles
  product unavailability; `exportPurchase_restore` explicitly syncs. Pending, cancellation and
  verification failures have visible status. `exportPurchase_close` dismisses without export.
  Close and request export again after purchase: it never silently shares a previously selected clip.
- Automatic folder copying never starts a purchase or changes the folder. Without verified access,
  including startup checking, paid-mode clips remain in History for manual export afterward. The
  folder explanation states this behavior.
- New Design-generated Saved Voices retain `generatedSourceMode` in existing enrollment metadata
  through candidate commit and reference playback. Imported/recorded originals remain recoverable
  for free. Legacy Saved Voices lack origin metadata and stay exportable without retrospective
  inference, rewriting or deletion. Existing History entries already record their generation mode.
- Actual failed-storage recovery audio/journals remain freely exportable. Only the existing enqueue/
  outbox recovery surfaces provide this exception; ordinary History/player/folder exports do not.
  This preserves the rule against making data recovery a payment demand.
- Refund/revocation removes paid export access, **never clips, voices, drafts, History or playback**.
  Access uses verified StoreKit entitlements and its offline cache, not a local paid flag. No app
  server, cloud inference, login, diagnostics bypass or receipt logging was introduced.

The existing stateful control audit owns options-sheet reachability/dismissal and explicitly blocks
purchase actions pending an approved StoreKit/sandbox session. It never buys or invokes Restore.
The opt-in `scripts/ui_test.sh ios purchase --retain-result` lane uses Apple StoreKitTest and a
fixture bundled **only in the UI-test target**. It attempts the local transaction lifecycle through
the real purchase sheet, never live purchases. The fixture price and native Xcode environment must
match before Buy; the test refuses preexisting local transactions and removes only its own afterward.
This is separate from sandbox/TestFlight, offline and complete paid/free export-route acceptance.
The [submission procedure](ios-appstore-submission.md#1-privacy--compliance-app-store-connect) owns
focused physical purchase acceptance and the remaining product metadata/account work.

A consolidated map of the Vocello iOS app: what every screen/element/option does (user
view) and how XCUITest drives it (stable identifier → action → expected). Use this to understand the
app before touching `Sources/iOS/`. All iOS UI work runs on a paired physical device; MLX cannot
initialize on the iOS Simulator.

> **Where this fits:** this is the canonical "what the app is + how to drive it" reference.
> The testing strategy lives in [`testing-runbook.md`](testing-runbook.md);
> device lanes (`scripts/ios_device.sh`) in [`ios-device-testing.md`](ios-device-testing.md);
> generation-engine internals in [`../ARCHITECTURE.md`](../ARCHITECTURE.md);
> tone/delivery prompt-writing in [`../qwen_tone.md`](../qwen_tone.md).
> String Catalog ownership, typed presentation text, and pseudo-localization acceptance are in
> [`localization.md`](localization.md).
> The compact UI state map is [`ios-ui-reference.md`](ios-ui-reference.md). XCUITest is the only
> autonomous iOS app UI driver.

---

## 1. Overview

Four tabs across the bottom (`rootTab_*`), with **Studio** as the default surface:

| Tab | `rootTab_*` | Purpose |
|-----|-------------|---------|
| Studio | `rootTab_studio` | Compose + generate (three modes — see below) |
| Voices | `rootTab_voices` | Browse built-in speakers + saved (cloned/designed) voices |
| History | `rootTab_history` | Past generations: replay, export, delete, search |
| Settings | `rootTab_settings` | Voice models, clone consent, playback/variation/accessibility prefs |

Three generation modes (Studio segmented control `generateSection_*`):

- **Built-in Voice** (`generateSection_custom`) — pick a built-in speaker + optional delivery.
- **Voice Design** (`generateSection_design`) — describe a voice in natural language.
- **Voice Cloning** (`generateSection_clone`) — use a saved voice, record a new reference, or
  import audio from Files and enroll it permanently.

The UI is what this guide drives. Headless, non-UI device diagnostics are documented in
[`ios-device-testing.md`](ios-device-testing.md); that path is separate from XCUITest.

The App Store bundle requires `arm64` and Apple's `iphone-performance-gaming-tier`, aligning
installation eligibility with Vocello's iPhone 15 Pro-or-newer runtime guard before the first
public version. `IOSDeviceEligibilityPolicy` owns the source-level predicate and description;
archive/IPA verification rejects any capability drift.

---

## 2. The app, screen by screen

### Onboarding (first run) — `Sources/iOS/Overlays/IOSOnboardingFlow.swift`

Three pages (Welcome → Install → Ready). Controls: `onboarding_skip` (top-right on pages
1–2) and `onboarding_cta` (primary button; label changes per page: "Get started" →
"Continue" → "Open Studio"). Tests interact with these visible controls. There is no hidden
onboarding bypass.

### Studio — `Sources/iOS/IOSStudioCanvas.swift`, `IOSGenerationModeViews.swift`

The mode segmented control is `generateSectionPicker` (`.contain`) with
`generateSection_custom|design|clone`. Tests establish Studio state from the visible root tab,
mode segments, composer, and primary action; there is no hidden screen-presence marker.

| Element | Identifier | Notes |
|---|---|---|
| Mode segment | `generateSection_custom\|design\|clone` | Tap to switch mode (keeps its id — not shadowed) |
| Script composer | `textInput_textEditor` | Multi-line; live char counter `textInput_lengthCount`; over-limit warning `textInput_limitMessage` |
| **Generate CTA** | `textInput_generateButton` | Shown when the mode's model is installed |
| **Install CTA** | `textInput_installModelButton` | Shown instead of Generate when the model is **missing** (see §3) |
| Cancel | `textInput_cancelButton` | Inside the generating progress bar |
| Error retry | `textInput_generationError` | Retry bar on a failed generation |
| Player controls | `studio_livePreview_playPause`, `studio_livePreview_cancel`; `studio_inlinePlayer_playPause`, `studio_inlinePlayer_save`, `studio_inlinePlayer_download`, `studio_inlinePlayer_dismiss` | Live streaming preview and completed-take controls. The enclosing SwiftUI card has no test identifier. |
| Cadence review | `studio_inlinePlayer_cadenceNotice`, `studio_inlinePlayer_cadenceRetry` | An accepted take with unusual pause spacing remains playable and saved, but exposes a non-color-only warning and an explicit “Generate again” action using the currently visible settings. Severe gaps remain rejected before this surface. |

**Selector pills (chips)** — `studioChip_*` identifiers are directly queryable in Studio. Per mode:

| Mode | Identified pills |
|---|---|
| Custom | `studioChip_voice` → voice picker · `studioChip_delivery` · `studioChip_language` · `studioChip_seedPin` (only while a seed is pinned) |
| Design | `studioChip_voiceBrief` → brief editor · `studioChip_delivery` · `studioChip_language` · `studioChip_seedPin` (conditional) |
| Clone | `studioChip_reference` → saved voice, `referenceClip_recordNewClip`, or `referenceClip_importAudioFile` · `studioChip_bankDelivery` (only while a bank member is selected) · `studioChip_language` · `studioChip_seedPin` (conditional) |

`studioChip_seedPin` (DP-15) shows the pinned sampling seed; tapping offers the unpin
confirmation, returning to a fresh seed per take. `studioChip_bankDelivery` (DP-16) shows the
selected emotion-bank persona's current delivery and opens the bank member sheet below.

Clone reads the persistent `voiceCloning_consentAcknowledgment` preference from Settings. Generate
remains unavailable until the user acknowledges consent there. The optional transcript selects
transcript-backed conditioning; no transcript selects the separate audio-only x-vector path. The
reference transcript's language describes the conditioning clip only. Auto output language always
resolves from the script being synthesized; an explicit Studio language always wins.

Studio lifecycle state is attempt-scoped. `StudioGenerationCoordinator.start` returns an opaque
token that every single-take and long-form live or terminal callback must present. Delayed success,
failure, deferred cleanup, or cancellation callbacks from an older take therefore cannot clear or
replace a newer take. Cancel keeps the matching attempt nonterminal until the engine-owned
cancellation barrier returns; a barrier failure is shown to the user, and a repeated Cancel cannot
start a second barrier for the same attempt.

Short-form Built-in, Design, and Clone takes share one execution boundary in
`IOSSingleTakeGenerationExecutor`. Views construct the exact mode request and perform any
mode-specific preparation (including Clone priming), then the executor singularly owns frontend
timeline submission/terminal recording, engine invocation, materialized-output cancellation
cleanup, playback handoff, History outbox persistence, and optional Files export. Successful
inline-card publication remains attempt-scoped in the view after the shared boundary returns.

### Bottom sheets — `Sources/iOS/Sheets/IOSBottomSheets.swift`

Sheets are separate overlays, so **inside-sheet elements keep their own identifiers**
(not shadowed). Every sheet has a confirm header and/or `bottomSheet_close` (×).

**Voice picker** — rows `voicePickerRow_<id>`, per-row preview `voicePickerPreview_<id>`,
confirm `voicePicker_confirm`. Selecting a row is **provisional** (sheet stays open) —
tap Confirm to commit + dismiss. Preview plays audio without selecting/closing.

**Language picker** — rows `languagePicker_<rawValue>` (e.g. `languagePicker_auto`,
`languagePicker_english`), confirm `languagePicker_confirm`.

**Delivery picker** — confirm `deliveryPicker_confirm`; a 2-column preset grid in two labeled
sections per the DP-14 measured split — "Distinct deliveries" (Neutral/Calm/Whisper/Sad) then
"Directional hints" (Happy/Angry/Fearful/Surprised) — with cells `deliveryPickerPreset_<presetID>`
and the hints advisory as the section footer (`deliveryPickerSheet_hintAdvisory`); and a custom
tone editor: `deliveryPickerSheet_customTone` (toggle in), `deliveryPickerSheet_customTone_editor`
(text, `/500` counter `deliveryPickerSheet_customTone_charCount`),
`deliveryPickerSheet_customTone_examples`, `deliveryPickerSheet_customTone_back`.

**Bank delivery picker** (Clone only, DP-16) — `IOSBankDeliveryPickerSheet`: one row per bank
member (`bankDeliveryRow_<voiceID>`; Neutral is the persona's base voice, each emotion row that
delivery's verified reference). Selecting applies the concrete member voice through the ordinary
`applySavedVoice` path and dismisses.

**Voice brief editor** (Design only) — `voiceBrief_editor` (multi-line) + `voiceBrief_confirm`.

### Voices tab — `Sources/iOS/IOSVoicesView.swift`

Container `screen_voices`. Filter chips `voicesFilter_all|builtIn|saved`. Built-in rows
`voicesRow_<speakerId>` (e.g. `voicesRow_aiden`); saved-voice rows `voicesRow_saved_<id>` (an
emotion-bank member's caption reads "Voice bank · <Delivery>"; standalone voices read "Cloned
reference" — every member stays listed because each reference clip is individually previewable).
The Save a New Voice card has one visible action: `voices_saveNewVoice` starts the recorder
(iPhone also imports reference files — the "Import audio file" row, `voices_importAudioFile`,
presents a native `fileImporter` for WAV/MP3/AIFF/M4A and continues through the same
name → review sheet, restored 2026-08-15; a saved Voice Design voice can also serve as the
clone reference through the Studio handoff). Studio Clone exposes the same permanent-enrollment
pipeline directly through `referenceClip_importAudioFile`; it dismisses the custom reference panel
before presenting Files and never creates a session-only reference. The enrollment sheet exposes
`saveVoice_nameField`, `saveVoice_transcriptEditor`, `saveVoice_transcriptionStatus`,
`saveVoice_referenceLanguagePicker`, `saveVoice_useAudioOnlyButton`, and `saveVoice_saveButton`. A
matching `.txt` sidecar is preferred;
otherwise `VoiceClipTranscriber` starts automatically on device, keeps Save disabled until the
result is reviewable, and cannot replace a manual edit with a delayed result. If recognition cannot
produce text, the user must enter text or explicitly choose Use audio only. A transcript whose
language remains inconclusive also requires an explicit Reference language selection. The app
persists typed, privacy-safe enrollment evidence (source, outcome, attempted locale order,
availability/on-device support, scores, confidence, and an evidence digest) beside the saved voice;
it stores no diagnostic transcript copy or raw Speech error. The reviewed transcript and reference
language survive relaunch, while delayed recognition can never overwrite a sidecar or manual edit.
Save prepares an opaque
candidate that does not enter the catalog until any quality warning is explicitly kept. Cancel, Discard, and
outside dismissal discard the candidate. A successful commit creates `voicesRow_saved_<id>` and
hands the reference to Studio Clone. Each saved row exposes `voicesRowMenu_<id>` with
`voicesDelete_<id>`; confirmation `voicesDeleteConfirm_<id>` names the exact voice and explains
that deleting one voice-bank member leaves the others. Delete stops a matching preview, removes
the engine assets and prepared prompt caches, and clears a matching Studio draft/handoff; failures
remain visible and retryable. Search is `voicesSearchField`.

Explicit F-01/ICI-4 device acceptance is `scripts/ui_test.sh ios saved-voice-lifecycle`. It requires
`ICI Direct Clone Import.wav` without a matching `.txt` staged in the app Documents directory and
drives the genuine direct Clone import, automatic transcription, permanent enrollment, Clone
generation, preview, confirmation, deletion, and draft-cleanup surfaces. It never runs in ordinary
CI or release work.

### History tab — `Sources/iOS/History/HistoryScreen.swift`

Search `historySearchField`; clear menu `historyClearMenu` → `historyClearKeepFiles` /
`historyClearDeleteFiles`; retry `historyRetryButton`. Mode-filter chips
`historyModeFilter` container + `historyModeFilter_all|custom|design|clone`. Rows:
`historyRow_<id>`, tap area `historyRowTap_<id>` (opens player), menu `historyRowMenu_<id>`
(Play / Save audio / Pin seed / Delete — the pin item `historyRowPinSeed_<id>` appears only for
takes with a recorded seed and lands in that take's Studio mode with `studioChip_seedPin`
visible), delete-confirm `historyRowDeleteConfirm_<id>`. Grouped by Today /
Yesterday / Previous 7/30 Days / Earlier.

Database failures are typed and fail closed. The error state does not masquerade as empty History;
destructive actions remain disabled until `historyRetryButton` completes a successful read.
Published single takes are written to the local `history-outbox/`, when storage permits, before their
idempotent SQLite commit. Startup and History entry reconcile pending rows. If attention remains,
`historyRecovery_banner` exposes `historyRecovery_retry` and `historyRecovery_export`; clear-all
uses a resumable database-first marker so a database failure cannot delete audio behind live rows.
If the outbox write itself fails, the app-wide `historyUnqueued_banner` offers
`historyUnqueued_retry` and `historyUnqueued_export` while successful audio stays playable.
That retry identity is app-session memory, not crash-safe recovery; export before quitting if
retry fails. Manual storage retry never regenerates audio. Clear-all refuses unqueued records.

Long-form generation and segment regeneration await the shared journaled acceptance boundary.
Unique candidate audio, segment/joined QC, and manifest serialization precede accepted History
mutation. A failed replacement retains the previous accepted project; interrupted commits are
reconciled before History is read or written. Progress counts unique completed segments, including
reused ones, once. Completed segments are individually saved and remain exportable/deletable in History after
abandonment or relaunch; project continuation is still in-session only. They are not reported as
a saved project until whole-project acceptance succeeds. Manifest v4 stays compatible;
generation continuation is not restored across app launches.

A corrupt long-form journal does not hide unrelated standalone History. Project rows stay withheld
and mutations fail closed; Export Recovery Files can retain the private bounded journals for repair.
The warning explains that exports may include script text and local paths; exporting does not repair
or delete the originals.

### Settings tab — `Sources/iOS/Settings/SettingsScreen.swift`

The compact Settings heading (`iosSettings_title`, localized as Réglages) introduces the hub
(`screen_settings`) and its three flat groups: Audio, App Language and Models & Files;
Design & Clone Export; Privacy & Permissions, Accessibility, and About. The shared tab dock is
unchanged. Six `iosSettings_<category>Row` links push into the existing Settings navigation stack;
categories are `audio`, `appLanguage`, `modelsFiles`, `privacyPermissions`, `accessibility`, and `about`.
Each has `screen_settings_<category>` and a 44-point `iosSettings_<category>BackButton`.
No nested navigation stack is introduced. App Language adds a UI-only persisted preference,
defaulting to System Default, then native-name choices from complete bundled translations
(currently English and French). It does not select the language of generated speech. The
observable app-lifetime owner updates typed display copy without replacing runtime dependencies;
system dialogs may retain the OS language. English/French switching, relaunch and draft checks have
partial physical evidence; full AX-XXXL/pseudo layout acceptance and the remaining eight translation
batches are still pending under ASR-12/ISU-4.

Audio retains `iosSettings_autoPlayToggle` (default on) and the unchanged
`iosSettings_variationRow` menu. Models & Files owns `iosSettings_voiceModelsRow` and
`iosSettings_savedOutputsRow`, including the existing History/folder picker and bookmark behavior.
Accessibility owns `iosSettings_reduceMotionToggle` and `iosSettings_reduceTransparencyToggle`.
Privacy & Permissions retains `voiceCloning_consentAcknowledgment`, its full legal disclosure,
`iosSettings_privacyPolicyRow`, and `iosSettings_openIOSSettingsRow`. About owns
`iosSettings_supportRow`, `iosSettings_openSourceRow`, `iosSettings_sourceCodeRow`, and the
dynamic, non-interactive `iosSettings_versionLabel`. Support and Source Code retain their URLs.
Rows use decorative symbols, wrapping labels and subordinate trailing values at ordinary sizes;
values and the variation picker reflow below their labels at accessibility sizes. No forced
Dynamic Type limit or fixed-width value column is used. Models & Files and Accessibility have
short contextual introductions. About starts with a compact Vocello identity, local-voice tagline
and the installed bundle's version/build, rather than a duplicate version row. The unchanged
cloning disclosure sits outside its consent card, before the policy and permissions group.
Decorative symbols fit 20-point artwork inside 28-point slots; Back chevrons stay within their
44-point controls with a muted surface. Text retains semantic scaling. At accessibility sizes, switch tracks reflow
below their labels rather than reserving a narrow trailing column.

The restrained gold `iosSettings_exportPurchaseRow` opens the same purchase sheet as all export
entry points. Its summary reflects locked/checking/unlocked state and never displays a price.
The sheet separates the benefit, free functionality, one-time/no-subscription reassurance,
full-width live StoreKit-price action, Restore, policy/support links, and thank-you text. All
purchase states, disabling rules and explicit post-purchase export retry remain unchanged.
If product information cannot load while verified export access is already unlocked, the notice
explicitly confirms that exports remain available. Product availability does not revoke access.
New Settings/purchase presentation copy is typed and includes English/French catalog entries.
Settings variation names and model names/actions/statuses are localized display values; saved
variation raw values, model IDs, installation behavior and purchase policy remain unchanged.
The existing Settings localization walk includes a French-Default pass alongside the four
English layout configurations. Shared lifecycle tests explicitly select English in the app's
process-local launch arguments; localization walks may override it, and the phone's persisted
language is untouched. Compilation alone does not qualify that physical-device journey.
Current-source physical visual, accessibility and purchase acceptance require separate authorization;
historical Settings and local StoreKit passes are not proof for the refined layout.

`iosSettings_openSourceRow` pushes `screen_openSourceLicenses`. The offline browser is generated from
the exact application SwiftPM resolution, owned-runtime license/NOTICE/origin records, and the six
production model revisions. Rows expose `iosAttributionRow_<componentID>` and
`iosModelAttributionRow_<modelID>-<variantID>`; the 44-point
`iosSettings_openSourceBackButton` returns to About. Each detail exposes complete license text,
applicable NOTICE/origin text, pinned identity, and the upstream source without requiring network access.
The resource is fail-closed in deterministic and archive/IPA verification.

`iosSettings_voiceModelsRow` pushes the dedicated `screen_voiceModels` destination. That screen
keeps the system navigation bar hidden and provides the compact 44-point
`iosSettings_voiceModelsBackButton` returning to Models & Files, the `iosSettings_storageRow` summary, and the three
`iosModelRow_<modelID>` lifecycle rows (full state contract below). Both surfaces derive their
bottom content clearance from the greater of the shared fade metric and RootView's measured dock
height, plus the existing spacing. The same environment value serves Settings detail and attribution
scroll content. These surfaces reflow values/actions vertically
at accessibility Dynamic Type sizes. At ordinary text sizes each model keeps its icon, name,
metadata, textual status, and sole valid action in one compact summary row; two-action states and
accessibility sizes reflow below the summary without reducing the 44-point control targets.

### Player + overlays

Full-screen player (`Sources/iOS/Sheets/IOSPlayerSheet.swift`):
`iosPlayer_playPause`, `iosPlayer_download` (labeled "Share"),
`iosPlayer_scrubber`, `iosPlayer_transcript`, and — only when a caller
supplies a distinct save handler — `iosPlayer_save`. Recording overlay (`Sources/iOS/Overlays/IOSRecordingOverlay.swift`):
`iosRecord_close`, `iosRecord_start` / `iosRecord_stop`, `iosRecord_retake`, `iosRecord_use`.
Lifecycle toasts (`IOSEngineLifecycleToast.swift`) are transient ("Preparing runtime",
"Model loading") and labeled with `engineLifecycleToast_<id>`.

---

## 3. Model download management & state (generation precondition)

**A generation is impossible without the mode's model installed.** Three mode models map
to the contract: `pro_custom` (Custom), `pro_design` (Design), `pro_clone` (Clone). iOS
ships the **Speed (4-bit)** variant only (Quality is macOS-only); the iOS-eligible set
comes from `qwenvoice_ios_model_catalog.json`.

### Per-model states (Settings → Voice Models, `iosModelRow_<modelID>`)

| State | Visible control | What it means |
|---|---|---|
| Not installed | `iosModelDownload_<id>` ("Install") | Default; nothing staged |
| Queued / waiting / downloading / retrying | `iosModelCancel_<id>` (visible "Cancel"; VoiceOver "Cancel download") plus phase/progress detail | Durable request awaiting its turn or connectivity, actively transferring, or applying a typed retry |
| Verifying / installing / cancelling / deleting | Text-and-symbol status plus phase detail | Hash/receipt validation, atomic install, cancellation barrier, or removal is in progress; no invalid competing action is shown |
| Failed | `iosModelRetry_<id>` ("Retry") | Retry preserves verified files |
| Incomplete | `iosModelRepair_<id>` ("Repair") plus `iosModelDelete_<id>` ("Remove") | Repair revalidates the incomplete package; Remove discards it through the named confirmation |
| Installed | `iosModelStatus_<id>` ("Ready") plus `iosModelDelete_<id>` ("Remove") | Ready to generate; removal is visible without opening an overflow menu |
| Update available | `iosModelUpdate_<id>` ("Update") plus `iosModelDelete_<id>` ("Remove") | Installed and still usable, but the pinned catalog identity moved on; Update re-downloads the changed files through the authenticated delivery path |

Cancel opens a confirmation dialog: `iosModelCancelDownloadConfirmButton` (cancel, deletes staged
data). There is no paused state or Resume control. Waiting for connectivity comes from URLSession;
an active task separately reports no progress after 20 seconds. `iosModelProgress_<id>` exposes
exact `durable logical catalog bytes / catalog bytes` while transfer is incomplete. The visible
detail derives its percentage and byte counts from that same presentation value, alongside
smoothed speed, ETA, retry reason, and verified-file reuse. Transfer completion replaces the
determinate bar with `Download complete — finishing setup`; verification and installation use
indeterminate `Checking downloaded files` and `Making the model available offline` activity.
Only terminal `Ready` is complete. MD-3's physical-device closure proved this UI truth remains
correlated with authenticated publication across cancellation, adoption, shared-component reuse,
three-model installation/removal, and relaunch; the lane remains the regression authority.

One bundle-aware background URLSession lives for the app lifetime. On launch, the atomic v2 ledger
and current catalog adopt exactly matching tasks, cancel stale/unknown/duplicate tasks, and create
only missing tasks. Progress remains monotonic through backgrounding, process relaunch, and retry.
Delegate files move into durable App Group staging before the callback returns, and UIKit's
background completion waits for durable install/failure postprocessing. Full contract:
[`model-delivery.md`](model-delivery.md).

The explicit `scripts/ui_test.sh ios model-download` procedure follows this redesigned state model
instead of assuming an empty screen: it snapshots canonical readiness, normalizes only its fixed
test-owned root through visible Cancel/Retry/Remove controls, verifies the `Not Installed` →
`Downloading` → `Ready` action contract, confirms one real cancellation and restart, adopts the
restarted Custom transfer across termination/relaunch, installs Design and Clone, removes all three
through their named confirmations, and finally proves the canonical snapshot is unchanged. A
five-minute no-advance watchdog now distinguishes an advancing slow transfer from a stuck adopted
request, captures the stalled row, and drives isolated visible cleanup before restoring the
canonical snapshot.

### The Studio gates generation on the installed model

The composer's primary CTA reflects model readiness:

- **Model missing → `textInput_installModelButton`** (Install CTA; `textInput_generateButton` absent).
- **Model installed → `textInput_generateButton`** (Generate CTA).

Tapping **Install [mode]** opens Settings → Models & Files → Voice Models and immediately
requests that mode's model through the existing app-lifetime installer. There is no second Install
tap. The selected descriptor is captured at the tap; Studio text, selections and references stay
unchanged. Ordinary Settings navigation and Back do not start or replay downloads. Progress,
queueing, cancellation, storage checks and errors remain owned by the normal model-delivery path;
installation does not automatically start generation. The isolated model-download acceptance lane
exercises this shortcut for Built-in, Design and Clone; no normal smoke lane downloads models.

So "is this mode ready to generate?" is **test-readable from the Studio surface**: if
`textInput_installModelButton` is present, the model isn't installed.

### Generation-test preconditions

**Always confirm the mode's model is installed before composing/generating.** XCUITest requires
Generate rather than Install. Destructive install/cancel/delete actions are outside normal lanes.

### Model lifecycle sequence

- **Install:** Settings → Voice Models → `iosModelDownload_<id>`.tap() → (wait for complete → `iosModelStatus_<id>` = "Ready").
- **Cancel:** `iosModelDownload_<id>`.tap() → `iosModelCancel_<id>`.tap() →
  `waitForConfirmationButton("iosModelCancelDownloadConfirmButton")` → tap it → Install reappears.
- **Retry/cancel:** Retry a failed request with `iosModelRetry_<id>` to reuse verified files. Cancel
  an active request with `iosModelCancel_<id>`, then confirm `iosModelCancelDownloadConfirmButton`;
  staging is removed only after URLSession cancellation callbacks and tasks are terminal.
- **Delete:** `iosModelDelete_<id>`.tap() → `deleteModelSheet_confirm`.tap() → Install reappears.
  The compatibility container identifier `iosModelMenu_<id>` remains around the visible Remove
  action for older automation; new tests drive `iosModelDelete_<id>` directly.

---

## 4. What each option means

### Modes

- **Built-in Voice** — a built-in Qwen3 speaker reads your script, with an optional delivery
  style. Fastest, most consistent path.
- **Voice Design** — describe a voice in plain language (character, age, accent, gender,
  pitch); the model invents a new voice from that brief each call. Name gender + concrete
  pitch register to avoid underspecified results. The result can be saved and reused in Clone.
- **Voice Cloning** — supply a reference clip by recording in-app on this iPhone, selecting a
  saved voice, or importing a WAV, MP3, AIFF, or M4A file directly from the Clone reference panel.
  A neighboring `.txt` file prefills an imported clip's transcript; otherwise the same on-device
  recognizer used for recorded enrollment runs automatically. The editable review must resolve to
  text or an explicit Use audio only choice before Save becomes available. Enrollment permanently
  saves the app-owned reference and hands it directly to Clone. The transcript is optional after
  that explicit review: its presence selects transcript-backed
  conditioning, while an empty transcript uses the genuine audio-only x-vector path. The visible
  Settings control `voiceCloning_consentAcknowledgment` must be enabled before Generate. Saved
  voices from the Voices tab are reusable references. Clone
  cannot take a separate delivery instruction on current checkpoints — the delivery must live in
  the reference clip. Curated emotion reference banks make that practical: a bank persona's
  members enroll as ordinary saved voices ("Voice bank · <Delivery>" captions in Voices), and
  selecting the persona in Clone offers a Delivery chip that swaps between its verified
  per-emotion references ([emotion-reference-banks.md](emotion-reference-banks.md)).

### Speakers (Built-in Voice) — `qwenvoice_contract.json`

9 built-in: **Aiden, Ryan** (English) · **Vivian, Serena, Uncle Fu, Dylan, Eric** (Chinese) ·
**Ono Anna** (Japanese) · **Sohee** (Korean). Default: Aiden. Speakers carry baked-in
delivery biases (e.g. Ryan is naturally expressive; start from Aiden/Serena for a neutral read).

### Delivery — `Sources/QwenVoiceCore/EmotionPreset.swift`

8 presets: **Neutral** (a real instructed preset since 2026-08-01), plus
**Happy, Sad, Angry, Fearful, Surprised, Calm, Whisper** — one instruction each. The picker is
sectioned by the measured DP-12/DP-14 split: **Neutral, Calm, Whisper, Sad** are distinct
deliveries a listener identifies above chance (`EmotionPreset.distinctDeliveryIDs`); **Happy,
Angry, Fearful, Surprised** are directional hints that move energy and pace reliably while the
named emotion may not land on every take, and selecting one shows the shared advisory copy.
`Excited` and `Dramatic` were retired 2026-08-03 (DP-10): both scored below the chance floor for
cross-preset separability, so neither was a control a listener could act on.
The user-facing **intensity** control was retired 2026-08-02: DP-3 measured the `strong` copy at
nearly double the recognisability of `normal` (mean per-preset recall 0.278 against 0.157, chance
0.053) and showed the two tiers are not separable from each other, so every preset now ships its
strong copy. `EmotionIntensity` survives internally so the delivery matrix harness can still address
both texts and drafts saved earlier resolve to exactly what they stored. Or write a **custom tone** (free text, 500-char cap) — see
[`../qwen_tone.md`](../qwen_tone.md) for the prompt-writing rules (combine emotion + pace +
pitch + timbre; negative constraints like "without laughing" work; write instructions in
English or Chinese regardless of output language; describe the sound, not a persona).

### Languages — `GenerationSemantics` / language picker

**Auto** (detected from the script's Unicode ranges / `NLLanguageRecognizer`) or pinned to
one of 10: English, Chinese, Japanese, Korean, German, French, Russian, Portuguese, Spanish,
Italian. The instruction/brief language and saved-reference language are independent of the
spoken-text language. Clone Auto uses target text, not the language of its reference transcript.
Schema-2 generation receipts retain stored selection, detected target, reference transcript,
final model language, think/no-think token mode, and conditioning mode separately.

### Cross-cutting

- **Speed vs Quality** — iOS is Speed-only (smaller, faster, lower memory). Quality (8-bit) is macOS-only.
- **Reproducible takes** — Settings → `iosSettings_variationRow`: **Expressive** (most variety,
  default) / **Balanced** / **Consistent** (most stable). Each generation records its effective
  seed in History (schema v6); "Pin seed" on a History row reproduces that take on demand and the
  Studio Seed chip shows/unpins the state (DP-15). Batch
  generation is intentionally absent from iOS.
- **Text limits** — enforced live (`textInput_lengthCount` + `textInput_limitMessage`); custom-tone cap `/500`.

---

## 5. Driving through XCUITest

`VocelloiOSUITests` uses stable accessibility identifiers, condition-based waits, and shared test
support. Coordinates, OCR taps, and label-only fallback tables are not accepted test selectors.

Canonical flows remain:

- Onboarding → Studio: advance or skip until the Studio tabs and composer are visible.
- Custom: select Custom, confirm model readiness, configure voice/delivery/language, compose,
  Generate, then verify the completed player and matching deterministic evidence.
- Design: select Design, enter a voice brief, compose, Generate, and verify telemetry.
- Clone: enable consent through Settings, select Clone, choose a saved reference, compose,
  Generate, and verify telemetry.
- History: open the History tab, find the generated take, and replay it.
- Settings: review model and preference state; visibly enable persistent Clone consent for
  acceptance, and restore temporary reversible changes such as Auto-play.

Gotchas:

1. Picker selection is provisional until its visible Confirm action is activated.
2. Dismiss the keyboard before Generate when it obscures the button.
3. Wait for cold model loading rather than repeating a click.
4. Attach named screenshots at important semantic states and failures.
5. Recording and destructive model lifecycle actions are outside smoke and benchmark. The isolated
   physical-device model-delivery proof is selected explicitly with
   `scripts/ui_test.sh ios model-download` and cleans up through visible Settings controls.
6. Settings clearance uses the genuine `rootTabDock` container, not a single tab button (the dock
   has two rows at accessibility sizes). Production bottom padding follows the measured dock
   height rather than a fixed Dynamic Type estimate. Layout assertions require the entire element within the
   unobscured viewport. Explicit oversized-navigation activation instead requires a visible central
   44-point band and XCUI hittability; this is never accepted as full-row layout evidence.

---

## 6. Remaining test-coverage gaps (driveability backlog)

Most interactive controls now carry an `accessibilityIdentifier`. If a future scenario needs a
control without one, add a stable identifier before automating it; label-only and coordinate
fallbacks are not supported.

- ~~Player sheet scrubber + transcript~~ — **closed 2026-07-02**: the scrubber is an adjustable VoiceOver element (`iosPlayer_scrubber`, "Playback position" + value) and the karaoke transcript reads as one prose element (`iosPlayer_transcript`).
- **Mode meta labels** ("Built-in voice" / "Designed voice"), section headings, empty-state cards,
  and sheet titles are currently descriptive rather than test-driving targets.
- **Lifecycle toasts** — transient, but labeled with `engineLifecycleToast_<id>`.

A separate, optional follow-up is consolidating **all** ids (most are inline string
literals today) into `Sources/iOS/IOSAccessibilityIdentifiers.swift` so they're grep-able
constants — a refactor, not a behavior change.
