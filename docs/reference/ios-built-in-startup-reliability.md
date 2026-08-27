---
status: active
owner: backend-and-platform
summary: Governed diagnosis of the reported iOS Built-in Voice startup failure, including conservative historical classification, typed request receipts, startup boundaries, physical-device plans, and closure requirements.
sourceOfTruth:
  - config/roadmap.json
  - Sources/QwenVoiceCore/GenerationStartupDiagnostics.swift
  - Sources/QwenVoiceCore/GenerationOutputAdapter.swift
  - Sources/QwenVoiceCore/MLXTTSEngine.swift
  - Sources/QwenVoiceCore/StartupReliabilityDiagnosticEvidence.swift
  - Sources/QwenVoiceCore/IOSUnloadQuiescence.swift
  - Sources/iOS/IOSStartupReliabilityRunner.swift
  - config/ios-startup-reliability-result-schema-v2.json
  - scripts/ios_device.sh
  - scripts/ios_startup_reliability.py
---
# iOS Built-in Voice startup reliability

> **Currency review (2026-08-27):** request receipts now include resolved instruction language and
> the latest diagnostics include codec replay, complete QC evidence, crash-log classification, and
> unload-quiescence proof. ISR-05's false-startup-message fix remains closed; staged characterization
> and the exact-script closure gate (ISR-04/ISR-06) remain open.

This investigation covers the reported `vivian × calm.strong × english` Built-in Voice startup
failure with a 285-character script. The external *Vocello Built-in Voice Startup Reliability —
Codex Handout Revision 2.0* was reviewed as descriptive input. It correctly separates a pre-audio
startup defect from the post-generation delivery evaluator, but it was prepared against an older
public revision and does not override this checkout, the runtime, or `config/roadmap.json`.

Fresh physical-iPhone evidence localized one source-proven defect: the engine's outer catch labeled
a fully generated audio-QC rejection as a failure to start audio generation. That presentation bug
is fixed without accepting the rejected audio. The exact original script bytes are still required
for closure; the 285-character text reconstructed from the screenshot is useful diagnostic input,
but it cannot substitute for the original bytes.

Result-v2 replay subsequently localized two additional behaviors without changing delivery copy or
sampling. Streaming seed `38112006` preserves its unusual cadence in live, exact-range incremental,
and full replay, proving that the sampled codec sequence—not the decoder or writer—contains the
spacing. Separately, quality-first accumulation retained a large lazy MLX graph and could terminate
under critical memory pressure. Compact materialized codec frames plus 25-frame invariant-tested
decode partitions keep the same output while bounding the graph.

## What is now measurable

`GenerationRequestReceipt` binds each attempt to privacy-safe generation, request, session, and
prewarm digests plus model, speaker, canonical delivery cell, instruction digest and length,
language, seed and source, variation, streaming, warm state, predecessor, retry attempt, and
operation generation. It never retains the prompt, instruction, output path, or arbitrary error.

The verbose telemetry timeline records one-shot boundaries at existing ownership points:

```text
request validation -> memory admission -> model load -> prewarm
  -> generation reservation -> audio-consumer claim -> session directory
  -> engine open -> first model token / first audio-code group
  -> first decoded frame -> first published stream chunk
```

The first token and first audio-code boundaries may share one observed timestamp when the owned
runtime materializes them through the same signal. Capture is allocation-light and does not add a
per-token file write, actor hop, or parallel state machine.

Failure-journal schema v3 adds the privacy-safe receipt needed to reconstruct a deferred allocation
attempt while continuing to decode schema-v2 rows. The first allocation failure remains absent from
public terminal telemetry by design, but the gated bounded journal represents attempt zero even when
attempt one succeeds.
Allocation recovery retains the same generation, request, session, prewarm, seed, predecessor,
and operation identity; only `retryAttempt` and the observed warm state may change. Host validation
requires exactly attempt zero or the contiguous sequence zero then one.

## Read-only historical classification

`scripts/delivery_failure_topology.py` accepts retained matrix reports, experiment state,
generation telemetry, and failure journals without launching a model or reading audio. Every row
is classified as success, confirmed pre-audio startup, confirmed post-generation QC, timeout,
cancellation, memory failure, crash, or unmaterialized/unknown. A missing WAV alone remains
unknown. Typed decoded-audio evidence or a retained rejected-output identity proves the request
crossed the startup boundary.

Example local-only use:

```sh
python3 scripts/delivery_failure_topology.py \
  --matrix <matrix-report.json> \
  --experiment <execution-state.json> \
  --telemetry <generations.jsonl> \
  --failure-journal <generation-failures.jsonl> \
  --output-dir build/artifacts/diagnostics/delivery-failure-topology/<opaque-run-id>
```

The emitted JSON/Markdown contains only allowlisted identities, source digests, typed outcomes,
attempt scope, predecessor/warm context when available, and confidence. It contains no source
path, script, audio, URL, device identity, or raw error prose.

## Physical-device runner

The diagnostics-compiled app extends the existing `IOSDeviceDiagnosticsRunner`; it is not a
second engine or UI driver. A plan contains 1–128 ordered takes and one exact script digest and
character count. Each take fixes speaker, strict `<preset>.<intensity>` delivery ID, language,
seed, variation, streaming, predecessor, and one preparation mode: production state, full runtime
unload, prepared-cache clear, or prewarm disabled.

The current iOS production bootstrap already selects `skipDedicatedCustomPrewarm` to avoid a
memory spike. Consequently, the production and prewarm-disabled rows are expected-equivalent on
this checkout: the latter is a verification arm that proves the skip remained active, not an
independent runtime treatment. The result must not be interpreted as an A/B prewarm comparison
unless a future supported runtime path creates that contrast explicitly.

```sh
scripts/ios_device.sh delivery-reliability \
  --plan <plan.json> \
  --script-file <untracked-exact-script.txt>
```

The host verifies the script bytes before launch, passes them only through an ephemeral launch
input, builds and installs the exact diagnostics binary, polls for the terminal record, and always
attempts the final pull and crash snapshot. Polling binds to the exact PID from CoreDevice's launch
response: if that process exits without a terminal record, the run fails immediately and preserves
partial evidence instead of waiting for the overall timeout. A temporarily unavailable process
query remains unknown and cannot be mislabeled as an exit. The app continues after a typed take
failure when safe, writes each take first, exports the bounded journal, and writes the terminal
sentinel last. Successful audio is hashed with a bounded streaming read and removed after evidence
capture. Nothing publishes automatically.

The result validator requires every planned take, exact script identity, plan/receipt parity,
ordered startup marks, decoded-audio evidence for a pass, predecessor continuity, terminal-last
ordering, and complete allocation-retry accounting. It rejects cross-run evidence and any retained
private field.

Result schema v2 preserves schema-v1 decoding and closes the diagnostic gaps exposed by the first
device characterization. A QC rejection carries the complete final `AudioQCReport`, its bounded
chunk reports, the exact silence start/duration, and a run/generation-scoped rejected WAV identity.
When the diagnostic request captured a complete codec trace, the loaded engine replays the same
codes through Mimi twice: once at the exact observed production chunk boundaries and once as a
single full decode. Both outputs are written with the production PCM limiter and receive persisted
WAV QC. Retained JSON contains only artifact digests, sizes, duration, code counts/ranges, and QC;
the WAV and binary trace remain untracked and are removed after successful collection.

Full-runtime-unload preparation is now fail-closed. The runner records MLX active/cache/peak,
Metal allocation, physical footprint, process headroom, engine operation/reservation state, and
loaded-model state before unload, after owned references are released, after cache clearing,
immediately before reload, and after reload. It polls for at most 30 seconds and admits the next
request only after three consecutive stable samples meet the existing 4.5 GiB footprint guard,
the 768 MiB healthy-headroom floor, and the 32 MiB stability tolerance. This is diagnostic
containment, not a permanent production-threshold change.

If the exact launched PID exits before the terminal sentinel, the host composes every partial take
plus explicit `process_terminated` and `not_started_after_process_exit` rows; it never fabricates an
app-completed result. CoreDevice `systemCrashLogs` are diffed before/after the run. Raw reports stay
untracked and only allowlisted process, reason, footprint, timestamp, and a typed Jetsam/other
classification enter the summary. Missing crash evidence leaves the memory cause unconfirmed.

## Visible request parity

The explicit lane below uses physical-device XCUITest only:

```sh
scripts/ui_test.sh ios startup-parity --script-file <untracked-exact-script.txt>
```

It selects Vivian, Calm / Strong, and English through the real Studio sheets, verifies the visible
chips, enters the script through the production composer, and generates with the ordinary streaming
path. The host correlates the completed player’s genuine generation UUID with the engine receipt
and requires matching speaker, canonical delivery ID (which also proves the exact shipped
instruction resolved), instruction digest, language, generated seed source, Balanced variation,
streaming mode, and decoded-audio boundary. There is no hidden route, app-seeded script, Simulator,
or alternate UI driver.

An XCUITest automation bootstrap timeout is a separate host classification, not a product result.
It qualifies only when the `.xcresult` reports zero launched tests and the log proves there was no
app assertion, generation request, crash, or QC outcome. The failed bundle and exact manual rerun
command remain local. The lane never retries automatically or converts the original failure into a
pass; this repeatability work remains cross-referenced to AV-09.

## Characterization and causal-fix boundary

The closure sequence remains staged: fixed-seed cold launches, warm same-process repetition, eight
fixed seeds, focused predecessor transitions, four preparation arms, streaming parity, macOS and
iOS headless parity, and visible UI parity. The complete 9-speaker × 8-delivery grid runs only after
the first divergent boundary localizes the defect.

The screenshot-derived reconstruction has now produced decision-complete evidence for failure
classification, while remaining ineligible for exact-script closure:

- visible UI parity passed for Vivian / Calm Strong / English;
- five cold takes and ten warm same-process takes at seed `38112001` passed;
- the eight-seed screen passed six takes and rejected seeds `38112004` and `38112006` only after
  model tokens, decoded audio, and published stream chunks existed;
- the two rejections were deterministic long-dropout QC failures (`2725 ms` and `14992 ms`), not
  startup failures, and neither used allocation recovery;
- an immediate production-state retry after the `38112004` rejection remained alive and produced
  the same honest post-generation QC result;
- the diagnostics-only forced-unload successor exited after a memory warning without a new retained
  crash record. It remains an unrepresented preparation-arm failure, not evidence of a product
  startup defect, and blocks acceptance of that arm.

A phone-independent macOS CLI control on 2026-08-24 used the tracked 280-character sentinel, the
exact resolved 119-character `calm.strong` instruction (digest
`5e0b8f214f3f9aaf06104a9ed3b58249beb26b2663244411336cb62816805662`), Vivian, English,
Expressive variation, and the Speed artifact from this checkout. Seeds `38112001`, `38112004`, and
`38112006` each passed mandatory QC in three fresh processes for both streaming and non-streaming
execution (18/18). Their respective streaming/non-streaming durations were stable at 46.80/27.36,
66.40/36.00, and 59.76/30.48 seconds across all repetitions. This rules out a universal failure of
those seed numbers or the shipped instruction on the Mac sentinel, but it does not explain the
iPhone dropout or establish codec identity across execution styles. The stable, large duration
differences make the planned bounded codec-trace comparison material; no RNG, decoder, or
persistence conclusion is drawn without those traces. Raw WAVs remain untracked.

The causal code error was in `MLXTTSEngine`'s outer failure wrapper. It converted every downstream
error into `.streamStartup`, including the mandatory final audio-QC rejection emitted after output
materialization. `NativeRuntimeError` now carries a typed failure code; existing runtime errors pass
through the outer catch unchanged, and QC rejection remains `.streamFailed` /
`audio.quality_rejected`. The user sees that the take contained an unusable silent gap and was not
saved, while allowlisted diagnostics retain the exact QC flag. A generic engine failure still uses
the startup message, and the existing allocation-retry wording remains unchanged.

No prompt, sampling default, model pin, speaker roster, audio-QC rule, hidden retry, seed mutation,
or product API changed. The rejected WAV still cannot be saved or promoted. This closes ISR-05's
smallest evidence-supported false-startup fix; it does not close the original-script requirement,
the forced-unload memory finding, or ISR-06's broader reliability matrix.

## Current status

- Historical/topology classifier: implemented with conservative negative fixtures.
- Strict delivery resolution, request receipts, startup marks, retry preservation, and journal v3:
  implemented and deterministic-test covered.
- Ordered device runner and visible UI parity lane: implemented and exercised on the physical
  iPhone with the screenshot-derived reconstruction.
- Cold/warm and fixed-seed characterization: partially complete; no pre-audio failure was observed,
  while two seeds produced typed post-generation dropout rejection.
- macOS CLI sentinel control: the passing and two iPhone-rejected seeds pass QC 3/3 in streaming
  and non-streaming modes; codec/output-mode identity remains unproven and the original script
  remains unavailable.
- False-startup presentation: fixed and regression-tested; the audio-QC gate remains fail-closed.
- Diagnostic result v2, complete rejected-output QC, generation-scoped artifacts, codec replay,
  system-crash sanitization, and process-exit composition: implemented and live-proven. The
  `38112006` replay preserves the same approximately 980 ms silence and cadence warning across live,
  incremental, and full decoding, classifying the spacing as sampled output.
- Quality-first memory: bounded 25-frame decode partitions are deterministic-test covered and two
  cold physical-device controls completed at 2.92-3.02 GiB instead of the earlier 6.29 GiB critical
  termination. A subsequent 10-take sentinel run completed five full unload/quiescence/reload cycles
  at 2.78-3.19 GiB per-take peaks with at least 2.96 GiB headroom, no capture failure, no crash-log
  delta, and correct warm/cold receipts.
- XCUITest bootstrap classification: implemented and deterministic-test covered; no automatic
  retry is introduced.
- Exact 285-character source bytes: not supplied, so exact-script characterization and closure stay
  blocked.
- Forced-unload successor: represented as a process termination after critical pressure with no
  correlated system-crash report. The quality-first graph cause is repaired and five tracked-sentinel
  cycles now pass; equivalent exact-script cycles remain blocked on the unavailable bytes.

This report is descriptive. Source, schemas, test scripts, runtime contracts, and
`config/roadmap.json` remain authoritative.
