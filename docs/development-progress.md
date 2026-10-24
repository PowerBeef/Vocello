---
status: active
owner: backend-and-platform
reviewed: 2026-10-24
summary: Current resume checkpoint; config/roadmap.json owns open work, config/roadmap-archive.json holds finished work, and older narrative lives in git history.
sourceOfTruth:
  - config/roadmap.json
  - config/runtime-refactor-contract.json
---
# Vocello development checkpoint

Start here, then follow `config/roadmap.json`'s `primaryPlan` and the
[release-first execution plan](reference/release-first-execution-2026-09.md).
This is a narrative, not a second work ledger. Product source, contracts and scripts win.
Checkpoints older than the five below live in git history (`git log -p -- docs/development-progress.md`;
the last copy with every earlier checkpoint is at commit a0597deb).

## Resume now

### October 24, evening: RF-15 on build 24 (resume here)

- **Phone state:** build 3.0.0 (24) from TestFlight, onboarded by the `first-launch` row, with the
  three shipping models Ready and no clone voice yet. CoreDevice reports the team's own TestFlight
  build as `builtByDeveloper: true`, so every run takes `--candidate-origin-attestation`
  (`093772a0`; `d157f3f0` fixed the field name).
- **Rows (`e7847527`):** `first-launch` (onboarding and models; no permission prompt, runs
  unattended) and `clone-voice` (the benchmark voice from a Design take; Save as Voice raises the
  Speech Recognition prompt on a fresh install, which the maintainer answers, never a row). The
  review found that blocker before the run.
- **Unattended runs, all retained** (`ios-xcui-candidate-smoke-20261024-*`): first-launch PASS,
  onboarding walked through its three pages and all three models downloaded (`195718-935a856b`);
  navigation PASS (`200241-53f60937`); long-form PASS (`200402-db93f093`); accessibility FAIL
  (`201553-857a53b4`: Dynamic Type partial on Studio and the purchase sheet, purchase-sheet contrast,
  text clipped in Design and Clone at AX-XXXL). Not a release blocker (no accessibility declaration in
  App Store Connect); parked as BKL-31, and RF-15 needs the maintainer to fix it with a new candidate
  or accept it as a limitation. Earlier failed runs: `171623` (locked), `171715` (field name),
  `173613` (first-launch guard).
- **Resume, with the maintainer at the phone** (the prompts): `--scenario clone-voice`, answering
  Speech Recognition; `voice-lifecycle`; `record-then-play`, answering Microphone; then `modes` and
  `one-word` (or `all`), each with `--preinstalled-candidate build/artifacts/ios/release-candidate-v3.0.0-ios.3 --retain-result --candidate-origin-attestation "<statement>"`.
  Unpushed: `d157f3f0`, `093772a0`, `938e259c`, `e7847527` and this checkpoint.

### October 24 — the iPhone 3.0 release candidate goes to TestFlight (resume here)

- **Maintainer decision:** iPhone focus. TestFlight carries the 3.0 release candidate, 3.0.0 (24):
  Internal at once and submitted for Apple's beta review at once; the Public Beta group waits for RF-17's
  exact-tag promotion (maintainer, later on October 24). The What to Test notes ask for the
  last bugs and for the hardware floor (iPhone 15 Pro, 8 GB). Fast-tracked: the agent approves the
  `release` gate and distributes when processing ends.
- **Archive path repaired:**
  - `13e9d05d`: mlx-c `__FILE__` paths (ASR-07).
  - `50c347a8`: `dlopen` is the only banned loader, and the export keeps the archived executable.
  - `054b5e4a`: release evidence accepts the summary the IPA verifier really writes (ASR-10). Release
    run 40085945191 failed on that after archiving, exporting and verifying the IPA.
- **Candidate tags without a Manual-mode session (`fc8bb78e`, RF-12):** on the maintainer's request,
  `python3 scripts/ios_candidate_tag.py` signs and pushes the next `v<version>-ios.N` tag. It refuses
  unless main is pushed, CI passed and the build number is unused. A candidate push runs only the iPhone
  archive and the TestFlight upload. `v3.0.0-ios.3` on `26995f71` started release run 40103005257.
- **RF-15 journeys (`10d0d603`):** `ui_test.sh ios smoke --preinstalled-candidate DIR --scenario ROW`
  runs black-box rows on the installed TestFlight build: modes, voice-lifecycle, one-word,
  record-then-play, long-form, accessibility or all. Development-build evidence the same day: startup
  Retry and the unverified purchase locked until Restore (AUD-07), both PASS.
- **Housekeeping:** issue #108 (stale nightly) is closed. RF-10's due date moved to 2026-10-31.
- **Keep-voice capture fix proven** (macos-xcui-marketing-20261024-145129-78cc21e5): the range
  warning appeared, Keep was clicked and the designed voice saved. The test then found no "Voice
  added" alert and failed; that is parked as BKL-28.
- **State at 15:04 UTC, when the CLI session ended** (the work moves to the Claude Code desktop app):
  - Release run 40103005257 (`v3.0.0-ios.3`) was still in the Security CodeQL Swift scan, with no
    approval pending and no build 24 in App Store Connect.
  - The release rehearsal 40103799663, dispatched on `26995f71` for issue #107, was still running.
  - `main` had local commits not yet pushed (the checkpoint and roadmap updates).
- **Desktop session, 15:40 UTC:** rehearsal 40103799663 passed and #107 is closed. `main` is pushed
  with `1b1ab348` (the Claude desktop app workflow, DW-04), CI green; release run 40103005257 was still
  in CodeQL.
- **Build 24 is on TestFlight (16:44 UTC):** the `release` gate was approved at 15:42, run 40103005257
  passed end to end and build 3.0.0 (24), `e008a349-a87b-4d9d-8790-be4c0e4a687c`, went VALID. Its What
  to Test notes are in, Internal testers have it (the group has access to all builds, so adding it by
  hand is refused), and beta review is submitted (WAITING_FOR_REVIEW). No external group: Public Beta
  waits for RF-17.
- **Same session:** the README became a project page (`e52d8d1e`, RF-32), a CI stub race was fixed
  (`9ced9a37`), and RF-34 redesigns the website home page for regular users.
- **Resume here, in order** (steps 1 to 3 are done):
  1. Done: when run 40103005257 asked for the `release` environment, it was approved. The maintainer asked to
     fast-track: `gh api -X POST repos/PowerBeef/Vocello/actions/runs/40103005257/pending_deployments
     -F 'environment_ids[]=22764362076' -f state=approved -f comment="fast-track the 3.0 RC"`.
     If the run fails, fix the cause, push `main`, wait for CI, then cut the next candidate with
     `python3 scripts/ios_candidate_tag.py`.
  2. Done (see above): when `asc builds list --app 6794692745 --platform IOS --build-number 24
     --processing-state all` showed VALID, it was distributed with the build's id:
     - `asc builds test-notes create --build-id ID --locale en-US --whats-new TEXT`, where TEXT is the
       candidate text in `docs/releases/v3.0.0.md` ("TestFlight: what to test");
     - `asc builds add-groups --build-id ID --group 70bd66ea-9d12-4f77-84b5-38e7a64ed871` (Internal);
     - `asc testflight review submit --build-id ID --confirm`;
     - not yet the Public Beta group (`2375b641-4224-486c-8c0a-0fa326d7b641`): it waits for RF-17.
  3. Done: rehearsal 40103799663 passed and #107 is closed.
  4. The maintainer installs 3.0.0 (24) from TestFlight over the development build. Then run
     `scripts/ui_test.sh ios smoke --preinstalled-candidate DIR --scenario all`, where DIR is the run's
     verified `vocello-ios-release-candidate` artifact. Then by hand: the offline relaunch and VoiceOver.
  5. Last: the approved fresh install (onboarding and the file opened during onboarding).

### October 23 — Vocello 3.0.0 for the Mac and the CLI is public

- **Published 2026-10-24 00:06 UTC as the latest release** by the maintainer's route A (from the signed
  draft, without a quality-promotion record). Release run 40020993733 on `e7a8e2ae` passed Security,
  source authority, packaging (Developer ID, notarized and stapled DMGs and pkg, the runner's install,
  upgrade and uninstall), the Sparkle feed and the draft. Before publication the draft was checked
  locally: SHA256SUMS, stapled tickets, Gatekeeper, the pkg signature, attestations, app 3.0.0 (24),
  `vocello 3.0.0`, the appcast enclosure and signature, and notes identical to `docs/releases/v3.0.0.md`.
  The published DMG's Developer ID CLI passed `cli_package.py qualify`. RF-08 and RF-32 are closed.
- **The first run (39914320626 on `41a147f6`) stopped before signing:** the tag checkout's detached HEAD
  made `dev.sh status` raise in `release.sh`'s Python suite. `e7a8e2ae` fixed it and `v3.0.0` moved there
  (the maintainer authorized the agent once to sign and replace it with hooks paused in the untracked
  `settings.local.json`, restored byte-identical).
- **Developer ID Installer certificate:** issued 2026-10-23, expires 2027-11-22; its `release`
  environment secrets are set.
- **README and website (RF-32):** integrated as `3aa8f20c`..`f269bf71`; the site goes live when `main`
  is pushed. The agent worktrees `wf_9f99b8e0-4f2-1`..`4` are integrated and can be removed.
- **Next:** the iPhone submission from the same `v3.0.0` tag in the coming days (RF-10's packaged-app
  checks stay open); RF-30 and RF-31 after it.

### October 22, night — the Mac and CLI 3.0 release starts from the release commit

- **Maintainer decision:** release the Mac app and the CLI 3.0 first; submit the iPhone app a few days later
  from the same `v3.0.0` tag. Recorded in `focusLock` (maxInFlight 3); RF-10 joins the release plan in
  flight; RF-32 (README and website) follows publication.
- **Release pipeline repaired on CI's Xcode 26.6 and Linux:** `0ffe6fa3` (event-stream test), `6f3efa57`
  (macOS-only package tests), `f9326d16` (`release.sh` otool SIGPIPE), `8b0ee46b` (the package smoke
  read the CLI's Info.plist only at lengths divisible by four). CI is green from `f9326d16`.
- **Tag signing:** `~/.ssh/vocello_tag_signing` signs tags for this repository only (local git config);
  the maintainer registers it on GitHub (`gh auth refresh -s admin:ssh_signing_key`, then
  `gh ssh-key add --type signing`).
- **Still the maintainer's:** the Developer ID Installer certificate and its two `release` secrets, the
  signed `v3.0.0` tag, the `release` environment approvals, and the publication route.
- **Promotion evidence:** an audit of the eight macOS lanes found the language lane unsatisfiable (six of
  the ten required languages); this commit adds the other four as pinned cells. Lanes run with HEAD on
  this exact commit and a clean tree; their records move to `build/artifacts/quality-promotion/` before
  the managed download capture, which needs the tag. No edit or commit until `create` and `validate`
  pass. Risks: Fast QC warnings, `custom-ja-auto`, Portuguese.

### October 22, later — RF-29 closes: `vocello mcp` serves agents

- **RF-29 done** (`bd045167`): `vocello mcp` is an in-house stdio MCP server.
  - It serves the stateless 2026-07-28 revision and the `initialize`-era ones.
  - Its 17 tools run the CLI's own commands, on one warm engine behind a FIFO gate.
  - Consent is checked per request, and paths are confined: reads come from `<data>/outputs`, writes go
    to `<data>/outputs/cli`, and `--allow-dir` adds folders for both.
  - It reports progress and handles cancellation.
  - `--print-config` and `--self-test` help with setup.
  - It was proven over stdio with a real take, a cancelled take and a take after it, and a headless
    Claude Code session (`claude -p --mcp-config`) generated a real take through it.
  - It had two Swift reviews, with every finding fixed.
- **Fixed on the way:**
  - `generate` never replaces a History take's audio.
  - RF-08: through any link (the installer's `/usr/local/bin/vocello`, `build/vocello` outside the
    checkout), MLX could not find its metallib, so every take failed. `vocello` now execs its real path.
- **Moved on:**
  - To RF-31: the interactive Claude Code cancel (Esc), and the server holding the engine lease for its
    whole life.
  - To RF-30: MCP History rows and `delete_history_item`.
- **CLI work before the submission is complete** (RF-25 to RF-29). RF-30 and RF-31 follow the iOS
  submission.
- **RF-08 in flight:** the maintainer still needs the Developer ID Installer certificate, its two
  `release` secrets and the first rehearsal.
- **Release items waiting:** RF-09's freeze checks are due 2026-10-23.
- **Not pushed:** local commits are unpushed; the iPhone candidate stays at `0919e998`.

### October 22 — RF-28 closes; RF-29 (the MCP server) starts

- **RF-28 done:**
  - `settings set`, `models use` and `models prefer-lower-memory` write the app's preferences as its
    Settings do; turning `prefer-lower-memory` on clears the per-mode choices.
  - `models install-recommended` (with `--plan`) and `models remove`. Removal reconciles a package
    choice that named the model, refuses mode aliases, and is refused beside a running engine.
  - `voices enroll`, `replace`, `save-take` and `delete` save voices as the app's voice sheet does.
    `--transcribe auto` never prompts; `--on-warnings` chooses keep, discard or fail; a signal discards
    the candidate.
  - Each write posts `com.qwenvoice.shared.*DidChange`, and the Mac app reloads its saved voices or its
    model manager (`8cf6d4b7`; a Mac-only app edit).

  It had two Swift reviews, with every finding fixed (`b1160e36`, `213ded27`). Commits run from
  `d364f073` to `213ded27`. Enrollment, replace and delete ran for real in a scratch data folder;
  `save-take` has run only in tests, because the maintainer's History is empty.
- **RF-29 in flight:** the in-house stdio MCP server (`vocello mcp`), per the plan in
  `docs/audits/2026-10-21-cli-overhaul-plan.md` (tools, safety, the warm engine, setup helpers).
- **RF-08 in flight:** the maintainer still needs the Developer ID Installer certificate, its two
  `release` secrets and the first rehearsal.
- **Release items waiting:** RF-09's freeze checks are due 2026-10-23.
- **Not pushed:** local commits are unpushed; the iPhone candidate stays at `0919e998`.
