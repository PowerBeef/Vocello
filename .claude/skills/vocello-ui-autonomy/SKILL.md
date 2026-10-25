---
name: vocello-ui-autonomy
description: Run the default autonomous route for device and UI checks XCUITest does not cover — iPhone through iPhone Mirroring with computer use, the Mac directly, and Claude's review of lane screenshots — inside a maintainer-announced window.
argument-hint: "<RF row, check or exploration goal> [iphone|mac]"
---

# Autonomous UI checks beyond XCUITest

Goal: $ARGUMENTS

Read docs/reference/development-workflow.md (Computer use) and the routing table in
docs/reference/ios-device-testing.md. Maintainer decisions of 2026-10-25: XCUITest stays the only
automated evidence; computer use is the default route for everything it cannot cover; a computer-use
record closes an attended row only when the maintainer confirms it; phone work happens only in a
window the maintainer announced; Claude never changes a system or security setting, grants a
permission, enters a passcode or credential, deletes the app or confirms a purchase.

## Route each check
- XCUITest can drive it (app UI with stable identifiers): use `scripts/ui_test.sh` (skill
  `vocello-ios-validation` or `vocello-macos-ui`), then review the run's screenshots (below).
- XCUITest cannot, and the check survives Mirroring's conditions (UI flows, in-app settings, model
  management, TestFlight installs, reproductions, visual inspection): computer use.
- Maintainer by hand: anything needing an iPhone system setting (Wi-Fi off, airplane mode, Auto-Lock,
  Low Data Mode, Developer Mode, UI Automation), a permission prompt, the passcode or Face ID, the
  microphone or camera, audio routing or interruptions (Mirroring sends audio to the Mac), VoiceOver,
  app deletion, a purchase confirmation. Pause and notify (below).

## Window protocol (iPhone)
1. Setup card, sent once at the window's start: Wi-Fi and Bluetooth on (both devices); Auto-Lock as
   the rows need; Developer Mode and UI Automation on; a Focus on so notifications stay out of
   screenshots; the build to test installed; Screen Recording allowed once for the capturing app;
   the phone unlocked.
2. Block A, lanes: `scripts/ios_device.sh mirroring stop`, then every XCUITest lane in scope. The
   lanes' `ui-preflight` refuses while iPhone Mirroring runs, because XCUITest breaks under it.
3. Handoff: ask the maintainer to lock the phone (Mirroring needs it locked; unlocking ends Mirroring).
4. Block B, Mirroring: `scripts/ios_device.sh mirroring status`, then
   `scripts/ios_device.sh mirroring session <label>`; `request_access` for "iPhone Mirroring";
   `open_application` "iPhone Mirroring"; screenshot before every action; act; after each meaningful
   step `scripts/ios_device.sh mirroring capture <label> --step "<action>" --observed "<what shows>"`;
   verify before moving on.
5. Close: `scripts/ios_device.sh mirroring stop`; report each record (folder under
   build/artifacts/ios/mirroring) for the maintainer's confirmation; never claim a row closed before it.

Never drive the phone or the Mac while a native, device or measured lane runs.

## Input through iPhone Mirroring
- Tap: a click on the element. Scroll: scroll events over the Mirroring window, never a drag (a drag
  registers as a long press and opens Home Screen edit mode).
- Cmd-1 Home Screen, Cmd-2 App Switcher, Cmd-3 Spotlight, Cmd-4 Control Center (macOS 27).
- Typing has not reached the phone so far; until the first-window probe settles a method, avoid
  steps that need typed text or use the app's own paste from the Mac clipboard.
- A Mac authentication prompt for Mirroring, or any phone system sheet, is the maintainer's.

## Mac
Drive Vocello and its menus, Finder reveal and drag-and-drop of reference files directly, between
lanes only. No TCC grants, sign-ins or Sparkle installs. Report steps with screenshots; the attended
walk in docs/reference/macos-release-qa.md is a typical session.

## Pause and notify
At any step that is the maintainer's, stop, send a PushNotification naming the exact step, and resume
only on their word. Keep the session and its record open meanwhile.

## Review lane screenshots
After every XCUITest lane, read `<run>/screenshots/index.json` and open each failure frame and each
named state the row asserts: look for clipping, overlap, wrong state, untranslated text or an
unexpected dialog. Report-only; classify each finding as a release blocker or a backlog line.
