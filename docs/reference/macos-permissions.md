---
status: active
owner: macos
summary: macOS TCC permissions, code signing, and the dev loop — what users experience, why the historical friction is gone, and permissions_doctor.sh diagnosis.
sourceOfTruth:
  - scripts/permissions_doctor.sh
  - Sources/QwenVoice.entitlements
---
# macOS permissions (TCC), code signing, and the dev loop

The single source of truth for how Vocello interacts with macOS privacy
permissions — why the project used to fight TCC constantly, how that's fixed,
what end users experience, and how to diagnose problems.
Diagnose anything permission-related with **`scripts/permissions_doctor.sh`**.

## The TCC model (why this was ever a problem)

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

## How each build flavor is signed

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
  *and* the embedded XPC service ended up signed as expected.
- The dev-signed app and the shipped (Developer ID) app have different
  designated requirements, so the installed release prompts once on its own —
  expected.
- First signing with a new certificate may show a keychain prompt
  ("codesign wants to sign…") — choose **Always Allow**.
- Switching ad-hoc → certificate leaves stale TCC rows behind; reset once:
  `scripts/permissions_doctor.sh --reset-tcc` (then grant on next launch).
- **UI-lane builds are ad-hoc signed** (`scripts/ui_test.sh` builds with
  `CODE_SIGN_IDENTITY="-"`), so they never match the dev identity's TCC grant: any *real*
  microphone request from a lane-built app prompts fresh, and answering it re-keys the row to that
  build's throwaway identity (the next real-mic use of the dev-signed app may then prompt once —
  grant it; stable signing keeps it). In practice lane builds only reach the real-mic path when the
  virtual-microphone fixture is broken, which the smoke suite asserts explicitly. The lane's
  advisory `ui-preflight` checks TCC row existence per bundle id and cannot see this identity
  mismatch.

## Permission map (which process touches what)

| Permission | macOS app | XPC engine service | `vocello` CLI |
|---|---|---|---|
| Microphone (`NSMicrophoneUsageDescription`, `device.audio-input` entitlement) | record reference clips (`ReferenceClipRecorder`) | — | — |
| Speech recognition (`NSSpeechRecognitionUsageDescription`) | on-device transcript auto-fill (`VoiceClipTranscriber`, `requiresOnDeviceRecognition` always) | — | — |
| Files & Folders | `NSOpenPanel`/`NSSavePanel` (user intent ⇒ no extra prompt); writing to a **persisted** custom output dir under ~/Desktop/Documents/Downloads prompts once per folder category | — (receives paths as strings) | app-support folders only |
| Everything else (contacts, photos, location, automation, screen) | not used | not used | not used |

The app process is the TCC client for everything; the XPC service and CLI
never trigger prompts.

## OS gates beyond TCC

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

## User-facing permission UX inventory

- **Record sheet** (`RecordReferenceClipSheet`): mic-denied alert + status
  label with an Open System Settings (Privacy → Microphone) path; a
  "No microphone detected" state when there's no input device; permission
  state refreshes on app activation.
- **Enroll sheet** (`SavedVoiceSheet`): transcript section shows
  "Transcribing on-device…" while running and a denied/Siri-disabled caption
  with a direct System Settings button otherwise; retries the auto-fill when
  access is granted mid-session.
- **Voice Cloning**: same unavailability hint near the transcript field for
  fresh-file imports; clears + retries on activation.
- **Settings → Storage**: warning badge + caption when the configured output
  folder is missing/unwritable; generation transparently falls back to the
  default outputs folder (`AudioService.makeOutputPath`) so audio is never lost.

## Troubleshooting

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

## XCUITest setup (separate from mic/speech TCC)

macOS frontend acceptance runs from the `VocelloMacUITests` target under Xcode's test runner.
Configure its signing and test destination through the project and repository test script. XCTest
screenshots need no separate screen-capture plugin route. These concerns are distinct from the
application's microphone and speech permissions above.

## Virtual microphone (registered debug knob)

`QWENVOICE_FAKE_MIC_WAV` is a registered input-substitution knob
(`config/runtime-debug-knobs.json`, master-gated behind `QWENVOICE_DEBUG`). When both are set and
the path points at a readable audio file, `ReferenceClipRecorder` simulates capture: elapsed time
and level-meter values come from the clip's real amplitude envelope, auto-stop fires at clip end or
the 20 s cap, and stop-and-save delivers a copy of the clip — so the record→review→enroll flow runs
end to end with no input hardware and no mic TCC prompt. The recording XCUITest journey uses this
knob with a synthesized speech-like clip; the flow it drives is the genuine visible recording sheet,
and it deliberately cancels at the review stage — accepting a clip starts transcript auto-fill,
whose speech-recognition TCC dialog only a human may answer (see "Manual testing / TCC caveat").
Inert in production: the knob is ignored without the master gate, which Finder launches never set.

## Manual testing / TCC caveat

TCC permission dialogs require a **human** to answer; UI tests must stop before a permission-
sensitive scenario when the grant is absent. After a permission reset, answer the prompt and
verify the outcome with `scripts/permissions_doctor.sh` (or the TCC query). With stable dev signing
this is now a once-per-machine event rather than an every-rebuild hazard.
