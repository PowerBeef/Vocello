# benchmarks/

Validated, privacy-safe benchmark **summaries** live here. Raw telemetry, audio, screenshots, traces,
and result bundles are never tracked. Successful profile traces are ephemeral by default: their
digest, capture settings, extracted evidence, original path, and retention status are published
before the raw trace is discarded. `--keep-trace` is an explicit local diagnostic exception.

## What may live here

- **`runs/`** — one allowlisted `<kind>/<run-id>.json` record for each successful benchmark; clean,
  comparable runs are canonical while dirty-source successes remain exploratory.
- **`HISTORY.md`** — a generated index. Never append to it manually.
- **`LEGACY_HISTORY.md`** — the former hand-maintained ledger, preserved verbatim as incomplete historical
  context. It is not schema-v1 benchmark evidence.
- **`hardware-profiles.json`** — the canonical Mac mini M2 8 GB and iPhone 17 Pro profiles.
- **`schema-v3.json`** — the record shape when every take carries the typed quality-registry identity
  (generation lanes since 2026-07-26); **`schema-v2.json`** is still published for records without it
  (`ui-perf`); **`schema-v1.json`** is read-only; `scripts/benchmark_history.py` is the executable validator.
- **`OPTIMIZATION.md`** — a dated historical optimization decision ledger. Current performance truth
  comes from validated records in `runs/`, the generated `HISTORY.md`, and current telemetry documentation.
- Existing dated Markdown/JSON snapshots and `benchmarks/baselines/` remain preserved reference
  artifacts. They are not silently converted into complete schema-v3 evidence. New successful runs
  use a kind directory under `runs/`; optional baseline comparisons remain local model-dependent QA and never an
  ordinary CI or packaging gate.

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

- macOS: Mac mini `Mac14,3`, Apple M2, 8 GB (`mac-mini-m2-8gb`)
- iOS: iPhone 17 Pro `iPhone18,1` (`iphone-17-pro`)

Schemas v2 and v3 accept `ui-generation`, `engine-generation`, `language`, `instrument-profile`,
`memory-qualification`, `prosody-calibration`, and `ui-perf`. Schema-v1 `telemetry-overhead` records remain
readable but memory-contract-incomplete; new overhead verdicts stay local because sampling the
`off` lane would change the observer-effect experiment. An unfiltered 29-take UI matrix on the matching
hardware is canonical; a filtered matrix is focused; a dirty checkout is exploratory; an
Instruments run is instrumented; and a hint-only language run is partial. Only compatible clean
runs share a comparison key. Instrumented, exploratory, and partial records are never silently
mixed into normal timing trends.

Each record binds UTC timing, matrix/status, source and pre/post workspace fingerprints, hardware
and toolchain/executable identity, project/harness/model/fixture hashes, selected-evidence and
result digests, ordered per-take metrics, per-cell median/IQR/min/max and worst-state summaries,
and an optional independent listening-annotation block. Its canonical SHA-256 is computed with the `digest` field
omitted.

The executable validator independently rechecks kind-specific success semantics after publication:
structured target-PID/CPU/signpost
profile proof, complete prosody-calibration aggregates, full hardware context, and cell summaries
recomputed from the ordered takes. A publisher PASS alone cannot make an incomplete tracked record
valid.

Corpus identity is derived from fixed harness sources and the ordered generation-time prompt
digests. Delivery and calibration records also bind the exact prosody-analysis profile. Prompt
text and profile source paths are never copied into telemetry or the registry.

The selected-evidence digest is derived from the distilled take/output/QC payload and raw/result/
trace evidence identities, not from mutable labels or wrapper metadata. Rewrapping the same
underlying evidence under a different run ID is therefore rejected.

Every validator selects one collision-resistant run ID and emits one atomic, untracked
`benchmark-evidence.json`. History publication consumes only that manifest's ordered generation
IDs, cells, layer verdicts, output/QC verdicts, and crash result; it never scans a historical
diagnostics tree. A publication failure after a successful run leaves the local evidence intact
and prints the idempotent `record --artifact-dir` repair command.

Listening review is optional metadata and can be added later with `annotate`; it never establishes,
clears, or blocks automated benchmark success. Promotion-quality audio requires the applicable
fixed-seed PCM QC, exact-output identity, locale-locked ASR consensus, and prosody/delivery gates.
`annotate` is the only supported post-publication mutation: it updates the listening block and
recomputes the record digest without changing the captured run evidence.

Comparison metadata is derived from all tracked records, not insertion order. `rebuild-index`
reconciles each compatible clean run with its nearest earlier equivalent and updates the record
digest when an earlier record arrives later through a merge; `rebuild-index --check` and ordinary CI
reject stale comparison metadata.

See [`docs/reference/benchmarking-procedure.md`](../docs/reference/benchmarking-procedure.md)
for the operator runbook (workflows, preflight, reading results) and
[`docs/reference/telemetry-and-benchmarking.md`](../docs/reference/telemetry-and-benchmarking.md)
for the telemetry schema and knobs.
