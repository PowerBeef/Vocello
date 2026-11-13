#!/usr/bin/env bash
# Validate the hosted iPhone model catalog against Sources/Resources/qwenvoice_contract.json.
# Replaces the retired Python check_ios_catalog.py with a curl + jq port that
# preserves the same validation rules and JSON output shape.
#
# Usage:
#   check_ios_catalog.sh [--url <catalog_url>]
#
# Exit codes:
#   0  catalog is consistent with the contract
#   1  fetch or validation failure (errors in the JSON payload)
#   2  bad arguments

set -euo pipefail

DEFAULT_CATALOG_URL="bundle://vocello/ios/catalog/v1/models.json"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_DIR="$(cd -- "$SCRIPT_DIR/.." &>/dev/null && pwd)"
CONTRACT_PATH="$PROJECT_DIR/Sources/Resources/qwenvoice_contract.json"
BUNDLED_CATALOG_PATH="$PROJECT_DIR/Sources/Resources/qwenvoice_ios_model_catalog.json"

URL="$DEFAULT_CATALOG_URL"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      URL="${2:?missing value for --url}"
      shift 2
      ;;
    -h|--help)
      sed -n '2,12p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "check_ios_catalog.sh: unknown argument '$1'" >&2
      exit 2
      ;;
  esac
done

if [[ ! -f "$CONTRACT_PATH" ]]; then
  jq -n --arg url "$URL" --arg path "$CONTRACT_PATH" \
    '{ok: false, catalog_url: $url, error: ("missing contract at " + $path)}'
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "check_ios_catalog.sh: jq is required but not installed." >&2
  exit 2
fi

# Fetch the catalog. -f makes curl exit non-zero on HTTP errors.
catalog_body=""
trap '{
  if [[ -n "${catalog_body:-}" && "$catalog_body" == /tmp/* ]]; then
    rm -f "$catalog_body"
  fi
}' EXIT

if [[ "$URL" == bundle://* ]]; then
  catalog_body="$BUNDLED_CATALOG_PATH"
  if [[ ! -f "$catalog_body" ]]; then
    jq -n --arg url "$URL" --arg path "$catalog_body" \
      '{ok: false, catalog_url: $url, error: ("missing bundled catalog at " + $path)}'
    exit 1
  fi
else
  catalog_body="$(mktemp)"
  if ! curl -fsSL --max-time 60 -A "VocelloCatalogCheck/1.0" "$URL" -o "$catalog_body"; then
    jq -n --arg url "$URL" \
      '{ok: false, catalog_url: $url, error: "failed to fetch catalog"}'
    exit 1
  fi
fi

if ! jq empty "$catalog_body" 2>/dev/null; then
  jq -n --arg url "$URL" \
    '{ok: false, catalog_url: $url, error: "catalog is not valid JSON"}'
  exit 1
fi

# All validation logic lives in this jq program. It mirrors _validate_catalog
# in the retired Python script. Rules:
#   - prefer the iOS "speed" variant; fall back to first iOS-eligible variant
#     or to the model itself when iosDownloadEligible is true at the top level
#   - catalog entries are keyed by (modelID, artifactVersion); each must be
#     present, totalBytes must match, baseURL must be https://, and every
#     requiredRelativePath must appear in files[]
#   - per-file rules: non-empty relativePath, no leading "/", no ".." segment,
#     non-negative integer sizeBytes, 64-char sha256, https:// url when present
#   - sum of file sizeBytes must equal totalBytes
#   - at least one iOS-eligible model must be checked
#   - catalog must have a non-empty models[] array
result="$(jq -n \
  --slurpfile contract "$CONTRACT_PATH" \
  --slurpfile catalog "$catalog_body" \
  --arg url "$URL" \
  '
def preferred_ios_descriptor:
  . as $model
  | (.variants // []) as $variants
  | ($variants | map(select(.platforms? | index("iOS")) | select(.iosDownloadEligible == true))) as $eligible
  | if ($eligible | length) > 0 then
      ((($eligible | map(select(.kind == "speed")) | first)
        // ($eligible | first)) as $v
       | {modelID: $model.id,
          artifactVersion: $v.artifactVersion,
          estimatedDownloadBytes: $v.estimatedDownloadBytes,
          requiredRelativePaths: ($v.requiredRelativePaths // [])})
    elif $model.iosDownloadEligible == true then
      {modelID: $model.id,
       artifactVersion: $model.artifactVersion,
       estimatedDownloadBytes: $model.estimatedDownloadBytes,
       requiredRelativePaths: ($model.requiredRelativePaths // [])}
    else
      empty
    end;

def validate_descriptor($entries):
  . as $d
  | $entries[($d.modelID + "@" + $d.artifactVersion)] as $entry
  | if $entry == null then
      ["missing entry for " + $d.modelID + " artifact " + $d.artifactVersion]
    else
      ([
        ($entry.totalBytes) as $actualTotal
        | (if ($d.estimatedDownloadBytes != null) and ($actualTotal != $d.estimatedDownloadBytes)
             then [$d.modelID + " totalBytes mismatch: expected " + ($d.estimatedDownloadBytes|tostring) + ", found " + ($actualTotal|tostring)]
             else [] end),
        (if ((($entry.baseURL // "") | type) != "string") or (($entry.baseURL // "") | startswith("https://") | not)
           then [$d.modelID + " baseURL must be https://, found " + (($entry.baseURL // null) | tostring)]
           else [] end),
        (($entry.files // []) as $files
         | ($files | map(.relativePath // "")) as $paths
         | (($d.requiredRelativePaths // []) - $paths | unique | sort) as $missing
         | (if ($missing | length) > 0
              then [$d.modelID + " missing required paths: " + ($missing | join(", "))]
              else [] end)),
        (($entry.files // []) as $files
         | ($files | map(.relativePath // "")) as $paths
         | ([$paths[] | select(. != "")] | group_by(.) | map(select(length > 1) | .[0]) | unique | sort) as $dupes
         | (if ($dupes | length) > 0
              then [$d.modelID + " duplicate paths: " + ($dupes | join(", "))]
              else [] end)),
        (($entry.files // []) | map(
            (.relativePath // "") as $p
            | (.sizeBytes) as $sz
            | (.sha256 // "") as $sha
            | (.url) as $u
            | [
                (if $p == "" then [$d.modelID + " contains empty relativePath entry"] else [] end),
                (if ($p | startswith("/")) or ($p | split("/") | index(".."))
                   then [$d.modelID + " invalid relativePath: " + $p]
                   else [] end),
                (if ($sz | type) != "number" or ($sz % 1) != 0 or $sz < 0
                   then [$d.modelID + " invalid sizeBytes for " + $p + ": " + ($sz | tostring)]
                   else [] end),
                (if ($sha | type) != "string" or ($sha | length) != 64
                   then [$d.modelID + " invalid sha256 for " + $p]
                   else [] end),
                (if $u != null and ((($u | type) != "string") or (($u | startswith("https://")) | not))
                   then [$d.modelID + " file URL must be https:// for " + $p + ", found " + ($u | tostring)]
                   else [] end)
              ] | add
          ) | add // []),
        (($entry.files // [])
         | map(select((.sizeBytes | type) == "number" and (.sizeBytes % 1) == 0 and .sizeBytes >= 0) | .sizeBytes)
         | add // 0) as $computed
        | ($entry.totalBytes) as $actualTotal
        | (if ($actualTotal | type) == "number" and ($actualTotal % 1) == 0 and $actualTotal >= 0 and $computed != $actualTotal
             then [$d.modelID + " file sizes sum to " + ($computed|tostring) + ", but totalBytes is " + ($actualTotal|tostring)]
             else [] end)
      ] | flatten)
    end;

($contract[0].models // []) as $models
| ($models | map(preferred_ios_descriptor)) as $checked
| ($catalog[0].models // []) as $catalogModels
| ($catalogModels | map({(.modelID + "@" + .artifactVersion): .}) | add // {}) as $entries
| ($checked | map(validate_descriptor($entries)) | flatten) as $perDescriptor
| ($perDescriptor
   + (if ($checked | length) == 0 then ["shared contract exposes no iPhone-downloadable models"] else [] end)
   + (if ($catalogModels | length) == 0 then ["catalog at " + $url + " returned no models"] else [] end)
  ) as $errors
| {
    ok: (($errors | length) == 0),
    catalog_url: $url,
    checked_models: ($checked | map(.modelID)),
    error_count: ($errors | length),
    errors: $errors
  }
  ')"

echo "$result"

if [[ "$(jq -r '.ok' <<<"$result")" == "true" ]]; then
  exit 0
else
  exit 1
fi
