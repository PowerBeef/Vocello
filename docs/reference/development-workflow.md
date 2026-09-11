---
status: active
owner: release-qa
summary: Fast local development workflow — path-aware focused checks, content-complete checkpoints, governed cache reuse, measured latency, and the unchanged explicit acceptance boundary.
sourceOfTruth:
  - scripts/dev.sh
  - scripts/development_workflow.py
  - scripts/tree_fingerprint.py
  - scripts/hooks/precommit_gate.sh
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
scripts/dev.sh focused     # fast regeneration plus adjacent Python/changed XCTest checks
scripts/dev.sh checkpoint  # refresh, relevant contracts/tests and platform checks
scripts/dev.sh checkpoint --full  # complete deterministic checkpoint
```

Run `focused` repeatedly while editing. Run one `checkpoint` after a coherent change is ready. The
checkpoint records a privacy-safe exact-tree PASS marker, so staging the same bytes and committing
does not run the project gate again. Any subsequent edit, added untracked file, or HEAD change
invalidates the marker. Local markers also bind resolved tool executables, Python/OS/Xcode identity
and relevant toolchain environment. Equivalent shell PATH ordering reuses a marker only when PATH
membership and all fingerprinted tool resolutions remain unchanged. They are not release evidence. The checker refuses edits during
verification instead of attaching PASS to the later untested content. The commit hook
(`scripts/hooks/precommit_gate.sh`, wired as a Claude Code `PreToolUse` Bash hook in
`.claude/settings.json`) only checks the receipt and blocks if it is absent, stale or unreadable. It
never starts another build. Run the checkpoint directly so long checks remain observable and are not
limited by the hook timeout. The receipt binds tree bytes plus resolved tool identities, not PATH
membership, so the hook environment and the tool shell agree. `scripts/dev.sh status` prints the
receipt state (fresh, stale, missing) with the branch, dirty paths and verification class; the
`SessionStart` hook prints it at the start of every session. Two more `PreToolUse` guards
(`scripts/hooks/policy_guard.sh`, `scripts/hooks/generated_file_guard.sh`) block Simulator destinations,
whole-cache deletion, force pushes, new branches, direct `project.pbxproj` writes and hand edits of
generated files; `scripts/claude_config_contract.py` validates the wiring.

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

| Change | Local checkpoint |
| --- | --- |
| Classified prose, generated docs or roadmap state | Derived refresh/validation, links, lifecycle/digests, facts, roadmap evidence and surface coverage |
| Python/configuration tooling | All static project contracts plus reverse-dependency-selected Python tests |
| macOS-only source | Static contracts, applicable Python fixtures, macOS deterministic tests and app build |
| iOS source/policy | Static contracts, host-executed policy tests and generic iOS compile |
| Shared runtime/resources or build/verification authority | Both platforms; routing/build-authority edits require full Python discovery |
| Unknown/deleted tooling input or unknown dependencies | Full Python discovery; unknown repository classes also broaden native checks |

Python selection walks literal import/helper/config references transitively; it deliberately
over-selects on shared basenames. A changed input without a known test consumer falls back to full
discovery. Selection is local feedback, not a proof of complete dependency coverage; CI/release
retain discovery of every test. Dynamic or unusual dependencies warrant `checkpoint --full`.
Native applicability also consults iOS/shared source membership in `project.yml`; a path list cannot
silently omit a newly shared source. Unknown project syntax broadens to both platforms.

`scripts/dev.sh plan --json --paths docs/development-progress.md` previews representative changes
without executing anything or recording PASS. Executable checkpoints always derive their actual
changed paths from Git and reclassify after derived refresh. `scripts/dev.sh assists` checks optional
Xcode configuration only; it neither requires installation nor contacts devices/accounts.

`check_project_inputs.sh` without arguments remains the full gate. `--local` selects local Python
feedback and is rejected in CI. `repo_invariants.sh` holds the exact product-invariant greps and
the Python suite runs once, inside the parent gate. Documentation link/path/command checks
live in `documentation_contract.py`, with negative fixtures, rather than duplicate inline scripts.

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
