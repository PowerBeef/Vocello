---
status: active
owner: backend-and-platform
reviewed: 2026-10-21
summary: The approved plan for overhauling the vocello CLI (parity with the Mac app, an agent contract and a vocello mcp stdio server, a signed .pkg installer, shared History and settings) and its roadmap items RF-08 and RF-25 to RF-31.
sourceOfTruth:
  - config/roadmap.json
  - Sources/VocelloCLI/Support.swift
  - Sources/VocelloCLI/CLIRuntime.swift
  - scripts/cli_package.py
  - project.yml
---
# CLI overhaul plan (2026-10-21): the `vocello` CLI: Mac-app parity, agent-driven (JSON contract + MCP), shipped as a signed .pkg

## Context

The maintainer asked (2026-10-21) for the CLI to become a full tool that offers the Mac app's features,
can be driven by AI agents, and ships as a standalone installable package alongside the releases.
Decisions taken in planning: a **signed, notarized .pkg** (DMG folder kept as fallback); a **stable JSON
contract on every command plus a `vocello mcp` stdio MCP server**; **full sharing with the Mac app**
(CLI takes appear in History, app settings are the CLI's defaults, a cross-process History lock).

What exists (explored): the CLI already runs the app's engine in-process and shares its models and saved
voices (`Sources/VocelloCLI/`, `VocelloCLICore`), with `generate`/`batch`/`voices`/`models`/catalog/`bench`.
Gaps: a hand-rolled parser with real defects (bare flags swallow values, unknown flags ignored, no `-h`
in subcommands); JSON only on result paths, plain-text errors, no events, no capabilities; no History,
no model removal, no voice review/transcription/rename, long-form reimplemented without app QC, batch
semantics differ from the app's; it drives `MLXTTSEngine` raw. Packaging already builds a sealed, signed,
notarized `Vocello-macos26-cli.dmg` in the Mac release lane (`scripts/cli_package.py`, `release.sh`,
`verify_packaged_cli.sh`, evidence and attestation), but RF-08's gate forbids an installer and the
hardened-runtime CLI has never run a real take under Developer ID.

Constraints that shape the plan:
- **Release focus lock.** The iPhone candidate is frozen at `0919e998`; every commit names a release-plan
  item; `maxInFlight` 2 (RF-23 is in flight). Mac and CLI publication follow the iOS submission.
- **Don't touch iPhone-compiled code before the submission.** Each pre-submission item passes
  `git diff --quiet 0919e998 -- Sources/iOS Sources/iOSSupport Sources/SharedSupport Sources/QwenVoiceCore
  Sources/QwenVoiceBackendCore Sources/Resources Packages` plus `scripts/dev.sh ios`. The one change that
  needs those files (the History lock) lands after the submission, before the CLI is published.
- Agents: worktrees, disjoint files, no native builds, no roadmap edits; the lead builds, tests and
  integrates; release/signing/notarization/publication stay maintainer-authorized (`release.sh` is denied
  to the session).

## Architecture

- **New macOS static framework `VocelloDesktopCore`** (`Sources/VocelloDesktopCore/`) holds the shared,
  UI-free app logic the CLI and MCP reuse. It compiles existing app files by path — the subset
  `VocelloCoreTests` already compiles without UI: `TTSEngineStore`, `MacMemoryBudgetPolicy`,
  `IOSSingleTakeGenerationExecutor`, `StudioGenerationCoordinator`, `IOSLongFormProject`,
  `MacStudioGenerationRequestFactory`, `GenerationTextLimitPolicy`, `GenerationOutputFileName`,
  `MacFileSaveCopy`, `DatabaseService` and `Sources/SharedSupport/Database/*`, `GenerationHistoryRecovery`,
  `VocelloPresentationText` (English defaults), `VoiceClipTranscriber`, `ReferenceTranscriptionReviewState`,
  `VoiceDesignBriefCatalog`, `SavedVoicesBusyRetryPolicy`, `ModelDeletionSequence`,
  `MacModelVariantResolution` — added only as the compiler demands. Never `GenerationPersistence`,
  `AudioPlayerViewModel`, `MacInterfaceText`, either `AppPaths`, either `TTSModel`, `TTSContract`, or
  either `ModelManagerViewModel`. (As built, RF-27: the long-form runner and `MacLineBatchRequest` are
  compiled by path rather than extracted, so no app file changes before the submission;
  `MacInterfaceText` comes with the latter, unreached from the CLI. `batch` keeps its own semantics for
  the QC lanes, and `generate --line-by-line` carries the app's line batch. The CLI writes no History
  until RF-30's lock, instead of an opt-in interim. Engine leases live in one per-user folder,
  `EngineHostLease` in `VocelloDesktopCore` until the app adopts it.)
- **New `Sources/DesktopShared/`** (Mac-only pure logic, compiled by the Mac app's glob and by
  `VocelloDesktopCore`): extractions from Mac files so both share one implementation — `MacSettingsKeys`,
  `MacModelSelection` and `ModelInventory` (from `ModelManagerViewModel`), `MacLineBatchPlan` (from
  `MacLineBatchRequest`), `StudioSingleTakeAttemptRunner` (from `MacStudioSingleTakeRunner`),
  `HistoryProcessLock`, `EngineHostLease`. The Mac types delegate to them (Mac-only edits).
- **Hazard resolutions in `VocelloDesktopCore`**: `DesktopAppPaths` (module-internal `AppPaths` over a
  configured data root: `--data-dir`, debug override, then `~/Library/Application Support/QwenVoice`),
  `DesktopModelAliases` (`TTSModel = ModelDescriptor`, default speaker from the macOS registry),
  `DesktopAppSettings` (reads/writes `com.qwenvoice.app` through CFPreferences, never `UserDefaults`),
  `HeadlessHistoryWriter` (the History write `GenerationPersistence` makes, without the player),
  `HeadlessSingleTakeHooks` and headless long-form hooks/services/playback.
- **Engine**: product commands host `TTSEngineStore` exactly as `MacEngineBootstrap` does (admission,
  memory budget, consent, idle unload, cancellation order); `bench` and codec replays keep the raw
  `CLIRuntime`. Long-form runs `IOSLongFormCoordinator` (app QC, manifest v4, History) instead of the
  reimplementation; line batch uses `MacLineBatchPlan` (per-line seeds, whole-script language, Neutral
  default, a row per planned line).
- **One service facade, `VocelloService`** (`@MainActor`, in `VocelloDesktopCore`) with public
  `Codable, Sendable` request/result types. Both the argv commands and the MCP tools call it, so they cannot
  drift. Operations never print; they report through an injected event sink.
- **`VocelloCLICore`** moves to `Sources/VocelloCLI/Core/` and holds: `CommandModel/` (declarative
  `CommandSpec`/`OptionSpec`, parser, help, completion and capabilities generation), `Contract/` (envelope,
  error codes, exit status, NDJSON writer, schema DSL, request ledger, presenters), `MCP/` (transport,
  server, tools, progress, path policy, generation gate). `project.yml` gains the target; the Mac app excludes
  `Sources/VocelloDesktopCore`; `VocelloCoreTests` compiles the new files by path; regenerate in the same
  commit.
- **Parser: in-house declarative command model**, not swift-argument-parser (no new dependency; its
  attribution would have to enter an iPhone resource before the submission; one model feeds the parser,
  help, generated zsh/bash/fish completions, `capabilities` and the MCP tool schemas). Strict unknown-flag
  errors with did-you-mean, `-h` anywhere, `help a b` = `a b --help`, global flags anywhere before `--`.

## Agent contract

- `--output-format text|json|ndjson` (`--json`, `--ndjson` aliases). Machine modes: stdout carries only one
  envelope (json) or NDJSON events ending in a `result` record; stderr is quiet unless `--verbose`; errors
  are envelopes too. Text mode is unchanged and not part of the contract.
- **Envelope** `{schemaVersion, ok, command, requestID, result, error, warnings, meta}`; **error**
  `{code, category, exitCode, message, retryable, retryAfterMs, hint, detail}`. Codes map from the engine's
  existing typed failures (`GenerationFailurePresentationReason`, `TTSEngineError`, `DownloadError`,
  `CLIEngineCancellation`) through one `CLIFailure.classify`; `CLIError` loses its untyped initializer. Seeds
  and other 64-bit values are decimal strings.
- **Exit codes**: 0 ok · 1 failure · 2 usage/invalid input (`--mode` errors move from 1 to 2) · 66 not found ·
  69 model not installed / speech unavailable · 73 output unavailable · 74 storage/io · 75 transient (busy,
  memory pressure, network) · 77 consent/permission · 78 config/schema · 130/143 signals. SIGPIPE ignored;
  a broken stdout cancels with owned cleanup.
- **NDJSON events** on stdout (`started`, `model_loading`, `generation_started`, `chunk`, `progress`,
  `download_progress`, `qc`, `output_published`, `warning`, `result`): never block generation (Mutex queue
  plus a writer thread; progress coalesces, terminal records never drop); no text, transcript or PCM.
- **Agent ergonomics**: `vocello capabilities --json` (commands, flags, modes, languages, speakers,
  deliveries, models and install state, limits, error and exit codes, MCP tools; instant, no engine boot);
  `vocello run --request -` and `--requests` (JSONL on one warm engine; input = the MCP tool input);
  `--plan`/`--dry-run`; `--client-request-id` with a flock'd request ledger under `<data>/cli/requests/`
  (replay, conflict, in-progress); `--no-input` and stdin read only when named in machine modes;
  deterministic refusal instead of prompts.
- **Schemas** under `config/cli-contract/v1/` rendered from the Swift types; a Swift golden test and
  `scripts/cli_contract.py` (registered in `scripts/lib/contract_gate.py`, no new Python dependency)
  validate examples, MCP transcripts, docs tables and completion; additive-only compatibility within v1.
- **Migrate the existing JSON callers in the same item**: `cli_package.py` smoke/qualify,
  `voice_identity_language_reliability.py`, `audio_qc_calibration_takes.py`, the lang-bench lane (a tolerant
  reader lands first).

## MCP server (`vocello mcp`)

- **In-house JSON-RPC subset, no Swift SDK**: the official SDK lags the current MCP protocol (2026-07-28,
  stateless, `server/discover`) and would add four or more dependencies. Serve both 2026-07-28 and the
  `initialize`-era versions; stdio, newline-delimited, stdout reserved by `dup`/`dup2`; reader and writer
  threads; an actor dispatcher.
- **Tools**: `get_capabilities`, `list_speakers`, `list_deliveries`, `list_voices`, `list_models`,
  `get_status`, `list_history`, `get_history_item`, `generate_speech` (long-form included; progress and
  cancellation through the engine's typed barrier), `enroll_voice`, `delete_voice`, `export_history_item`,
  `delete_history_item`, `get_settings`, and `install_model` only when the server is started with
  `--allow-model-install`.
- **Safety**: `confirmConsent` is a required argument for every clone and enrollment, checked per request
  (never inherited from the app); paths confined to `<data>/outputs` plus `--allow-dir` roots, symlink-safe;
  outputs returned as paths (inline audio only on request and capped); stderr logs carry no text or paths.
- **Warm engine**: one `TTSEngineStore` per server process, a FIFO single-flight gate (`--max-queue`, then
  `engine_busy`), idle unload from the engine's policy.
- **Setup helpers**: `vocello mcp --print-config claude-code|claude-desktop` and `--self-test`; docs show
  `claude mcp add --scope user vocello -- /usr/local/bin/vocello mcp`.

## Feature parity (command tree)

- **generate** (`custom|design|clone` shortcuts): all three modes; auto long-form routing
  (`--long-form auto|always|never`, the app's `LongTextGenerationRouter`); `--line-by-line`; speaker,
  delivery/cell, brief or `--brief <id>`, saved voice or reference + transcript; `--variant speed|quality|auto`
  (app setting, then hardware recommendation); language, seed, `--seed-from <historyID>`, variation;
  `--out` (export copy), `--out-dir`, History on by default; `--plan`, `--retry-from <receipt>`, `--play`.
  `batch` stays as a compatibility alias.
- **voices**: `list`, `show`, `enroll` (prepare, review, commit/discard; `--transcribe auto|always|never`,
  `--audio-only`, `--on-warnings keep|discard|fail`), `replace`, `save-take <historyID>` (Design take to
  voice), `delete` (busy retry), `banks`.
- **history**: `list` (mode/search/order/limit/segments), `search`, `show`, `export`, `delete`, `clear`,
  `recover status|reconcile|export|set-aside`.
- **models**: `list`, `status`, `verify` (digest), `install`, `install-recommended`, `remove`, `use`,
  `prefer-lower-memory`, `active`.
- **settings**: `list`, `get`, `set` (variation, output folder, prefer-lower-memory, per-mode variant,
  autoplay); consent and interface language are not settable.
- **catalog**: `speakers`, `modes`, `deliveries`, `languages`, `briefs`; plus `doctor`, `version`,
  `capabilities`, `completions`, `mcp`, `help`, and `bench` (internal).
- **Excluded, with reasons** (recorded in `config/cli-parity.json`): microphone recording (TCC attributes it
  to the terminal; record elsewhere and enroll the file), live streaming playback and the player UI (only
  `--play`), Sparkle updates (the .pkg updates the CLI), interface language (English; agents read codes),
  in-session long-form resume and regenerate-segment, Finder/haptics/VoiceOver.
- **Speech recognition**: the binary embeds `NSSpeechRecognitionUsageDescription`; `--transcribe auto`
  never prompts (transcribes only if already authorized, else needs `--transcript`/`--audio-only`); macOS
  denies it when Siri is off.

## Cross-process safety

- **History**: keep the rollback journal (WAL would weaken `secure_delete`). `HistoryProcessLock`
  (`<appSupport>/.history.lock`, non-blocking flock polled with backoff, short sections only) wraps every
  History mutation in both the app and the CLI; a macOS busy timeout in `DatabaseService`; a schema-skew
  guard (an older CLI refuses a newer schema, exit 78). Until that lands (after the submission), CLI History
  writes are opt-in and refused while the app runs on the same data root; this interim state never ships.
- **Change notifications**: the CLI posts `com.qwenvoice.shared.{historyDidChange,savedVoicesDidChange,
  modelsDidChange,settingsDidChange}`; the app observes them and reloads (Mac-only edit).
- **Engines**: `EngineHostLease` files under `<appSupport>/engine-hosts/`; on 8 GB Macs a second engine is
  refused (`--allow-concurrent-engine`, `--wait-for-engine`), elsewhere it warns; `models remove` refuses a
  model another host has loaded. Voices and model stores are already locked.

## Packaging (.pkg)

- One sealed payload ships twice: `Vocello-macos26-cli.pkg` and the existing DMG folder.
  `pkgbuild --install-location /usr/local/lib/vocello` with a component plist marking every bundle
  **non-relocatable** (the app has same-identifier bundles Installer could otherwise "relocate" into);
  `preinstall` removes a previous installed payload (Installer never deletes stale files); `postinstall`
  makes relative symlinks `/usr/local/bin/vocello` and the zsh completion (shared directories stay out of the
  payload); `productbuild` with a script-free Distribution (arm64, macOS 26, boot volume); `productsign`
  with the new Developer ID Installer identity; notarize and staple. Receipt `com.qwenvoice.cli`; sealed
  `uninstall.sh` (`sudo sh /usr/local/lib/vocello/uninstall.sh`) removes the links, the folder and the
  receipt and never the data store.
- **Pipeline**: `cli_package.py pkg` and `pkg-verify` (expanded-package checks: payload equals the sealed
  manifest, Bom ownership and modes, no relocation, scripts byte-equal, root-free simulated install with a
  smoke through the symlink); `verify_packaged_cli.sh --include-pkg` with a real install/upgrade/uninstall on
  the CI runner; `release_evidence.py` binding, SHA256SUMS, attestation, SBOM entries; `promote-release.yml`
  attests every binary from evidence; rehearsal with an unsigned pkg; the shared notarization block moves
  into a sourced function; orchestration template v3.
- **Entitlements**: add a `macos-cli` role (expected empty) to `config/macos-entitlement-policy.json`,
  checked by `entitlement_contract.py verify-bundle`; confirmed by an early **hardened-runtime probe**:
  `build.sh cli-optimized`, stage, sign ad hoc with `--options runtime`, then Developer ID, and run
  `cli_package.py qualify` (three modes, two-item batch, cancellation). If MLX needs an exception, add only the
  key the failure names.
- **Public surfaces**: `docs/reference/cli.md` (install, uninstall, upgrade, coexistence), release notes,
  in-package README, `config/public-product-facts.json` `cliDistribution`, website link gated to the
  stable release. RF-08's gate is rewritten for the .pkg (no Homebrew, no shell-profile edits, no updater);
  RF-10 qualifies both forms, including app/CLI coexistence on one store.

## Roadmap items and order (release-first plan; every commit names its item)

The lead opens these with the maintainer's 2026-10-21 decision recorded in `focusLock.decision`, re-gates
RF-08 into the release plan and updates RF-10. One CLI item in flight while RF-23 is; two once disjoint.

| Item | Scope | Before or after the iOS submission |
|---|---|---|
| RF-08 (re-gated) | Maintainer: Developer ID Installer certificate and two `release` secrets. Lead: the hardened-runtime probe. Agents: pkg build/verify, evidence/SBOM/policy, pipeline/workflows (three disjoint worktrees). | Before (runs in parallel) |
| RF-25 | Command model, parser, contract foundation: envelope, typed errors and exits, presenters, capabilities (static), schemas and `cli_contract.py`, NDJSON writer, `--no-input`, SIGPIPE; existing JSON callers migrated (tolerant reader first). | Before |
| RF-26 | `VocelloDesktopCore` and `DesktopShared` extractions; read-only parity: catalog, settings get/list, models list/status/verify, voices list/show/banks, history list/search/show/export (read-only queue), doctor, capabilities runtime facts. | Before |
| RF-27 | Generation on the shared pipeline: `TTSEngineStore` host, headless hooks, long-form coordinator, line batch plan, app-settings defaults, `--plan`, `run --request(s)`, request ledger, NDJSON progress, engine lease, interim History policy. | Before |
| RF-28 | Saved voices parity (enroll review, transcription policy, replace, save-take, delete) and model/settings writes (install-recommended, remove, use, prefer-lower-memory, settings set, notifications). | Before |
| RF-29 | `vocello mcp`: transport, both protocol eras, read tools, then write tools, progress, cancellation, path policy, gate, config helpers. | Before |
| RF-30 | History cross-process lock in app and CLI, busy timeout, schema guard, app observing notifications and adopting the lease; History on by default; history delete/clear/recover; typed long-form failure reason. Touches iPhone-compiled files with identical iOS behaviour. | After |
| RF-31 | Parity map `config/cli-parity.json` with `test_cli_parity.py`; docs (`cli.md` rewrite, `cli-agents.md`, `vocello help agents`); extended `cli_package.py qualify` (History round trip, voices, long-form, MCP generate and cancel, coexistence); RF-10 qualification of the signed pkg and DMG; ship with the Mac release. | After |

## Defaults taken unless the maintainer objects

The new exit table (usage stays 2; invalid `--mode` moves 1→2); the in-house parser and MCP
implementation (no new dependencies); the CLI's default variant and batch semantics follow the app's
(explicit `--variant` keeps old scripts working); `--out` becomes an export copy when History is on;
`install_model` off by default in MCP; `set_settings` not exposed to MCP in v1; History opt-in only in the
unshipped interim; the Speech usage string in the CLI binary; RF-30's edits to iPhone-compiled files after
the submission.

## Verification

- **Per item**: `scripts/dev.sh check` (parser and contract tables, golden schemas and completions, contract
  validator, migrated Python callers); `scripts/dev.sh test --only` the new suites (`CLIArgumentsTests`
  table rewrite, `CLICommandModelGoldenTests`, `CLIContractTests`, `CLIEventStreamTests`,
  `CLIRequestLedgerTests`, headless hooks over `StoreFixtureEngine`, long-form over the `LongFormFixture*`
  fakes, `MacModelSelectionTests`, `DesktopAppSettingsTests`, `HistoryReaderTests`,
  `SavedVoiceEnrollmentWorkflowTests`, `MCPServerTests` with JSON-RPC transcripts, `MCPStdioProcessTests`,
  `HistoryProcessLockTests` with cross-process clear-vs-commit); the pre-submission iOS-diff gate; the
  `vocello-swift-review` agent on each Swift diff; `/security-review` for the MCP path policy, the History
  lock and the pkg scripts.
- **End to end (lead, on the Mac with installed models)**: `vocello capabilities --json`; one take per mode in
  json and ndjson; a long-form project; a take that then appears in the Mac app's History; voices enroll and
  delete; models verify; `vocello mcp --self-test`, then `claude mcp add` and a real `generate_speech` and a
  cancel from Claude Code; the Mac smoke lane after the app-side edits.
- **Packaging**: `cli_package.py pkg` plus `pkg-verify` locally; the hardened-runtime probe with a real take
  per mode; the release rehearsal on GitHub (unsigned pkg, runner install/upgrade/uninstall); before
  publication, the maintainer's signed `release.sh` run and RF-10's qualification of the installed
  `/usr/local/bin/vocello` and the copied DMG folder.
