---
trigger: glob
globs: "**/Sources/**, **/Packages/**, **/Tests/**, **/project.yml, **/config/runtime-debug-knobs.json, **/config/concurrency-safety.json, **/config/runtime-refactor-contract.json, **/config/model-artifact-receipts.json, **/config/macos-entitlement-policy.json, **/config/ios-control-audit.json"
---

# Native Engineering Rule

Before editing Swift sources, packages, tests, `project.yml`, or native runtime/entitlement/control
contracts, read `docs/reference/native-engineering.md` (the authoritative native engineering rule).

Non-negotiable invariants enforced here:
- **Release-only:** no `#if DEBUG`; diagnostics use `VOCELLO_INTERNAL_DIAGNOSTICS`, `QWENVOICE_DEBUG=1`,
  and knobs registered in `config/runtime-debug-knobs.json`.
- **Swift 6 & concurrency:** register any `@unchecked Sendable` or `nonisolated(unsafe)` in
  `config/concurrency-safety.json`; never pass MLX arrays across isolation boundaries; honor
  `NonisolatedNonsendingByDefault`, `InferIsolatedConformances`, `MemberImportVisibility`, and strict
  memory safety.
- **MLX facade & pins:** product targets import only `VocelloQwen3Core`; exact pins move only with
  authorization and benchmark review (`docs/reference/mlx-guide.md` §9).
- **Generated project:** edit `project.yml`, never `QwenVoice.xcodeproj/project.pbxproj`; run
  `./scripts/regenerate_project.sh --fast` in the same commit when adding/moving/deleting Swift files.
- **Physical iPhone & XCUITest only:** no Simulator destinations; XCTest in Xcode test targets
  (Swift Testing only in `Packages/VocelloQwen3Core`).
- **Swift review:** run the read-only `vocello-swift-review` subagent on substantive Swift diffs and
  commit with `git commit --trailer 'Reviewed-by: vocello-swift-review'`.
