#!/usr/bin/env bash
# Resolve the repository-owned build-output contract.
#
# This file is sourced by build/test/release scripts. The JSON manifest and its
# validator own the actual paths; callers must not silently fall back to legacy
# build roots when the policy cannot be loaded.

# shellcheck shell=bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    echo "error: scripts/lib/build_paths.sh must be sourced" >&2
    exit 1
fi

_qvoice_build_paths_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
_qvoice_build_paths_helper="$_qvoice_build_paths_root/scripts/build_output_policy.py"

if [[ ! -f "$_qvoice_build_paths_helper" ]]; then
    echo "error: build-output policy helper is missing: $_qvoice_build_paths_helper" >&2
    return 1
fi

_qvoice_build_paths_env=""
if ! _qvoice_build_paths_env="$(python3 "$_qvoice_build_paths_helper" shell-env)"; then
    echo "error: could not load the repository build-output policy" >&2
    return 1
fi

# shell-env is emitted by the tracked policy helper using shell-safe quoting.
eval "$_qvoice_build_paths_env"

_qvoice_build_paths_required=(
    QVOICE_BUILD_ROOT
    QVOICE_XCODE_MACOS_DERIVED
    QVOICE_XCODE_MACOS_TSAN_DERIVED
    QVOICE_XCODE_IOS_DERIVED
    QVOICE_XCODE_SOURCE_PACKAGES
    QVOICE_SWIFTPM_RUNTIME_CACHE
    QVOICE_DELIVERY_ANALYSIS_CACHE
    QVOICE_SCRATCH_FOUNDATION
    QVOICE_SCRATCH_PACKAGE_RESOLUTION
    QVOICE_SCRATCH_TRANSIENT
    QVOICE_SCRATCH_GATE_FINGERPRINT
    QVOICE_SCRATCH_RELEASE_MACOS
    QVOICE_SCRATCH_RELEASE_IOS
    QVOICE_SCRATCH_XCODEBUILDMCP_MACOS
    QVOICE_SCRATCH_XCODEBUILDMCP_IOS
    QVOICE_SCRATCH_CI
    QVOICE_ARTIFACTS_MACOS
    QVOICE_ARTIFACTS_IOS
    QVOICE_ARTIFACTS_UI_TESTS
    QVOICE_ARTIFACTS_DIAGNOSTICS
    QVOICE_SYMBOLS_MACOS
    QVOICE_SYMBOLS_IOS
    QVOICE_ARTIFACTS_FOUNDATION
    QVOICE_DIST_MACOS
    QVOICE_DIST_IOS
)

for _qvoice_build_paths_name in "${_qvoice_build_paths_required[@]}"; do
    _qvoice_build_paths_value="${!_qvoice_build_paths_name:-}"
    if [[ -z "$_qvoice_build_paths_value" ]]; then
        echo "error: build-output policy did not export $_qvoice_build_paths_name" >&2
        return 1
    fi
    case "$_qvoice_build_paths_value" in
        "$_qvoice_build_paths_root/build"|"$_qvoice_build_paths_root/build/"*) ;;
        *)
            echo "error: $_qvoice_build_paths_name escapes the repository build root: $_qvoice_build_paths_value" >&2
            return 1
            ;;
    esac
    export "${_qvoice_build_paths_name?}"
done

if [[ "$QVOICE_BUILD_ROOT" != "$_qvoice_build_paths_root/build" ]]; then
    echo "error: build-output policy root mismatch: $QVOICE_BUILD_ROOT" >&2
    return 1
fi

unset _qvoice_build_paths_env _qvoice_build_paths_helper
unset _qvoice_build_paths_name _qvoice_build_paths_required
unset _qvoice_build_paths_root _qvoice_build_paths_value
