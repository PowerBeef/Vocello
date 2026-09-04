---
status: active
owner: backend-and-platform
reviewed: 2026-09-04
summary: Local-first privacy and on-disk storage layout on both platforms — what lives where, what never leaves the device, and deletion semantics.
sourceOfTruth:
  - Sources/SharedSupport
  - Sources/iOSSupport/Services/IOSStorageProtectionPolicy.swift
  - config/ios-storage-protection-policy.json
---
# Privacy And Local Storage

QwenVoice/Vocello is local-first. Prompts, recorded or imported reference clips, transcripts, saved voices, generated audio, model files, and history stay on the user's device unless the user explicitly exports, shares, or uploads them elsewhere.

## macOS Storage

Installed/public macOS Release app support root:

```text
~/Library/Application Support/QwenVoice/
```

Debug builds use a separate persistent development root so models, saved voices, outputs, and `history.sqlite` survive rebuilds:

```text
~/Library/Application Support/QwenVoice-Debug/
```

Repository-built internal diagnostics binaries honor this hermetic macOS override only with the
`QWENVOICE_DEBUG` master gate enabled; distributed builds cannot enable it:

```sh
QWENVOICE_APP_SUPPORT_DIR=/path/to/custom/app-support
```

Maintained macOS subtrees and preferences:

- `models/` stores installed Hugging Face model files. Speed and Quality folders for the same
  generation mode can coexist on macOS. Catalog-v2 installs may also use the hidden
  `.qwenvoice-components-v1/` content-addressed store; ordinary model paths remain regular hard
  links, and component liveness is derived from strict installed manifests.
- `.qwenvoice-downloads/` stores staged model downloads, partial files, resume data, and download-state metadata while a download is in progress.
- `diagnostics/model-downloads/` stores allowlisted transfer/failure summaries, capped at 60 records and 5 MB; raw URLs and absolute paths are excluded.
- `outputs/CustomVoice/`, `outputs/VoiceDesign/`, and `outputs/Clones/` store generated audio unless the user chooses a different output directory. If a user-chosen directory becomes missing or unwritable, new audio falls back to these default folders and Settings shows a warning — a generation is never lost to a vanished folder.
- `outputs/bench-archive/<runID>/` (debug-store only; created by `vocello bench --delivery`) retains each delivery benchmark run's take WAVs and result/prosody/quality manifests as the durable measurement evidence. Local-only, never tracked or uploaded; unbounded, prune manually ([`delivery-harness.md`](delivery-harness.md) §3).
- `voices/` stores committed saved-voice reference assets (the source audio format plus an optional `.txt` transcript sidecar). Each voice is individually deletable; deleting a voice-bank member does not delete its siblings.
- `voice-candidates/` privately stages saved-voice review candidates. Candidates are not listed or usable as saved voices, expire after 24 hours, and are removed on Cancel, Discard, or outside dismissal. `voice-transactions/` holds short-lived commit/replacement/delete journals; startup reconciliation restores a pre-publication replacement, completes a post-publication commit, and completes a user-confirmed delete without resurrecting it.
- Reference-clip **recording** (macOS, 2026-06) uses two short-lived directories under the system temporary directory: `voice-clone-references/` holds the in-progress capture and `voice-enroll/` holds a stable copy while the private candidate is prepared. Both are deleted as part of enrollment/cancel; only an explicitly committed candidate moves into `voices/`.
- `history.sqlite` stores local generation history. Database initialization, migration, read,
  write, or delete failures are typed and fail closed: the UI shows a degraded state and disables
  destructive history actions instead of presenting an unavailable database as empty.
- `history-outbox/` queues published single-take audio for its pending History write when storage permits.
  The local schema-v1 JSON entry contains the generation record and is removed only after an
  idempotent SQLite commit. Startup and History entry reconcile it; the macOS recovery banner
  exposes Retry, Reveal Audio, and Export Audio without putting script or path data in telemetry.
  A separate atomic clear transaction deletes database rows before pending entries or WAVs, so a
  database failure cannot leave live History rows pointing to files clear-all already removed.
  If the queue write itself fails, a visible app-wide warning offers Retry History Save and Export
  Audio without interrupting playback. The exact pending record is retained only in app-session
  memory; it is **not** crash-safe until retry creates the outbox entry. The WAV remains on disk.
  Clear-all refuses to discard an unqueued record; no storage retry regenerates audio.
- `history-outbox/long-form/` holds bounded, digest-checked acceptance journals (at most 64 pending
  entries, 8 MiB each). Candidate segments and joined WAVs have unique names. Segment/assembly/joined
  QC and manifest serialization precede the atomic manifest and transactional History update.
  Before History reads or writes, reconciliation either confirms the database commit or restores
  the prior manifest and removes only newly owned, unreferenced candidate audio. Accepted audio
  is never deleted as rollback cleanup. Corrupt/unrecoverable journals remain for visible recovery;
  their private paths and generation records never enter telemetry or tracked evidence.
- Active macOS model-quality choices are stored in app preferences, keyed per generation mode. `DebugMode` isolates preferences to `com.qwenvoice.app.debug`; Release builds use `UserDefaults.standard`.

Delete local macOS app data by quitting the app and removing the app support root or the specific
subtree above. Use the model manager for an individual model so shared components still referenced
by another installed manifest remain valid. Deleting the whole `models/` root removes both model
folders and the component store and requires downloading them again; it does not by itself clear
normal app preferences such as the active model-quality choice.

## iPhone Storage

The iPhone app uses the App Group:

```text
group.com.patricedery.vocello.shared
```

Its shared container is rooted under the app-owned `Vocello` subtree and is managed by `Sources/iOSSupport/Services/AppPaths.swift`.

The May 2026 iOS identity rename moved pre-release storage from the old QVoice App Group to this Vocello App Group without migration, so device builds after the rename start with fresh iPhone data.

Repository-built internal diagnostics binaries honor this hermetic iPhone override only with the
`QWENVOICE_DEBUG` master gate enabled; distributed builds cannot enable it:

```sh
QVOICE_APP_SUPPORT_DIR=/path/to/custom/app-support
```

For physical-device XCUITest, a single safe relative component such as
`model-download-acceptance` resolves beneath the app's managed Application Support root. Path
separators and traversal components are rejected. That managed leaf also receives a stable,
one-way-digested background-session identity distinct from production; the leaf and any absolute
diagnostic path are never disclosed in the identifier. Production uses the App Group container and
its historical bundle-scoped background-session identifier when the debug master gate is absent.

Maintained iPhone subtrees:

- `models/` stores verified installed model files plus the hidden catalog-v2
  `.qwenvoice-components-v1/` content-addressed store. Model-visible component paths are regular
  hard links; deletion preserves blobs still live in another strict installed manifest.
- `downloads/ios_model_delivery_state.json` is the atomic schema-v2 delivery ledger. It stores only privacy-safe identifiers, relative paths, receipts, retry counts, byte progress, and terminal state.
- `downloads/staging/` is the only iPhone delivery staging tree; it holds durable delegate files plus per-model verified files, partials, and resume data.
- `diagnostics/model-downloads/` stores allowlisted local transfer/failure summaries, capped at 60 records and 5 MB. It excludes raw URLs, absolute paths, device identity, and user data.
- `outputs/` stores generated audio. The user can optionally also copy each new clip to an external Files/iCloud folder via Settings → "Saved outputs" (a user-granted security-scoped bookmark; no new entitlement). The internal copy here is always kept and is what History plays from.
- `voices/` stores committed saved-voice reference assets. Each row can delete only its own audio, transcript, and prepared prompt artifacts after an explicit confirmation; other voice-bank members remain intact.
- `voice-candidates/` privately stages review candidates for at most 24 hours. They are invisible to the saved-voice catalog until Keep/Save commits them; Cancel, Discard, and outside dismissal remove them. `voice-transactions/` is the bounded recovery journal for commit/replacement/delete operations.
- `cache/imported_references/` stores app-owned materializations of WAV, MP3, AIFF, or M4A files
  selected directly from Studio Clone, selected from Voices, or opened through Files, plus an
  adjacent `.txt` sidecar when supplied. A sidecar is preferred; otherwise on-device recognition
  produces an editable review without uploading audio. Enrollment stages the selected reference as
  a private candidate and copies it into `voices/` only after the user confirms Save. Picker
  cancellation, import failure, enrollment cancellation, and candidate discard do not publish a
  Saved Voice or replace the current Clone draft.
- Other `cache/` subtrees store required runtime cache data.
- `history.sqlite` stores local generation history. Database initialization, migration, read,
  write, or delete failures are typed and fail closed: the UI shows a degraded state with a visible
  Retry action and disables destructive history actions instead of presenting an unavailable database
  as empty.
- `history-outbox/` uses the same schema-v1 atomic publication/commit/reconciliation protocol as
  macOS. The iPhone recovery banner exposes Retry and an explicit system share/export action for
  available pending audio. Clear-all is resumable and database-first; its local marker remains until
  every requested pending-entry and audio cleanup has completed.
  The same app-session-only enqueue-failure warning and bounded `long-form/` acceptance journal
  apply on iOS. Long-form generation continuation remains session-scoped: retained segments are
  not a durably accepted History project until joined QC and the entire acceptance commit succeed.

The iPhone app intentionally keeps shared state constrained to the App Group app-support subtree. It does not use a parallel shared-user-defaults channel for model or voice state.

### Data protection and backup policy

`config/ios-storage-protection-policy.json` is the path-level authority. During bootstrap,
`IOSStorageProtectionPolicy` applies `NSFileProtectionCompleteUntilFirstUserAuthentication` to the
managed Vocello root and every governed subtree. This keeps local voice and generation data
encrypted while the device has not been unlocked after boot, while still allowing the established
background model-delivery session to finish after the first unlock. The app does not use the weaker
`NSFileProtectionNone` class and does not silently upgrade delivery state to
`NSFileProtectionComplete`, which would break background completion while the device is locked.

Backup behavior is intentional rather than inherited:

- downloaded models, delivery staging/ledger state, regenerable caches, candidates, transactions,
  and diagnostics are excluded from backup;
- generated outputs, committed saved voices, History, and its recoverable outbox remain included because they are
  user-created data that cannot necessarily be reconstructed;
- the policy is applied to existing descendants during bootstrap, including the SQLite database
  and its WAL/SHM sidecars, so a prior file cannot keep stale attributes indefinitely.

Catalog-v2 shared model blobs are deliberately published with mode `0444` and hard-linked into
each installed model. On 2026-09-02 a signed-device launch proved that recursively applying backup
and data-protection metadata could fail on one of those immutable links before the app finished
initializing. Bootstrap now opens an owner-write-only metadata window for an existing read-only
regular file, applies the governed attributes, and restores the exact original mode even when the
metadata operation throws. This does not weaken the protection class, make model content
persistently writable, or create another model owner; policy application still completes before
the engine and background delivery coordinator are created.

The deterministic policy validator rejects a missing path class, a protection mismatch, or an
unclassified maintained subtree. ASR-06 remains open until an exact signed candidate proves the
effective file attributes, backup exclusions, deletion behavior, and locked/relaunch behavior on a
physical iPhone.

## Voice Cloning Consent

Voice cloning accepts user-provided reference audio — recorded in the app or imported through the
native Files picker/document-open route. Only clone voices you own or have permission to use.
Reference clips, transcripts, and saved voices are local files, but the user remains responsible for
rights and consent before recording, importing, or reusing them.

Both apps expose the genuine `voiceCloning_consentAcknowledgment` control in Settings and keep
Clone Generate disabled until it is enabled. The choice is stored locally as
`vocello.voiceCloningConsent.v1`; it is not telemetry or an upload. A transcript is optional:
transcript-backed conditioning uses the supplied text, while a clip without text uses the distinct
audio-only x-vector path. Those modes have separate cache/artifact identities.

## Microphone And On-Device Transcription

Recording a reference clip uses the **Microphone** permission; transcript auto-fill for both recorded
and no-sidecar imported clips uses **Speech Recognition**. Both are requested on first use, and
recognition always runs with `requiresOnDeviceRecognition` — the audio is never sent to Apple or any
server, on macOS or iPhone. The review stays editable, Save is blocked while recognition is
unresolved, and unavailable recognition requires manual text or an explicit Use audio only choice.
Operation generations and cancellation prevent a stale recognizer result from replacing a newer
file or a user's edit. Transcripts are stored only as the local `.txt` sidecar next to the voice's
WAV. The prepared voice also stores privacy-safe enrollment metadata: a separately confirmed
reference-language value, transcript-source classification, automatic-transcription outcome, and
digest of the typed evidence. It stores no recognized text, raw error, or source path. Reference
language describes the conditioning clip only; it never selects the language of a future Clone
output. On macOS, transcription additionally requires Siri to be enabled (an OS gate — the system
silently refuses speech-recognition authorization otherwise); the app detects this and links the
relevant System Settings panes. Full permission model: [`macos-permissions.md`](macos-permissions.md).

## Diagnostics

Diagnostics should be user-initiated. The app may write local logs or exportable diagnostic files for model download, generation, playback, XPC, and model-admission failures, but it should not report those details over the network automatically.

When runtime telemetry is explicitly enabled, `generation-failures.jsonl` is a privacy-reduced
schema-v3 support log capped at 200 entries and 256 KiB; schema-v2 rows remain decodable. It stores
only an allowlisted error code and classification, known lifecycle stage and model identifier,
generation mode, text length, streaming flag, timestamp, and privacy-safe request/attempt receipt
identities. It never stores prompts, transcripts, delivery copy, voice descriptions, paths, URLs,
reflected/localized errors, stack symbols, credentials, email addresses, or arbitrary metadata.
The logger exposes a local clear operation; it never uploads the file.

Repository-local build and QA state lives under the ignored `build/` tree. Its machine-readable
contract is `config/build-output-policy.json`; `scripts/build_output_policy.py validate` rejects an
unowned root or a tracked command that bypasses the contract.

Persisted Codex task/session state is separate user-scoped developer-tool data, not Vocello app
data or repository build output. Its optional inventory and explicitly approved cleanup process is
documented in [`codex-session-storage.md`](codex-session-storage.md); live manifests, identifiers,
and journals remain temporary and untracked.

The table below is rendered from the manifest by
`python3 scripts/build_output_policy.py status --markdown`. Policy validation compares the marked
block byte-for-byte, so a manifest change cannot silently leave documentation stale.

<!-- BEGIN GENERATED BUILD OUTPUT POLICY TABLE -->
| Path | Owner | Class | Cleanup | Retention |
| --- | --- | --- | --- | --- |
| `build/cache/xcode/macos/` | macOS build and XCUITest lanes | `cache` | `aggressive` | Persistent incremental macOS Xcode cache |
| `build/cache/xcode/macos-tsan/` | Scheduled macOS ThreadSanitizer characterization lane | `cache` | `aggressive` | Isolated incremental macOS ThreadSanitizer Xcode cache |
| `build/cache/xcode/ios-device/` | Physical-device iOS build and XCUITest lanes | `cache` | `aggressive` | Persistent incremental physical-device Xcode cache |
| `build/cache/xcode/source-packages/` | Serialized Xcode SwiftPM resolver | `cache` | `aggressive` | Shared pinned Xcode package checkout and artifact store |
| `build/cache/swiftpm/mlx-audio-runtime/` | Owned Vocello Qwen3 Core SwiftPM commands | `cache` | `aggressive` | Persistent package-specific SwiftPM scratch cache |
| `build/cache/delivery-analysis/` | Operator-local delivery evaluator | `cache` | `aggressive` | Content-addressed canonical PCM and source-bound analysis layers; never promotion evidence by itself |
| `build/scratch/derived-data/foundation/` | Foundation target compile-safety lane | `scratch` | `routine` | Delete after successful invocation and during routine cleanup |
| `build/scratch/derived-data/package-resolution/` | Serialized Xcode SwiftPM resolver | `scratch` | `routine` | Ephemeral resolver intermediates; the shared checkout lives under build/cache |
| `build/scratch/transient/` | One-off repository tooling and migration-only diagnostic probes | `scratch` | `routine` | Invocation-local helpers and obsolete untracked probes; routine cleanup removes them |
| `build/scratch/gate-fingerprint/` | T1 commit-gate hook (scripts/hooks/precommit_gate.sh) | `scratch` | `routine` | Tree fingerprint and last-run log for the commit gate; removing it only re-runs the gate once |
| `build/scratch/derived-data/release-macos/` | macOS release build and archive lane | `scratch` | `routine` | Isolated release DerivedData; never reused as a development cache |
| `build/scratch/derived-data/release-ios/` | Local iOS archive and export lane | `scratch` | `routine` | Isolated local archive DerivedData; never reused as a development cache |
| `build/scratch/derived-data/xcodebuildmcp/macos/` | XcodeBuildMCP macOS profile | `scratch` | `routine` | Session scratch; repository scripts remain authoritative |
| `build/scratch/derived-data/xcodebuildmcp/ios-device/` | XcodeBuildMCP physical-device iOS profile | `scratch` | `routine` | Session scratch; repository scripts remain authoritative |
| `build/scratch/derived-data/ci/` | GitHub Actions deterministic compile and archive lanes | `scratch` | `routine` | Ephemeral CI DerivedData |
| `build/artifacts/macos/` | macOS deterministic, benchmark, and profile validators | `artifact` | `governed` | Retain compact summaries and publication-repair evidence; prune raw evidence only after validation |
| `build/artifacts/ios/` | Physical-device iOS diagnostics, benchmarks, and profiles | `artifact` | `governed` | Retain compact summaries and publication-repair evidence; prune raw evidence only after validation |
| `build/artifacts/ui-tests/` | Unified macOS and physical-device XCUITest runner | `artifact` | `prune-ui-results` | Keep policy-selected passing and failure result bundles |
| `build/artifacts/diagnostics/` | Cross-platform logs, crash deltas, and local diagnostics | `artifact` | `governed` | Validator-owned; preserve unresolved failure and publication-repair evidence |
| `build/artifacts/project-health/` | Generated project-health inventory and release-readiness diagnostics | `artifact` | `routine` | Local detailed reports are disposable; the compact reproducible snapshot is tracked under docs |
| `build/artifacts/quality-promotion/` | Source-bound public-promotion manifests and managed quality receipts | `artifact` | `preserve` | Preserve the current candidate manifest until promotion or explicit candidate retirement |
| `build/artifacts/app-store/` | Redacted App Store Connect, build-collision, and model-host readiness probes | `artifact` | `preserve` | Preserve the current candidate readiness summaries until closure or explicit candidate retirement |
| `build/artifacts/symbols/macos/` | macOS build and release identity checks | `artifact` | `preserve` | Keep only symbols whose UUIDs match the current macOS app and XPC products |
| `build/artifacts/symbols/ios/` | Physical-device iOS build and archive identity checks | `artifact` | `preserve` | Keep only symbols whose UUIDs match the current iOS app product |
| `build/artifacts/foundation/` | Foundation compile-safety result bundles and logs | `artifact` | `routine` | Compile-safety result bundles and logs are disposable after the command verdict |
| `build/dist/macos/` | macOS signing, notarization, and packaging lane | `distribution` | `dist` | Never remove during routine or aggressive cleanup; explicit distribution cleanup only |
| `build/dist/ios/` | iOS archive and TestFlight export lane | `distribution` | `dist` | Never remove during routine or aggressive cleanup; explicit distribution cleanup only |
<!-- END GENERATED BUILD OUTPUT POLICY TABLE -->

### External Xcode components are not repository cache

Repository inventory and cleanup own only the paths declared by
`config/build-output-policy.json`. They never delete, download, install, or manage Xcode Platform
Support, CoreSimulator runtime components, or global Xcode DerivedData. Removing all compatible iOS
runtime components can make `generic/platform=iOS` unavailable on current Xcode 26 toolchains even
while `xcodebuild -showsdks` still lists `iphoneos`. That state is an external toolchain issue, not
reclaimable repository output. Use `scripts/lib/ios_platform_preflight.py check`, then make any
multi-gigabyte component installation explicitly through Xcode Settings.

The public `build/Vocello.app` and `build/vocello` paths are manifest-owned symlinks to the current
canonical macOS products; they are not independent application or CLI copies.

Every Xcode invocation supplies an explicit DerivedData and cloned-package path. Local macOS outputs
are arm64-only. XcodeBuildMCP uses its own managed scratch DerivedData and never becomes a third
persistent cache. Xcode GUI DerivedData outside the repository is report-only; cleanup touches it
only through `--external-xcode --yes` after exact project matching.

`project.yml` remains the source of truth for the CLI and app-host-free iOS logic-test targets.
XcodeGen cannot directly emit their shared schemes (verified unchanged through 2.46.0), so `scripts/regenerate_project.sh`
follows XcodeGen with two narrow renderers: `scripts/generate_cli_scheme.py` and
`scripts/generate_ios_logic_scheme.py`. They substitute generated target identifiers into the
checked-in `VocelloCLI` and `VocelloiOSLogic` templates; project-input validation rejects a missing
or stale result. Supported commands therefore use explicit schemes and managed DerivedData rather
than leaking state through scheme-less `-target` invocations.

Exact-PID Allocations traces can grow by multiple gigabytes during one cold model run, so successful
profiles publish compact evidence and discard the raw trace unless `--keep-trace` is explicit. Use
`scripts/clean_build_caches.sh` for a read-only inventory and `--routine --dry-run` for the bounded
cleanup preview. Inventory reports filesystem free space, automatically eligible bytes, blocked
evidence, and failed-profile bytes that require explicit acknowledgement. `--routine` removes
eligible scratch while preserving
source, tracked benchmark history, persistent caches, current UUID-matched dSYMs, distribution
outputs, publication-repair evidence, and model stores. `--aggressive` additionally removes
persistent compilation/package caches and the public aliases. `--prune-ui-results` and `--dist`
target only their named class; `--clobber --yes` removes ignored repository-local generated state.
`./scripts/build.sh clean` delegates to bounded aggressive cleanup rather than deleting the whole
tree. Model deletion remains a separate explicit `--models` action. UI pruning includes smoke,
benchmark, and model-download lanes: it keeps the latest pass, preserves matching benchmark
publication-repair evidence, and reduces resolved failures or unrepairable unpublished results to
small lifecycle summaries. Legacy/malformed or explicitly pinned results stay blocked. A failed
profile trace is compacted only after a newer same-kind capture resolves it or through the exact,
reviewable command `--compact-profile-failure RUN_ID`. An explicit retention pin always wins.
Compaction keeps the required marker and summary plus at most 8 MiB of allowlisted auxiliary
diagnostics; each retained log is capped at 1 MiB. Copied or misrouted public app/CLI products make
selective or aggressive cache cleanup fail closed instead of deleting the unexpected product.

Persistent caches are independently selectable:

```sh
scripts/clean_build_caches.sh --cache macos --dry-run
scripts/clean_build_caches.sh --cache ios --dry-run
scripts/clean_build_caches.sh --cache packages --dry-run
scripts/clean_build_caches.sh --cache runtime --dry-run
```

Heavy local lanes read their minimum free-space requirement and cleanup hint from the same manifest.
They fail before regeneration, compilation, target launch, or evidence creation when the floor is
not met. Profile tracer stages retain their 5 GiB CPU and 15 GiB memory checks; their prerequisite
macOS/iOS builds still require 8 GiB and 10 GiB respectively, making those the effective full CPU
command floors. No runner
automatically applies a global routine or cache cleanup after success; UI/profile runners only apply
their own validator-safe retention transaction.
