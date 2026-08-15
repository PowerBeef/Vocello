---
status: historical
owner: backend-mlx
summary: ADR (accepted 2026-07-14): the Qwen3 runtime is a first-party monorepo package at Packages/VocelloQwen3Core, not a patch stack; compatibility identities preserved behind the facade.
contentDigest: sha256:bd44fd793b3436e3613088e4688789a6bcbfd1606d52932220fc886867f5fb04
---
# ADR: Own the Qwen3 runtime as a monorepo core package

- **Status:** Accepted
- **Date:** 2026-07-14
- **Owners:** Backend/MLX and Release/QA

## Context

Vocello's Qwen3 implementation began as a narrowed import of `mlx-audio-swift`, but it now owns
product-specific loading, generation, streaming, cancellation, memory, telemetry, codec, and clone
artifact contracts. The former `third_party_patches/` path implied a replaceable patch stack and
encouraged unsafe rebase or wholesale-copy assumptions.

## Decision

The complete runtime lives at `Packages/VocelloQwen3Core` as a first-party monorepo package. Its
stable application-facing product and import module are `VocelloQwen3Core`. The package also
preserves the original Swift package name (`MLXAudio`), compatibility products (`MLXAudioCore`,
`MLXAudioCodecs`, `MLXAudioTTS`), targets, import modules, and public APIs behind that facade. The
move changed ownership and location without changing synthesis behavior or persistent identities.

The current contracts are:

- `VENDOR_MANIFEST.json`: component and contract index;
- `LINEAGE.json`: immutable import origin and separate upstream review point;
- `COMPATIBILITY.json`: preserved package and dependency identities;
- `OWNERSHIP.json`: allowed module imports and prohibited reverse dependencies;
- `RUNTIME_CAPABILITIES.json`: current owned behavior and evidence;
- `UPSTREAM_BASELINE.json` and `PATCHES.json`: retained historical comparison evidence;
- `ORIGINS.md`, `NOTICES.md`, and `LICENSE`: attribution and licensing.

`scripts/vendor_runtime_contract.py` validates these contracts offline. New runtime work is owned
capability development, not an accumulating patch. Selective upstream intake remains possible, but
it must preserve product behavior and never rewrite the historical import identity.

## Consequences

- Contributors review this package as critical first-party runtime code.
- Application, UI, XPC, persistence, and product-policy modules may consume the package but may not
  become package dependencies.
- Package/product/module names remain compatible behind the implemented typed facade, reducing
  migration risk while product sources depend only on `VocelloQwen3Core`.
- Retiring legacy MLXAudio implementation naming and large-file decomposition remain explicit
  follow-up work requiring separate behavior-preserving changes and deterministic evidence.
