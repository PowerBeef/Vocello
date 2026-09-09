from __future__ import annotations

import importlib.util
import base64
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "supply_chain_contract.py"
SPEC = importlib.util.spec_from_file_location("supply_chain_contract", SCRIPT)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


class SupplyChainContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for relative in (
            ".github/workflows", ".github/ISSUE_TEMPLATE", "config", "scripts", "website"
        ):
            (self.root / relative).mkdir(parents=True, exist_ok=True)
        self.sha = "a" * 40
        (self.root / "config/toolchain.json").write_text(json.dumps({
            "schemaVersion": 1,
            "native": {}, "release": {}, "website": {},
            "actions": {
                "actions/checkout": {"version": "v4", "sha": self.sha},
                "actions/upload-artifact": {"version": "v4", "sha": self.sha},
            },
        }), encoding="utf-8")
        workflow = """on:
  push:
    tags: ['v*']
jobs:
  source-authority:
    permissions:
      contents: read
      checks: read
    steps:
      - name: Checkout
        uses: actions/checkout@%s # v4
      - run: |
          git merge-base --is-ancestor "$commit" origin/main
          gh api repos/${GITHUB_REPOSITORY}/git/ref/tags/${RELEASE_TAG}
          gh api repos/${GITHUB_REPOSITORY}/git/tags/${tag_object}
          gh api --paginate --slurp "repos/${GITHUB_REPOSITORY}/commits/${commit}/check-runs?filter=latest&per_page=100"
          python3 scripts/release_source_authority.py
          python3 scripts/release_evidence.py verify-source
  package:
    needs: source-authority
    runs-on: macos-26
    steps:
      - name: Verify release tag and source identity
      - name: Generate and validate release evidence
      - name: Attest verified DMG provenance
      - name: Create or reuse draft GitHub Release
      - name: Reset draft Release assets
        run: gh release view "$RELEASE_TAG" --json assets && gh release delete-asset "$RELEASE_TAG" stale --yes
      - name: Upload verified assets to draft Release
      - name: Verify downloaded Release assets
        run: echo "unexpected or missing draft Release assets"
      - name: Verify packaged DMG
        run: ./scripts/verify_packaged_dmg.sh artifact.dmg metadata.txt
      - name: Run process-bound iOS release readiness
        run: python3 scripts/required_step_ledger.py run --step platform-readiness -- bash -euo pipefail -c 'scripts/macos_test.sh gate && ./scripts/build_foundation_targets.sh ios'
      - name: Reject an existing App Store build identity
        run: ./scripts/install_pinned_asc.sh && python3 scripts/required_step_ledger.py run --step build-collision-preflight -- python3 scripts/app_store_build_preflight.py check --output app-store-build-preflight.json
      - name: Archive VocelloiOS
      - name: Export App Store IPA
      - name: Verify exported IPA identity and signing contract
        run: python3 scripts/required_step_ledger.py run --step ipa-verification -- python3 scripts/verify_ios_release_artifacts.py --output ios-release-artifact-verification.json
      - name: Generate and validate iOS release evidence
  compile-ios:
    needs: source-authority
  archive-ios:
    needs: source-authority
""" % self.sha
        (self.root / ".github/workflows/release.yml").write_text(workflow, encoding="utf-8")
        promotion = """on:
  workflow_dispatch:
    inputs:
      tag:
permissions:
  contents: write
  checks: read
steps:
  - name: Checkout
    uses: actions/checkout@%s # v4
  - name: Verify tag and draft state
    run: |
      git merge-base --is-ancestor "$commit" origin/main
      gh api repos/${GITHUB_REPOSITORY}/git/ref/tags/${RELEASE_TAG}
      gh api repos/${GITHUB_REPOSITORY}/git/tags/${tag_object}
      gh api --paginate --slurp "repos/${GITHUB_REPOSITORY}/commits/${commit}/check-runs?filter=latest&per_page=100"
      python3 scripts/release_source_authority.py
  - name: Download and validate candidate plus promotion evidence
    run: |
      test -f quality-promotion.json
      python3 scripts/release_evidence.py validate --output-dir remote
      python3 scripts/quality_promotion.py validate --platform macos
  - name: Publish source-bound verified Release
    run: gh release edit "$RELEASE_TAG" --draft=false
""" % self.sha
        (self.root / ".github/workflows/promote-release.yml").write_text(promotion, encoding="utf-8")
        security = """name: Security
on:
  pull_request:
  push:
    branches: [main]
  schedule:
    - cron: '23 8 * * 2'
  workflow_dispatch:
jobs:
  changes:
    name: Security path routing
    outputs:
      native: ${{ steps.classify.outputs.native }}
      website: ${{ steps.classify.outputs.website }}
    steps:
      - name: Checkout
        uses: actions/checkout@%s
      - id: classify
        run: |
          git diff --name-only "origin/$BASE_REF...HEAD"
          git diff --name-only "$BEFORE_SHA..$HEAD_SHA"
  dependency-review:
    steps: []
  swift-dependency-submission:
    if: github.event_name == 'push' || github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'
    permissions:
      contents: write
    steps:
      - name: Checkout
        uses: actions/checkout@%s
      - run: python3 scripts/swift_dependency_snapshot.py > "$RUNNER_TEMP/swift-dependency-snapshot.json"
      - run: gh api repos/example/project/dependency-graph/snapshots --input "$RUNNER_TEMP/swift-dependency-snapshot.json"
  npm-advisory-audit:
    needs: changes
    if: needs.changes.outputs.website == 'true'
    permissions:
      contents: read
    steps:
      - run: npm --prefix website audit --package-lock-only --audit-level=high
  codeql:
    needs: changes
    if: needs.changes.outputs.native == 'true' || needs.changes.outputs.website == 'true'
    runner: macos-26
    steps:
      - name: Select and validate native toolchain
        run: |
          NUMPY_PIN="$(python3 -c "import json; print(json.load(open('config/toolchain.json'))['native']['numpy']['version'])")"
          python3 -m pip install --quiet --break-system-packages "numpy==${NUMPY_PIN}"
          ./scripts/install_pinned_tools.sh
          if ! xcrun metal --version >/dev/null 2>&1; then
            xcodebuild -downloadComponent metalToolchain
          fi
          xcrun metal --version
      - name: Prepare Swift CodeQL build inputs
        if: matrix.language == 'swift'
        run: ./scripts/build.sh codeql-prepare
      - name: Initialize CodeQL
      - name: Build Swift targets for CodeQL
        if: matrix.language == 'swift'
        run: ./scripts/build.sh codeql
      - name: Analyze
  security-required:
    name: Security required
    needs: [changes, dependency-review, swift-dependency-submission, npm-advisory-audit, codeql]
    if: always()
    steps:
      - run: grep -Eq '"result": *"(failure|cancelled)"'
""" % (self.sha, self.sha)
        (self.root / ".github/workflows/security.yml").write_text(security, encoding="utf-8")
        dependency_watch = """name: Swift dependency watch
on:
  schedule:
    - cron: '41 14 * * 1'
  workflow_dispatch:
permissions:
  contents: read
  security-events: read
jobs:
  inspect:
    steps:
      - name: Checkout
        uses: actions/checkout@%s
      - run: python3 scripts/swift_dependency_updates.py validate
      - run: |
          python3 scripts/swift_dependency_updates.py report --repository "$GITHUB_REPOSITORY" --generated-at 2026-08-26T00:00:00Z --json-out "$RUNNER_TEMP/swift-dependency-watch.json" --markdown-out "$RUNNER_TEMP/swift-dependency-watch.md"
      - name: Retain proposal
        uses: actions/upload-artifact@%s
        with:
          path: |
            ${{ runner.temp }}/swift-dependency-watch.json
            ${{ runner.temp }}/swift-dependency-watch.md
          retention-days: 14
""" % (self.sha, self.sha)
        (self.root / ".github/workflows/swift-dependency-watch.yml").write_text(
            dependency_watch, encoding="utf-8"
        )
        (self.root / "config/swift-dependency-update-policy.json").write_text(json.dumps({
            "schemaVersion": 1,
            "packages": [
                {"identity": identity}
                for identity in (
                    "grdb.swift", "mlx-swift", "mlx-swift-lm",
                    "swift-huggingface", "swift-transformers",
                )
            ],
        }), encoding="utf-8")
        (self.root / "scripts/build.sh").write_text(
            '\n'.join((
                '#!/usr/bin/env bash',
                'DESTINATION="platform=macOS,arch=arm64"',
                'CODEQL_DESTINATION="generic/platform=macOS"',
                'CODEQL_DERIVED_DATA="$QVOICE_SCRATCH_CI/codeql-macos"',
                'CODEQL_BUILD_PHASE="none"',
                'ARCHS=arm64',
                'assert_mlx_metallibs() {',
                '  local app_bundle="$1"',
                '  local relative_path',
                '  for relative_path in "Contents/Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib" "Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib"; do',
                '    if [ ! -s "$app_bundle/$relative_path" ]; then',
                '      return 1',
                '    fi',
                '  done',
                '}',
                'build_app() {',
                '  local -a build_tail=(build)',
                '  if [ "$CODEQL_BUILD_PHASE" = "trace" ]; then',
                "    build_tail=('EXCLUDED_SOURCE_FILE_NAMES=*.metal' build)",
                '  fi',
                '  if [ "$CODEQL_BUILD_PHASE" = "none" ]; then',
                '    sync_dev_signing_cache "$signing_identity" "$XCODEBUILD_APP" "$APP_BUNDLE"',
                '  fi',
                '  echo "${build_tail[@]}"',
                '  if [ ! -d "$XCODEBUILD_APP" ]; then',
                '    return 1',
                '  fi',
                '  if [ "$CODEQL_BUILD_PHASE" = "trace" ]; then',
                '    assert_macos_bundle_arm64_only "$XCODEBUILD_APP"',
                '    return 0',
                '  fi',
                '  assert_mlx_metallibs "$XCODEBUILD_APP"',
                '  assert_macos_bundle_arm64_only "$XCODEBUILD_APP"',
                '  assert_signing_identity "$XCODEBUILD_APP" "$signing_identity"',
                '  if [ "$CODEQL_BUILD_PHASE" = "prepare" ]; then',
                '    return 0',
                '  fi',
                '  if [ -e "$APP_BUNDLE" ] || [ -L "$APP_BUNDLE" ]; then',
                '    quit_app_if_running',
                '    rm -rf "$APP_BUNDLE"',
                '  fi',
                '  ln -s "$XCODEBUILD_APP" "$APP_BUNDLE"',
                '  preserve_dsyms',
                '  write_build_provenance',
                '  record_dev_signing_identity',
                '}',
                'configure_codeql_build() {',
                '  CODEQL_BUILD_PHASE="$1"',
                '  DESTINATION="$CODEQL_DESTINATION"',
                '  DERIVED_DATA="$CODEQL_DERIVED_DATA"',
                '  XCODEBUILD_APP="$DERIVED_DATA/Build/Products/Release/$APP_NAME.app"',
                '}',
                'cmd_codeql_prepare() {',
                '  configure_codeql_build prepare',
                '  build_app "scripts/build.sh codeql-prepare"',
                '}',
                'touch_codeql_sources() {',
                '  find "$ROOT_DIR/Sources" "$ROOT_DIR/Packages/VocelloQwen3Core/Sources" -name "*.swift" -exec touch {} +',
                '}',
                'cmd_codeql() {',
                '  configure_codeql_build trace',
                '  touch_codeql_sources',
                '  build_app "scripts/build.sh codeql"',
                '}',
                'case "${1:-}" in',
                '  codeql-prepare) ;;',
                '  codeql) ;;',
                'esac',
            )),
            encoding="utf-8",
        )
        (self.root / "scripts/verify_release_bundle.sh").write_text(
            '\n'.join((
                'SKIP_LAUNCH_SMOKE="${QWENVOICE_SKIP_LAUNCH_SMOKE:-0}"',
                'if [ "$SKIP_LAUNCH_SMOKE" = "1" ] && [ "${CI:-}" = "true" ]; then exit 1; fi',
                '/usr/bin/open -n "$APP_PATH"',
                'echo "did not remain running long enough to pass startup smoke"',
            )),
            encoding="utf-8",
        )
        (self.root / "scripts/verify_packaged_dmg.sh").write_text(
            '"$SCRIPT_DIR/verify_release_bundle.sh" "$COPIED_APP"\n',
            encoding="utf-8",
        )
        (self.root / ".github/dependabot.yml").write_text(
            '\n'.join(f'package-ecosystem: "{value}"' for value in ("github-actions", "npm", "swift")),
            encoding="utf-8",
        )
        (self.root / "website/package.json").write_text(json.dumps({
            "scripts": {key: "true" for key in ("lint", "test", "build", "check")}
        }), encoding="utf-8")
        for relative in (
            "SECURITY.md", ".github/CODEOWNERS", ".github/ISSUE_TEMPLATE/bug_report.yml",
            ".github/ISSUE_TEMPLATE/feature_request.yml", ".github/ISSUE_TEMPLATE/config.yml",
            "scripts/release_evidence.py", "scripts/release_sbom.py",
            "scripts/release_source_authority.py",
            "scripts/swift_dependency_snapshot.py",
            "scripts/swift_dependency_updates.py",
            "scripts/verify_ios_release_artifacts.py",
        ):
            contents = "fixture\n"
            if relative == "scripts/swift_dependency_snapshot.py":
                contents = "\n".join((
                    "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
                    "Packages/VocelloQwen3Core/Package.resolved",
                ))
            elif relative == "scripts/release_source_authority.py":
                contents = "\n".join((
                    'DEFAULT_REQUIRED_CHECKS = ("CI required", "Security required")',
                    'reference_object.get("type") != "tag"',
                    'verification.get("verified") is not True',
                    'verification.get("reason") != "valid"',
                    'row.get("head_sha") == commit',
                    'latest.get("status") != "completed"',
                    'latest.get("conclusion") != "success"',
                ))
            (self.root / relative).write_text(contents, encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_fixture_passes(self) -> None:
        self.assertEqual(module.validate(self.root), [])

    def test_mutable_action_ref_fails(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        path.write_text(path.read_text().replace(self.sha, "v4"), encoding="utf-8")
        self.assertTrue(any("full SHA" in value for value in module.validate(self.root)))

    def test_published_release_trigger_fails(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        path.write_text(path.read_text() + "\nrelease:\n  types: [published]\n", encoding="utf-8")
        self.assertTrue(any("must not trigger" in value for value in module.validate(self.root)))

    def test_publish_before_quality_verification_fails(self) -> None:
        path = self.root / ".github/workflows/promote-release.yml"
        text = path.read_text()
        text = text.replace("  - name: Publish source-bound verified Release\n", "")
        text = text.replace(
            "  - name: Download and validate candidate plus promotion evidence\n",
            "  - name: Publish source-bound verified Release\n"
            "    run: gh release edit \"$RELEASE_TAG\" --draft=false\n"
            "  - name: Download and validate candidate plus promotion evidence\n",
        )
        path.write_text(text, encoding="utf-8")
        self.assertTrue(any("ordering" in value for value in module.validate(self.root)))

    def test_candidate_workflow_cannot_publish_directly(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        path.write_text(
            path.read_text(encoding="utf-8")
            + "\n  - name: Publish verified GitHub Release\n    run: gh release edit --draft=false\n",
            encoding="utf-8",
        )
        self.assertTrue(any("verified draft" in value for value in module.validate(self.root)))

    def test_draft_asset_set_must_be_reset_and_checked_exactly(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("gh release delete-asset", "echo skip-delete"), encoding="utf-8")
        self.assertTrue(any("exact draft asset set" in value for value in module.validate(self.root)))

    def test_macos_release_must_run_packaged_launch_smoke_on_macos_26(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("runs-on: macos-26", "runs-on: macos-15", 1), encoding="utf-8")
        self.assertTrue(any("packaging must run on macos-26" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                "    runs-on: macos-26\n",
                "    runs-on: macos-26\n    env:\n      QWENVOICE_SKIP_LAUNCH_SMOKE: \"1\"\n",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("must not bypass" in value for value in module.validate(self.root)))

        path.write_text(text.replace("./scripts/verify_packaged_dmg.sh", "./scripts/skip_dmg_verification.sh"), encoding="utf-8")
        self.assertTrue(any("must verify the packaged DMG" in value for value in module.validate(self.root)))

    def test_packaged_launch_contract_cannot_be_weakened(self) -> None:
        bundle = self.root / "scripts/verify_release_bundle.sh"
        text = bundle.read_text(encoding="utf-8")
        bundle.write_text(text.replace('[ "${CI:-}" = "true" ]', '[ "${CI:-}" = "false" ]'), encoding="utf-8")
        self.assertTrue(any("reject CI bypass" in value for value in module.validate(self.root)))

        bundle.write_text(text.replace('/usr/bin/open -n "$APP_PATH"', 'echo skip-launch'), encoding="utf-8")
        self.assertTrue(any("launch the external app bundle" in value for value in module.validate(self.root)))

        dmg = self.root / "scripts/verify_packaged_dmg.sh"
        dmg.write_text("echo skip-bundle-verification\n", encoding="utf-8")
        self.assertTrue(any("launch-check the extracted app" in value for value in module.validate(self.root)))

    def test_ios_export_must_be_verified_before_evidence(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("scripts/verify_ios_release_artifacts.py", "scripts/skip_ios_verification.py"),
            encoding="utf-8",
        )
        self.assertTrue(any("artifact-verification binding" in value for value in module.validate(self.root)))

    def test_ios_readiness_must_be_process_bound_before_archive(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("--step platform-readiness", "--step unbound-readiness"),
            encoding="utf-8",
        )
        self.assertTrue(any("readiness binding" in value for value in module.validate(self.root)))

    def test_release_tool_validation_is_isolated_from_native_tools(self) -> None:
        path = self.root / "config/toolchain.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["native"] = {
            "compiler": {
                "version": "native-expected",
                "versionCommand": [sys.executable, "-c", "print('native-observed')"],
            }
        }
        manifest["release"] = {
            "gh": {
                "version": "2.95.0",
                "versionCommand": [sys.executable, "-c", "print('gh 2.95.0')"],
            }
        }
        path.write_text(json.dumps(manifest), encoding="utf-8")

        self.assertEqual(module.validate(self.root, "release"), [])
        self.assertTrue(any("compiler" in value for value in module.validate(self.root, "all")))

    def test_swift_dependency_submission_cannot_run_on_pull_requests(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "if: github.event_name == 'push' || github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'",
                "if: github.event_name != 'schedule'",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("submission must run only" in value for value in module.validate(self.root)))

    def test_swift_dependency_submission_push_is_limited_to_main(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("    branches: [main]", "    branches: [develop]", 1), encoding="utf-8")
        self.assertTrue(any("push trigger must remain limited" in value for value in module.validate(self.root)))

    def test_swift_dependency_submission_has_only_required_permission(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("      contents: write", "      contents: write\n      actions: write", 1), encoding="utf-8")
        self.assertTrue(any("only contents:write" in value for value in module.validate(self.root)))

    def test_root_swift_dependency_watch_cannot_write_repository_state(self) -> None:
        path = self.root / ".github/workflows/swift-dependency-watch.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("contents: read", "contents: write", 1), encoding="utf-8")
        self.assertTrue(any("must remain read-only" in value for value in module.validate(self.root)))

    def test_root_swift_dependency_watch_must_retain_the_coordinated_report(self) -> None:
        path = self.root / ".github/workflows/swift-dependency-watch.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("retention-days: 14", "retention-days: 1", 1), encoding="utf-8")
        self.assertTrue(any("retention-days: 14" in value for value in module.validate(self.root)))

    def test_root_swift_dependency_policy_must_cover_every_exact_pin(self) -> None:
        path = self.root / "config/swift-dependency-update-policy.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        value["packages"] = value["packages"][:-1]
        path.write_text(json.dumps(value), encoding="utf-8")
        self.assertTrue(any("every coordinated exact pin" in value for value in module.validate(self.root)))

    def test_npm_advisory_audit_must_follow_website_path_routing(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "if: needs.changes.outputs.website == 'true'",
                "if: github.event_name == 'schedule'",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("website-relevant" in value for value in module.validate(self.root)))

    def test_security_required_aggregate_is_mandatory(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("    name: Security required", "    name: Security advisory"), encoding="utf-8")
        self.assertTrue(any("Security required aggregate" in value for value in module.validate(self.root)))

    def test_release_source_authority_is_mandatory(self) -> None:
        path = self.root / ".github/workflows/release.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("          python3 scripts/release_source_authority.py", "          echo skip-authority"),
            encoding="utf-8",
        )
        self.assertTrue(any("exact-source control" in value for value in module.validate(self.root)))

    def test_promotion_rechecks_signed_exact_sha_authority(self) -> None:
        path = self.root / ".github/workflows/promote-release.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("      python3 scripts/release_source_authority.py", "      echo skip-authority"),
            encoding="utf-8",
        )
        self.assertTrue(any("signed exact-SHA control" in value for value in module.validate(self.root)))

    def test_swift_codeql_tooling_must_stay_pinned_and_brew_free(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                'python3 -m pip install --quiet --break-system-packages "numpy==${NUMPY_PIN}"',
                "python3 -m pip install --quiet numpy",
            ).replace("NUMPY_PIN=\"$(python3 -c \"import json; print(json.load(open('config/toolchain.json'))['native']['numpy']['version'])\")\"", ""),
            encoding="utf-8",
        )
        self.assertTrue(
            any("pip-pin numpy" in value for value in module.validate(self.root))
        )
        path.write_text(
            text.replace(
                "./scripts/install_pinned_tools.sh",
                "brew install xcbeautify shellcheck\n          ./scripts/install_pinned_tools.sh",
            ),
            encoding="utf-8",
        )
        self.assertTrue(
            any("must not install drifting tools through Homebrew" in value
                for value in module.validate(self.root))
        )
        path.write_text(
            text.replace("./scripts/install_pinned_tools.sh", "echo skip-pinned-tools"),
            encoding="utf-8",
        )
        self.assertTrue(
            any("SHA-pinned xcodegen/ripgrep/xcbeautify/shellcheck" in value
                for value in module.validate(self.root))
        )
        path.write_text(text.replace("runner: macos-26", "runner: macos-15"), encoding="utf-8")
        self.assertTrue(any("macos-26 ARM runner" in value for value in module.validate(self.root)))

    def test_swift_codeql_requires_the_optional_metal_toolchain(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("xcodebuild -downloadComponent metalToolchain", "echo skip-metal-download"),
            encoding="utf-8",
        )
        self.assertTrue(any("optional Metal Toolchain" in value for value in module.validate(self.root)))

        path.write_text(text.replace("xcrun metal --version", "true"), encoding="utf-8")
        self.assertTrue(any("verify the Metal compiler" in value for value in module.validate(self.root)))

    def test_swift_codeql_build_must_remain_inside_tracing_shell(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "run: ./scripts/build.sh codeql\n",
                "run: arch -arm64 /bin/bash ./scripts/build.sh codeql\n",
            ),
            encoding="utf-8",
        )
        self.assertTrue(any(
            "inside the CodeQL tracing shell" in value
            for value in module.validate(self.root)
        ))

    def test_swift_codeql_preparation_is_required_before_initialization(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        prepare = (
            "      - name: Prepare Swift CodeQL build inputs\n"
            "        if: matrix.language == 'swift'\n"
            "        run: ./scripts/build.sh codeql-prepare\n"
        )
        initialize = "      - name: Initialize CodeQL\n"
        path.write_text(text.replace(prepare + initialize, initialize + prepare), encoding="utf-8")
        self.assertTrue(any("toolchain -> prepare -> initialize" in value for value in module.validate(self.root)))

    def test_swift_codeql_must_use_dedicated_traced_build_command(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("run: ./scripts/build.sh codeql\n", "run: ./scripts/build.sh build\n"),
            encoding="utf-8",
        )
        self.assertTrue(any("authoritative traced build" in value for value in module.validate(self.root)))

    def test_swift_codeql_must_use_generic_arm64_build_contract(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace('CODEQL_DESTINATION="generic/platform=macOS"', 'CODEQL_DESTINATION="platform=macOS,arch=arm64"'),
            encoding="utf-8",
        )
        self.assertTrue(any("generic macOS destination" in value for value in module.validate(self.root)))

        path.write_text(text.replace("ARCHS=arm64", "ARCHS=x86_64"), encoding="utf-8")
        self.assertTrue(any("emit arm64 products" in value for value in module.validate(self.root)))

    def test_swift_codeql_commands_must_each_select_the_generic_destination(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "  configure_codeql_build prepare\n",
                "  configure_codeql_build trace\n",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("preparation must build and validate" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                "  configure_codeql_build trace\n",
                "  configure_codeql_build prepare\n",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("CodeQL build must select" in value for value in module.validate(self.root)))

    def test_swift_codeql_traced_build_must_invalidate_all_owned_swift(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace('  touch_codeql_sources\n  build_app "scripts/build.sh codeql"', '  build_app "scripts/build.sh codeql"'),
            encoding="utf-8",
        )
        self.assertTrue(any("touch owned Swift" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace('"$ROOT_DIR/Packages/VocelloQwen3Core/Sources"', '"$ROOT_DIR/Packages/Other/Sources"'),
            encoding="utf-8",
        )
        self.assertTrue(any("VocelloQwen3Core/Sources" in value for value in module.validate(self.root)))

    def test_swift_codeql_metal_exclusion_is_traced_build_only(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace("  configure_codeql_build trace\n", ""),
            encoding="utf-8",
        )
        self.assertTrue(any("isolated trace phase" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                '  if [ "$CODEQL_BUILD_PHASE" = "trace" ]; then',
                '  if true; then',
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("scoped to the dedicated traced build" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace('CODEQL_BUILD_PHASE="none"', 'CODEQL_BUILD_PHASE="trace"'),
            encoding="utf-8",
        )
        self.assertTrue(any("complete runnable products" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                'CODEQL_DERIVED_DATA="$QVOICE_SCRATCH_CI/codeql-macos"',
                'CODEQL_DERIVED_DATA="$QVOICE_XCODE_MACOS_DERIVED"',
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("managed CI scratch" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace("  local -a build_tail=(build)\n", "  local -a build_tail=()\n"),
            encoding="utf-8",
        )
        self.assertTrue(any("scoped to the dedicated traced build" in value for value in module.validate(self.root)))

    def test_swift_codeql_scratch_phases_cannot_mutate_public_products(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")

        path.write_text(
            text.replace(
                '  if [ "$CODEQL_BUILD_PHASE" = "none" ]; then',
                '  if true; then',
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("must not synchronize" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                '  if [ "$CODEQL_BUILD_PHASE" = "none" ]; then\n'
                '    sync_dev_signing_cache "$signing_identity" "$XCODEBUILD_APP" "$APP_BUNDLE"\n'
                '  fi\n',
                '  if [ "$CODEQL_BUILD_PHASE" = "none" ]; then\n'
                '    true\n'
                '  fi\n'
                '  sync_dev_signing_cache "$signing_identity" "$XCODEBUILD_APP" "$APP_BUNDLE"\n',
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("must not synchronize" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                '    assert_macos_bundle_arm64_only "$XCODEBUILD_APP"\n    return 0\n',
                '    assert_macos_bundle_arm64_only "$XCODEBUILD_APP"\n    rm -rf "$APP_BUNDLE"\n    return 0\n',
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("trace phase contains a public-product mutation" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                '  if [ "$CODEQL_BUILD_PHASE" = "prepare" ]; then\n    return 0\n',
                '  if [ "$CODEQL_BUILD_PHASE" = "prepare" ]; then\n    preserve_dsyms\n    return 0\n',
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("preparation contains a public-product mutation" in value for value in module.validate(self.root)))

    def test_swift_codeql_scratch_phases_validate_before_returning(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")

        path.write_text(
            text.replace('  if [ ! -d "$XCODEBUILD_APP" ]; then\n    return 1\n  fi\n', ""),
            encoding="utf-8",
        )
        self.assertTrue(any("only after the traced build succeeds" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                '    assert_macos_bundle_arm64_only "$XCODEBUILD_APP"\n',
                "    true\n",
                1,
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("verify an arm64 product" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                '  if [ "$CODEQL_BUILD_PHASE" = "prepare" ]; then\n    return 0\n',
                '  if [ "$CODEQL_BUILD_PHASE" = "prepare" ]; then\n    true\n',
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("preparation must validate Metal" in value for value in module.validate(self.root)))

    def test_swift_codeql_must_verify_prebuilt_metal_libraries(self) -> None:
        path = self.root / "scripts/build.sh"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace('  assert_mlx_metallibs "$XCODEBUILD_APP"\n', ""),
            encoding="utf-8",
        )
        self.assertTrue(any("must verify the required" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace(
                "Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib",
                "Contents/XPCServices/QwenVoiceEngineService.xpc/missing.metallib",
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("XPCServices" in value for value in module.validate(self.root)))

        path.write_text(
            text.replace('if [ ! -s "$app_bundle/$relative_path" ]; then', 'if [ ! -e "$app_bundle/$relative_path" ]; then'),
            encoding="utf-8",
        )
        self.assertTrue(any("fail closed" in value for value in module.validate(self.root)))

    def test_swift_codeql_special_steps_must_remain_swift_only(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "      - name: Prepare Swift CodeQL build inputs\n        if: matrix.language == 'swift'\n",
                "      - name: Prepare Swift CodeQL build inputs\n",
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("build inputs must remain Swift-only" in value for value in module.validate(self.root)))

    def test_swift_codeql_must_not_duplicate_project_regeneration(self) -> None:
        path = self.root / ".github/workflows/security.yml"
        text = path.read_text(encoding="utf-8")
        path.write_text(
            text.replace(
                "run: ./scripts/build.sh codeql-prepare",
                "run: ./scripts/regenerate_project.sh\n      - run: ./scripts/build.sh codeql-prepare",
            ),
            encoding="utf-8",
        )
        self.assertTrue(any("build.sh own project regeneration" in value for value in module.validate(self.root)))

    def test_swift_dependency_snapshot_must_cover_both_tracked_locks(self) -> None:
        path = self.root / "scripts/swift_dependency_snapshot.py"
        path.write_text("Packages/VocelloQwen3Core/Package.resolved\n", encoding="utf-8")
        self.assertTrue(any("QwenVoice.xcodeproj" in value for value in module.validate(self.root)))


class ReleaseCredentialHygieneTests(unittest.TestCase):
    """Execute real workflow blocks with dummy bytes; never call Apple/ASC tools.

    Only home paths and the platform-specific plist executable are substituted.
    Permission checks run before chmod/import and after copies, not just at the end.
    """

    ROOT = SCRIPT.parent.parent
    SETUP_MAC = "Setup signing keychain"
    SETUP_KEY = "Write App Store Connect API key file"
    SETUP_IOS = "Import signing assets"
    STUBS = r'''
assert_private() {
  "$CREDENTIAL_TEST_PYTHON" -c 'import os,pathlib,stat; root=pathlib.Path(os.environ["CREDENTIAL_TEST_ROOT"]); files=[p for p in root.rglob("*") if p.is_file() and p.suffix in (".p8",".p12",".mobileprovision",".keychain-db")]; assert all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in files), "credential permissions"'
}
security() {
  assert_private || return 99
  case "$1" in
    create-keychain) : > "${@: -1}" ;;
    delete-keychain)
      [ "$FAIL_STAGE" != cleanup ] || return 57
      command rm -f "${@: -1}"; return ;;
    import)
      if [ "$FAIL_STAGE" = terminate ]; then kill -TERM "$$"; fi ;;
    find-identity) printf '%s\n' '1) FIXTURE "Developer ID Application: Fixture"' ;;
    cms) printf '%s\n' '<plist><dict/></plist>' ;;
    list-keychain|list-keychains|set-keychain-settings|unlock-keychain|set-key-partition-list) : ;;
    *) return 98 ;;
  esac
  [ "$FAIL_STAGE" != "$1" ] || return 41
}
base64() {
  assert_private || return 99
  if [ "$FAIL_STAGE" = decode ]; then printf 'partial'; return 41; fi
  "$CREDENTIAL_TEST_PYTHON" -c 'import base64,sys; sys.stdout.buffer.write(base64.b64decode(sys.stdin.buffer.read(),validate=False))'
}
chmod() {
  assert_private || return 99
  [ "$FAIL_STAGE" != chmod ] || return 41
  command chmod "$@"
}
cp() {
  assert_private || return 99
  command cp "$@" || return
  assert_private || return 99
  case "$1:$FAIL_STAGE" in
    *.mobileprovision:profile-copy|*.p8:key-copy) return 41 ;;
  esac
}
fixture_plistbuddy() { printf '%s\n' 'AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE'; }
openssl() { printf '%s\n' 'fixture-random-password'; }
uuidgen() { printf '%s\n' 'fixture-random-password'; }
asc() { return 0; }
'''

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vocello-credential-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runner = self.root / "runner with spaces"
        self.runner.mkdir()
        self.user_root = self.root / "isolated user"
        self.user_root.mkdir()
        self.env_file = self.root / "github-env"
        self.env_file.touch()
        encoded = base64.b64encode(b"fixture-only-not-a-real-credential").decode()
        self.env = {
            "PATH": os.environ["PATH"], "RUNNER_TEMP": str(self.runner),
            "GITHUB_ENV": str(self.env_file), "CREDENTIAL_TEST_ROOT": str(self.root),
            "CREDENTIAL_TEST_HOME": str(self.user_root), "CREDENTIAL_TEST_PYTHON": sys.executable,
            "CERT_BASE64": encoded, "CERT_PASSWORD": "fixture-password",
            "IOS_DIST_CERT_P12": encoded, "IOS_DIST_CERT_PASSWORD": "fixture-password",
            "IOS_PROVISION_PROFILE": encoded, "ASC_API_KEY_P8": encoded,
            "APPLE_API_KEY_ID": "FIXTURE123", "ASC_API_KEY_ID": "FIXTURE123",
            "NOTARY_KEY_P8": "-----BEGIN PRIVATE KEY-----\nfixture-only-invalid-key\n",
            "FAIL_STAGE": "",
        }

    def block(self, name):
        workflow = (self.ROOT / ".github/workflows/release.yml").read_text()
        step = workflow.split("      - name: " + name + "\n", 1)[1]
        step = step.split("\n      - name:", 1)[0]
        run = step.split("        run: |\n", 1)[1]
        lines = []
        for line in run.splitlines():
            if line.strip() and not line.startswith("          "):
                break
            lines.append(line)
        return textwrap.dedent("\n".join(lines))

    def run_block(self, name, failure="", mutation=None):
        body = self.block(name)
        if mutation:
            body = mutation(body)
        # Do not repurpose HOME or touch real home/Keychain state.
        body = body.replace("$HOME", "${CREDENTIAL_TEST_HOME}").replace("~/", '"${CREDENTIAL_TEST_HOME}"/')
        body = body.replace("/usr/libexec/PlistBuddy", "fixture_plistbuddy")
        self.assertNotIn("${{", body)
        self.assertNotIn("$HOME", body)
        env = self.env | {"FAIL_STAGE": failure}
        result = subprocess.run(["bash", "-euo", "pipefail", "-c", self.STUBS + "\n" + body],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=15)
        for secret in ("fixture-password", "fixture-random-password", "fixture-only-not-a-real-credential",
                       self.env["CERT_BASE64"]):
            self.assertNotIn(secret, result.stdout + result.stderr)
        # Mimic GitHub's next-step environment; partial setup registrations survive.
        for line in self.env_file.read_text().splitlines():
            key, value = line.split("=", 1)
            self.env[key] = value
        return result

    def credentials(self):
        return [p for p in self.root.rglob("*") if p.is_file()
                and p.suffix in (".p8", ".p12", ".mobileprovision", ".keychain-db")]

    def test_gitignore_blocks_credentials_but_keeps_documented_examples(self):
        (self.root / ".gitignore").write_text((self.ROOT / ".gitignore").read_text())
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        blocked = ["key.p8", "nested/key.p12", "key.pfx", "secret.key", "private.pem",
                   "signing.keychain-db", "signing.keychain", "app.mobileprovision", "app.provisionprofile",
                   ".env", ".env.local", "nested/.env.production", ".asc/config.json",
                   ".appstoreconnect/private_keys/key.p8", "id_rsa", "nested/id_ed25519"]
        allowed = [".env.example", "nested/.env.sample", "Tests/Fixtures/VocelloExports.storekit",
                   "Sources/iOS/Commerce/IOSStoreKitClient.swift", "config/public-product-facts.json"]
        r = subprocess.run(["git", "-c", "core.excludesFile=/dev/null", "check-ignore", "--stdin"],
                           cwd=self.root, input="\n".join(blocked + allowed), capture_output=True, text=True)
        self.assertEqual(set(r.stdout.splitlines()), set(blocked))

    def test_permissions_and_success_cleanup_on_both_platforms(self):
        for name in (self.SETUP_MAC, self.SETUP_KEY):
            r = self.run_block(name)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.credentials()), 2)  # keychain + notary key, no decoded P12
        self.assertEqual(self.run_block("Cleanup signing material").returncode, 0)
        self.assertFalse(self.credentials())
        r = self.run_block(self.SETUP_IOS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.credentials()), 4)  # keychain + profile + two key copies
        self.assertEqual(self.run_block("Cleanup iOS signing material").returncode, 0)
        self.assertFalse(self.credentials())
        self.assertEqual(self.run_block("Cleanup iOS signing material").returncode, 0)

    def test_early_failures_and_termination_remove_partial_material(self):
        cases = [(self.SETUP_MAC, x) for x in ("decode", "create-keychain", "import", "set-key-partition-list", "terminate")]
        cases += [(self.SETUP_KEY, "chmod")]
        cases += [(self.SETUP_IOS, x) for x in ("create-keychain", "decode", "import", "profile-copy", "chmod", "key-copy", "terminate")]
        for name, failure in cases:
            with self.subTest(step=name, failure=failure):
                r = self.run_block(name, failure)
                self.assertEqual(r.returncode, 143 if failure == "terminate" else 41, r.stderr)
                self.assertFalse(self.credentials(), str(self.credentials()))

    def test_existing_files_are_not_overwritten_or_deleted(self):
        cases = [(self.SETUP_MAC, self.runner / "cert.p12"),
                 (self.SETUP_KEY, self.runner / "AuthKey_FIXTURE123.p8"),
                 (self.SETUP_IOS, self.user_root / ".appstoreconnect/private_keys/AuthKey_FIXTURE123.p8"),
                 (self.SETUP_IOS, self.user_root / "Library/MobileDevice/Provisioning Profiles/AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE.mobileprovision")]
        for name, path in cases:
            with self.subTest(step=name, path=path.name):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"existing-owner")
                path.chmod(0o600)
                r = self.run_block(name)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(path.read_bytes(), b"existing-owner")
                self.assertEqual(self.credentials(), [path])
                path.unlink()

    def test_cleanup_failure_does_not_skip_remaining_credentials(self):
        self.assertEqual(self.run_block(self.SETUP_IOS).returncode, 0)
        self.assertEqual(self.run_block("Cleanup iOS signing material", "cleanup").returncode, 1)
        self.assertEqual([p.suffix for p in self.credentials()], [".keychain-db"])
        self.assertEqual(self.run_block("Cleanup iOS signing material").returncode, 0)
        self.assertFalse(self.credentials())

    def test_invalid_key_content_and_missing_environment_file_fail_cleanly(self):
        self.env["NOTARY_KEY_P8"] = "invalid-fixture-key"
        self.assertEqual(self.run_block(self.SETUP_KEY).returncode, 1)
        self.assertFalse(self.credentials())
        self.env["GITHUB_ENV"] = str(self.root / "missing-parent" / "env")
        for name in (self.SETUP_MAC, self.SETUP_KEY, self.SETUP_IOS):
            with self.subTest(step=name):
                self.assertNotEqual(self.run_block(name).returncode, 0)
                self.assertFalse(self.credentials())

    def test_final_cleanup_is_always_run_and_missing_setup_is_safe(self):
        workflow = (self.ROOT / ".github/workflows/release.yml").read_text()
        for name in ("Cleanup signing material", "Cleanup iOS signing material"):
            step = workflow.split("      - name: " + name + "\n", 1)[1].split("        run: |", 1)[0]
            self.assertIn("if: always()", step)
            self.assertEqual(self.run_block(name).returncode, 0)
            self.assertFalse(self.credentials())

    def test_missing_restrictions_and_traps_are_detected(self):
        r = self.run_block(self.SETUP_KEY, mutation=lambda s: s.replace("umask 077", "umask 022"))
        self.assertEqual(r.returncode, 99)  # permission check before chmod
        self.assertFalse(self.credentials())
        r = self.run_block(self.SETUP_KEY, "chmod", mutation=lambda s: s.replace("trap cleanup_setup EXIT", "trap - EXIT"))
        self.assertEqual(r.returncode, 41)
        self.assertEqual(len(self.credentials()), 1)  # deliberate-negative fixture
        self.assertEqual(self.run_block("Cleanup signing material").returncode, 0)
        self.assertFalse(self.credentials())


if __name__ == "__main__":
    unittest.main()
