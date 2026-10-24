---
status: active
owner: backend-and-platform
reviewed: 2026-10-21
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

### October 23 — Vocello 3.0.0 for the Mac and the CLI is public (resume here)

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

### October 21, late — RF-27 closes; RF-28 starts

RF-27 closed with its deviations recorded: `batch` keeps its semantics for the QC lanes, the CLI
writes no History until RF-30, and the single-take executor moves to RF-30. The maintainer asked
whether the CLI is over-engineered and chose to continue the approved plan.

### October 21, evening — RF-26 closes; RF-27 hosts takes like the app and routes long scripts

- **RF-26 done:** `VocelloDesktopCore` (the app's store, History records, settings keys and
  model selection, compiled by path plus `Sources/DesktopShared`) gives the CLI read-only parity:
  History list/search/show/export (refused while the app runs on the same data root until RF-30),
  settings, briefs, voices show/banks, models active/verify, languages, doctor and runtime facts in
  `capabilities` (`701c0da9` to `6950f227`, reviewed).
- **RF-27 in flight:** takes default to the app's package and variation; `generate --plan`;
  `run --request(s)` with idempotent client ids whose identity is the resolved take; `generate`,
  `batch` and `run` host the engine through `TTSEngineStore` as `MacEngineBootstrap` does; a script
  past one take runs as a long-form project through the shared `CLILongFormProject` runner
  (`d2eee3c5` to `abc3d300`). Each step had a Swift review; its findings are fixed, including a hang
  where a store refusal stranded the stream drain. Verified on this Mac: a hosted 2-segment
  long-form take (60 s of audio in 17 s) and a SIGINT that keeps the finished segment. A review of
  `01f9206f` and `abc3d300` is running. Left: long-form through `IOSLongFormCoordinator` with its
  joined-output QC, the line batch on the app's plan, the interim History write policy, the engine
  lease, NDJSON progress polish and a hosted take per mode.
- **RF-08 in flight:** the pipeline, evidence and entitlement work landed (`3acf1251` to
  `e6a0a761`); the maintainer still needs the Developer ID Installer certificate, its two `release`
  secrets and the first rehearsal.
- Local commits are not pushed; the iPhone candidate stays at `0919e998` awaiting the maintainer's tag.

### October 21, later — the CLI overhaul starts: RF-25 lands, RF-08 builds a .pkg

The maintainer asked for a full CLI: Mac-app parity, driven by agents (a JSON contract and an MCP
server), shipped as a signed `.pkg` beside the releases. The plan is
`docs/audits/2026-10-21-cli-overhaul-plan.md` (RF-25 to RF-31, RF-08 re-gated); no iPhone-compiled
file changes before the submission (`git diff --quiet 0919e998 -- Sources/iOS …`).

- **RF-25 done:** one command tree drives the strict parser, help, completions, `capabilities` and
  `config/cli-contract/v1/commands.json`; every command but `bench` speaks the v1 envelope
  (`--json`) or NDJSON events (`--ndjson`) with typed codes and exits; the contract, schemas,
  examples and additive-only baseline validate in the contract gate; every JSON caller reads
  through `scripts/lib/vocello_cli_json.py` (`26c0cee6`, `0e8eeff0`, reviewed).
- **RF-08 in flight:** `cli_package.py pkg`/`pkg-verify` build and verify an unsigned installer
  package with relative `/usr/local` links and a sealed `uninstall.sh` (`cdb5eea6`). Left: evidence
  and entitlement policy, the release pipeline, the hardened-runtime probe, and the maintainer's
  Developer ID Installer certificate with its two `release` secrets.
- **RF-26 in flight next:** `VocelloDesktopCore` and read-only parity.
- Local commits are not pushed; the iPhone candidate stays at `0919e998` awaiting the maintainer's tag.

### October 21 — the freeze moves to `0919e998`; Mac updates land

`main` is pushed through `0919e998`, the freeze commit; the freeze record follows it. The maintainer
holds the release: no tag yet.

- **RF-24 (release blocker, maintainer report): the iPhone Clone Studio matches the other modes.**
  Clone had stacked its reference transcript review under the canvas (since `46504a11`), pushing
  Generate up and squeezing the script. The review now sits at the top of the Reference panel
  (`50761bcc`, `08372fdd`, reviewed). `ios smoke --scenario studio-layout` (also part of full smoke)
  passed on the iPhone (`ios-xcui-smoke-20261021-050240-000ce5bc`): Generate sits 8.6 pt above the
  tab dock in all three modes. macOS was never affected (its review lives in a popover).
- **RF-23 (maintainer request): Sparkle updates for the Mac app.** Vocello > Check for Updates…, a
  Settings > Updates category, Sparkle's second-launch prompt, no silent installs, a signed feed
  required and updates verified before extraction; the EdDSA key is in the maintainer's keychain
  and the `release` environment. The release workflow signs the DMG and the feed in a minimal job;
  the Swift and security reviews' findings are fixed; the Mac layout lane passes; the privacy page
  names the check. Left: the release rehearsal on GitHub and one end-to-end update between signed
  builds.
- **The freeze:** the full checks pass on `0919e998` (website browser smoke included now that
  Playwright's Chromium is installed locally); `focusLock.freeze` names it.
- **Next:** the maintainer's signed `v3.0.0` tag (tag-signing key setup first), then ASR-10's signed
  archive and TestFlight (RF-12, RF-15), each on the maintainer's go.
