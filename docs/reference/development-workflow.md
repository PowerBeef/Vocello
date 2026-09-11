---
status: active
owner: release-qa
summary: Local development workflow — path-aware checks, no commit receipt, governed cache reuse, and the unchanged explicit acceptance boundary.
sourceOfTruth:
  - scripts/dev.sh
  - scripts/development_workflow.py
  - scripts/hooks/commit_lint.sh
  - scripts/privacy_scan.py
  - scripts/hooks/policy_guard.sh
  - scripts/hooks/generated_file_guard.sh
  - .claude/settings.json
  - scripts/build_foundation_targets.sh
  - scripts/regenerate_project.sh
  - scripts/evidence_impact.py
---
# Development workflow

Vocello separates rapid feedback from publication evidence. The edit loop answers whether the
changed unit is coherent; the local checkpoint checks the current tree in proportion to the change.
CI remains the independent complete T2 authority. Model, phone, UI, benchmark, signing, and release
lanes remain explicit and are never silently inferred.

## Daily route

```sh
scripts/dev.sh plan        # read-only: show changes, classifications, and selected commands
scripts/dev.sh check [--dry-run]   # lint, contracts, selected tests and the native lanes the dirty tree touches
scripts/dev.sh test | py | lint | ios   # one lane at a time
scripts/dev.sh ci                  # exactly what push CI runs, serially
```

Nothing blocks a commit except the commit lint hook (`scripts/hooks/commit_lint.sh`, wired as a
Claude Code `PreToolUse` Bash hook in `.claude/settings.json`): the branch must be `main`, the staged
diff whitespace-clean, and `scripts/privacy_scan.py` must find no private path or credential in the
staged files. It finishes in seconds and never builds. Run `scripts/dev.sh check` before pushing; the
routing is the same `scripts/ci/classify_changes.py` CI uses, so the local plan and the CI lanes agree.
CI on `main` is the gate; a red push is fixed forward or reverted. Two more `PreToolUse` guards
(`scripts/hooks/policy_guard.sh`, `scripts/hooks/generated_file_guard.sh`) block Simulator destinations,
whole-cache deletion, force pushes, new branches, direct `project.pbxproj` writes and hand edits of
generated files; `scripts/tests/test_claude_hooks.py` pins their behaviour.

Finalize intended tracked-file membership **before** derived refresh: project-health inventories
use Git-tracked files. Adding a new file to the index afterward can stale that generated summary
even if the content fingerprint is unchanged. Do not change index membership during a gate.

During frozen acceptance, do not run an editing/checkpoint cycle between shards. Keep progress in
the existing pinned untracked run bundles; follow [device pause/resume](ios-device-testing.md#pause-and-resume).
At a deliberate source checkpoint, update the roadmap and narrative together and acknowledge the
new full-tree evidence identity.

`scripts/evidence_impact.py` remains the classifier. The optional, versioned `localVerification`
section of its existing contract controls local scheduling; release/promotion requirements stay
separate. Exact reviewed prose exclusions prevent a package README from being treated as engine
code. New/unreviewed resource documentation and license/NOTICE files remain conservative.

`scripts/dev.sh check --dry-run` prints the lanes and commands for the dirty tree; `check` runs them.
Python selection walks literal import/helper/config references transitively and deliberately
over-selects on shared basenames; an input without a known test consumer, or a change to shared
tooling, runs the whole suite. Selection is local feedback, not a proof of complete dependency
coverage; CI runs every test.

`check_project_inputs.sh` without arguments is the full gate. `--local` selects local Python feedback
and is rejected in CI. `repo_invariants.sh` holds the exact product-invariant greps, `privacy_scan.py`
the private-path and credential scan, and `public_facts_contract.py` the release-identity and public
copy checks. Nothing local schedules XCUITest, a model download, generated audio, a benchmark,
signing, notarization, App Store work, or a release; run those canonical scripts only when the task
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

September 6 workflow validation measured the representative documentation checkpoint at **24.3 s**
on the development Mac: refresh 6.7 s, derived validation 3.2 s, documentation 1.0 s, metadata 6.1 s,
roadmap 7.3 s and surface coverage under 0.1 s. Every command passed and the source remained
unchanged. No native build, model or phone was used. This is a route measurement, not full-patch
acceptance or a permanent timing gate. An analyzer-edit example selected 45 of 122 Python modules
through reverse dependencies; unknown/routing changes still select all modules.

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

- The complete project gate, discovered Python inventory, native tests and generic device-SDK
  compile remain CI/release authorities. Local selection cannot replace candidate evidence.
- The commit marker hashes HEAD, final tracked content, and every non-ignored untracked path and
  byte. It ignores only index placement, so staging identical content is free while a re-edit cannot
  reuse stale evidence.
- `project.yml` remains the only project authority. Fast regeneration cannot record a stamp until
  XcodeGen and both generated schemes succeed.
- Local test selection is an optimization, never coverage authority. CI/release still run the full
  required inventory. Legacy quick-gate behavior remains local-only; new work uses `dev.sh`.
- Full logs and `.xcresult` bundles remain governed artifacts; concise output discards no evidence.

When a focused lane exposes an environment failure, use the applicable build/test triage guidance.
Do not switch to Simulator, invent a cache root, or weaken the checkpoint.
