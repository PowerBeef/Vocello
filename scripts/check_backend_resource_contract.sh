#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
command -v rg >/dev/null 2>&1 || { echo "error: ripgrep (rg) is required" >&2; exit 1; }
search_regex_in_file() { rg -q -- "$1" "$2"; }
search_fixed_in_file() { rg -Fq -- "$1" "$2"; }
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PROJECT_YML="$PROJECT_DIR/project.yml"
PBXPROJ="$PROJECT_DIR/QwenVoice.xcodeproj/project.pbxproj"

fail() {
    echo "error: $*" >&2
    exit 1
}

check_project_metadata() {
    [ -f "$PROJECT_YML" ] || fail "missing project.yml at $PROJECT_YML"
    [ -f "$PBXPROJ" ] || fail "missing generated project at $PBXPROJ"

    if search_fixed_in_file 'path: Sources/Resources/backend' "$PROJECT_YML"; then
        fail "project.yml must not bundle Sources/Resources/backend into shipped app resources"
    fi
    if search_fixed_in_file 'path: Sources/Resources/python' "$PROJECT_YML"; then
        fail "project.yml must not bundle Sources/Resources/python into shipped app resources"
    fi
    if search_regex_in_file 'dstPath = backend;' "$PBXPROJ" || search_regex_in_file 'dstPath = python;' "$PBXPROJ"; then
        fail "generated project must not include backend/python copy-files phases"
    fi
    if search_regex_in_file 'server_compat.py in Resources' "$PBXPROJ" || search_regex_in_file 'server.py in Resources' "$PBXPROJ"; then
        fail "generated project must not bundle deleted Python backend files into the app"
    fi
}

check_app_bundle() {
    local app_path="$1"
    [ -d "$app_path" ] || fail "app bundle not found: $app_path"

    local resources_dir="$app_path/Contents/Resources"
    [ ! -e "$resources_dir/backend" ] || fail "bundled backend directory must be absent: $resources_dir/backend"
    [ ! -e "$resources_dir/python" ] || fail "bundled Python runtime must be absent: $resources_dir/python"
    [ ! -e "$resources_dir/ffmpeg" ] || fail "bundled ffmpeg must be absent: $resources_dir/ffmpeg"

    if find "$resources_dir" \( -type d -name "__pycache__" -o -name "*.pyc" -o -name "*.whl" \) -print -quit | grep -q .; then
        fail "Python runtime artifacts must not be bundled into the native app resources"
    fi
}

usage() {
    cat >&2 <<'EOF'
Usage:
  ./scripts/check_backend_resource_contract.sh --project
  ./scripts/check_backend_resource_contract.sh --app-bundle /path/to/QwenVoice.app
  ./scripts/check_backend_resource_contract.sh --app-bundle /path/to/Vocello.app
EOF
    exit 1
}

if [ $# -lt 1 ]; then
    usage
fi

case "$1" in
    --project)
        [ $# -eq 1 ] || usage
        check_project_metadata
        echo "==> Native app resource contract is clean."
        ;;
    --app-bundle)
        [ $# -eq 2 ] || usage
        check_app_bundle "$2"
        echo "==> Native app bundle resource contract is clean."
        ;;
    *)
        usage
        ;;
esac
