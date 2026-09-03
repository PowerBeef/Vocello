---
status: active
owner: release-qa
summary: Fast local development workflow — path-aware focused checks, content-complete checkpoints, governed cache reuse, measured latency, and the unchanged explicit acceptance boundary.
sourceOfTruth:
  - scripts/dev.sh
  - scripts/development_workflow.py
  - scripts/tree_fingerprint.py
  - scripts/hooks/precommit_gate.sh
  - scripts/build_foundation_targets.sh
  - scripts/regenerate_project.sh
  - scripts/evidence_impact.py
---
# Development workflow

Vocello separates rapid feedback from publication evidence. The edit loop answers whether the
changed unit is coherent; the checkpoint answers whether the complete current tree is safe to
commit. CI remains the independent T2 authority. Model, phone, UI, benchmark, signing, and release
lanes remain explicit and are never silently inferred.

## Daily route

```sh
scripts/dev.sh plan        # read-only: show changes, classifications, and selected commands
scripts/dev.sh focused     # fast regeneration plus adjacent Python/changed XCTest checks
scripts/dev.sh checkpoint  # refresh, full tree gate, and path-required native evidence
```

Run `focused` repeatedly while editing. Run one `checkpoint` after a coherent change is ready. The
checkpoint records a privacy-safe exact-tree PASS marker, so staging the same bytes and committing
does not run the project gate again. Any subsequent edit, added untracked file, or HEAD change
invalidates the marker.

`scripts/development_workflow.py` obtains merge-required native lanes from
`scripts/evidence_impact.py`; it does not maintain a parallel classifier. It always refreshes and
validates derived artifacts and runs the quick project-input gate. That gate still executes the
complete Python self-test inventory whenever `scripts/` or `config/` changed. The workflow then
runs the deterministic macOS and incremental generic-iOS lanes required by the classified paths.

The helper never schedules XCUITest, a model download, generated audio, a benchmark, signing,
notarization, App Store work, or a release. Run those canonical scripts only when the task
explicitly asks for their evidence.

## Cache and generation policy

- `./scripts/regenerate_project.sh --fast` runs XcodeGen and the two narrow shared-scheme renderers,
  then atomically records the `project.yml` digest. It does not claim repository validation.
- `./scripts/regenerate_project.sh` retains checkpoint behavior and runs the project gate after
  generation. Normal iteration uses `--fast`, followed by one checkpoint.
- `./scripts/build_foundation_targets.sh ios --incremental` reuses the governed
  `build/cache/xcode/ios-device` DerivedData and matches physical-device Release optimization. The
  default command retains disposable clean DerivedData for isolated or CI-style proof. After the
  shared app and logic-test builds finish, the incremental route UUID-validates and preserves the
  final sibling app dSYM so `scripts/ios_device.sh preflight` cannot inherit stale symbols from the
  product that existed before the checkpoint.
- Internal diagnostic flags are target settings rather than package-wide `OTHER_SWIFT_FLAGS`, so
  diagnostics do not rebuild MLX, GRDB, NIO, Swift Collections, and every other dependency.
- Foundation and UI lanes retain full Xcode output under `build/artifacts/` while showing concise
  progress and a bounded failure tail in the task.

Do not delete persistent caches to recover speed. Use the build-output policy and selective cleanup
only when a verified invalidation or storage threshold requires it.

## Measured 2026-08-27 baseline

These are observations on the base M2/8 GB development Mac, not permanent thresholds:

| Operation | Before / cold | Steady state after overhaul |
| --- | ---: | ---: |
| Xcode project regeneration | full repository gate coupled to regeneration | 0.29 s fast generation |
| Focused 12-test Swift state suite | full core bundle was the only script route | 7.3 s warm |
| Generic iOS app + logic compile | 239 s clean package rebuild | 12.5 s warm governed cache |
| Failed iOS UI invocation output | 2.18 MB / 7,865 console lines | retained log plus concise output |

The first compile after removing the global diagnostics flag rebuilds the dependency graph once.
The regression signal is whether a no-source-change incremental run reuses it.

## Quality controls retained or strengthened

- The project gate, discovered Python inventory, native deterministic tests, generic device-SDK
  compile, and T2 CI are unchanged authorities.
- The commit marker hashes HEAD, final tracked content, and every non-ignored untracked path and
  byte. It ignores only index placement, so staging identical content is free while a re-edit cannot
  reuse stale evidence.
- `project.yml` remains the only project authority. Fast regeneration cannot record a stamp until
  XcodeGen and both generated schemes succeed.
- Focused test selection is an optimization, never coverage authority. Checkpoint and CI still run
  the full required inventory.
- Full logs and `.xcresult` bundles remain governed artifacts; concise output discards no evidence.

When a focused lane exposes an environment failure, use the applicable build/test triage guidance.
Do not switch to Simulator, invent a cache root, or weaken the checkpoint.
