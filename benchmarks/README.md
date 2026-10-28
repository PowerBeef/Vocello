---
status: active
owner: release-qa
summary: What the benchmark registry may hold, how successful runs are published into it, the privacy and size rules on committed records, and the canonical hardware and run classes.
sourceOfTruth:
  - scripts/benchmark_history.py
  - scripts/publish_benchmark_history.py
  - benchmarks/hardware-profiles.json
  - benchmarks/schema-v3.json
---
# benchmarks/

Validated, privacy-safe benchmark **summaries** live here. Raw telemetry, audio, screenshots, traces,
and result bundles are never tracked. A successful profile publishes its trace digest, capture
settings, extracted evidence, original path, and retention status first. A CPU profile's raw trace is
then discarded unless `--keep-trace` was given; a memory profile keeps its raw trace locally by
default (`keptByDefault`), because the trace is its only allocation and VM evidence.

## What may live here

- **`runs/`** — one allowlisted `<kind>/<run-id>.json` record for each successful benchmark; clean,
  comparable runs are canonical while dirty-source successes remain exploratory.
- **`HISTORY.md`** — a generated index. Never append to it manually.
- **`LEGACY_HISTORY.md`** — the former hand-maintained ledger, preserved verbatim as incomplete historical
  context. It is not schema-v1 benchmark evidence.
- **`hardware-profiles.json`** — the canonical Mac mini M6 16 GB (since 2026-09-22) and iPhone 17 Pro
  profiles, plus the retired Mac mini M2 8 GB profile that its history records keep.
- **`schema-v3.json`** — the record shape when every take carries the typed quality-registry identity
  (generation lanes since 2026-07-26); **`schema-v2.json`** is still published for records without it
  (`ui-perf`); **`schema-v1.json`** is read-only; `scripts/benchmark_history.py` is the executable validator.
- **`baselines/`** — `mac-gate-bench.json`, the governed baseline the macOS gate bench compares
  against, and older JSON baselines kept as reference artifacts. Baselines are never converted into
  schema-v3 evidence; comparisons against them stay local model-dependent QA, never an ordinary CI or
  packaging gate.
- **`qc/`** — QC v2 threshold evaluations (`eval-v<N>.json`, aggregates only; see
  [`docs/reference/qc.md`](../docs/reference/qc.md)).
- **`OPTIMIZATION.md`** — a dated historical optimization decision ledger. Current performance truth
  comes from validated records in `runs/`, the generated `HISTORY.md`, and current telemetry documentation.

## Registry commands

Successful benchmark validators write an untracked `benchmark-evidence.json`; the runner then publishes it:

```sh
# Publication-repair example; use the exact policy-owned artifact directory printed by the runner.
python3 scripts/benchmark_history.py record \
  --artifact-dir build/artifacts/macos/<runner-owned-path>/<run-id>
python3 scripts/benchmark_history.py validate --all
python3 scripts/benchmark_history.py rebuild-index --check
# Optional subjective annotation; never a PASS prerequisite.
python3 scripts/benchmark_history.py annotate --run-id <id> --listening pass --note "reviewed"
```

Publication only writes the JSON record and generated index. It never stages, commits, or pushes. Repeating
`record` with byte-identical evidence is idempotent; conflicting run IDs or duplicate evidence fail.
If a validated benchmark cannot publish, do not move or rewrite its evidence: rerun the exact
`record --artifact-dir …` repair command printed by the owning macOS, iOS, or XCUITest runner.

## Rules (enforced by `scripts/check_project_inputs.sh`)

- **No raw `*.jsonl`.** The per-generation diagnostics JSONL is large and lives on disk under
  `~/Library/Application Support/QwenVoice[-Debug]/diagnostics/` (gitignored, and auto-pruned to a size
  budget by `GenerationTelemetryJSONLSink`). Commit a distilled summary, not the raw stream.
- **Each committed file ≤ 256 KB.** Keep it a summary, not a dump.
- **Successful evidence only.** Failed, interrupted, crashed, incomplete-layer, unreadable-output, or failed-QC
  runs must leave the tracked registry unchanged.
- **Strict privacy allowlist.** Records reject serial numbers, UDIDs, ECIDs, device/host/user names,
  absolute paths, prompts, transcripts, voice descriptions, raw errors, URLs, email addresses, and
  path-like or secret-bearing labels. Run labels are opaque identifiers made only from letters,
  numbers, `.`, `_`, and `-`; warnings are bounded machine codes, never prose or copied errors.
- **Dirty runs are exploratory.** They retain source fingerprints but are excluded from comparable trends.
- JSON baseline comparisons are explicit local QA. They do not run automatically in ordinary CI or
  release packaging. See the canonical procedure for the supported save/compare commands.

## Canonical hardware and run classes

New native comparisons use the profiles in `hardware-profiles.json`:

- macOS: Mac mini `Mac18,5`, Apple M6, 16 GB (`mac-mini-m6-16gb`), canonical since 2026-09-22
- iOS: iPhone 17 Pro `iPhone18,1` (`iphone-17-pro`)

The retired canonical Mac, Mac mini `Mac14,3`, Apple M2, 8 GB (`mac-mini-m2-8gb`), keeps its records
as valid history. They are never rewritten and never compared with M6 records; the M6 series starts
fresh. The 8 GB Mac stays the product support floor.

Schemas v2 and v3 accept `ui-generation`, `engine-generation`, `language`, `instrument-profile`,
`memory-qualification`, `prosody-calibration`, and `ui-perf`. Schema-v1 `telemetry-overhead` records remain
readable but memory-contract-incomplete; new overhead verdicts stay local because sampling the
`off` lane would change the observer-effect experiment. An unfiltered 29-take UI matrix on the matching
hardware is canonical; a filtered matrix is focused; a dirty checkout is exploratory; an
Instruments run is instrumented; and a hint-only language run is partial. Only compatible clean
runs share a comparison key. Instrumented, exploratory, and partial records are never silently
mixed into normal timing trends.

A record's canonical SHA-256 is computed with its `digest` field omitted. The selected-evidence
digest comes from the distilled take/output/QC payload and the raw/result/trace evidence identities,
never from labels or wrapper metadata, so rewrapping the same evidence under another run ID is
rejected. Corpus identity comes from the fixed harness sources and the ordered prompt digests;
delivery and calibration records also bind the prosody-analysis profile, and no prompt text or
profile path enters the registry. `annotate` is the only supported post-publication mutation.

What a record binds, how the validator rechecks it, how `rebuild-index` reconciles comparison
metadata and lineage, and the listening-annotation rules are in
[`docs/reference/telemetry-and-benchmarking.md` §8](../docs/reference/telemetry-and-benchmarking.md#8-publication-lineage-and-baselines),
which is also the operator runbook (workflows, preflight, reading results, telemetry schema and
knobs).
