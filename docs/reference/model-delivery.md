# Model delivery

Vocello uses one shared native downloader, `HuggingFaceDownloader`, for pinned Hugging Face model
artifacts. macOS and the CLI use foreground `URLSession` instances. iPhone uses one bundle-aware
background session for the app lifetime. There is no second downloader, cloud synthesis path, or
ordinary-CI model fetch.

## Integrity and installation

Every file is matched to the model contract or the bundled iOS catalog, downloaded into staging,
checked against its exact byte count and SHA-256, and installed by an atomic directory swap. A
newly assembled file is hashed once. A same-process verified-artifact receipt permits finalization
without reading the complete file again; after a relaunch the staged file is hashed once before a
new receipt is trusted. Installed models retain the existing integrity-manifest format. Catalog-v2
artifacts additionally carry a shared-component installation plan: the installer publishes verified
component blobs before atomically presenting complete ordinary model folders.

macOS and CLI staging remains next to the model store under `.qwenvoice-downloads/`. iPhone has one
layout under the app-support root:

```text
downloads/
  ios_model_delivery_state.json
  staging/
    delegate-files/
    <model-id>/{files,partials,resume-data}/
diagnostics/model-downloads/
models/
  .qwenvoice-components-v1/  # content-addressed shared-component blobs and publication state
```

iPhone model downloads exclude cellular at the URLSession level (`allowsCellularAccess = false`):
multi-gigabyte artifacts stay pinned to Wi-Fi even when Wi-Fi Assist would silently reroute a flaky
connection over LTE, which collapsed observed throughput to sub-MB/s. The allowlisted
`diagnostics/model-downloads/` records (per-transfer task metrics including the cellular/expensive/
constrained path flags, phase transitions, and terminal summaries) are dual-written into the
devicectl-pullable caches mirror (`Library/Caches/Vocello/diagnostics/model-downloads/`) so download
behavior is triageable from the host; the App Group primary cannot be pulled.

### Cross-platform production catalog

`Sources/Resources/qwenvoice_production_model_catalog.json` is the reproducible, bundled catalog
contract used by macOS, CLI, and iPhone delivery. Its versioned shape is declared
by `config/model-catalog-schema-v2.json`; it is generated only from the shared model contract and
checked-in exact file evidence:

```sh
python3 scripts/model_catalog_contract.py rebuild --check
python3 scripts/model_catalog_contract.py validate
```

Every covered artifact has a 40-character immutable Hugging Face revision, an allowlisted HTTPS
resolve URL, safe relative paths, positive exact byte counts, and a lowercase SHA-256 for every
required file. Source digests make independent edits to the shared contract, iPhone catalog, or
generated catalog fail validation.

Initial artifact requests remain restricted to the catalog's exact host. URLSession redirects are
also policy-checked: only HTTPS destinations without credentials or IP/local hosts are accepted,
and the destination must remain on the configured host or the explicit Hugging Face distribution
suffixes `huggingface.co` and `hf.co`. A rejected redirect is never adopted as background work.

The catalog is `complete`: the bundled iPhone evidence supplies the three Speed variants and
`config/model-artifact-receipts.json` supplies the three Quality variants. All six packages pin a
revision plus the exact size and SHA-256 of every required file; no hash or size is inferred.
Schema v2 also proves that the four files beneath `speech_tokenizer/` have the same content across
all six artifacts. It gives that component separate content identity (ordered path, size, and
SHA-256) and compatibility identity (content plus component schema, loader ABI, runtime profile,
and encoder capability), along with ordered source artifacts. Schema-v1 catalog documents remain
read-compatible but cannot claim shared-component reuse.

macOS, CLI, and iOS now resolve `ProductionModelCatalog.deliveryPlan(...)` rather than enumerating a
live repository. `validate --require-complete` proves this static contract. It does not replace the
isolated Mac/iPhone lifecycle proofs, which must be refreshed after redirect, restoration,
delivery-routing, or shared-component changes. The current Mac proof is the 2026-08-08
isolated `pro_custom_speed` install at the 2026.08.06.1 marking re-pin (currency note
below); the current-generation iPhone proof is queued for the next phone window. The
2026-07-23 six-artifact Mac run and three-artifact iPhone run described below remain exact
history for the prior artifact generation.

## Shared component store

`SharedModelComponentStore` is the one content-addressed storage implementation. It lives beneath
the existing model root, not in another cache, and provides these fail-closed rules:

- A component is reusable only after every blob passes the catalog's exact size and SHA-256.
- When the store is verified, a later artifact's delivery plan omits only those exact component
  files and records the reused byte count; all other files still download normally.
- New component bytes are published immutably. The installed model exposes regular hard links to
  the verified blobs, never symlinks, so existing regular-file and deep-integrity checks still hold.
- Hashing and full replica validation happen outside the cross-process publication lock. Only the
  stale-safe atomic exchange, tombstone, and liveness publication hold the lock.
- Deleting a model never removes blobs needed by another installed manifest. Pruning derives
  liveness from strict installed manifests rather than mutable reference counts.
- Corrupt/missing blobs, symlink traversal, a concurrently changed model, or failed post-install
  validation aborts or rolls back without replacing the last valid model.

The production install path is integrated for all hosts. Resolving a schema-v2 delivery plan also
reconciles an existing installed artifact one at a time: every catalog file is authenticated before
the model can publish component bytes, and a healthy model is left alone while a damaged linked
presentation is repaired only from verified store blobs. A failed local authentication leaves the
existing directory untouched, grants no reuse, and lets the ordinary downloader repair it from the
network. Live validation completed 2026-07-23: an isolated Mac root installed all six artifacts
(final `models status` complete; one 682,293,092-byte tokenizer blob at a single inode with
nlink=7 across all six models plus the store; newest fully retained window measured
wire = expected − 682,295,738 exactly with zero retries), and the extended physical-iPhone lane
delivered Custom full-wire (2,312,057,897 bytes) then Design and Clone with exact
shared-component reuse (wire 1,629,761,538 and 1,653,779,429; zero duplicates, zero retries,
nominal thermal). Observed disk cost on the Mac was 12 GiB for the 16.2 GB catalog total.

> **Currency note (2026-08-01):** artifactVersion **2026.08.01.1** halves the shared
> speech tokenizer to f16 (341,179,884 bytes, digest `88f0a51a…`; OPTIMIZATION.md §R).
> The live-validation record above remains exact history for the 2026.07.26.1
> generation; fresh post-change delivery evidence rides the next release's battery per
> the standing rule that static completeness never substitutes for live proof.

> **Currency note (2026-08-08):** artifactVersion **2026.08.06.1** adds the required
> Article 50 marking generator (`marking/audioseal_wm16_generator_fp16.safetensors`,
> 29,360,042 bytes, digest `0e743d11…`) to every artifact. Fresh Mac delivery evidence
> ran the same day: an isolated root installed `pro_custom_speed` at the new
> 1,708,583,689-byte plan with the marking file arriving byte-exact against its pinned
> digest, full verify + install clean, zero retries. iOS post-change delivery evidence
> queues for the next physical-device window.

The iOS ledger is atomically written, versioned, and contains only privacy-safe identifiers and
relative paths. It records the logical request, model and artifact version, expected and verified
files, retries, monotonic received bytes, and terminal state. A one-time migration cancels the old
per-model sessions, waits for their cancellation callbacks, moves recoverable staging into the v2
layout, and removes the old document only when those sessions are empty. Installed models are not
touched.

## iPhone restoration and ownership

At launch, the coordinator asks the single background session for all tasks. Valid tasks whose
encoded model/artifact/file identity exactly matches the ledger and current catalog are adopted.
Unknown, stale, or duplicate tasks are cancelled, and only missing files receive new tasks.
Delegate temporary files are synchronously moved into durable app-group staging before the callback
returns. UIKit's background-session completion handler is released only after all delegate events
and durable install/failure postprocessing finish. Completion routing is exact-identifier scoped:
the canonical and debug-isolated coordinators retain and acknowledge only their own session's
handler. A foreign handler is neither stored nor completed, while an owned session with no durable
work is completed after reconciliation.

iPhone runs one model request at a time. macOS keeps its existing foreground concurrency.
**macOS/CLI run per-file range chunking by default since 2026-08-08** (evidence under the
tuning policy below). **iPhone runs chunked transfers by default since 2026-08-11.** The
background mechanism: task identities are schema v2 with optional range qualification, so
one file's N chunk tasks each survive relaunch adoption instead of being reaped as
`relativePath` duplicates; reconciliation, completion parking, and adoption are keyed per
range slot; chunk tasks on a background session fan out to the daemon up front (submitted
tasks keep transferring across process death, and the OS scheduler owns concurrency —
per-host caps are inert there) with 128 MiB ranges; and chunk task descriptions carry
their identity so post-relaunch transfer metrics still attribute payload bytes to their
file. The registered `QVOICE_DOWNLOAD_ENGINE_PROFILE` knob keeps `legacy` as the
regression-comparison arm on iPhone (inert without `QWENVOICE_DEBUG`).

The iPhone default flip is an explicit maintainer call (2026-08-11) and a recorded
deviation from the pre-registered model-download-lane A/B protocol: the mechanism is
identical to the macOS/CLI code path whose interleaved controlled comparison measured the
87.1% median improvement against this CDN's per-connection shaping, the 12-finding
adversarial review of the background-specific surfaces was resolved with deterministic
regression tests, and the deciding live observation was same-day canonical on-device
delivery — the legacy stream crawling at the shaped 2–6 MB/s versus chunked multi-gigabyte
installs completing in minutes on the same phone, network, and catalog. A lane-based
device A/B (`scripts/ui_test.sh ios model-download --engine-profile legacy|chunked`)
remains available for regression comparisons but is no longer a gate for this default.

The chunked-transfer mechanism landed 2026-08-08 (download-throughput investigation:
Hugging Face's CDN shapes throughput per connection — measured from the canonical Mac,
~20 MB/s for the first ~15 s of a connection, then 2-6 MB/s sustained with high variance —
so the multi-gigabyte long pole crawls on any single stream). Files at or above the
96 MiB threshold split into 64 MiB ranges drained by a bounded worker pool, with a
quarter-size tail window so the last ranges never leave one throttled connection running
alone; a failed chunk retries its own 16-64 MiB range, sibling chunk tasks are actively
cancelled on file failure (no duplicate wire bytes), files dispatch largest-first, chunk
transfer metrics attribute their bytes to their file so `wireBytes` accounting stays
exact, and an optional per-worker-session mode defeats HTTP/2/3 connection coalescing
(measured equivalent to the shared session on this CDN; kept as a diagnostic lever). The
CLI A/B knob is `QVOICE_DOWNLOAD_ENGINE_PROFILE` (`legacy` | `chunked` |
`chunked-multisession`, registered, inert without `QWENVOICE_DEBUG`).
Since 2026-08-11 a chunked partial is crash-resumable: each landed range is recorded in a
completed-range sidecar beside the partial (written atomically, after the bytes are in the
partial), so a process death re-fetches only missing ranges; a missing or invalid sidecar
fails closed to a clean restart of that file, and single-stream attempts invalidate any
sidecar so the two resume schemes can never disagree about the bytes on disk.

## States, cancellation, and retry

Visible states are: queued, waiting for connectivity, downloading, retrying, verifying, installing,
cancelling, installed, failed, deleting, and deleted. Speed and ETA are shown only during active
transfer. A separate no-progress message appears after 20 seconds of an actively running task;
waiting-for-connectivity comes from the URLSession delegate.

Explicit **Cancel** is a discard operation. The coordinator first persists `cancelRequested`, stops
new task registration, awaits all resume-data cancellation callbacks and terminal tasks, persists
the final deleted tombstone, and only then removes staging or reports deletion. If either critical
ledger write fails, cancellation fails closed: tasks or staging are preserved as applicable, the UI
shows a privacy-safe storage error, and relaunch cannot silently reinterpret the request as queued.
**Retry** preserves already verified files and reconstructs progress from the ledger, staged
partials, and adopted task byte counts.

Transient connection failures and HTTP 408, 429, and 5xx responses retry up to three times. A
`Retry-After` value is honored up to five minutes. One integrity mismatch receives one clean retry.
Cancellation, disk exhaustion, local filesystem errors, TLS trust failures, configuration errors,
and permanent 4xx responses do not retry.

## Diagnostics and acceptance

Local diagnostic summaries retain at most 60 records and 5 MB (raised from 20 in Phase 8 so one three-artifact shared-component lifecycle keeps every per-file record). Their allowlisted fields cover
timing, protocol, redirect/reuse and constrained/expensive-network flags, transferred bytes, and a
sanitized failure class. A successful attempt also records expected and wire bytes, duplicate bytes,
retry count, protocol set, thermal state, phase timings, and final-integrity status. Task completion
waits for URLSession's terminal callback so the success summary cannot overtake final task metrics.
Foreground delegate callbacks are serialized, durable staging is sequenced before terminal
completion, and high-frequency byte callbacks are reduced to bounded cumulative progress updates
plus the exact terminal byte count. This prevents a completed transfer from being stranded behind
its own progress backlog without sacrificing final byte accuracy.
Diagnostic summaries never contain a raw URL, absolute path, device identity, or user data.

Deterministic tests are model-free and Simulator-free. Live delivery is an explicit diagnostic:

```sh
# isolated macOS/CLI data root
./scripts/build.sh cli models install pro_custom_speed \
  --data-dir "$PWD/build/scratch/transient/model-download-acceptance" --verbose

# paired physical iPhone; safe leaf under managed Application Support,
# never the canonical App Group model tree
scripts/ui_test.sh ios model-download
```

The iPhone proof backgrounds and terminates the app during transfer, relaunches it, requires
non-regressing adopted progress, and waits for exact verified installation of Custom. With Custom
retained in the isolated root it then delivers Design and Clone, whose plans must reuse the
verified shared speech-tokenizer component — the pulled diagnostics validator requires each of the
three newest successes to account for its full catalog bytes either entirely on the wire or with
exactly the shared-component bytes reused, and at least two artifacts to show reuse. The same
validator is the autonomous transfer-health verdict: every payload transfer must report
`cellular=false` (proving the session-level Wi-Fi pin), and each artifact's payload throughput
(wire bytes over its network window) must clear the crawl floor —
`QVOICE_IOS_DOWNLOAD_MIN_MBPS`, default 2 MB/s, deliberately far below healthy Wi-Fi so only a
genuine collapse fails — with per-artifact and per-transfer rates written into
`validated-summary.json`. The lane's only precondition is a visibly quiescent canonical Settings
surface: each production model installed or plainly downloadable with no active transfer, and the
identical snapshot must be visible again after the isolated cleanup, so the proof also runs on a
freshly restored device. All three
isolated models are then deleted through the visible UI. It is not part of smoke, benchmark, CI, release, or packaging.
Crash-delta snapshots retain hashes rather than duplicating the device's historical diagnostics;
the lane pulls only its bounded model-download summaries into the local untracked result artifact.

The 2026-07-14 isolated Custom Speed acceptance passed on the Mac mini M2 8 GB and physical iPhone
17 Pro. Both transfers moved the exact 2,312,057,897 expected bytes without retry or duplicate
payload. Any control-plane traffic in earlier delivery routes was recorded separately and was never
classified as duplicate model payload. The iPhone XCUITest completed its
background/relaunch/install/visible-delete lifecycle in
81.6 seconds and reported HTTP/2 plus HTTP/1.1 with fair thermal state. This is lifecycle evidence,
not a performance baseline, and did not change concurrency or range-chunking defaults.

The lane also enters canonical Settings before and after the isolated lifecycle and requires all
three production models to remain installed with no visible canonical transfer in flight. The
debug isolation override accepts only an absolute
diagnostic path or one safe relative leaf; traversal and nested relative paths fail closed. Only
the managed relative leaf selects a separate app-lifetime background session, and its identifier
contains a one-way digest rather than the leaf itself. Production and absolute diagnostic roots
retain the historical bundle-scoped session identifier, so private paths cannot create arbitrary
URLSession namespaces.

Post-policy physical-iPhone run `ios-xcui-model-download-20260716-163359-61377762` repeated the
complete lifecycle. Expected and wire bytes both equaled 2,312,057,897, with zero retries or
duplicate bytes, one accepted redirect per artifact inside the declared provider boundary, HTTP/3
plus HTTP/1.1, nominal thermal state, final integrity, visible isolated cleanup, and canonical model
state preserved. Post-catalog macOS/CLI proof `model-download-acceptance-9a8da87` then transferred
the same exact 2,312,057,897 expected and wire bytes with zero control or duplicate bytes, zero
retries, HTTP/3 plus HTTP/1.1, and nominal thermal state. It measured 35.638 seconds of network
time, 0.003 seconds of verification, and 0.001 seconds of installation, reported final integrity,
and removed the isolated payload after preserving only bounded local diagnostics. These single
transfers are lifecycle evidence rather than concurrency tuning experiments.

## Tuning policy

One live transfer is a lifecycle proof, not a concurrency experiment. Connection counts or chunking
defaults may change only after a controlled comparison improves total transfer time by at least 15%
without more retries, duplicate bytes, thermal regression, or restoration failure.

> **Controlled comparison (2026-08-08, canonical Mac mini M2, isolated roots):** interleaved
> ABBABA·ABBABA, n=6 per arm, full fresh `pro_custom_speed` installs (1,708,583,689 bytes,
> artifactVersion 2026.08.06.1). Arm A (`legacy`: single-stream, 4 connections/host): median
> network window **232.6 s** (185.1-284.7 s; ~7.3 MB/s — the CDN was shaping, so the regime
> guard passes). Arm B (`chunked`: 64 MiB ranges + quarter-size tail, 4 workers,
> 6 connections/host, shared session): median **30.0 s** (28.2-30.5 s; ~57 MB/s).
> **Median improvement 87.1%**, every run zero retries, zero duplicate bytes, nominal
> thermal, final integrity clean; the chunked arm also collapsed run-to-run variance from
> ~100 s to ~2 s. A per-worker-session pilot measured within noise of the shared session
> (30.8 s vs 28.6 s), so the shared session remains the default topology. This is the
> evidence behind the macOS/CLI default flip; iPhone chunking remains a future device
> experiment per the concurrency section above.

Background Assets was evaluated and not adopted in this change. See
[`../decisions/model-delivery-background-assets.md`](../decisions/model-delivery-background-assets.md).

Changed-path evidence expectations are classified by
[`evidence-impact.md`](evidence-impact.md). Live model downloads remain explicit quality evidence,
not ordinary commit, merge, or release-packaging blockers.
