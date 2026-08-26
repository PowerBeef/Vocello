---
status: active
owner: backend-and-platform
summary: Standing policy: why the macOS engine stays outside the App Sandbox, the constrained entitlement exceptions, and the trust boundary those exceptions must never widen.
sourceOfTruth:
  - Sources/QwenVoice.entitlements
  - Sources/QwenVoiceEmbeddedRuntime.entitlements
---
# Runtime hardening and trust boundary

**Status:** Accepted
**Owners:** Backend runtime, macOS, release/QA
**Review trigger:** Entitlement, dynamic-library, model-loading, XPC trust, or runtime-override changes

## Decision

Vocello's macOS engine remains outside the App Sandbox because the current MLX/Metal runtime and
local model workflow require capabilities that are not compatible with the product's present
sandbox profile. The app and XPC service use the hardened runtime, but the app entitlement set
contains `com.apple.security.app-sandbox=false`,
`com.apple.security.cs.disable-library-validation=true`, and
`com.apple.security.cs.allow-unsigned-executable-memory=true`.

Those exceptions are not treated as general extension points. Vocello does not load user-selected
executables, plug-ins, frameworks, or arbitrary dynamic libraries. The exceptions are constrained
to the signed application, its signed XPC service, pinned Swift packages, MLX-generated executable
memory, and catalog-verified model data.

## Assets and trust boundaries

| Asset | Trusted producer | Required controls |
| --- | --- | --- |
| App and XPC executables | Verified release workflow | Hardened runtime, matching Team ID, nested signature verification, notarization, staple validation |
| Swift/runtime dependencies | Repository manifests | Exact pins, lock agreement, action SHA pins, SBOM and dependency automation |
| Model files | Product catalog | Immutable revision, safe relative path, exact size and SHA-256, verified staging, atomic install |
| User audio, prompts, voices, history | Local user workflow | App-owned directories, no tracked content, privacy-safe bounded diagnostics, explicit export |
| XPC requests | Signed app/service pair | Expected bundle IDs and Team ID, typed wire contract, one active generation owner |
| Diagnostic overrides | Maintainer-run scripts | Internal-build capability plus `QWENVOICE_DEBUG`, classified registry, isolated storage, privacy-safe override provenance |

Network content is data, never executable code. Redirects remain HTTPS and host-allowlisted. A
downloaded artifact cannot become installed until its catalog identity, path, size, and digest pass.

## Compensating controls

1. `scripts/verify_release_bundle.sh` fails signed releases when the app and XPC Team IDs differ
   from each other, their signed metadata, or the expected release identity.
2. The release workflow builds a draft, verifies signature/notarization/checksums/SBOM/evidence,
   then publishes last. Failure leaves no newly public release.
3. Production-affecting environment overrides are inventoried in
   `config/runtime-debug-knobs.json` and require both the repository-owned
   `VOCELLO_INTERNAL_DIAGNOSTICS` build capability and explicit `QWENVOICE_DEBUG`. Distribution
   routes omit the capability, and internal generation telemetry binds active overrides by key and
   digest without retaining their raw values.
4. Path overrides must be absolute, normalized, writable, and debug-gated. They are for isolated
   tests and acceptance fixtures, not for selecting a production runtime or library.
5. `config/concurrency-safety.json` inventories every owned `@unchecked Sendable` declaration and
   binds it to an owner, synchronization invariant, and deterministic evidence.
6. The XPC service owns one generation at a time. Cancellation must reach a terminal barrier before
   unload, and cancellation is a typed terminal state rather than a string-shaped failure.
7. Diagnostics use allowlists and bounded retention; default persistence excludes prompts,
   transcripts, absolute paths, usernames, device identity, URLs, and secrets.
8. `config/macos-entitlement-policy.json` is the exact per-role allowlist. The app receives the
   five documented app capabilities; the engine XPC receives only the two MLX runtime exceptions;
   nested frameworks receive none. `scripts/entitlement_contract.py` checks source routing and
   rejects owned arbitrary-code loading APIs on every deterministic change, while packaged release
   verification compares the actual signed entitlements against the same allowlist.
9. The entitlement policy binds its exception review to the exact resolved `mlx-swift` and
   `mlx-swift-lm` versions. An MLX pin change cannot pass until the need and removal condition for
   both hardened-runtime exceptions are explicitly re-reviewed.

## Explicitly unsupported

- Disabling SIP, ad-hoc substitution of shipped binaries, or signature modification.
- Loading arbitrary plug-ins, frameworks, model-side scripts, or executable model artifacts.
- Enabling distributed behavior through process environment, even when `QWENVOICE_DEBUG` is set.
- Trusting a model solely because it came from a configured host or immutable revision.
- Treating an unsandboxed app as permission to broaden file, network, or process access.

## Residual risk and reconsideration

Disabling library validation increases the consequence of a malicious library entering the process,
and unsigned executable memory increases the importance of dependency and model-data boundaries.
The release and runtime contracts reduce but do not eliminate that risk. Re-evaluate sandboxing and
library validation whenever MLX packaging changes, Apple adds a compatible entitlement model, or the
runtime no longer needs these exceptions. The current 0.31.6/3.31.4 review retains both exceptions;
the machine-readable policy makes that conclusion stale automatically when either resolved pin moves.
