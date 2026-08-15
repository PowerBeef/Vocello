---
status: historical
owner: ios
summary: ADR (accepted 2026-07-14): retain the repaired background URLSession model-delivery path; Background Assets rejected for a second lifecycle and unvalidated store semantics.
contentDigest: sha256:29f146ca88f0624bb9b448a3939da3283716148d18f118e2b1607fbba6c57fc9
---
# ADR: retain background URLSession model delivery

- Status: accepted
- Date: 2026-07-14
- Decision owner: iOS and backend

## Context

Vocello downloads multi-gigabyte, revision-pinned Qwen model packages from Hugging Face. iPhone must
survive backgrounding and process relaunch while preserving SHA-256 verification, atomic install,
App Group storage, user-controlled deletion, and the repository's no-bundled-weights posture.

## Options considered

| Option | Advantages | Costs and constraints |
| --- | --- | --- |
| Repaired background `URLSession` | Works with current Hugging Face hosting and catalog; supports App Store/TestFlight; preserves current App Group, integrity, retry, cancellation, and cleanup contracts | The app owns durable task reconciliation, ledger migration, and background completion |
| Unmanaged Background Assets with existing hosting | System-managed scheduling and storage may improve large-download lifecycle | Requires a Background Assets extension and a second delivery lifecycle; entitlement, App Store behavior, host behavior, update cadence, migration, and deletion semantics require separate validation |
| Apple-hosted on-demand Background Assets | Strong system integration and Apple-hosted delivery | Requires redistribution of model payloads, hosted-asset operations and cost, licensing confirmation for every model, App Store asset cadence, and migration away from direct pinned Hugging Face revisions |

## Decision

Use the repaired single background `URLSession` route for production. Do not add a Background Assets
target, extension, entitlement, hosted payload, or parallel downloader in this change.

## Revisit criteria

Reconsider only through a separate product decision after confirming App Store/TestFlight support,
Hugging Face and model redistribution rights, asset-hosting cost, update cadence, extension and App
Group migration, deletion/storage behavior, and a measured lifecycle or transfer advantage over the
current implementation.
