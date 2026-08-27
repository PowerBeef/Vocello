---
status: active
owner: release-qa
summary: Standing policy: Vocello is the public name; QwenVoice/QVoice remain compatibility identities wherever change would break imports, signatures, persisted data, or evidence — with the compatibility map and migration bar.
sourceOfTruth:
  - project.yml
---
# Product identity compatibility

> **Currency review (2026-08-27):** the new support, attribution, and Settings surfaces use Vocello
> publicly while retaining the existing module, bundle, storage, and evidence compatibility IDs.
> No identity migration was introduced.

**Status:** Accepted
**Owners:** Release/QA with affected platform owners
**Review trigger:** Branding, bundle/module identity, storage root, App Group, environment key, or schema changes

## Decision

**Vocello** is the public product name. **QwenVoice** and **QVoice** remain compatibility identities
where changing them would break source imports, signatures, persisted data, scripts, or historical
evidence. They are not stale branding to replace opportunistically.

Persistent identifiers may change only through a separately reviewed migration that proves
backward reads, atomic transfer, rollback, and preservation of installed models, voices, outputs,
history, diagnostics, and release identity.

## Compatibility map

| Surface | Current contract | Policy |
| --- | --- | --- |
| Public app/site/release name | Vocello | Use for user-facing copy and new public artifacts |
| Repository | QwenVoice | Stable project and automation identity |
| Swift application/core modules | `QwenVoice*` | Preserve until a facade-backed source migration proves compatibility |
| Owned model package | `Packages/VocelloQwen3Core` | First-party path and public facade; legacy `MLXAudio*` products are transitional implementation compatibility |
| macOS/iOS bundle IDs | `config/apple-platform-capability-matrix.json` | Never rename without signed update and data/keychain migration review |
| Shared iOS App Group | `group.com.patricedery.vocello.shared` | Persistent container identity; never rotate without container migration |
| macOS support directory | `QwenVoice` / debug-isolated equivalent | Preserve installed models, voices, outputs, and history |
| iOS managed support directory | `Q-Voice` fallback or App Group `Vocello` root | Preserve for fallback and migration compatibility |
| Environment variables | `QWENVOICE_*` and `QVOICE_*` | Existing names remain stable; every production use is registered and gated/classified |
| Telemetry and benchmark schemas | Versioned QwenVoice/Vocello records | Additive evolution with backward decoding; historical records are immutable |
| XPC service and wire names | QwenVoice compatibility identifiers | App-owned typed contract; change only with coordinated client/service compatibility |

## New naming

New public APIs and first-party package capabilities use `VocelloQwen3*` names. Low-level imported
or compatibility symbols may keep `MLXAudio*` until product imports have migrated and parity is
proven. New persistent identifiers should use Vocello naming only when no installed-state migration
is created by doing so.

## Migration requirements

Any proposal to remove a compatibility identity must include:

1. an inventory of readers, writers, signatures, scripts, CI, and tracked evidence;
2. a versioned forward migration with backward-read support;
3. atomicity, interruption, corruption, and rollback tests;
4. platform-specific release/update behavior;
5. privacy review for copied or renamed user data;
6. documentation and support messaging;
7. evidence that no historical benchmark or release identity was rewritten.
