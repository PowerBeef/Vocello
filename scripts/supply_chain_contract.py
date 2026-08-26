#!/usr/bin/env python3
"""Validate immutable CI actions, release ordering, governance, and tool versions."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ACTION = re.compile(
    r"^\s*uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(?:/[A-Za-z0-9_./-]+)?@([^\s#]+)",
    re.MULTILINE,
)


def _workflow_job(text: str, name: str) -> str:
    match = re.search(rf"(?m)^  {re.escape(name)}:\s*$", text)
    if not match:
        return ""
    next_job = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", text[match.end():])
    end = match.end() + next_job.start() if next_job else len(text)
    return text[match.start():end]


def _job_permissions(job: str) -> list[str]:
    match = re.search(r"(?ms)^    permissions:\s*$\n(.*?)(?=^    [A-Za-z0-9_-]+:|\Z)", job)
    if not match:
        return []
    return [line.strip() for line in match.group(1).splitlines() if line.strip()]


def _shell_function(text: str, name: str) -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\(\)\s*\{{\s*$", text)
    if not match:
        return ""
    end = re.search(r"(?m)^}\s*$", text[match.end():])
    return text[match.start():match.end() + end.end()] if end else ""


def _tool_output(command: list[str]) -> str:
    try:
        return subprocess.check_output(command, stderr=subprocess.STDOUT, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        raise ValueError(f"could not execute {' '.join(command)}: {error}") from error


def validate(root: Path, installed: str | None = None) -> list[str]:
    errors: list[str] = []
    manifest_path = root / "config/toolchain.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"config/toolchain.json: {error}"]
    if manifest.get("schemaVersion") != 1:
        errors.append("config/toolchain.json: unsupported schemaVersion")

    configured_actions = manifest.get("actions", {})
    workflows = sorted((root / ".github/workflows").glob("*.yml"))
    used_actions: set[str] = set()
    for workflow in workflows:
        text = workflow.read_text(encoding="utf-8")
        for repository, reference in ACTION.findall(text):
            used_actions.add(repository)
            if not re.fullmatch(r"[0-9a-f]{40}", reference):
                errors.append(f"{workflow.relative_to(root)}: action is not pinned to a full SHA: {repository}@{reference}")
                continue
            configured = configured_actions.get(repository)
            if not configured:
                errors.append(f"{workflow.relative_to(root)}: action is absent from config/toolchain.json: {repository}")
            elif configured.get("sha") != reference:
                errors.append(f"{workflow.relative_to(root)}: {repository} SHA differs from config/toolchain.json")
    for repository in sorted(set(configured_actions) - used_actions):
        errors.append(f"config/toolchain.json: configured action is unused: {repository}")

    release_path = root / ".github/workflows/release.yml"
    release = release_path.read_text(encoding="utf-8") if release_path.is_file() else ""
    if re.search(r"\brelease\s*:\s*\n\s*types\s*:\s*\[?published", release):
        errors.append("release workflow must not trigger after a Release is published")
    if not re.search(r"push:\s*\n\s*tags:\s*\[?['\"]?v\*", release):
        errors.append("release workflow must accept protected v* tag pushes")
    ordered = [
        "Verify release tag and source identity",
        "Generate and validate release evidence",
        "Attest verified DMG provenance",
        "Create or reuse draft GitHub Release",
        "Reset draft Release assets",
        "Upload verified assets to draft Release",
        "Verify downloaded Release assets",
    ]
    positions = [release.find(value) for value in ordered]
    if any(value < 0 for value in positions) or positions != sorted(positions):
        errors.append("release workflow does not preserve verify -> draft -> upload -> remote verify ordering")
    if "Publish verified GitHub Release" in release or re.search(r"--draft=false", release):
        errors.append("release candidate workflow must stop at a verified draft")
    package_job = _workflow_job(release, "package")
    if not package_job:
        errors.append("release workflow is missing the macOS package job")
    else:
        if "runs-on: macos-26" not in package_job:
            errors.append("macOS release packaging must run on macos-26")
        if "QWENVOICE_SKIP_LAUNCH_SMOKE" in package_job:
            errors.append("macOS release packaging must not bypass packaged-app launch smoke")
        if "./scripts/verify_packaged_dmg.sh" not in package_job:
            errors.append("macOS release packaging must verify the packaged DMG")
        if "needs: source-authority" not in package_job:
            errors.append("macOS release packaging must depend on signed exact-SHA source authority")
    source_authority = _workflow_job(release, "source-authority")
    if not source_authority:
        errors.append("release workflow is missing signed exact-SHA source authority")
    else:
        if _job_permissions(source_authority) != ["contents: read", "checks: read"]:
            errors.append("release source authority must have only contents:read and checks:read")
        for required_source_control in (
            'git merge-base --is-ancestor "$commit" origin/main',
            "git/ref/tags/${RELEASE_TAG}",
            "git/tags/${tag_object}",
            "commits/${commit}/check-runs?filter=latest&per_page=100",
            "gh api --paginate --slurp",
            "python3 scripts/release_source_authority.py",
            "python3 scripts/release_evidence.py verify-source",
        ):
            if required_source_control not in source_authority:
                errors.append(
                    f"release source authority is missing exact-source control: {required_source_control}"
                )
    for dependent_job_name in ("compile-ios", "archive-ios"):
        dependent_job = _workflow_job(release, dependent_job_name)
        if not dependent_job or "needs: source-authority" not in dependent_job:
            errors.append(f"release job {dependent_job_name} must depend on source authority")
    for required in (
        "gh release delete-asset",
        'gh release view "$RELEASE_TAG" --json assets',
        "unexpected or missing draft Release assets",
    ):
        if required not in release:
            errors.append(f"release workflow does not enforce an exact draft asset set: {required}")

    bundle_verifier_path = root / "scripts/verify_release_bundle.sh"
    bundle_verifier = (
        bundle_verifier_path.read_text(encoding="utf-8")
        if bundle_verifier_path.is_file()
        else ""
    )
    for required, message in (
        ('SKIP_LAUNCH_SMOKE="${QWENVOICE_SKIP_LAUNCH_SMOKE:-0}"',
         "packaged-app launch skip must remain opt-in"),
        ('[ "${CI:-}" = "true" ]',
         "packaged-app launch smoke must reject CI bypass"),
        ('/usr/bin/open -n "$APP_PATH"',
         "packaged-app verifier must launch the external app bundle"),
        ('did not remain running long enough to pass startup smoke',
         "packaged-app verifier must prove startup survival"),
    ):
        if required not in bundle_verifier:
            errors.append(message)

    dmg_verifier_path = root / "scripts/verify_packaged_dmg.sh"
    dmg_verifier = (
        dmg_verifier_path.read_text(encoding="utf-8")
        if dmg_verifier_path.is_file()
        else ""
    )
    if '"$SCRIPT_DIR/verify_release_bundle.sh" "$COPIED_APP"' not in dmg_verifier:
        errors.append("packaged DMG verification must launch-check the extracted app")

    promotion_path = root / ".github/workflows/promote-release.yml"
    promotion = promotion_path.read_text(encoding="utf-8") if promotion_path.is_file() else ""
    if not re.search(r"workflow_dispatch:\s*\n\s*inputs:", promotion):
        errors.append("promotion workflow must be manual-only")
    promotion_order = [
        "Verify tag and draft state",
        "Download and validate candidate plus promotion evidence",
        "python3 scripts/release_evidence.py validate",
        "python3 scripts/quality_promotion.py validate",
        "Publish source-bound verified Release",
        "gh release edit \"$RELEASE_TAG\"",
    ]
    promotion_positions = [promotion.find(value) for value in promotion_order]
    if any(value < 0 for value in promotion_positions) or promotion_positions != sorted(promotion_positions):
        errors.append("promotion workflow does not preserve draft -> release evidence -> quality evidence -> publish ordering")
    for required in ("quality-promotion.json", "--platform macos", "--draft=false"):
        if required not in promotion:
            errors.append(f"promotion workflow is missing source-bound publication control: {required}")
    for required in (
        "checks: read",
        'git merge-base --is-ancestor "$commit" origin/main',
        "git/ref/tags/${RELEASE_TAG}",
        "git/tags/${tag_object}",
        "commits/${commit}/check-runs?filter=latest&per_page=100",
        "gh api --paginate --slurp",
        "python3 scripts/release_source_authority.py",
    ):
        if required not in promotion:
            errors.append(f"promotion workflow is missing signed exact-SHA control: {required}")

    ios_release_order = re.compile(
        r"Run process-bound iOS release readiness.*Archive VocelloiOS.*"
        r"Export App Store IPA.*Verify exported IPA identity and signing contract.*"
        r"Generate and validate iOS release evidence",
        re.DOTALL,
    )
    if not ios_release_order.search(release):
        errors.append(
            "iOS release workflow must preserve readiness -> archive -> export -> artifact verification -> evidence ordering"
        )
    for required in (
        "--step platform-readiness",
        "scripts/macos_test.sh gate",
        "./scripts/build_foundation_targets.sh ios",
    ):
        if required not in release:
            errors.append(f"iOS release workflow is missing process-bound readiness binding: {required}")
    for required in (
        "--step ipa-verification",
        "scripts/verify_ios_release_artifacts.py",
        "ios-release-artifact-verification.json",
    ):
        if required not in release:
            errors.append(f"iOS release workflow is missing artifact-verification binding: {required}")

    required = [
        "SECURITY.md", ".github/CODEOWNERS", ".github/dependabot.yml",
        ".github/workflows/security.yml", ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/bug_report.yml", ".github/ISSUE_TEMPLATE/feature_request.yml",
        "scripts/release_evidence.py", "scripts/release_sbom.py",
        "scripts/release_source_authority.py",
        "scripts/swift_dependency_snapshot.py",
        "scripts/swift_dependency_updates.py",
        "config/swift-dependency-update-policy.json",
        ".github/workflows/swift-dependency-watch.yml",
        "scripts/verify_ios_release_artifacts.py",
        "scripts/verify_release_bundle.sh", "scripts/verify_packaged_dmg.sh",
    ]
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f"required supply-chain surface is missing: {relative}")
    dependabot_path = root / ".github/dependabot.yml"
    dependabot = dependabot_path.read_text(encoding="utf-8") if dependabot_path.is_file() else ""
    for ecosystem in ("github-actions", "npm", "swift"):
        if f'package-ecosystem: "{ecosystem}"' not in dependabot:
            errors.append(f"Dependabot does not cover {ecosystem}")

    dependency_watch_path = root / ".github/workflows/swift-dependency-watch.yml"
    dependency_watch = (
        dependency_watch_path.read_text(encoding="utf-8") if dependency_watch_path.is_file() else ""
    )
    if not dependency_watch:
        errors.append("root Swift dependency watch workflow is missing")
    else:
        for required_token in (
            "schedule:",
            "workflow_dispatch:",
            "contents: read",
            "security-events: read",
            "python3 scripts/swift_dependency_updates.py validate",
            "python3 scripts/swift_dependency_updates.py report",
            '--repository "$GITHUB_REPOSITORY"',
            "swift-dependency-watch.json",
            "swift-dependency-watch.md",
            "actions/upload-artifact@",
            "retention-days: 14",
        ):
            if required_token not in dependency_watch:
                errors.append(f"root Swift dependency watch is missing: {required_token}")
        for forbidden_token in (
            "pull_request:",
            "push:",
            "contents: write",
            "issues: write",
            "pull-requests: write",
            "git commit",
            "gh pr create",
        ):
            if forbidden_token in dependency_watch:
                errors.append(f"root Swift dependency watch must remain read-only: {forbidden_token}")

    dependency_policy_path = root / "config/swift-dependency-update-policy.json"
    if dependency_policy_path.is_file():
        try:
            dependency_policy = json.loads(dependency_policy_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            errors.append(f"Swift dependency update policy is invalid JSON: {error}")
        else:
            identities = {
                row.get("identity")
                for row in dependency_policy.get("packages", [])
                if isinstance(row, dict)
            }
            expected_identities = {
                "grdb.swift", "mlx-swift", "mlx-swift-lm", "swift-huggingface", "swift-transformers"
            }
            if dependency_policy.get("schemaVersion") != 1:
                errors.append("Swift dependency update policy has an unsupported schema")
            if identities != expected_identities:
                errors.append("Swift dependency update policy does not cover every coordinated exact pin")

    security_path = root / ".github/workflows/security.yml"
    security = security_path.read_text(encoding="utf-8") if security_path.is_file() else ""
    if not re.search(r"(?m)^  push:\s*$\n^    branches:\s*\[main\]\s*$", security):
        errors.append("security workflow push trigger must remain limited to main")
    changes = _workflow_job(security, "changes")
    if not changes:
        errors.append("security workflow is missing path routing")
    else:
        for token in (
            "Security path routing",
            "native: ${{ steps.classify.outputs.native }}",
            "website: ${{ steps.classify.outputs.website }}",
            'git diff --name-only "origin/$BASE_REF...HEAD"',
            'git diff --name-only "$BEFORE_SHA..$HEAD_SHA"',
        ):
            if token not in changes:
                errors.append(f"security path routing is missing: {token}")
    submission = _workflow_job(security, "swift-dependency-submission")
    expected_submission_condition = (
        "if: github.event_name == 'push' || github.event_name == 'schedule' || "
        "github.event_name == 'workflow_dispatch'"
    )
    if not submission:
        errors.append("security workflow is missing Swift dependency submission")
    else:
        if expected_submission_condition not in submission:
            errors.append("Swift dependency submission must run only on main push, schedule, or manual dispatch")
        if _job_permissions(submission) != ["contents: write"]:
            errors.append("Swift dependency submission must have only contents:write permission")
        for required_command in (
            "python3 scripts/swift_dependency_snapshot.py",
            "dependency-graph/snapshots",
            "--input \"$RUNNER_TEMP/swift-dependency-snapshot.json\"",
        ):
            if required_command not in submission:
                errors.append(f"Swift dependency submission is missing: {required_command}")

    npm_audit = _workflow_job(security, "npm-advisory-audit")
    expected_audit_condition = "if: needs.changes.outputs.website == 'true'"
    if not npm_audit:
        errors.append("security workflow is missing the path-relevant npm advisory audit")
    else:
        if "needs: changes" not in npm_audit:
            errors.append("npm advisory audit must depend on security path routing")
        if expected_audit_condition not in npm_audit:
            errors.append("npm advisory audit must run for website-relevant push, PR, or scheduled work")
        if "npm --prefix website audit --package-lock-only --audit-level=high" not in npm_audit:
            errors.append("npm advisory audit must inspect the committed website lock at high severity")

    codeql = _workflow_job(security, "codeql")
    if not codeql:
        errors.append("security workflow is missing CodeQL")
    else:
        if "needs: changes" not in codeql:
            errors.append("CodeQL must depend on security path routing")
        if "if: needs.changes.outputs.native == 'true' || needs.changes.outputs.website == 'true'" not in codeql:
            errors.append("CodeQL must run for path-relevant push and pull-request work")
        if "runner: macos-26" not in codeql:
            errors.append("Swift CodeQL must retain the macos-26 ARM runner")
        # 2026-08-06: the drifting tools moved off Homebrew entirely —
        # xcodegen/ripgrep/xcbeautify/shellcheck install from artifactPins
        # and numpy pip-pins to the manifest version. Homebrew's mid-roll
        # formula drift (and the ARM/Rosetta guard dance it required here)
        # must not return.
        if "numpy==${NUMPY_PIN}" not in codeql:
            errors.append("Swift CodeQL must pip-pin numpy to the toolchain manifest version")
        if "brew install" in codeql:
            errors.append("Swift CodeQL must not install drifting tools through Homebrew; use the pinned installer")
        if "./scripts/install_pinned_tools.sh" not in codeql:
            errors.append("Swift CodeQL must install SHA-pinned xcodegen/ripgrep/xcbeautify/shellcheck release artifacts")
        if "xcodebuild -downloadComponent metalToolchain" not in codeql:
            errors.append("Swift CodeQL must install Xcode 26's optional Metal Toolchain when absent")
        if "xcrun metal --version" not in codeql:
            errors.append("Swift CodeQL must verify the Metal compiler before initialization")
        if not re.search(r"(?m)^\s*(?:run:\s*)?\./scripts/build\.sh codeql-prepare\s*$", codeql):
            errors.append("Swift CodeQL must prepare generated inputs and packages before tracing")
        if not re.search(r"(?m)^\s*(?:run:\s*)?\./scripts/build\.sh codeql\s*$", codeql):
            errors.append("Swift CodeQL must invoke the authoritative traced build command")
        if re.search(r"(?m)^\s*(?:run:\s*)?\./scripts/build\.sh build\s*$", codeql):
            errors.append("Swift CodeQL must not substitute the ordinary local build command")
        if "./scripts/regenerate_project.sh" in codeql:
            errors.append("Swift CodeQL must let build.sh own project regeneration")
        if "arch -arm64 /bin/bash ./scripts/build.sh" in codeql:
            errors.append("Swift CodeQL compilation must remain inside the CodeQL tracing shell")
        for step_name in ("Prepare Swift CodeQL build inputs", "Build Swift targets for CodeQL"):
            if not re.search(
                rf"(?m)^\s*- name: {re.escape(step_name)}\s*$\n\s+if: matrix\.language == 'swift'\s*$",
                codeql,
            ):
                errors.append(f"{step_name} must remain Swift-only")
        codeql_order = [
            "Select and validate native toolchain",
            "Prepare Swift CodeQL build inputs",
            "Initialize CodeQL",
            "Build Swift targets for CodeQL",
            "Analyze",
        ]
        codeql_positions = [codeql.find(value) for value in codeql_order]
        if any(value < 0 for value in codeql_positions) or codeql_positions != sorted(codeql_positions):
            errors.append(
                "Swift CodeQL must preserve toolchain -> prepare -> initialize -> traced build -> analyze ordering"
            )

    security_required = _workflow_job(security, "security-required")
    if not security_required:
        errors.append("security workflow is missing the exact-SHA Security required aggregate")
    else:
        for token in (
            "name: Security required",
            "needs: [changes, dependency-review, swift-dependency-submission, npm-advisory-audit, codeql]",
            "if: always()",
            '"result": *"(failure|cancelled)"',
        ):
            if token not in security_required:
                errors.append(f"Security required aggregate is missing: {token}")

    authority_path = root / "scripts/release_source_authority.py"
    authority = authority_path.read_text(encoding="utf-8") if authority_path.is_file() else ""
    for token in (
        'DEFAULT_REQUIRED_CHECKS = ("CI required", "Security required")',
        'reference_object.get("type") != "tag"',
        'verification.get("verified") is not True',
        'verification.get("reason") != "valid"',
        'row.get("head_sha") == commit',
        'latest.get("status") != "completed"',
        'latest.get("conclusion") != "success"',
    ):
        if token not in authority:
            errors.append(f"release source authority is missing fail-closed control: {token}")

    build_path = root / "scripts/build.sh"
    build_source = build_path.read_text(encoding="utf-8") if build_path.is_file() else ""
    for token, message in (
        ('DESTINATION="platform=macOS,arch=arm64"', "The ordinary macOS build destination must remain explicit"),
        ('CODEQL_DESTINATION="generic/platform=macOS"', "CodeQL must use the generic macOS destination"),
        ('CODEQL_DERIVED_DATA="$QVOICE_SCRATCH_CI/codeql-macos"', "CodeQL must use managed CI scratch"),
        ('CODEQL_BUILD_PHASE="none"', "Ordinary macOS builds must publish complete runnable products"),
        ("ARCHS=arm64", "CodeQL must emit arm64 products"),
        ("codeql-prepare)", "build.sh is missing the CodeQL preparation command"),
        ("codeql)", "build.sh is missing the traced CodeQL build command"),
    ):
        if token not in build_source:
            errors.append(message)
    configure_function = _shell_function(build_source, "configure_codeql_build")
    for token in (
        'CODEQL_BUILD_PHASE="$1"',
        'DESTINATION="$CODEQL_DESTINATION"',
        'DERIVED_DATA="$CODEQL_DERIVED_DATA"',
        'XCODEBUILD_APP="$DERIVED_DATA/Build/Products/Release/$APP_NAME.app"',
    ):
        if token not in configure_function:
            errors.append(f"CodeQL scratch configuration is missing: {token}")
    codeql_prepare_function = _shell_function(build_source, "cmd_codeql_prepare")
    if "configure_codeql_build prepare" not in codeql_prepare_function \
            or "configure_codeql_build trace" in codeql_prepare_function \
            or 'build_app "scripts/build.sh codeql-prepare"' not in codeql_prepare_function:
        errors.append("CodeQL preparation must build and validate the complete app in managed scratch")
    codeql_build_function = _shell_function(build_source, "cmd_codeql")
    if "configure_codeql_build trace" not in codeql_build_function \
            or "touch_codeql_sources" not in codeql_build_function \
            or 'build_app "scripts/build.sh codeql"' not in codeql_build_function:
        errors.append(
            "CodeQL build must select the isolated trace phase, touch owned Swift, and reuse managed scratch"
        )
    build_app_function = _shell_function(build_source, "build_app")
    build_tail_position = build_app_function.find("local -a build_tail=(build)")
    sync_condition = 'if [ "$CODEQL_BUILD_PHASE" = "none" ]; then'
    sync_position = build_app_function.find(sync_condition)
    build_tail_block = build_app_function[build_tail_position:sync_position]
    if build_tail_position < 0 or sync_position < 0 \
            or 'if [ "$CODEQL_BUILD_PHASE" = "trace" ]; then' not in build_tail_block \
            or "build_tail=('EXCLUDED_SOURCE_FILE_NAMES=*.metal' build)" not in build_tail_block \
            or '"${build_tail[@]}"' not in build_app_function:
        errors.append("CodeQL Metal exclusion must remain scoped to the dedicated traced build")
    sync_call_position = build_app_function.find('sync_dev_signing_cache "$signing_identity" "$XCODEBUILD_APP" "$APP_BUNDLE"')
    build_position = build_app_function.find('"${build_tail[@]}"')
    sync_guard_match = re.search(
        re.escape(sync_condition) + r"\s*\n(?P<body>.*?)(?m:^\s*fi\s*$)",
        build_app_function[sync_position:build_position],
        re.DOTALL,
    )
    if not (
        0 <= sync_position < sync_call_position < build_position
        and sync_guard_match is not None
        and 'sync_dev_signing_cache "$signing_identity" "$XCODEBUILD_APP" "$APP_BUNDLE"'
        in sync_guard_match.group("body")
    ):
        errors.append("CodeQL scratch phases must not synchronize or remove the public app product")

    product_position = build_app_function.find('if [ ! -d "$XCODEBUILD_APP" ]; then', build_position)
    trace_condition = 'if [ "$CODEQL_BUILD_PHASE" = "trace" ]; then'
    trace_position = build_app_function.find(trace_condition, product_position)
    metallib_position = build_app_function.find('assert_mlx_metallibs "$XCODEBUILD_APP"', trace_position)
    trace_block = build_app_function[trace_position:metallib_position]
    if not (
        0 <= build_position < product_position < trace_position < metallib_position
        and 'assert_macos_bundle_arm64_only "$XCODEBUILD_APP"' in trace_block
        and "return 0" in trace_block
    ):
        errors.append("CodeQL trace phase must verify an arm64 product and stop only after the traced build succeeds")
    for prohibited in (
        "$APP_BUNDLE", "sync_dev_signing_cache", "preserve_dsyms",
        "write_build_provenance", "record_dev_signing_identity", "ln -s", "rm -rf",
    ):
        if prohibited in trace_block:
            errors.append(f"CodeQL trace phase contains a public-product mutation: {prohibited}")

    normal_arch_position = build_app_function.find(
        'assert_macos_bundle_arm64_only "$XCODEBUILD_APP"', metallib_position
    )
    signing_position = build_app_function.find(
        'assert_signing_identity "$XCODEBUILD_APP" "$signing_identity"', normal_arch_position
    )
    prepare_condition = 'if [ "$CODEQL_BUILD_PHASE" = "prepare" ]; then'
    prepare_position = build_app_function.find(prepare_condition, signing_position)
    public_position = build_app_function.find('if [ -e "$APP_BUNDLE" ]', prepare_position)
    prepare_block = build_app_function[prepare_position:public_position]
    if not (
        0 <= metallib_position < normal_arch_position < signing_position < prepare_position < public_position
        and "return 0" in prepare_block
    ):
        errors.append(
            "CodeQL preparation must validate Metal, arm64, and signing before stopping ahead of public staging"
        )
    for prohibited in (
        "quit_app_if_running", "preserve_dsyms", "write_build_provenance",
        "record_dev_signing_identity", "ln -s", "rm -rf",
    ):
        if prohibited in prepare_block:
            errors.append(f"CodeQL preparation contains a public-product mutation: {prohibited}")
    if 'assert_mlx_metallibs "$XCODEBUILD_APP"' not in build_app_function:
        errors.append("Every runnable macOS app build must verify the required app and XPC MLX Metal libraries")
    metallib_function = _shell_function(build_source, "assert_mlx_metallibs")
    if 'if [ ! -s "$app_bundle/$relative_path" ]; then' not in metallib_function:
        errors.append("MLX Metal verification must fail closed for missing or empty libraries")
    for required_path in (
        "Contents/Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib",
        "Contents/XPCServices/QwenVoiceEngineService.xpc/Contents/Resources/mlx-swift_Cmlx.bundle/Contents/Resources/default.metallib",
    ):
        if required_path not in metallib_function:
            errors.append(f"MLX Metal verification is missing required bundle path: {required_path}")
    touch_function = _shell_function(build_source, "touch_codeql_sources")
    for source_root in ("$ROOT_DIR/Sources", "$ROOT_DIR/Packages/VocelloQwen3Core/Sources"):
        if source_root not in touch_function:
            errors.append(f"CodeQL traced rebuild does not cover owned Swift root: {source_root}")

    snapshot_path = root / "scripts/swift_dependency_snapshot.py"
    snapshot_source = snapshot_path.read_text(encoding="utf-8") if snapshot_path.is_file() else ""
    for lock_path in (
        "QwenVoice.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved",
        "Packages/VocelloQwen3Core/Package.resolved",
    ):
        if lock_path not in snapshot_source:
            errors.append(f"Swift dependency snapshot does not cover tracked lock: {lock_path}")
    package_path = root / "website/package.json"
    if package_path.is_file():
        package = json.loads(package_path.read_text(encoding="utf-8"))
        scripts = package.get("scripts", {})
        for command in ("lint", "test", "build", "check"):
            if not scripts.get(command):
                errors.append(f"website/package.json is missing the deterministic {command} script")

    if installed:
        groups = ("native", "release", "website") if installed == "all" else (installed,)
        for group in groups:
            for name, spec in manifest.get(group, {}).items():
                command = spec.get("versionCommand")
                expected = spec.get("version")
                if not isinstance(command, list) or not expected:
                    errors.append(f"config/toolchain.json: invalid {group}.{name} entry")
                    continue
                try:
                    output = _tool_output(command)
                except ValueError as error:
                    errors.append(str(error))
                    continue
                if not re.search(rf"(?<![0-9]){re.escape(str(expected))}(?![0-9])", output):
                    first = output.splitlines()[0] if output.splitlines() else "<empty>"
                    errors.append(f"{name}: expected {expected}, observed {first}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--installed", choices=("native", "release", "website", "all"))
    args = parser.parse_args()
    errors = validate(args.root.resolve(), args.installed)
    if errors:
        for error in errors:
            print(f"error: {error}")
        return 1
    print("Supply-chain contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
