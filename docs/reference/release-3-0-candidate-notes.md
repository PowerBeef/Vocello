---
status: active
owner: release-qa
reviewed: 2026-09-04
summary: Prepared 3.0.0 candidate notes and reviewer test focus; not a publication announcement or candidate acceptance record.
sourceOfTruth:
  - project.yml
  - config/roadmap.json
  - config/public-product-facts.json
  - Sources/QwenVoiceCore/EmotionPreset.swift
  - Sources/ViewModels/VoiceDesignCoordinator.swift
  - Sources/SharedSupport/Services/GenerationPersistence.swift
  - scripts/cli_package.py
---
# Vocello 3.0.0 — candidate notes

Prepared for the next release, **3.0.0/build 24**. This document is not a release announcement:
3.0 artifacts have not been published, and the current public macOS release remains 2.4.0.
Candidate verification and publication authorization are separate. At the authorized source freeze,
finish the candidate evidence section and copy the curated notes into the exact tag's release file;
do not change historical 2.4.0 notes.

## Headline changes

- **A downloadable CLI alongside the Mac app.** The release workflow now packages a separate
  complete `Vocello CLI` folder/DMG with its runtime resources, source identity and third-party
  notices. It is designed to run without a checkout, Python, privileged installation or shell edits.
  Model downloads remain separate and explicit.
- **Voice Design preserves the started request on Mac.** Language, pinned seed, delivery, brief
  and variation are captured before asynchronous preparation. Editing the next draft does not
  silently change the request already starting.
- **Safer long-form replacement.** Segment regeneration stages audio and manifests before accepting
  the replacement into History. Failed acceptance preserves the prior project, and interrupted
  filesystem/database commits are reconciled. Generation continuation remains session-scoped;
  this is not a promise of continuing unfinished generation after quitting.
- **Visible History-save recovery.** Successfully generated audio stays playable when saving fails.
  Retry and Export remain available when durable recovery queuing cannot be created. A database
  failure can use the existing outbox; an unqueued result is only held in the current app session.
- **Reference enrollment and language ownership.** iPhone Clone import uses permanent, reviewed
  enrollment with on-device transcription or editable manual text. Reference-language metadata
  stays separate from the selected output language; automatic results do not replace manual edits.

## Delivery behavior and compatibility

The current delivery set contains Neutral, Happy, Sad, Angry, Fearful, Surprised, Calm and Whisper.
Excited was folded into Happy and Dramatic was retired from the picker; retained custom/legacy
instruction text remains governed by the existing compatibility path. Delivery is a directional instruction,
not a guarantee of a particular perceived emotion. This candidate makes no listener-proven
improvement claim and does not waive audio-QC rejection for a fixed seed. Explicit retry remains
user-controlled; there is no hidden best-of-N regeneration.

Installed models, saved voices and History are user data. Upgrade acceptance must verify their
preservation; uninstalling the app is not the default upgrade or troubleshooting procedure.

## Requirements

- macOS 26.0 or later on Apple Silicon, with at least 8 GB memory.
- iOS 26.0 or later on supported hardware beginning with iPhone 15 Pro.
- Internet and sufficient free storage for the selected multi-gigabyte model downloads from
  Hugging Face. No weights are bundled. The model screen reports the catalog's current sizes.
- Synthesis runs locally after the required model is installed. Import/recording permissions and
  on-device Speech availability affect enrollment transcription, not permission to use cloud ASR.

## Install

After an explicitly authorized publication, use the signed/notarized artifacts from the
[official releases page](https://github.com/PowerBeef/Vocello/releases).

For the Mac app, open its DMG and copy `Vocello.app` into Applications. For the CLI, copy the
**entire** `Vocello CLI` folder from the separate CLI DMG to a user-owned location; keep the
executable, resource bundles and catalogs together. Quote the executable path if it contains
spaces. Run `vocello --version` and `vocello --help` before generating. Copying only the executable
is unsupported. There is no Homebrew distribution or automatic shell-profile modification in
this release programme.

An iOS TestFlight invitation or existing installed beta is not proof that build 24 has been uploaded.
The candidate's processed build identity must be verified separately before testing it.

## TestFlight — What to Test (3.0.0/build 24)

Use this section only for the exact processed candidate after a separately authorized upload.

- Install models through the visible model screen; check progress, cancel/relaunch recovery,
  Ready, offline use and removal without changing unrelated installed models or saved voices.
- Generate in Built-in, Design and Clone. Verify the selected output language and delivery;
  include French Voice Design and a transcript-backed Clone reference.
- Import a test-owned audio file from Studio Clone, review automatic or manual transcription and
  reference language, save explicitly, generate, then delete only that test-owned voice.
- Generate a long project and regenerate one segment. Verify the prior accepted project survives
  an error, the completed replacement opens in History, and unchanged segments remain intact.
- Confirm successful synthesis remains playable when History persistence reports a problem;
  test recovery/export through the governed fault tests rather than damaging personal storage.
- Exercise cancel, playback, scrubbing, export, background return and accessible layouts. Preserve
  every fixed-seed failure; do not replace it with a different seed or call a skipped case passed.

## Candidate evidence boundary

Source tests and development-package checks do not establish signed-candidate acceptance. The
historical ad-hoc 2.4.0/build 23 CLI package passed all three generation modes and cancellation;
it does not qualify 3.0.0, establish Clone fidelity, or prove notarization. The standing macOS
candidate UI smoke is deliberately deferred until the signed candidate exists. Record its exact
verdict or deliberate skip at freeze; do not borrow the old release's PASS.

No new 3.0 performance claim or chart is made here. Existing benchmark records keep their original
source identities. Signed desktop/CLI qualification, applicable promotion evidence, the full iOS
campaign, current screenshots, processed-candidate proof and qualified privacy/rights decisions
remain governed by RF-02 and RF-09 through RF-12 in the authoritative roadmap.
