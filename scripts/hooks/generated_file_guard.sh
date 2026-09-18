#!/usr/bin/env bash
# Claude file-edit / Codex apply_patch PreToolUse hook.
#
# Reads all normalized edit paths and refuses (exit 2) direct edits of files the
# repository generates or freezes, naming the generator so the fix is one
# command away. Path checks are plain `case` globs on the repository-relative
# path; the hook never reads git state and finishes in milliseconds.

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
file_paths="$(python3 "$HOOK_DIR/agent_hook_input.py" paths)"
[[ -n "$file_paths" ]] || exit 0
root="${CLAUDE_PROJECT_DIR:-$(cd "$HOOK_DIR/../.." && pwd)}"
root="$(cd "$root" && pwd -P)"

block() {
  echo "generated-file guard: BLOCKED — $relative is generated or frozen; do not hand-edit it." >&2
  echo "Regenerate it instead: $1" >&2
  exit 2
}

while IFS= read -r file_path; do
  relative="${file_path#"$root"/}"
  case "$relative" in
  docs/ROADMAP.md)
    block "edit config/roadmap.json, then python3 scripts/roadmap.py render" ;;
  Sources/Resources/qwenvoice_production_model_catalog.json)
    block "edit config/model-artifact-receipts.json, then python3 scripts/model_catalog_contract.py rebuild" ;;
  docs/charts/*.svg)
    block "python3 scripts/generate_readme_charts.py" ;;
  benchmarks/HISTORY.md)
    block "python3 scripts/benchmark_history.py (regenerated from benchmarks/runs)" ;;
  benchmarks/runs/*)
    block "frozen evidence is never edited; publish a new record with scripts/publish_benchmark_history.py" ;;
  QwenVoice.xcodeproj/*)
    block "edit project.yml, then ./scripts/regenerate_project.sh --fast" ;;
  Packages/VocelloQwen3Core/CURRENT_INVENTORY.json)
    block "python3 scripts/qwen3_core_contract.py rebuild-current-inventory" ;;
  Packages/VocelloQwen3Core/FACADE_API_BASELINE.json)
    block "python3 scripts/qwen3_core_contract.py rebuild-facade-api-baseline" ;;
  esac
done <<< "$file_paths"

exit 0
