---
status: active
owner: release-qa
summary: Source-bound quality promotion for making a verified macOS draft public or submitting an iOS candidate for external App Store review.
sourceOfTruth:
  - config/quality-promotion-contract.json
  - config/evidence-impact.json
  - scripts/quality_promotion.py
  - .github/workflows/promote-release.yml
---
# Source-bound quality promotion

Candidate production and public promotion are separate operations. `release.yml` may build, sign,
notarize, attest, archive, upload an internal TestFlight build, and create a verified draft using
deterministic evidence only. It never makes the GitHub Release public. `promote-release.yml` is the
only GitHub publication route and requires `quality-promotion.json` for the exact tag.

The same boundary applies to iOS: archive/export and internal TestFlight upload remain useful
candidate-validation steps; external TestFlight distribution, App Review submission, and public
App Store release require a validated iOS promotion manifest.

## What the manifest binds

`scripts/quality_promotion.py` binds one privacy-safe artifact to:

- the tag commit, clean release source identity, exact `release-evidence.json` bytes, version, and build;
- the evidence-impact contract and the exact paths changed since the previous release commit;
- the capability/change matrix for Speed, Quality, Studio modes, multilingual output, delivery
  evaluation, and model lifecycle, including dimensions the current evidence does not support;
- the required platform lanes, record or receipt digests, and explicitly accepted warnings;
- benchmark hardware profile, OS, toolchain, executable hashes, and Mach-O UUIDs already validated
  by `scripts/benchmark_history.py`.

Benchmark records must be clean, fingerprint-stable, no more than seven days old, and produced by
the exact tag commit. The manifest never contains a UDID, serial number, personal device name,
username, hostname, or absolute path. “Device identity” means the checked-in canonical hardware
profile only.

Every platform requires its canonical 29-take Speed `ui-generation` matrix. Capability-sensitive
changes add the smallest platform-specific set declared by the contract: Quality requires a
Quality-tier engine record across Custom, Design, and Clone; multilingual changes require every
declared language cell; delivery changes require delivery cells carrying the governed prosody
metric; and model-catalog changes require the managed lifecycle receipt. Memory paths add
`memory-qualification`, and UI paths add `ui-perf`. `python3 scripts/evidence_impact.py
classify --base <previous-tag>` shows the conditional evidence before capture.

The manifest records `capabilityCoverage` and `unsupportedDimensions`. Unsupported combinations
such as multilingual Quality/Clone cohorts and independently held-out delivery calibration are
never silently implied by a successful Speed record. The research and device-evidence roadmap
items remain the authority for removing those labels.

## Capture after the candidate is frozen

1. Commit the release candidate, create its protected tag, and let `release.yml` produce the
   verified draft and `release-evidence.json`.
2. Check out that exact tag with a clean tree. Run only the lanes selected by the impact result.
   Publish successful benchmark records locally but do not create another source commit: exact-tag
   promotion records are external draft evidence, avoiding a self-referential commit.
3. Download the draft's exact release evidence for assembly (or download every asset and validate
   the complete deterministic bundle):

   ```sh
   gh release download vX.Y.Z --pattern release-evidence.json \
     --dir build/artifacts/quality-promotion/release
   ```

4. For a changed delivery surface, capture the command-bound receipt before a benchmark publisher
   creates uncommitted registry files; managed capture deliberately requires a clean tag checkout:

   ```sh
   python3 scripts/quality_promotion.py capture \
     --platform macos --tag vX.Y.Z \
     --evidence-id macos-model-download-lifecycle \
     --output build/artifacts/quality-promotion/macos-model-download.json -- \
     ./scripts/build.sh cli models install pro_custom_speed \
       --data-dir build/scratch/transient/model-download-acceptance --verbose

   python3 scripts/quality_promotion.py capture \
     --platform ios --tag vX.Y.Z \
     --evidence-id ios-model-download-lifecycle \
     --output build/artifacts/quality-promotion/ios-model-download.json -- \
     scripts/ui_test.sh ios model-download
   ```

The capture subprocess hashes but does not retain its output in the receipt, verifies the command
against the contract, and rejects a dirty or source-changing checkout.

## Assemble and validate

Use one `--record id=path` or `--receipt id=path` for every required lane. The command rejects
missing and extra lanes. The following shape is illustrative; use the classifier output for the
actual candidate:

```sh
python3 scripts/quality_promotion.py create \
  --platform macos --tag vX.Y.Z --base vW.Y.Z \
  --release-evidence build/artifacts/quality-promotion/release/release-evidence.json \
  --record macos-ui-benchmark=build/artifacts/quality-promotion/macos-ui-generation.json \
  --record macos-engine-benchmark=build/artifacts/quality-promotion/macos-engine-generation.json \
  --record macos-retained-memory=build/artifacts/quality-promotion/macos-memory-qualification.json \
  --record macos-ui-performance=build/artifacts/quality-promotion/macos-ui-perf.json \
  --accept-warning memory.pressure.soft_trim \
  --output build/artifacts/quality-promotion/quality-promotion.json

python3 scripts/quality_promotion.py validate \
  --platform macos --tag vX.Y.Z \
  --release-evidence build/artifacts/quality-promotion/release/release-evidence.json \
  --manifest build/artifacts/quality-promotion/quality-promotion.json
```

Warning acceptance is explicit and restricted by the checked-in allowlist. Omit
`--accept-warning` when every required record passed without warnings.

For macOS, upload the validated manifest to the existing draft, then manually dispatch **Promote
verified release** with the tag:

```sh
gh release upload vX.Y.Z build/artifacts/quality-promotion/quality-promotion.json \
  --clobber --repo OWNER/REPOSITORY
```

The workflow downloads all draft assets, revalidates the deterministic release bundle, validates
the promotion manifest against the checked-out tag, and only then changes the draft to public. A
candidate rebuild resets all draft assets, so its quality manifest must be regenerated and
re-uploaded.

For iOS, retain the validated iOS manifest with the submission evidence and validate it immediately
before external TestFlight distribution or App Review submission. Internal TestFlight upload is
deliberately not blocked: it can be needed to finish candidate validation.
