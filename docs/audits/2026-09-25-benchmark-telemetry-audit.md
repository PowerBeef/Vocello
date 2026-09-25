---
status: active
owner: backend-and-platform
reviewed: 2026-09-25
summary: Verified audit of the benchmarking harnesses and telemetry probes (106 findings) with the recommended sequence and the roadmap plan benchmark-telemetry-audit-2026-09.
---
# Benchmark and telemetry audit (2026-09-25)

Read-only audit of Vocello's benchmarking harnesses and telemetry probes, for accuracy and efficiency. Six area auditors and four gap sweeps each cited file:line evidence and numbers from committed benchmark records; an adversarial verifier re-checked every finding against the code and data (106 survived: 42 confirmed, 64 partially confirmed with corrections, none refuted). Corrected impacts and proposals are the verifiers'. Source: main at 16a2f808. Roadmap plan: benchmark-telemetry-audit-2026-09 (items BT-01 to BT-06).

# Vocello benchmarking and telemetry audit

## 1. Executive summary

This read-only audit, run at `16a2f808`, covers Vocello's benchmarking harnesses and telemetry probes. It looks at six areas: the engine bench and gate, generation telemetry, memory probes, the UI benchmark and ui-perf lanes, UI responsiveness, and audio and language evaluation. It adds four gap areas: the M6 host and the 8 GB floor, CI routing, Instruments profiles, and delivery and prosody evaluation. A second agent verified each of the 106 findings. Findings are numbered #1-#106 by corrected severity: #1-#12 are high, #13-#52 medium and #53-#106 low. The verifiers also found 14 further items, V-1 to V-14.

**Most important accuracy problems**
- **#1/#2:** Since the engine moved into the app process (628887c7), macOS UI memory has been summed from two samplers of the same process. The 8 records since then report about 1.8× the real footprint, and the next canonical record would publish doubled RAM.
- **#3 (with #4 and #16):** The 500 ms sampler misses short peaks: 119 of 173 memory-qualification takes miss the Metal peak, typically by 188 MB. The exact kernel-ledger and MLX high-water marks already exist and go unused.
- **#5:** The gate's footprint threshold has collapsed to a flat 5%, while identical-source runs drift 2-13%. The AV-17 re-seed on the M6 would therefore bring back false REGRESSION verdicts. The exact `mlxPeakMB` is the better memory signal.
- **#9:** On all 902 takes, the published `deliveryProsodyEffect` is the instructed take's absolute expressiveness, not the paired effect. The median is about 9, against paired values of −0.1 to 1.5.
- **#6:** The macOS stall gate went live on the M6 with zero tolerance for delayed heartbeats. 90.3% of M2 takes had at least one, so the first canonical M6 benchmark is likely to fail.

Two cheap code defects would each break part of the AV-17 session: #6, and #7 (the supervisor's swap probe fails under the host's fr_CA locale).

**Biggest efficiency wins**
- **#5, #13, #15 and #55, with #14:** Every change to the seed, the summary metrics or the cells that lands after the AV-17 re-seed forces another consent-bound re-baseline. On its own, following the printed repair command (#14) wastes at least one gate run.
- **#8:** Round-trip tests that pass each producer's output through `validate_record` would have caught four publication refusals. Each refusal cost a new consent-bound run of 14-17 minutes.
- **#57 and #53:** The gate runs VocelloCoreTests twice (20-24 s) and the full pytest suite (up to 67 s) on every run. A missing model is detected only after about 3-4 minutes of earlier steps.
- **#31:** Per canonical run, the UI benchmark spends about 5-9.5 s of harness time on each take, about 208 s waiting on captured playback and 75-100 s typing text one character at a time. None of this is measured today.
- **#47 and #91:** Mocking one host probe saves about 35-40 s of macOS CI on every push. Narrower CI routing would have skipped about 12 unneeded macOS lane runs in 12 days.

---

## 2. Findings at a glance

Column key:
- Kind: acc = accuracy, eff = efficiency, both = accuracy and efficiency.
- Severity is the verifier's corrected severity. Effort is S, M or L.
- Consent is "yes" when the fix needs a consent-bound lane (device, UI, model or benchmark run) to land or to be proven.

| # | id | Title | Kind | Severity | Effort | Consent | Corrected impact |
|---|---|---|---|---|---|---|---|
| #1 | generation-telemetry-macos-inprocess-memory-double-count | macOS UI memory is counted twice | acc | high | M | no | The 8 in-process UI records report about 1.8× the real memory, and the next canonical record would publish doubled RAM. |
| #2 | memory-probes-macos-inprocess-double-count | macOS UI memory totals count one process twice (duplicate of #1) | acc | high | S | no | Same defect as #1. The memory-qualification lane and iOS are unaffected. |
| #3 | memory-probes-sampled-peak-undershoot | The sampler misses peaks while exact high-water marks go unused | acc | high | M | no | 119 of 173 memory-qualification takes miss the Metal peak (typically by 188 MB, at most 868 MB). RAM deltas of a few percent are noise. |
| #4 | gap-1-06 | Sampled peaks depend on the tier's sampling cadence | both | high | S | yes | Short-cell peaks read at least 0.33 GB low in 75-86% of takes. The M6's faster cadence confounds tier comparisons. |
| #5 | engine-bench-01 | The gate threshold uses within-run spread, and the memory threshold is a flat 5% | acc | high | M | yes | A re-seeded M6 baseline brings back false memory REGRESSION verdicts (2-13% identical-source drift against 5%). Each costs a consent-bound rerun. |
| #6 | ui-responsiveness-01 | The stall gate went live on the M6 with zero tolerance and no calibration | both | high | M | yes | One delayed heartbeat in any of 29 takes fails the first canonical M6 benchmark. 90.3% of M2 takes had one. |
| #7 | gap-4-02 | The supervisor's swap probe fails under the fr_CA locale | both | high | S | no | On the M6, every uncached ASR run and every compact qualification fails closed. |
| #8 | gap-2-05 | No test passes producer output through the history validator | acc | high | M | no | Mismatches surface only at publication. Four refusals each forced a new consent-bound run of 14-17 minutes. |
| #9 | gap-4-01 | deliveryProsodyEffect is absolute, not paired | acc | high | M | no | All 902 takes carry a mislabelled metric (median about 9, against paired −0.1 to 1.5). No gate reads it. |
| #10 | audio-language-eval-no-speaking-rate-plausibility | Fast-QC never checks length or speaking rate | acc | high | M | no | Run-ons 2-3× too long pass QC: about 0.3% of takes, 2 of them in canonical records. |
| #11 | gap-1-01 | No evidence path for the 8 GB floor after AV-17 | acc | high | M | yes | No tracked 8 GB evidence is possible after AV-17, so a regression at the floor would go uncaught. |
| #12 | gap-3-1 | The trace summary discards every signpost duration | acc | high | M | yes | Every profile run loses the only kernel-timestamped witness for each stage. |
| #13 | engine-bench-02 | The gate bench runs without a fixed seed | both | medium | S | yes | The gate's QC outcome is a random draw that cannot be reproduced. Adding the seed changes the baseline identity, so it must land before the re-seed. |
| #14 | engine-bench-06 | The printed repair command produces a baseline the gate rejects | both | medium | S | yes | Following the hint wastes at least one consent-bound gate run at the AV-17 re-seed and at each CONV-21 toolchain move. |
| #15 | engine-bench-08 | The gate compares no latency metric | acc | medium | S | yes | A first-chunk regression passes unless it also pushes total RTF past about 5%. |
| #16 | engine-bench-04 | The gate's memory peak is sampled, while the kernel's exact peak is thrown away | acc | medium | M | yes | physFootMB is too noisy for a 5% comparison. Aliasing as the cause is unproven, and mlxPeakMB is the exact signal. |
| #17 | gap-1-07 | The UI benchmark never pins the model variant | acc | medium | M | yes | With Quality installed, AV-17(2) would publish Quality numbers under a hardware-only label. |
| #18 | ui-responsiveness-02 | The watchdog discards heartbeats still queued at session end | acc | medium | S | no | Stall maxima are biased low at the generation boundary in about 14% of macOS takes. |
| #19 | gap-1-02 | Records and the gate baseline carry no tier or policy identity | acc | medium | S | no | The gate baseline could be seeded from forced-floor rows without anyone noticing, and a record cannot prove its tier. |
| #20 | generation-telemetry-sidecar-prune-vs-matrix | The default 58-take matrix can never publish | eff | medium | S | no | A full default matrix loses its first 10 sidecars and fails publication, which wastes a consented run. |
| #21 | ui-bench-publication-validation-retry-loop | Validation reruns up to 60 times | eff | medium | S | no | Every deterministic failure costs 60 × (checker time + 1 s) and loses earlier output. |
| #22 | ui-bench-publication-lineage-key-overspecified | The comparison key almost never matches | acc | medium | M | no | 39 of 48 comparable UI records have no baseline and no deltas. Deltas are display-only, so no gate is lost. |
| #23 | gap-1-09 | Key fragmentation, and fixes after the re-seed orphan the M6 baselines | both | medium | M | no | Deltas disappear exactly when engine code changes, and any fix after the re-seed starts an M6 lineage with no baseline. |
| #24 | memory-probes-routine-trim-as-pressure | A routine cache clear is scored as memory pressure | acc | medium | S | no | Every take carries a pressure warning, so the status carries no information. No failure condition is weakened. |
| #25 | memory-probes-retention-low-power | The retained-memory gate only catches large leaks | acc | medium | S | yes | Leaks under about 205 MB per take on the Mac, or 307 MB on the iPhone, pass. |
| #26 | gap-1-05 | retained-memory-v1 misbehaves on the M6 | acc | medium | S | yes | The M6 limit doubles to 819 MB, and the metric becomes retained memory plus cache. |
| #27 | generation-telemetry-overhead-off-arm-not-off | The overhead lane's "off" arm is not off | acc | medium | M | yes | Today's verdicts are probably right, but the "off constructs no sink" contract is false and future costs behind the switch would be invisible. |
| #28 | ui-bench-publication-busy-host-published-canonical | UI records ignore host load | acc | medium | S | no | One canonical cold take ran at load 14.33 (RTF 1.359 against about 0.63). Load is not kept per take. |
| #29 | ui-bench-publication-unpinned-seeds | UI benchmark takes use random seeds | acc | medium | M | yes | Adds length variance to short design and clone cells. 2 run-ons among 108 warm takes enter the timing data. |
| #30 | ui-bench-publication-sample-allocation | Takes are spread evenly across cells | both | medium | M | yes | Short cells cannot resolve regressions under 5-12%, and cold cells are single samples. |
| #31 | ui-bench-publication-per-take-harness-overhead | Per-take harness overhead is unmeasured | eff | medium | M | yes | About 5-9.5 s of harness time per take. Each run also spends about 208 s waiting on captured playback and 75-100 s typing. |
| #32 | ui-responsiveness-03 | Accessibility queries run inside the confirmatory windows | acc | medium | M | yes | Ceilings include an unmeasured share of harness cost, so harness changes can look like app changes. |
| #33 | ui-responsiveness-04 | Model warms land inside measured windows | acc | medium | S | yes | sidebar-navigation measures tier-dependent warm churn that nothing records. Hitch inflation is unproven. |
| #34 | ui-responsiveness-06 | Ceilings are too loose to catch realistic regressions | acc | medium | M | yes | Only a hitch regression of about +100% triggers a warning. |
| #35 | ui-responsiveness-10 | The main-thread proxy cannot see render-server hitches | acc | medium | L | yes | GPU and compositor hitches are invisible, so the glass-off decision cannot be validated. |
| #36 | gap-1-03 | TTFC, chunk cadence and cold RTF differ by tier policy | acc | medium | S | yes | Tier policy alone shifts cold RTF by about 6-8% and warm TTFC by about 15-22%, so M2-to-M6 differences mix policy with hardware. |
| #37 | gap-1-08 | The delivery envelope is sized for the floor but measured in a way that cannot qualify it | both | medium | M | yes | M6 runs cannot qualify a floor-sized envelope, and the ASR footprint ceiling is a no-op. |
| #38 | gap-4-03 | The supervisor spawns processes on every tick | both | medium | M | no | Spikes between `ps` samples (about 52 ms apart) are invisible, and `ps` failures silently lower coverage. |
| #39 | gap-4-06 | Per-take adherence flags saturate the warnings | acc | medium | M | yes | 460 of 902 takes are flagged and 96 of 108 records warn, so a regression is invisible. |
| #40 | gap-4-07 | Features in Hz and seconds were calibrated on one speaker and one text | acc | medium | L | yes | Pass rates plausibly depend on the speaker and the script length. The size of the effect is unmeasured. |
| #41 | gap-4-08 | The prosody gate is inert but composes as PASS | acc | medium | M | no | "prosody: pass" claims more than the gate can observe: one flag in 902 takes. |
| #42 | audio-language-eval-lid-control-unproven | The language channel is weaker than the records claim | acc | medium | M | yes | Gate outcomes hold because WER rejects wrong-language output. The risk is misattribution (about 38 takes in 4 records). |
| #43 | audio-language-eval-wer-segmentation-artifact | WER counts word-boundary merges as errors | acc | medium | M | no | A correct German take uses 0.138 of the 0.15 budget, so one more merge fails it. |
| #44 | audio-language-eval-cohort-single-witness | The diagnostic cohort runs without whisper | acc | medium | S | yes | The cohort PASS that accepted corpus v2 rests on one ASR family. |
| #45 | memory-probes-ios-lane-polling-observer | The iOS memory lane copies the whole tree and cannot detect a jetsam | both | medium | S | yes | A jetsam or crash is reported only after 900 s, unclassified. Each poll copies a growing tree. |
| #46 | gap-2-01 | The darwin-only tests never run in any scheduled job | acc | medium | S | no | No scheduled coverage, and the documented promise is false. The coverage actually lost is narrow. |
| #47 | gap-2-02 | The darwin tests call real host probes | both | medium | S | no | About 35-40 s of macOS CI per push, and a unit test that queries the paired iPhone. |
| #48 | gap-3-2 | In-process timings are never reconciled with signposts | acc | medium | M | yes | Drift between trace and JSONL timings, and the observer's lag, are both unmeasured. |
| #49 | gap-3-3 | v9 MLX instants are computed backwards | acc | medium | S | yes | Same as #62: the materialization duration is zero under every policy. |
| #50 | gap-3-5 | There is no low-perturbation witness profile | acc | medium | M | yes | Profiled throughput is 29-80% below unprofiled. The metrics are labelled honestly, but no witness mode exists. |
| #51 | gap-3-6 | The iOS memory profile keeps standalone VM Tracker | acc | medium | S | yes | The iPhone acceptance lane runs with about 10× normal sampler lateness and contaminated throughput. |
| #52 | gap-3-7 | The iOS profile records its full window, then sleeps 10 s | both | medium | M | yes | Tens of idle seconds per profile (60-89% idle samples), and truncated takes go undetected. |
| #53 | engine-bench-05 | A missing model aborts the gate late, without a verdict or a finished ledger | both | low | S | no | About 3-4 minutes lost per occurrence and an unfinalized ledger. The gate still fails safe. |
| #54 | engine-bench-03 | INCONCLUSIVE is reported as FAIL, and host load is judged from one sample | acc | low | S | no | Inconclusive runs fail closed, contrary to release.md:89-90. Outside load at bench time goes unchecked. |
| #55 | engine-bench-07 | The first take after a model load is slower but counted as warm | acc | low | S | yes | Medians absorb most of it (clone/short +1%, gate +0.2%). Single-take lang-bench RTF reads about 4% high. |
| #56 | engine-bench-09 | The iOS gate copies the whole diagnostics tree every 10 s | both | low | S | yes | The iOS gate RTF is an -Onone smoke number. Full-tree polling matters more in the memory and clone waits. |
| #57 | engine-bench-10 | The gate repeats test work | eff | low | S | no | About 20-24 s per gate from a duplicate test bundle, and up to about 67 s from pytest. |
| #58 | generation-telemetry-rtf-excluded-startup-unpublished | The startup time RTF excludes is never published | acc | low | S | no | Work moved into the prewarm window would lower gate RTF unnoticed. |
| #59 | generation-telemetry-ttfc-observer-and-first-chunk-probe | ttfcMS means different things on macOS and iOS | acc | low | M | yes | One key carries two definitions. The observer's effects are unproven and small. |
| #60 | generation-telemetry-decode-wall-date-and-span | tokensPerSecond uses Date() | acc | low | S | yes | Violates native.md:70, with a 0.6% numeric effect. The drain key is dead. |
| #61 | generation-telemetry-hot-loop-ms-quantization | Per-step times are rounded to whole milliseconds | acc | low | S | yes | Sub-ms substages read 0, and "unattributed" hides the untimed token read. No published metric uses these keys. |
| #62 | generation-telemetry-v9-synthesized-mlx-instants | The v9 MLX instants are invented | acc | low | S | no | The sidecar asserts nanosecond MLX timings it never observed. Nothing reads them yet. |
| #63 | generation-telemetry-overhead-lane-statistics | The overhead lane's statistics are weak | both | low | M | yes | Verdicts near the 5% limit are unreliable, and a loaded host has no inconclusive outcome. |
| #64 | generation-telemetry-thread-count-port-leak | Thread ports are never released | both | low | S | no | A small, bounded leak in telemetry-on processes. No effect on published metrics. |
| #65 | memory-probes-probe-cost-threads | Thread ports leak and the probe's own cost is unmeasured (duplicate of #64) | both | low | S | no | Same leak as #64. The capture cost on the critical path is unmeasured; the only legacy hint is about 2%. |
| #66 | memory-probes-coverage-metric | The ≥95% coverage rule measures timer health only | acc | low | S | no | The qualification criterion is effectively always 1.0 and says nothing about whether the peak was caught. |
| #67 | memory-probes-marking-peak-blind-window | The marking zero-peak check uses sampled peaks | acc | low | S | no | Only a large, brief marking spike could slip through. |
| #68 | memory-probes-ios-gate-thresholds | The iOS memory gates ignore the device | acc | low | S | yes | Only the headroom gate can fire before jetsam. The Python and Swift thresholds differ by about 108-125 MB. |
| #69 | memory-probes-instruments-memory-profile-empty | The Instruments memory profile publishes no memory data | both | low | M | yes | A rarely run lane deletes its only unique evidence. |
| #70 | memory-probes-field-report-dedupe | The MetricKit report double-counts copies | acc | low | S | no | Counts inflate only when the report points at a parent of several lane directories. The report is advisory. |
| #71 | ui-bench-publication-trend-noise-and-ttfc | HISTORY reports noise as a direction | acc | low | S | no | Readers see noise as faster or slower, and UI first-chunk latency never appears. |
| #72 | ui-bench-publication-single-record-public-numbers | Public short-cell numbers come from one run | acc | low | S | no | Three public short-cell values can move by 0.02-0.08 at a repin with no code change. |
| #73 | ui-bench-publication-rebuild-index-double-validation | The registry is validated twice | eff | low | S | no | About 2 s per publication and per gate check, growing with the registry. |
| #74 | ui-bench-publication-capture-pacing-and-take-identity | Capture availability changes pacing | acc | low | S | yes | A pacing effect of a few percent on TTFC is plausible but unproven. |
| #75 | ui-bench-publication-build-skip-fingerprint-scope | The build skip almost never fires | eff | low | S | no | A narrower key would have skipped 3 of 13 builds, each well under a minute. |
| #76 | ui-bench-publication-derived-data-stored | Records store derived data | eff | low | M | no | Repository churn only. The 256 KiB cap is not binding. |
| #77 | ui-responsiveness-08 | M2 ceilings will be applied on the M6 | acc | low | S | no | Until AV-17 step 3, M6 records carry M2 verdicts with no marker. |
| #78 | gap-1-10 | ui-perf declares an M2 calibration profile that no code checks (duplicate of #77) | acc | low | S | no | Same as #77. The documented derivation rule has no tool. |
| #79 | ui-responsiveness-05 | Hitch per second is diluted by harness waiting | acc | low | S | no | Conceptual only. No hidden regression is shown. |
| #80 | ui-responsiveness-07 | The probe watchdog's summary is never published | both | low | M | yes | Dead instrumentation, with a latent contract violation if only the flush were fixed. |
| #81 | ui-responsiveness-09 | p95 comes from bucket edges, and maxGap is not clipped to the window | acc | low | M | yes | p95 is inert. maxGap can reach up to one block past each window edge. |
| #82 | ui-responsiveness-11 | Most perf-lane time is setup | eff | low | M | yes | Minutes per counted session. The exact share is unknown until phases are recorded. |
| #83 | ui-responsiveness-12 | Signposts go unused, and the environment is rebuilt per chunk | both | low | S | no | Negligible cost. App cost and harness cost stay mixed in the History scenarios. |
| #84 | audio-language-eval-dropout-under-wer-granularity | A skipped phrase can pass | acc | low | M | no | A skip of 2-4 units without a silent gap passes. No instance exists in the evidence. |
| #85 | audio-language-eval-click-metric-per-sample | Click tolerance grows with take length | acc | low | M | no | A seam regression of about 1-10 clamps per second would pass. |
| #86 | audio-language-eval-pinned-auto-duplicates | Pinned and Auto pairs regenerate identical audio | both | low | M | yes | About 30% of iOS full-run takes (6-8 minutes per rare run). The duplication is a deliberate proof of Auto resolution. |
| #87 | audio-language-eval-ios-per-take-overhead | iOS lang-bench polls on a fixed 10 s timer | eff | low | S | yes | Only about 1.5-3 minutes per full run can be attributed to polling. |
| #88 | audio-language-eval-macos-fixture-drift | macOS lang-bench ignores the corpus fixtures | acc | low | S | yes | Every macOS Design take uses a different brief, and zh/ja Custom uses a non-native speaker. |
| #89 | audio-language-eval-whisper-evidence-copied-fields | Whisper evidence fields are copied or confounded | acc | low | S | no | A small timing bias and a check that can never fail. No verdict changes. |
| #90 | gap-1-04 | The routine cache clear reads as pressure on the floor (duplicate of #24) | acc | low | S | no | Floor records overstate pressure. M6 records will read "passed", which is correct. README.md:128 goes stale at the repin. |
| #91 | gap-2-03 | Evidence and fixture paths send the full macOS lane through CI | eff | low | S | no | About 12 avoidable macOS lane runs in 12 days, costing 3-5 minutes of latency each. |
| #92 | gap-2-04 | Research tests skip when shared libraries change | acc | low | S | no | CI and local routing disagree. Local checks and nightly catch it. |
| #93 | gap-2-06 | The local check never selects registry tests for benchmark schema changes | acc | low | S | no | An early local signal is missed. CI still runs the tests. |
| #94 | gap-2-07 | Validator tests read live records | both | low | S | no | The tests break if records are pruned, and they pull evidence pushes into the macOS lane. |
| #95 | gap-3-4 | Per-step integer-ms rounding biases the substage sums (duplicate of #61) | acc | low | S | yes | Biases two unconsumed diagnostic keys. The effect on "unattributed" is small next to the untimed token read. |
| #96 | gap-3-8 | Summary counts are misnamed | acc | low | S | no | Misleading, but nothing reads them. |
| #97 | gap-3-9 | The two CPU witnesses disagree on the -O Mac profile | acc | low | M | yes | An unexplained CPU-attribution inconsistency on the one -O Mac record. It cannot be diagnosed because the trace was deleted. |
| #98 | gap-3-10 | No GPU instrument in any lane | acc | low | L | yes | GPU busy and idle time is unmeasured. |
| #99 | gap-3-11 | Profile lanes skip the quiet-host check and record one warm take | acc | low | S | no | Matters only once profiles are cited as timing witnesses. |
| #100 | gap-3-12 | Trace export and hashing repeat work | eff | low | S | no | Seconds per profile, plus peak Python memory. |
| #101 | gap-4-04 | The ASR footprint ceiling is never evaluated | acc | low | S | no | Whisper's Metal memory is unmeasured, and the printed ceiling is misleading. |
| #102 | gap-4-05 | Post-exit recovery is judged on a host-wide percentage | both | low | M | no | Unqualified results are unattributed rather than proven false. |
| #103 | gap-4-09 | The clone identity lane cannot calibrate its bands | acc | low | M | yes | The lane is advisory and publishes nothing. |
| #104 | gap-4-10 | Delivery sweeps pay for cold takes, and sidecar joins are loose | eff | low | M | yes | About 9-10% of sweep time is wasted, and a stale sidecar can be accepted. |
| #105 | gap-4-11 | The neutral outlier test cannot fire | acc | low | S | no | The check cannot fire at n ≤ 7. |
| #106 | gap-4-12 | Small-sample statistics discard pairing | acc | low | S | no | Overhead verdicts carry no uncertainty. |

**Items found by the verifiers (V-1 to V-14)**
- **V-1:** Since b093b71e, the iOS UI-benchmark checker's per-take model-identity checks and its schema check sit inside the one-seed-per-mode loop (`check_ios_ui_benchmark.py:728-758`). They run only when a mode used more than one seed, and then only against the last row. The next iOS publication would skip per-take identity validation.
- **V-2:** Under `.pipelined`, the GPU wait is untimed. The first blocking read, the `nextToken` item read at `Qwen3TTS.swift:3759`, has no timer and no signpost, so per-step GPU compute lands in `qwen_token_loop_unattributed`. A token-read timer and signpost is the prerequisite for #12, #49 and #95.
- **V-3:** The harness hash (`benchmark_history.py:891-944`) leaves out the base test-case files `VocelloMacUITestCase.swift` and `VocelloiOSUITestCase.swift`, whose code runs inside the measured windows. A harness change such as b23d8a7e's extra Studio click therefore keeps the lineage.
- **V-4:** The iOS memory thresholds differ between Python and Swift. Python uses 5.2×1024 and 4.5×1024 MB (`benchmark_memory.py:1033, 1045`). Swift uses 5,200 and 4,500 MiB (`IOSMemorySnapshot.swift:326-327`, `IOSUnloadQuiescence.swift:59`).
- **V-5:** `require_quiet_host` runs for every `macos_test.sh gate` (`:1455-1458`), even without `QWENVOICE_GATE_BENCH`. The deterministic gate is therefore refused while an agent worktree is locked or the native lock is held, although only the bench needs a quiet host.
- **V-6:** On macOS the per-take stamp file is a fixed machine-wide path, `/tmp/vocello-bench-current-take.json` (`BenchRunContext.swift:70-75`), shared by every checkout. Two bench processes running at once would stamp each other's takes. Only the "lanes run alone" procedure prevents it.
- **V-7:** The summarizer checks baseline identity before host load (`summarize_generation_telemetry.py:1831-1844`). A loaded host with a stale baseline therefore reports BASELINE INVALID instead of INCONCLUSIVE.
- **V-8:** The UI timing lanes run the quiet-host preflight before build-for-testing (`ui_test.sh:307` against `:1493-1514`), so load from the build can leak into the first takes (#28).
- **V-9:** The website heading "A first-party engine, measured on the minimum Mac." (`website/src/sections/Engineering.jsx:122`) becomes false at the AV-17(2) repin unless the copy changes with the numbers.
- **V-10:** Loudness is never published. `QC_METRIC_MAP` (`scripts/lib/audio_qc.py:26-36`) drops rmsDBFS, peak, hot samples and trailing silence, although the Swift QC report carries rmsDBFS (`GenerationQualityReportProducer.swift:82-83`). A level regression above the −45 dBFS warning line is invisible in history.
- **V-11:** `find_neutral` (`bench_delivery_prosody.py:304-328`) silently falls back to a neutral take of a different length. The row records only the instructed take's length, so deltas can be cross-length with no marker. This is minor today, because delivery runs use one length.
- **V-12:** The supervisor's SHA-256 is bound into prepared compact adapter configs and their execution identity (`delivery_compact_model_adapter.py:112-118`, `prepare_delivery_compact_model_config.py:332-353`). Any supervisor fix (#7, #38, #102) invalidates cached compact and ASR results, so the fixes should land as one batch before AV-17(5).
- **V-13:** The locale bug is confined to the Python supervisor's regex (`delivery_resource_supervisor.py:149`). The awk load parse in `host_preflight.sh:29-34` handles fr_CA decimal commas, and the hw.model and hw.memsize parsers do not depend on the locale.
- **V-14:** Every canonical macOS UI record that publishes the new RTF definition (488a9ed0 through 379db820) comes from the XPC era. No canonical record exists on the in-process topology (628887c7, 2026-09-15).

Note on V-numbers: V-11 and V-13 are inferred from the verifiers' notes and are not certain. V-13 is cited nowhere else in this report. The split of V-5, V-6 and V-7 across the three engine-bench notes is also inferred, from the verifier's order and from section 4.1.

---

## 3. Findings by area

Each area first lists what is solid and should be kept. Its findings follow in this format: Evidence, Mechanism, Corrected impact, Corrected fix, Verify. Each finding's heading gives its kind, corrected severity, effort and consent flag, as in section 2.

### 3.1 Engine bench and gate

**What is solid (keep)**
- **RTF definition.**
  - It is implemented as native.md states. The monotonic stage recorder runs from prepare entry to `streamCompleted`, which is marked after the final WAV write and before the post-generation trim. Model load and prewarm are excluded.
  - The engine emits `requestWallSeconds` and `realTimeFactor`, and rtf.py mirrors them.
  - Legacy speedup records are kept apart by `rtfDefinition` and never enter the same statistic.
  - The CLI times its own wall figure with ContinuousClock and labels it as operator feedback only.
- **Frozen evidence.**
  - The gate bench freezes the exact ordered selection (`benchmark-evidence.json`) before any summary or comparison.
  - It uses an isolated runtime directory, collision-resistant run IDs and strict run-ID selection.
  - Build receipts bind optimization labels to the executable digest (`build_provenance.py`).
- **Baseline identity.**
  - It deliberately excludes source and executable digests, so a regression survives source changes.
  - It binds the hardware, the optimization, the matrix and corpus hash, the model artifacts, the telemetry and QC versions, and the RTF definition.
  - The verdict is warm-only. Missing cells, missing sample counts and worse QC all fail closed.
  - Widening the threshold by dispersion is the right idea; only the estimator is weak (#5).
- **Determinism where seeded.** Sampling is request-local, and seeded lanes are token-exact: mac-memory-qualification-20260915-165501 produced 73 tokens on each of 3 custom takes and 95 on each of 3 design takes. `--memory-qualification` pins its whole protocol, seed included.
- **Host and step controls.**
  - `require_quiet_host` also refuses while another process holds the native lock or an agent worktree is locked.
  - The required-step ledger has fault injection.
  - The iOS `cmd_bench` already polls a sentinel-only file, so it does not disturb the take.
- **Corrections to the strengths list.**
  - The gate bench itself is not seeded (#13).
  - Part of the baseline identity is read from the installed tools at compare time, not from the evidence (#14).
  - The ledger is never finalized when a prerequisite helper exits the shell (#53).
  - The quiet-host check also blocks the plain deterministic gate (V-5).
  - The telemetry-overhead lane's "verbose ≈ off" result rests on an off arm that still runs the recorder (#27) and on unpaired medians of 6 (#63). In the July record, lightweight was 2.3% slower than off.

**#5 engine-bench-01: the gate threshold uses within-run spread, and the memory threshold is a flat 5%** (acc, high, M, consent: yes; related: #16)
- **Evidence:**
  - `summarize_generation_telemetry.py:1228-1241` sets the threshold to max(5%, 3 × baseline MAD/median) when the baseline has n ≥ 3. The MAD is computed at `:1036-1041`.
  - `:1373-1400` applies it to RTF and physFootMB. tok/s and TTFC keep a flat 5%. The current run's own spread is never used.
  - The committed baseline (`benchmarks/baselines/mac-gate-bench.json:63-66`) gives an RTF threshold of 5.19%. Its physFootMAD is 0.047 MB, so the footprint threshold is a flat 5%.
  - `git show 8d2b013d` shows physFootMAD dropping from 250.89 to 0.047 MB when the baseline was re-saved. The b88d6d03 message records that a flat 5% footprint threshold once failed an identical-source run at +10.5%. The baseline is back in that state.
  - Collapse is common. In 102 three-warm-take cells, physFoot MAD/median is below 0.2% in 41% of cells, and so is RTF MAD/median.
  - Correction: the finder's between-run RTF examples (13.1% and 9.7-11.3%) compared different commits, an optimisation-stage series and an A/B. projectInputHash does not hash engine source (`benchmark_history.py:952-956`). Grouped by identical clean commit, warm-median RTF spreads are 0.7-2.4% and footprint spreads 2.3-12.8%.
- **Mechanism:** The MAD of three consecutive takes measures jitter inside one session, while footprint varies mostly from session to session. With n=3 the MAD is often near zero, so the threshold falls to the 5% floor whatever the real variability.
- **Corrected impact:**
  - The real defect is memory. When AV-17 re-seeds on the M6, a baseline whose footprint MAD is near zero brings back the documented false REGRESSION: identical-source drift of 2-13% (10.5% in the gate cell) against a 5% threshold.
  - The gate fails rather than passes, which is the safe direction. But each false failure costs another consent-bound rerun and weakens the gate that CONV-21 relies on for MLX dependency moves.
  - On RTF, identical-source medians vary by about 1-3%, so false alarms at 5.19% are rare. Catching only about half of +5% regressions is what any 5% threshold does; it is a sensitivity limit, not a bug.
- **Corrected fix:**
  1. Floor the dispersion term for each metric: a footprint threshold of at least about 12-15%, or make physFootMB informational.
  2. Add `mlxPeakMB` to `build_summary` and compare it with a tight threshold as the memory-regression signal. It is the exact per-request MLX peak: reset at `NativeEngineRuntime.swift:773`, maxed over snapshots at `GenerationTelemetryRecord.swift:720`, and published through `benchmark_memory.py:762`. Its MAD/median is below 0.2% in 99% of cells.
  3. Seed the M6 baseline from at least 3 identical-source gate runs, and derive the threshold from the spread between runs. That may allow an RTF threshold of about 3%.
  4. Print the effective thresholds in bench.log.
  5. Moving to 5 warm takes is optional. If adopted, amend release.md:89, the CONV-21 gate text and benchmarking-procedure.md in the same change (4.4).
  6. Land all of this before the AV-17 re-seed.
- **Verify:**
  - Unit tests with no models: replay the committed gate record and the b88d6d03 medians through the new comparator. Expect no false regression, and a synthetic +6% RTF must still be flagged.
  - Then run at least 3 seeded identical-source gate runs in the AV-17 session (4.2).

**#13 engine-bench-02: the gate bench runs without a fixed seed** (both, medium, S, consent: yes)
- **Evidence:**
  - `macos_test.sh:1224-1226` calls `vocello bench` without `--seed`. `GenerateCommand.swift:267-273` then returns nil, and `Contracts.swift:150` draws `UInt64.random`.
  - In mac-gate-bench-20260912-234613 the warm takes produced 87, 83 and 85 tokens (6.96, 6.64 and 6.80 s of audio), and the cold take produced 77.
  - Seeded runs are token-identical: mac-memory-qualification-20260915-165501 produced 73 tokens on each of 3 custom takes and 95 on each of 3 design takes. `--seed` applies to every take (`BenchCommand.swift:1635`).
  - None of the 185 engine and memory-qualification records carries a seed. It only feeds matrixHash (`publish_benchmark_history.py:1491-1496`), although `schema-v2.json:789` already allows a take-level `seed`.
  - Across 102 cells, the range of audio length within a cell has a median of 4.0% and a p90 of 20.8%.
- **Mechanism:** Each warm take is a different token sequence and a different audio-QC draw. The gate's QC check (`macos_test.sh:1232-1248`) fails on any fail verdict, and QC defects depend on the seed.
- **Corrected impact:**
  - The extra RTF noise is modest, under 1%: about 0.3 s of fixed finalization over about 3.4 s of wall time, with about 4% variation in audio length.
  - The larger problem is that the gate's audio-QC outcome is a random draw that cannot be reproduced from the record.
  - An unseeded gate also contradicts release.md:95 (fixed seeds).
  - Adding the seed changes matrixHash and therefore the baseline identity. It must land before the AV-17 re-seed, or it forces a second consent-bound re-baseline.
- **Corrected fix:**
  1. Pass `--seed 19790615` (the memory-qualification seed) in run_gate_bench.
  2. Publish the seed as run.seed or take.seed; the schema already has a take-level field.
  3. Add a determinism check: seeded warm takes must share generatedTokens. A token difference from the baseline is reported as "engine output changed". It is informational, not a perf verdict, because a legitimate engine change can alter tokens.
  4. Land it before the AV-17 re-seed.
- **Verify:** Two consecutive seeded gate runs give identical generatedTokens, audio seconds and WAV digests for every take (consent-bound; part of 4.2).

**#14 engine-bench-06: the printed repair command produces a baseline the gate rejects** (both, medium, S, consent: yes)
- **Evidence:**
  - The repair hints at `macos_test.sh:1274` and `:1281`, and at benchmarking-procedure.md:806, omit `--evidence-manifest`. `:1281` also omits `--engine-only` and `--run-id`. Only the doc block at benchmarking-procedure.md:784-787 shows the correct command.
  - Without the manifest, `baseline_document` writes a baseline with no identity (`summarize_generation_telemetry.py:1244-1252`). `baseline_cells` then rejects it under `--require-baseline-identity` (`:1283-1287`), which the gate passes (`macos_test.sh:1271`).
  - The save at `:1562-1566` has no host-load, thermal or sample-count checks.
  - `host_identity` (`:1189-1205`) takes only `mac_ver()[0]` and the first line of `xcodebuild -version`, which drops the Xcode build (27A266a) and the OS build. It is also called at save time, so a baseline saved from older evidence after a toolchain update gets the wrong identity.
  - The evidence already carries toolchain.xcodeBuild, swiftVersion and hardware.osBuild (mac-gate-bench-20260912-234613).
  - The baseline is bound to the M2 with macOS 26.6.2 and Xcode 26.6 (`mac-gate-bench.json:7-11`), so every gate bench on the M6 ends BASELINE INVALID. The gate record's comparison block has baselineRunID null and deltas {}.
- **Mechanism:** The hints were not updated when identity binding was introduced (fd3bb5d3). Seeding happens outside the gate, and the identity mixes evidence fields with a live probe of the host.
- **Corrected impact:**
  - This affects the imminent AV-17 re-seed and every CONV-21 toolchain move. Following the printed hint wastes at least one full consent-bound gate run.
  - A baseline can also be saved from a loaded run.
  - Beta toolchains that share a marketing version share an identity.
- **Corrected fix:**
  1. Print the exact command with the run's own paths: `--run-id`, `--evidence-manifest`, `--engine-only` and `--save-baseline`.
  2. Add a governed seed mode, for example `QWENVOICE_GATE_BENCH_SEED=1`. It saves the baseline in the same run only when the host verdict is clean and every warm cell has n = 3, then reports "bench: BASELINE SEEDED" and publishes history.
  3. Build the identity from evidence fields (xcodeBuild, swiftVersion, osBuild) rather than live tools. Document that a new build number forces a re-baseline. This also removes an `xcodebuild -version` subprocess.
  4. Keep the baseline digest, the per-metric thresholds and the verdict in the gate evidence.
  5. Fix benchmarking-procedure.md:806 in the same change.
- **Verify:**
  - Unit tests with no models: the printed command round-trips (save, then compare on identical evidence exits 0), and a governed save refuses a loaded-host fixture.
  - The end-to-end seed is the AV-17 run.

**#15 engine-bench-08: the gate compares no latency metric** (acc, medium, S, consent: yes)
- **Evidence:**
  - ttfcMS comes only from the app row's frontend metrics and timings (`summarize_generation_telemetry.py:468-472, 499-501`). The gate runs `--engine-only` (`macos_test.sh:1270`), so the app lookup is empty (`:802-807`).
  - The baseline stores ttfcMS null in both cells, and `compare_summaries` skips a metric that is None on both sides (`:1382-1383`).
  - `firstChunkArrivalMS` is computed per run (`:573-577`) and per cell (`:768`) but is missing from `build_summary` (`:1072-1097`).
  - In the gate record, the CLI-observed TTFC of the warm takes is 501, 438 and 426 ms. Across macOS engine cells, TTFC MAD/median has a median of 0.83% and a p90 of 4.2%.
- **Mechanism:** The comparison loop lists a metric that is never filled in for the only lane that runs the comparison.
- **Corrected impact:**
  - The only automated perf gate, which CONV-21 uses for MLX dependency moves, has no latency metric. A start-up or first-chunk regression is caught only if it pushes total RTF past about 5%.
  - This also leaves the startup-exclusion blind spot of #58 unguarded.
  - Because warm#0 skews TTFC (#55) and the spread between runs is unmeasured, a flat 5% TTFC threshold would be noisy.
- **Corrected fix:**
  1. Add `engineFirstChunkMS`, the median of chunkTimeline[0].arrivalMS, to `build_summary`. The name marks it as engine-side (native.md:71-74).
  2. Compare it with a floored threshold of 10% or more, or with one based on the spread between runs, once the gate is seeded (#13).
  3. Include it in the AV-17 re-seed, so no second re-baseline is needed. App-level TTFC stays with the UI lanes.
- **Verify:** A unit test with fixtures taken from the committed gate record, then the consent-bound re-seed.

**#16 engine-bench-04: the gate's memory peak is sampled, while the kernel's exact peak is thrown away** (acc, medium, M, consent: yes; related: #3, #5)
- **Evidence:**
  - `IOSMemorySnapshot.swift:189-212` returns only resident, phys_footprint and compressed. The SDK struct also carries `ledger_phys_footprint_peak` (`mach/task_info.h:376`).
  - The cadence is 500 ms on floor8GBMac and iPhone and 250 ms on 16 GB Macs (`SemanticTypes.swift:1024-1037`). The peak is the maximum over samples (`NativeTelemetrySampler.swift:925-933`).
  - In 93.1% of 1,953 M2 engine-generation takes, the peak lies within 60 ms of a 500 ms multiple.
  - Correction: the claim that sampling on this grid explains the swings is not demonstrated.
    - The baseline run's three warm peaks agreed within 0.05 MB.
    - In mac-memory-qualification-20260915-165501, seeded design takes #1 and #2 both peaked at 2,571 MB. The 3,246 MB value is the first take after the cold take, not random aliasing.
    - mlxPeakMB's MAD/median is below 0.2% in 99% of 102 cells, against 41% for physFoot.
- **Mechanism:** A peak between ticks is caught only when a sample happens to land on it. But most footprint noise comes from memory outside MLX's allocator, or from how the OS accounts for it (for example compression on the 8 GB host), not from allocation differences.
- **Corrected impact:**
  - The sampled physFootMB is noisy and cannot support a 5% comparison (#5). Blaming that noise on aliasing is unproven, so a ledger peak alone may not reduce the spread between runs.
  - The ledger peak is a process-lifetime maximum. In the gate's single process (one cold take plus 3 warm), it is exact only for a take that sets a new maximum.
  - rusage `ri_interval_max_phys_footprint` is public (`sys/resource.h:324`), but its reset call is not in the SDK.
- **Corrected fix:**
  1. First, and cheaply: add mlxPeakMB to the gate summary and compare it tightly (#5, part 2).
  2. Give physFootMB a dispersion floor.
  3. Optionally, read `ledger_phys_footprint_peak` at sampler start and stop from the same task_info call. Publish it as a run-level exact process peak, labelled as a per-process lifetime maximum and never as a system peak (native.md:119). #3 part 1 adds the same fields.
  4. Before claiming a benefit, measure whether it reduces the spread between runs.
- **Verify:**
  - A deterministic unit test: a synthetic allocation spike between ticks gives a ledger peak at or above the sampled peak.
  - Across the seeded AV-17 gate runs, compare the between-run spread of the ledger peak, mlxPeakMB and the sampled peak.

**#53 engine-bench-05: a missing model aborts the gate late, without a verdict or a finished ledger** (both, low, S, consent: no)
- **Evidence:**
  - `macos_test.sh:1218-1222` (the cli-optimized build, the model check and the source snapshot) runs only at step 5, after steps 0-4.
  - `_test_models_die` calls `exit 1` (`scripts/lib/test_models.sh:54`), and `require_mac_benchmark_models` uses it (`:196-210`). `capture_benchmark_source` calls `die` (`macos_test.sh:53-58`).
  - `required_step_run` runs the step in the same shell (`required_steps.sh:15-31`), and cmd_gate has no EXIT trap, so the `|| return 1` never runs.
  - The untracked M6 artifact `build/artifacts/macos/gates/gate-mac-gate-20260924-231721` matches:
    - verdict.txt ends at "crashes: PASS";
    - required-steps.json has status "running" and completedAt null, and benchmark-validation and history-publication are missing;
    - bench.log ends with "[error] selected benchmark models are not ready", after 197 s of earlier steps plus a cli-optimized rebuild.
  - The bench also runs after an earlier step has failed: `macos_test.sh:1352-1359` does not check `overall`.
  - `publish_benchmark_history.py verify-hardware` exists (`:3775`), so a preflight is feasible.
- **Mechanism:** Prerequisite checks that exit the process run inside a ledger-wrapped function, and the cheap checks come after slow deterministic steps.
- **Corrected impact:**
  - This is a one-off failure mode, typically on a new host or with missing models. Each occurrence wastes about 3-4 minutes and leaves an unfinalized ledger and no GATE line.
  - The direction is safe, since the gate did not pass.
  - Running the bench after a failed step wastes model and build time, but it still leaves diagnostic numbers in bench.log.
- **Corrected fix:**
  1. When `QWENVOICE_GATE_BENCH=1`, check the prerequisites before step 0: models present, verify-hardware, and a dry check of the baseline identity that says up front when the comparison will be BASELINE INVALID.
  2. Call the helpers that can exit inside a subshell, so failures return and the ledger is finalized.
  3. When `overall` ≠ 0, skip the bench by leaving its step unrecorded; finalize then marks it missing and failed. Do not add a "skipped" status, because the ledger accepts only passed and failed (`required_step_ledger.py:317`).
- **Verify:** With a data directory that lacks the model, the gate stops within seconds with a preflight failure, and the verdict and a finalized ledger are present. Use the existing required-step fault injection; no model run is needed.

**#54 engine-bench-03: INCONCLUSIVE is reported as FAIL, and host load is judged from one sample** (acc, low, S, consent: no; see V-5, V-7)
- **Evidence:**
  - `require_quiet_host` runs once, at `macos_test.sh:1455-1458`. In the M6 run the bench step began 197 s later.
  - `hardware_context` keeps only `environments[0].loadAverage1Minute` (`publish_benchmark_history.py:729-732`). That is the cold take, which the verdict never compares. Per-take load is emitted only on the telemetry-overhead path (`:2856-2861`), although `NativeTelemetrySampler.swift:746` captures the environment at the start of each take.
  - `host_load_verdict` (`summarize_generation_telemetry.py:1208-1225`) treats a run as loaded only above 2× the core count and never checks lowPowerMode.
  - All 284 macOS records have load 1.28-14.38, nominal thermal state and lowPower false. The inconclusive rule has never fired.
  - Exit 3 maps to `return 1` at `macos_test.sh:1276`, and then to "bench: FAIL" and GATE: FAIL. release.md:89-90 says an inconclusive run is never pass or fail.
  - Corrections:
    - "Stale" is overstated. release.md:112-113 deliberately judges the run from its own load sample, taken at the start of the cold take, seconds before the warm takes. A 1-minute average covers them.
    - The finder's example of a run accepted at 1.8× the core count is a UI benchmark record, which host_load_verdict never judges.
    - The finder missed that this one sample includes the load of the gate's own build and test steps just before it.
- **Mechanism:** One load sample is taken right after the gate's own heavy work, and exit 3 collapses into a generic failure.
- **Corrected impact:**
  - Low today. An inconclusive result fails closed: bench.log prints INCONCLUSIVE, but verdict.txt and the exit code say FAIL, contrary to release.md:89-90.
  - The parallel-agent and native-lock checks are not repeated at bench time. Only the procedure (lanes run alone) protects the bench.
  - Low power mode is unchecked, but it has never been seen on the benchmark Mac minis.
- **Corrected fix:**
  1. Map exit 3 to "bench: INCONCLUSIVE", with its own gate status and exit code. The ledger accepts only passed and failed (`required_step_ledger.py:317`), so either record the step as failed with a reason or extend the ledger schema.
  2. Re-run `require_quiet_host` inside run_gate_bench after the cli-optimized build, with a short settle poll.
  3. Record per-take loadAverage1M for engine takes, and judge the maximum over the warm takes. The schema already allows the field (`benchmark_history.py:387`).
  4. Add lowPowerMode to host_load_verdict.
  5. Calibrating the load threshold is optional.
- **Verify:**
  - Unit tests of host_load_verdict with multi-take fixtures, including a lowPowerMode case.
  - Required-step fault injection for the exit-3 path through the verdict file and the ledger.

**#55 engine-bench-07: the first take after a model load is slower but counted as warm** (acc, low, S, consent: yes)
- **Evidence:**
  - `BenchCommand.swift:459-465` loads the Clone model without a prewarm. Its comment gives a "seed-consuming warm-up take" as the reason, which is outdated: every take gets the same explicit seed, and sampling is request-local (native.md:48-49).
  - mac-clone-speed-20260919-044640, clone/speed/short, warm#0 against the next warm takes:

    | Metric | warm#0 | Later warm takes |
    |---|---|---|
    | prewarmMS | 673 | 0 |
    | Finalization | 511 ms | 123 ms |
    | RTF | 0.971 | 0.778 and 0.793 |
    | TTFC | 1,728 ms | 756 ms |

  - `rtf.py:32-36` excludes load and prewarm from RTF, so the +24% comes from finalization and page faults. TTFC does include the prewarm.
  - How often warm#0 is the slowest take, across standard-RTF macOS three-warm cells:
    - 48% of all cells (mean +2.0%);
    - 93% of first-after-load cells (15 cells, mean +8%);
    - +1.4-5.4% in the custom and design first-after-cold cells;
    - +1.5% in the gate's one standard record.
  - Each lang-bench cell is a fresh process (`macos_test.sh:945-964`, with the preload at `GenerateCommand.swift:141-142`), so every take is its process's first generation: 5,410 page faults, against about 1,800 in steady state.
  - Correction: `warmState` means the model was resident at request start (`BenchCommand.swift:427-428`). A lang-bench take with modelLoadMS 0 is therefore warm by definition, and the label is not false.
- **Mechanism:** First-use costs (prewarm, lazy finalization, page faults and allocator growth) fall inside a timed take.
- **Corrected impact:**
  - Medians of three mostly absorb the effect: it inflates the clone/short median by about 1% and the gate's by about 0.2%. But when #0 is systematically slow, the median effectively uses only two takes.
  - Single-take lang-bench RTF runs about 4% above steady state (0.6055 against about 0.58 for custom medium).
  - The same pattern is larger in the UI benchmark, where custom short warm#0 is +5.5-15.7% after the cold take (#30).
- **Corrected fix:**
  1. For Clone, call the existing `engine.prewarmModelIfNeeded(for:)` (`MLXTTSEngine.swift:941`) after loadModel. Cells and matrixHash stay unchanged. Optionally add a recorded warm-up take that is excluded from the medians.
  2. Mark lang-bench RTF as first-take in the record rather than restructuring the lane.
  3. Fix the outdated comment.
  4. Any cell change must land before the AV-17 re-seed.
- **Verify:**
  - If a warm-up take is added, unit tests that the summarizer excludes it.
  - Then, in a seeded run, no warm take reports prewarmMS > 0, and the clone warm#0 gap shrinks to pair noise.

**#56 engine-bench-09: the iOS gate copies the whole diagnostics tree every 10 s** (both, low, S, consent: yes; related: #45)
- **Evidence:**
  - `( cmd_pull "$dest" )` runs every 10 s at `ios_device.sh:2768`, and cmd_pull copies the whole diagnostics tree (`:803-813`).
  - cmd_bench was moved to a sentinel-only probe on 2026-09-11 (7c2f9af2; `:816-833`). `_gate_generation_check` was not, and neither were `wait_memory_qualification_sentinel` (`:871-880`) and `wait_clone_conditioning_sentinel` (`:933-939`).
  - Corrections:
    - The three ios-gate-bench records (07-13, 07-19 and 08-11) all predate that fix. They use the legacy RTF definition and have ttfcMS null, so the claim that published TTFC includes the copying is false.
    - The finder missed a build detail. `_gate_generation_check` calls plain `cmd_build` (-Onone), not `cmd_build --optimized` as cmd_bench does, and all three records say toolchain.optimization -Onone.
- **Mechanism:** Each devicectl copy of a growing tree competes with the take for storage I/O, CPU and thermal headroom on the phone.
- **Corrected impact:**
  - The iOS gate's RTF is not representative of the product, because the build is -Onone. The label is honest, and polling interference is secondary to that.
  - The full-tree polling matters more in the iOS memory-qualification and clone-conditioning waits, where it perturbs timing and I/O (#45).
  - The runs are rare and consent-bound.
- **Corrected fix:**
  1. Switch all three waits to a sentinel-only probe, plus a probe for the failure marker, and pull once at the end. Share the change with #45.
  2. Either publish the iOS gate as a smoke record with no RTF trend, or build it with -O.
  3. Pass a fixed seed.
- **Verify:** Stubbed shell-contract tests with no full pull inside the loops, then a consent-bound iOS gate run whose generation.log shows sentinel-only polls.

**#57 engine-bench-10: the gate repeats test work** (eff, low, S, consent: no)
- **Evidence:**
  - The gate runs VocelloCoreTests twice: in step 2 (`cmd_core_test`, `scripts/macos_test.sh:819-821`) and again in step 3 before Qwen3RuntimeTests (`:1068-1072`), costing 24 s in the M6 run.
  - Step 0 runs all 1,656 pytest tests (66.6 s), although `QVOICE_GATES=quick` and `--python darwin-only|selected|none` already exist (`check_project_inputs.sh:20-24, 96-101`).
  - bench.log is 1.76 MB of rebuild output.
- **Mechanism:** The test steps overlap, and no step reuses an earlier result.
- **Corrected impact:** About 20-24 s per gate from the duplicate bundle and up to about 67 s from pytest. The lang-bench saving the finder claimed is overstated: the record duration includes the hint gate and whisper ASR, and loading the model per cell costs only about 1.6-1.7 s.
- **Corrected fix:**
  1. Drop core-tests from the macos-gate workflows in `config/orchestration-contract.json`, or skip Core in cmd_test when it already ran.
  2. Use `--python darwin-only` or `QVOICE_GATES=quick` locally.
  3. Send the cli-optimized build output to its own log.
  4. Keep lang-bench's one process per cell.
- **Verify:** A gate run without the bench shows the same test counts in less wall time.

Also verified in this area: V-5, V-6, V-7. Grouping by projectInputHash does not mean the source is identical, so any between-run analysis must group by `source.commit` with dirty=false.

---

### 3.2 Generation telemetry

**What is solid (keep)**
- One monotonic stage recorder per generation drives RTF. The memory sampler shares its start clock, so samples line up with stage marks.
- `streamCompleted` is marked before the JSONL, v9 and raw-sidecar writes, so the cost of writing telemetry never enters RTF.
- First audio is measured when the chunk is ready: each chunk is evaluated and copied in the producer, and the last chunk is a synchronous barrier.
- The package's chunk timings are always on (`LoadedModel.swift:562/579/599`), so the producer runs the same code whether telemetry is on or off.
- The sampler anchors its schedule to the generation clock, counts missed deadlines instead of catching up in bursts, and records lateness. It is healthy: across 3,634 takes, one take missed deadlines, and minimum coverage is 97.2%.
- A terminal gate guarantees exactly one engine row per generation. Each take records its environment. Shipping builds with telemetry off skip the recorder, sampler and sink.
- Correction to the strengths list: `withMirroredSignpost` has no caller, so Instruments and JSONL timings are paired by hand (#48).

**#1 generation-telemetry-macos-inprocess-memory-double-count: macOS UI memory is counted twice** (acc, high, M, consent: no; duplicate: #2)
- **Evidence:**
  - `AppGenerationTimeline.swift:60, 303-315` still builds a macOS app-layer memory sampler.
  - `IOSMemorySnapshot.capture` reads the memory of whichever process calls it (`:156-183`).
  - `benchmark_memory.py:886-900` adds the engine and app resident, footprint, compressed and GPU values, and `check_macos_ui_bench.py:723` overwrites the engine-only values with that sum. The same checker already proves app and engine share one process ID (`:373-402`).
- **Mechanism:** When the XPC service was retired (628887c7, 2026-09-15), app and engine became one process, but the aggregator still sums two samplers of that process.
- **Corrected impact:**
  - Peak footprint divided by mlxPeakMB has a median of 1.02 over 914 earlier takes and 1.84 (1.56-2.03) over 14 takes in 8 later records: UI peaks of 4,482-5,776 MB against 2,166-2,653 MB in CLI records on the same Mac. Metal ratios of 1.103 and 1.052 appear on an 8 GB Mac.
  - Every memory field is inflated except mlxPeakMB.
  - The 8 affected records are focused or exploratory, and they started their own lineage because harnessHash covers benchmark_memory.py. The next canonical record, however, would publish doubled RAM on the README and website, and the first corrected record would look like a large false improvement.
  - The extra sampler also doubles the probe cost.
- **Corrected fix:**
  1. Fix the Python side first. When app and engine rows share a process ID, build one sample series and never sum. The preferred series is the union of both layers' samples with duplicate uptimes removed, which keeps the window from app submit to app terminal. Use the app sidecar only for coverage and boundary order.
  2. Optionally stop the macOS app memory sampler and keep the app layer for frontend timings only.
  3. In the same change, update native.md:71-73 and :119 (see 4.4), telemetry-and-benchmarking.md:436-437, ARCHITECTURE.md:1027 and the two-process test fixture (`test_benchmark_memory.py:512-540`).
  4. Do not rewrite the 8 records.
  5. If the comparison key is narrowed (#22, #23), keep benchmark_memory.py in the ui-generation path list or add an explicit aggregation marker.
- **Verify:** A test feeding two sidecars with the same process ID, expecting single-process peaks. An offline recompute of the 14 takes should give a ratio near 1.0. The next consented UI run should show the ratio near 1.0 and a Metal ratio below about 0.6.

**#27 generation-telemetry-overhead-off-arm-not-off: the overhead lane's "off" arm is not off** (acc, medium, M, consent: yes)
- **Evidence:**
  - `--telemetry off` sets only the telemetry mode variable (`BenchCommand.swift:238-239`). `installRuntimeDebugOverride` then runs unconditionally (`:248`) and sets `QWENVOICE_DEBUG=1` (`:1458`).
  - `TelemetryGate.resolve` turns telemetry on for `QWENVOICE_DEBUG` whatever the mode says (`TelemetryGate.swift:22, 72-86`).
  - So the off arm still runs the recorder (`NativeEngineRuntime.swift:760-762`), v9 observations (`GenerationOutputAdapter.swift:1701`), audio statistics (`:1767-1768`), the WAV SHA-256 (`:2066`) and the engine-record write (`:2117`, `:2371`).
  - The work plan's `writesSink` and `constructsSampler` flags are never read in production.
- **Mechanism:** One master switch controls both production debug overrides and telemetry persistence, and bench forces it on for every arm.
- **Corrected impact:** These costs are probably well under 1% of a 6 s take, so today's 5% and 10% verdicts are unlikely to be wrong. But the documented "off constructs no sink" contract (telemetry-and-benchmarking.md:84-86) is false and untested, and any future cost placed behind the telemetry switch will be invisible to the lane. The lane is local-only, so no committed record is affected.
- **Corrected fix:**
  1. Split the switches: either let an explicit off mode win over the debug flag, or give RuntimeDebugGate its own key.
  2. Build the recorder and write engine records only through `NativeTelemetryWorkPlan.writesSink`.
  3. Check the other consumers of the switch: BenchForceColdPolicy, BenchCodecReplay and the MLXTTSEngine codec trace.
  4. Make telemetry_overhead.py fail if the off arm leaves engine JSONL or v9 files behind.
  5. Add a Swift test that the bench off-mode environment resolves telemetry to false.
  6. Keep measuring the lane through the CLI observer, since the off arm will no longer have engine rows.
- **Verify:** The Swift test, then one consented overhead run that leaves no engine JSONL in the off arm.

**#20 generation-telemetry-sidecar-prune-vs-matrix: the default 58-take matrix can never publish** (eff, medium, S, consent: no)
- **Evidence:**
  - The sink keeps at most 48 sidecar files and prunes on every verbose write (`GenerationTelemetryJSONLSink.swift:35, 99-106, 199-226`).
  - A plain `vocello bench` runs 58 verbose takes (`BenchCommand.swift:200-206, 271-279, 432`; Option B in benchmarking-procedure.md:230-242).
  - Publication needs the exact sidecar for every take (`benchmark_memory.py:169-185`).
- **Mechanism:** A storage budget meant for ad-hoc diagnostics deletes evidence in the middle of a run.
- **Corrected impact:** A default full matrix, or a long delivery sweep, would run to the end and then fail publication after losing the first 10 sidecars. That wastes a consented run but produces no wrong data. No committed record has more than 32 takes, so this has not happened yet.
- **Corrected fix:**
  1. Bench already owns an isolated diagnostics directory that is cleared at the start of each run. Set a sidecar budget there of at least the planned take count plus probes, or turn pruning off in that directory.
  2. Refuse the plan before any model loads if it still exceeds the budget.
  3. Update benchmarking-procedure.md:896.
- **Verify:** A unit test writes 60 sidecars under bench scope and loses none, plus a test of the preflight refusal.

**#58 generation-telemetry-rtf-excluded-startup-unpublished: the startup time RTF excludes is never published** (acc, low, S, consent: no)
- **Evidence:** `requestWallSeconds` subtracts the model-load and prewarm windows (`GenerationOutputAdapter.swift:3199-3229`, `rtf.py:55-71`), and no field publishes how much was subtracted. `prewarmMS` maps to the explicit prewarm (`NativeEngineRuntime.swift:1608-1705`), not the prewarm window inside the request. One local warm row excluded 4,359 ms: RTF 0.386 against 8.373/10.4 end to end.
- **Mechanism:** The RTF contract excludes these windows but nothing reports or bounds their size.
- **Corrected impact:** A latent blind spot. A change that moves per-request work into the prewarm window would lower gate RTF unnoticed, because the engine-only gate has no TTFC. Committed warm takes exclude little today. Correction: the 3 records with prewarmMS carry 673-789 ms, not 0.
- **Corrected fix:** Publish new per-take keys `excludedStartupMS`, `modelLoadWindowMS` and `prewarmWindowMS`, computed by rtf.py. Do not change what `prewarmMS` means. Have the gate compare a warm take's prewarm window with the baseline and warn above a threshold.
- **Verify:** Publisher fixture tests and `rebuild-index --check`.

**#59 generation-telemetry-ttfc-observer-and-first-chunk-probe: ttfcMS means different things on macOS and iOS** (acc, low, M, consent: yes)
- **Evidence:** On macOS, the CLI stamps the first chunk from a low-priority (`.utility`) task, measured from submission (`GenerateCommand.swift:65-83`), and publishes it as ttfcMS (`publish_benchmark_history.py:702`). iOS memory qualification uses the engine's first-chunk mark, measured from prepare entry (`IOSDeviceDiagnosticsRunner.swift:1427-1429`). Warm values are about 380 ms on iOS and 410-800 ms on Mac.
- **Mechanism:** The same key carries two different measurements.
- **Corrected impact:** The inconsistency in definition is the real problem. Effects from the observer's priority or probe work are unproven and small. The spread the finder blamed on the observer comes from clone warm#0 paying the explicit prewarm (IQR/median 0.49-2.14). Without those cells, the p90 of TTFC IQR/median is 0.10.
- **Corrected fix:**
  1. Add a `ttfcDefinition` field and keep the two definitions out of shared statistics.
  2. Optionally stamp on the producer side from one clock, and run the observer at the submitter's priority.
  3. Move the chunk-0 probe work after the chunk is handed off; it is cheap.
  4. Report clone warm#0 TTFC separately.
- **Verify:** A test with a recording fake sink, then one consented bench.

**#60 generation-telemetry-decode-wall-date-and-span: tokensPerSecond uses Date()** (acc, low, S, consent: yes)
- **Evidence:**
  - `Qwen3TTS.swift:3327, 3976` time generation with `Date()`, which feeds the published tokensPerSecond (296 of 355 records). native.md:70 forbids Date() for throughput.
  - `decodeWallSeconds` counts only loop iterations (`:3597`), but the comment at `GenerationOutputAdapter.swift:3106-3107` says it includes the drain.
  - The drain key (`:2040-2046`) can essentially never be positive.
- **Mechanism:** The Date-based span and the loop-only sum are subtracted as if they covered the same interval.
- **Corrected impact:** A contract violation with a negligible numeric effect (0.6%). The speedup keys are consistent but mis-documented. The drain key is dead. RTF is unaffected.
- **Corrected fix:**
  1. Use ContinuousClock.
  2. Fix the comment to say "in-loop iterations only".
  3. Delete the drain computation, or time the tail as `qwen_tail_decode_ms`.
  4. Put any new span under a new key, not an existing one.
- **Verify:** A deterministic test with synthetic timings.

**#61 generation-telemetry-hot-loop-ms-quantization: per-step times are rounded to whole milliseconds** (acc, low, S, consent: yes; duplicate: #95)
- **Evidence:**
  - `Qwen3TTS.swift:6173-6185` rounds each step to a whole millisecond before summing.
  - `:3743-3745` hard-code the enqueue and wait split.
  - The token read at `:3759` has no timer (V-2).
  - In a local row, the code-predictor and sampling totals read 0, and 312 of 2,620 ms are unattributed.
- **Mechanism:** Spans under 0.5 ms round to 0 before they are added up.
- **Corrected impact:** Sub-millisecond substages are wrong, and "unattributed" mixes the GPU wait of the token read with transfer and sink time. The dominant stage (step eval, 87%) is still identified correctly, and no published metric uses these keys. The code predictor's true host time is at most about 80 ms, not about 400 ms. The per-step rounding does not reach "unattributed", and the per-step keys have no consumer.
- **Corrected fix:**
  1. Accumulate in nanoseconds and round once at export, adding `*_ns` keys.
  2. Time the token read and the flush and sink hand-offs as their own keys.
  3. Mark the synthetic enqueue/wait split as unavailable.
  4. Fix the comment at GenerationTypes.swift:199-208, and make Engine.swift round instead of truncate.
  5. Rank all of this below the token-read timer.
- **Verify:** An accumulator unit test (15 × 0.4 ms must sum to 6 ms).

**#62 generation-telemetry-v9-synthesized-mlx-instants: the v9 MLX instants are invented** (acc, low, S, consent: no; see #49)
- **Evidence:**
  - Because enqueue always equals eval and wait is always 0 (`Qwen3TTS.swift:3743-3745`), `mlxChunkInstants` (`GenerationOutputAdapter.swift:3066-3092`) always reports a materialization duration of 0, and `generatedAtNS` is computed backwards from rounded milliseconds.
  - `materializedAtNS` is the consumer's own clock reading (`:1617`).
  - Publication requires all four fields (`GenerationStreamingTelemetryV9Bridge.swift:129-134`), and the validator checks only arithmetic (`GenerationStreamingTelemetryV9.swift:429-435`).
- **Mechanism:** The values are derived just to satisfy the schema.
- **Corrected impact:** The sidecar asserts nanosecond MLX timings it never observed, under every policy. Nothing reads them yet.
- **Corrected fix:**
  1. Mark the four fields as unobserved by the producer, using a v9 minor version with a relaxed readiness check. Or have the package stamp real instants.
  2. Document `materializedAtNS` as the time the consumer received the chunk.
  3. Fix the comments that say timestamps are never invented.
- **Verify:** A bridge and validator unit test.

**#63 generation-telemetry-overhead-lane-statistics: the overhead lane's statistics are weak** (both, low, M, consent: yes)
- **Evidence:** `telemetry_overhead.py:278-341` measures 2 of every 4 generations. `:370-400` compares unpaired medians of 6 against fixed 5% and 10% limits, with no confidence interval and no inconclusive outcome. Host context is recorded but never judged, and the tests cover only identity and PCM digests.
- **Mechanism:** Small samples, pairing thrown away, and no model of noise.
- **Corrected impact:** The lightweight arm's spread (CV 2.3%) is half the 5% limit, and a loaded host has no inconclusive path, so verdicts near the limit are unreliable. The lane is local-only. Correction: in the July record, lightweight was 2.26% slower than off, not faster.
- **Corrected fix:**
  1. Keep the CLI observer as the only measured quantity.
  2. Pair each take with the off takes of the same rotation, and report a median ratio with a bootstrap 95% interval and the exact Wilcoxon test from `delivery_statistics`.
  3. Exit 3 when the interval straddles the limit or a take's load or thermal state exceeds the gate limits.
  4. Consider `--warm 5`.
  5. Add tests for the verdict. Do not interleave arms in one process.
- **Verify:** Tests with synthetic samples, then one consented calibration run.

**#64 generation-telemetry-thread-count-port-leak: thread ports are never released** (both, low, S, consent: no; duplicate: #65)
- **Evidence:** `NativeTelemetrySampler.swift:1245-1262` frees the task_threads array but never releases the thread port rights. This runs on every sample in both samplers.
- **Mechanism:** Every call adds references that are never released.
- **Corrected impact:** A small, bounded leak in telemetry-on processes only (dead names for exited threads, saturated reference counts), plus some extra per-sample work. No effect on published metrics. `proc_pidinfo` is not available in the iOS SDK.
- **Corrected fix:** Call `mach_port_deallocate` on each returned port, which works on both platforms. Optionally use `proc_pidinfo` behind a macOS-only check.
- **Verify:** A unit test that the port-name count stays stable over about 1,000 captures.

Also verified in this area:
- Clone warm#0 is conditioning-cold, and cell statistics do not separate it.
- The telemetry write is awaited inside the CLI take time (`GenerationOutputAdapter.swift:2116-2146`). Engine RTF excludes it; the CLI wall time includes it.
- `NativeTelemetryClock` truncates (`TimingExtensions.swift:51-53`) while the package rounds.
- The merger re-reads both JSONL files for every generation, which is small inside a per-run directory.

---

### 3.3 Memory probes

**What is solid (keep)**
- **Rebuilt, digest-bound peaks.** Every published peak is rebuilt from the raw sidecar and bound by SHA-256.
- **Strict checks.** The pipeline requires:
  - monotonic clocks;
  - exactly one start sample and one stop sample;
  - a full, ordered set of lifecycle boundaries;
  - separate coverage for memory, threads, headroom and Metal;
  - consistent process roles;
  - agreement between typed events and stage marks.
- **Exact MLX peak.** The MLX peak is reset for each request (`NativeEngineRuntime.swift:773`), so `mlxPeakMB` is exact and repeats exactly across identical seeded takes (median range 0.0 MB). It is the most trustworthy memory number available.
- **Evidence-driven design.** The marking check was moved to compare within one take after a control experiment. Retention reads the sample taken after the trim.
- **Lane hygiene.** The lanes use a fixed seed and matrix, a quiet host, trace attachment to the exact process, the VM Tracker guard on macOS, and digest checks before deletion. MetricKit is treated as advisory.
- **Correction.** `memoryContractVersion` is not part of `comparison_key` (`benchmark_history.py:1429-1470`). harnessHash already covers benchmark_memory.py, the sampler, the adapter, the runtime, AppGenerationTimeline and the policy. Every change in this area therefore separates lineages automatically, and a contract-version bump alone would separate nothing.

**#2 memory-probes-macos-inprocess-double-count** (acc, high, S, consent: no). Same defect as #1.
- **Area notes:** The memory-qualification lane is unaffected: it is engine-only, with ratios of 0.91-1.06. iOS is engine-only too (`check_ios_ui_benchmark.py:371`). Use the combined sample series (#1), and no contract bump is needed.

**#3 memory-probes-sampled-peak-undershoot: the sampler misses peaks while exact high-water marks go unused** (acc, high, M, consent: no; related: #4, #16)
- **Evidence:**
  - Sampling runs every 500 ms on the 8 GB Mac and the iPhone Pro (`SemanticTypes.swift:1024-1037`), from a low-priority task (`NativeTelemetrySampler.swift:753-783`).
  - Only three task_vm_info fields are kept (`IOSMemorySnapshot.swift:185-214`), although the 27.0 SDK struct also carries `ledger_phys_footprint_peak` (`task_info.h:376`), the graphics ledger (`:389-390`) and `limit_bytes_remaining` (`:399`).
  - The MLX allocator updates its peak on every allocation (`allocator.cpp:165-166`), and Metal-allocated memory is always at least MLX's active memory. So whenever the sampled Metal peak is below `mlxPeakMB`, the sampler provably missed the peak.
- **Mechanism:**
  - Allocations shorter than one tick fall between samples, and boundary samples sit at stage edges, not at the spike.
  - In 20260915-165501 the largest stage snapshot is 1,828 MB, against an exact peak of 2,501 MB.
  - This contradicts telemetry-and-benchmarking.md:398-399.
- **Corrected impact:**
  - How often the peak is missed:

    | Record set | Missed | Typical gap | Largest gap |
    |---|---|---|---|
    | Memory qualification, Metal peak | 119 of 173 takes | 188 MB | 868 MB |
    | Memory qualification, footprint peak | 70 of 173 takes | 182 MB | 768 MB |
    | iOS UI | 397 of 505 takes | 464 MB | not reported |
    | Mac engine | 987 of 1,951 takes | not reported | 1,104 MB |

  - Identical seeded takes differ by about 200 MB from sampling alone, so "RAM ±x%" history deltas of a few percent are noise.
  - No iOS gate crossing is hidden today (3,583 + 734 MB stays under the 4,608 MB warning), but the margin shrinks on the 5 GB floor device.
- **Corrected fix:**
  1. Return the ledger peak, the graphics ledger and `limit_bytes_remaining` from the call already being made; no new syscalls are needed. Publish `kernelPhysFootprintPeakMB`, labelled "exact" when it rises within the take and "upperBound" otherwise.
  2. Get exact per-stage MLX peaks: at each boundary, read `Memory.peakMemory` and reset it. The setter can only reset to 0 (`Memory.swift:208-211`), so record the maximum of the peak since the reset, the active memory at the reset and the active memory now, and keep a running cumulative maximum.
  3. Warn in the validator whenever `peakGPUAllocatedMB < mlxPeakMB`. Backfill that warning offline over committed records, and correct the documentation.
  4. Drop task_threads from periodic ticks and use the time saved to sample the floor tiers faster.
- **Verify:**
  - A unit test run with `dev.sh test --only`: a sampler at 500 ms plus a 256 MB spike lasting about 50 ms between ticks. The sampled maximum should miss the spike and the ledgers should catch it.
  - The next consented memory lane should show the kernel peak at or above `mlxPeakMB` on every take.

**#24 memory-probes-routine-trim-as-pressure: a routine cache clear is scored as memory pressure** (acc, medium, S, consent: no; duplicate: #90)
- **Evidence:**
  - `GenerationOutputAdapter.swift:2003-2016` emits a softTrim with source `.postGeneration` whenever `clearCacheAfterGeneration` is set. That flag is on for the 8 GB Mac and the iPhone Pro (`NativeMemoryPolicyResolver.swift:47, 84`).
  - `benchmark_memory.py:311-314, 337-343` counts every softTrim as a pressure warning and raises the pressure level, ignoring the source.
  - All 3,634 takes have a pressure level of at least 1; only 2 carry a real pressure event.
- **Mechanism:** A policy-driven cache clear is recorded as a trim action, and every trim counts as pressure.
- **Corrected impact:**
  - The warning status and the pressure level are the same on every take, so they carry no information and reviewers learn to ignore them. No failure condition is weakened.
  - On the M6, runs will flip to "passed". That is correct for the M6 tier, but README.md:128 goes stale at the repin.
  - Real pressure events can still be counted separately.
- **Corrected fix:**
  1. Exclude only trims with source `postGeneration` and reason `post_generation_cache_clear`, and publish them as `policyCacheClearCount`.
  2. Keep runtime-, kernel- and app-sourced softTrims as warnings. Runtime trims include budget relief (`QVoiceiOSApp.swift:376-386`, `TTSEngineStore.swift:957-959`), and today their source is guessed from the reason text (`NativeEngineRuntime.swift:609-614`). Pass the trim source explicitly at each call site instead.
  3. Update telemetry-and-benchmarking.md:432-433.
  4. Keep the event-versus-stage cross-check consistent (`benchmark_memory.py:393-397`). release.md:91-94 is unaffected.
- **Verify:** Fixture tests: a routine clear gives "qualified" with `policyCacheClearCount=1`, while a kernel trim still warns. All committed records re-validate.

**#25 memory-probes-retention-low-power: the retained-memory gate only catches large leaks** (acc, medium, S, consent: yes; related: #26)
- **Evidence:**
  - The threshold is 5% of RAM with 3 repetitions (`config/memory-qualification-policy.json`). Growth is the highest end value of the later takes minus the first take's end value (`publish_benchmark_history.py:1155-1183`). That gives 409.6 MB on the Mac and 614 MB on the iPhone.
  - Noise between takes, as a median (p90): Mac 18.5 MB (197 MB), iPhone 20.6 MB (49 MB).
  - The MLX snapshot taken after the post-generation trim exists (`GenerationOutputAdapter.swift:2014`) but is never published.
- **Mechanism:** A leak of L per take shows up as roughly 2L of growth. The threshold scales with RAM, not with measurement noise.
- **Corrected impact:** Leaks under about 205 MB per take (Mac) or 307 MB per take (iPhone) pass. Because the Mac noise has a heavy tail (p90 197 MB), a tighter footprint-only threshold would fail spuriously.
- **Corrected fix:**
  1. Publish end-of-take MLX active and cache values, and gate MLX growth within a mode once its noise has been calibrated.
  2. Add graphics-ledger end values.
  3. Ship this as retained-memory-v2, with a new policy ID.
- **Verify:** Fixture tests, then one consented memory lane to calibrate the noise.

**#45 memory-probes-ios-lane-polling-observer: the iOS memory lane copies the whole tree and cannot detect a jetsam** (both, medium, S, consent: yes)
- **Evidence:**
  - `wait_memory_qualification_sentinel` copies the whole diagnostics tree every 10 s (`ios_device.sh:874-880, 803-813`).
  - The target process ID is captured (`:2384`) but only used for cleanup.
  - The timeout is 900 s (`:2344`), and no crash delta is taken.
  - Reusable helpers already exist: a run-scoped pull (`:984-995`), a process liveness check (`:1052-1080`), an early stop with exit 27 (`:1083-1125`) and crash snapshots (`:1152-1183`).
- **Mechanism:** The wait loop looks only for the success and failure markers, and a killed app writes neither.
- **Corrected impact:** A jetsam or crash is reported only after 900 s, without a classification. Each poll copies a growing tree. The copying happens in the CoreDevice daemon, so it costs time and may disturb timing, but it has not been shown to bias the footprint.
- **Corrected fix:**
  1. Poll only the two small marker files.
  2. Check that the process is alive on every iteration; when it is gone, stop and take the crash delta.
  3. Do one final pull that includes the global `engine/generations.jsonl` and the samples mirror.
  4. Apply the same change to the clone-conditioning and gate waits.
- **Verify:** Stubbed shell-contract tests (no full pull inside the loop, and an early typed exit), then one consented iOS memory lane.

**#69 memory-probes-instruments-memory-profile-empty: the Instruments memory profile publishes no memory data** (both, low, M, consent: yes)
- **Evidence:**
  - Only presence flags and the size of the allocation data are published (`publish_benchmark_history.py:3174-3203, 3466-3485`).
  - Both memory profiles are marked not exportable (7.03 GB on the Mac, 2.62 GB on iOS), and their traces were deleted.
  - The lane exists for allocation stacks and VM maps (`macos_test.sh:656-660`), and it needs 15 GiB free.
- **Mechanism:** xctrace cannot export these tables, so the only memory-specific data lives in the trace, which the default policy deletes.
- **Corrected impact:** A rarely run consent-bound lane (last run in July) deletes its only unique evidence. The fields are honestly named, and the sampler metrics carry Allocations overhead. The claim that the profile degrades the sampler relies on a record taken before the d52340a0 guard.
- **Corrected fix:** Choose one:
  - (a) change release.md:84-85 so traces are kept by default for memory profiles, or
  - (b) publish an allowlisted category table built from the in-process ledgers. `footprint --json` is not a good source: it needs task-port access, suspends the target and emits file paths.

  In either case, label the profile's sampler metrics as instrumented.
- **Verify:** A unit test of the table reducer, then one post-fix macOS memory profile.

**#67 memory-probes-marking-peak-blind-window: the marking zero-peak check uses sampled peaks** (acc, low, S, consent: no)
- **Evidence:** `check_marking_peak_equality.py:53-80` allows max(pre-marking samples) + max(5%, 48 MB). The steps run in this order (`GenerationOutputAdapter.swift:1905-1921`): before_marking, clear the cache, mark, clear the cache, after_marking. AudioSeal runs through MLX on the GPU (`AudioMarking.swift:29-46`).
- **Mechanism:** A marking spike is seen only if a tick happens to land inside it.
- **Corrected impact:** A false PASS needs a spike under 500 ms that also exceeds the pre-marking peak plus the tolerance. At marking time the footprint sits hundreds of MB below the peak (2,513 MB peak vs 1,879 MB at the end), so only a large, brief spike would slip through. When the pre-marking peak is undershot, the check becomes stricter, not laxer. The +9-18 MB marking cost is itself a sampled figure.
- **Corrected fix:**
  1. At before_marking, read `Memory.peakMemory` and reset it.
  2. At after_marking, record the maximum of the peak since the reset and the active memory at the reset, then fold it back into the running maximum.
  3. Optionally read the ledger peak at both boundaries.
  4. Assert that the marking MLX peak is at most the generation's MLX peak plus one page, and keep the sampled check as a secondary signal.
- **Verify:** A unit test with a fake marker that briefly allocates 200 MB: the exact check fails where the sampled check passes.

**#66 memory-probes-coverage-metric: the ≥95% coverage rule measures timer health only** (acc, low, S, consent: no)
- **Evidence:**
  - Coverage = periodic samples / max(periodic + missed, elapsed // target) (`benchmark_memory.py:703-708`). One miss fails a take that has fewer than 19 periodic samples, which describes 3,066 of 3,634 takes.
  - Only one take has ever missed a deadline (a pre-guard Instruments run). Timer lateness is 48 ms at p50 and 53 ms at p99.
  - `maximumIntervalNS` is computed (`NativeTelemetrySampler.swift:1014`) but never read.
- **Mechanism:** Coverage counts deadlines honoured; it cannot tell whether the extremes were observed.
- **Corrected impact:** The qualification criterion in release.md:91-93 and native.md:142-144 is effectively always 1.0 and says nothing about whether the peak was caught.
- **Corrected fix:**
  1. Publish `samplerMaximumIntervalMS` and gate on a maximum unobserved gap of at most 2× the target.
  2. Add a comparison of the sampled peak against the MLX or kernel peak as the accuracy criterion.
  3. Optionally use `Task.sleep(until:tolerance:)` to remove the systematic ~48 ms lateness.
  4. Update the rules and docs together (see 4.4).
- **Verify:** Unit tests for the gap rule.

**#68 memory-probes-ios-gate-thresholds: the iOS memory gates ignore the device** (acc, low, S, consent: yes)
- **Evidence:**
  - Python fails at 5.2×1024 MB footprint, 384 MB headroom or a Metal ratio of 0.8 (`benchmark_memory.py:1029-1049`); Swift uses 5,200 and 4,500 MiB (V-4).
  - Every iOS take reports a Metal working set of 8,192 MB against a process limit of 6,144 MB, so a 0.8 ratio (6,554 MB) is above the process limit.
  - The floor profile is 5,000 MB, below the 5,325 MB fail threshold.
  - `peakProcessBudgetUtilization` is computed but not gated.
  - Headroom and footprint come from separate calls (`IOSMemorySnapshot.swift:161-162`).
- **Mechanism:** The thresholds are absolute numbers and use the wrong denominators.
- **Corrected impact:** On the iPhone 17 Pro and the 5 GB floor device, only the headroom gate can fire before jetsam. The Python and Swift thresholds drift about 108-125 MB apart.
- **Corrected fix:** This is a policy change and needs a maintainer decision.
  1. Gate on the measured budget: fail at about 0.92 utilization and warn at about 0.80, using the kernel peak once available.
  2. Drop the Metal ratio on iOS, or divide by a better denominator.
  3. Read `limit_bytes_remaining` in the same call as the footprint.
  4. Keep a single source for the thresholds and fix the "5.2 GB" wording in the docs.
- **Verify:** Fixture tests, then one device run checking that `limit_bytes_remaining` matches `os_proc_available_memory`.

**#65 memory-probes-probe-cost-threads** (both, low, S, consent: no). Same leak as #64.
- **Area notes:** About 19-20 boundary samples per take are awaited inline, and the only A/B hint (legacy data) suggests about a 2% cost. Add `captureDurationNS` to each sample and `boundaryCaptureTotalNS` to each take, and note the change in the schema.

**#70 memory-probes-field-report-dedupe: the MetricKit report double-counts copies** (acc, low, S, consent: no)
- **Evidence:** `ios_memory_field_report.py:47-59, 160-218` sums every copy of the summary it finds without de-duplicating by (kind, intervalStart, intervalEnd). The Swift document already uses that triple as its identity (`MetricKitMemoryExitSummary.swift:188-189`).
- **Mechanism:** Each lane pulls its own copy of the same rolling document.
- **Corrected impact:** Counts inflate only when the report points at a parent of several lane directories. The default is correct, and the report is advisory.
- **Corrected fix:** De-duplicate on the triple (newest wins) and report a duplicate count.
- **Verify:** A test with two copies.

Also verified in this area: V-4. The peak-miss rate can be backfilled offline today. task_threads is the heaviest call on each tick. The only evidence of Instruments degrading the sampler predates the d52340a0 guard.

---

### 3.4 UI benchmark and publication

**What is solid (keep)**
- Published timings come from monotonic clocks inside the app, so XCUITest polling never enters a metric.
- Selection is exact and fails closed (`check_macos_ui_bench.py:944-1072`): run IDs, cell order, layers, matching process IDs, typed model identity, memory schema and the stall gate.
- Provenance is strong: a build receipt binding the binary, source fingerprints that exclude registry outputs, dirty trees marked exploratory, hardware verified before the build, and a quiet-host check.
- `rtfDefinition` keeps lineages apart. Records are compact behind a privacy allowlist, and HISTORY.md is reproducible with `--check`.
- The observer-effect work (OPTIMIZATION.md J, K) removed screen recording and bounded the accessibility-polling cost to about 3% or less.
- The playback capture is well built: real-time-safe, about 0.25 s of analysis per take, and thresholds taken from an 87-take corpus.
- Context: every canonical record is from the XPC era (V-14).

**#22 ui-bench-publication-lineage-key-overspecified: the comparison key almost never matches** (acc, medium, M, consent: no; merge with #23)
- **Evidence:**
  - `comparison_key` (`benchmark_history.py:1429-1470`) folds in harnessHash (45 files, including the engine under test and unrelated scripts, `:891-941`; it hashes schema v2 but not v3) and the whole-file projectInputHash (`:952-956`).
  - Since 2026-08-25, 118 of 461 commits touched a harness file and 60 touched project.yml.
  - Only 9 of 48 comparable UI records have a baseline (2 of 16 canonical macOS, 0 of 6 iOS). Engine records: 7 of 114.
- **Mechanism:** Provenance hashes are treated as measurement identity.
- **Corrected impact:**
  - 39 of 48 comparable UI records show "baseline" and have no deltas. Deltas are for display only, so no gate is lost.
  - Replaying the narrower key links only 9 of 16 canonical records, not 14. Changes of model (5 of 15 transitions), evidence contract (4) and RTF definition (1) rightly keep breaking lineages.
  - A hand-bumped contract version alone could miss a real change such as the move from XPC to in-process (628887c7).
- **Corrected fix:**
  1. Give each record kind its own harness path list. For ui-generation that is:
     - the UI lane scripts, checkers, XCUITests and UIAutomationSupport;
     - BenchRunContext, AppGenerationTimeline, the sampler and GenerationTelemetryRecord;
     - rtf.py, playback_capture.py and the current schema.

     Drop the publisher, repo_invariants, the other lanes' probes, the iOS scripts and NativeEngineRuntime.swift.
  2. Replace projectInputHash with the UI scheme subset of project.yml.
  3. Put the required layer set (the topology) in the key.
  4. A contract version may be added, but not as the only guard.
  5. Version the key by schemaVersion so legacy keys stay byte-identical.
  6. Add the two base test-case files (V-3) and keep benchmark_memory.py (#1).
- **Verify:** Replay the committed records offline: expect about 9 of 16 linked, with XPC and in-process records never linked. `rebuild-index --check` stays green.

**#28 ui-bench-publication-busy-host-published-canonical: UI records ignore host load** (acc, medium, S, consent: no)
- **Evidence:**
  - Classification uses only the dirty and instrument flags (`benchmark_history.py:1627-1633`), and only the highest load across takes is kept (`check_macos_ui_bench.py:108-120`).
  - Canonical record 488a9ed0 ran at load 14.33. Its custom/medium/cold RTF is 1.359 and its TTFC 6,446 ms, against 0.623-0.646 and 1,252-2,474 ms in the other runs.
- **Mechanism:** The quiet-host check runs once, at `ui_test.sh:307`, before build-for-testing (`:1493-1514`). The build's 1-minute load average plausibly leaks into the first take (V-8).
- **Corrected impact:** The observed damage is one single-sample cold take. The other 28 takes are in line, and warm medians and public numbers are unaffected. 83dcb7d1 (load 14.38) shows no clear outlier, and the gate's 2×-cores rule would flag neither record. Load is not kept per take.
- **Corrected fix:**
  1. Re-run `require_quiet_host`, with a bounded wait for load to settle, after build-for-testing and just before the tests run.
  2. Store `loadAverage1M` for each take.
  3. Optionally classify a run exploratory when any take exceeds about 1× the core count. That changes release.md and host_preflight.sh (4.4).
- **Verify:** Reclassify the committed records offline, plus unit tests.

**#29 ui-bench-publication-unpinned-seeds: UI benchmark takes use random seeds** (acc, medium, M, consent: yes)
- **Evidence:**
  - Studio requests use `draft.pinnedSeed` (`MacCustomVoiceScreen.swift:333`, `MacVoiceDesignScreen.swift:371`), which is set only from History (`ContentView.swift:225-231`).
  - Run-ons: db6af858 warm#0 took 14.96 s over 187 tokens and passed QC; 6cb80773 warm#2 took 15.12 s.
  - RTF correlates with 1/length at +0.53 in short design cells and +0.54 in short clone cells.
- **Mechanism:** Take length and the occasional run-on change with the seed.
- **Corrected impact:** This adds length variance to short design and clone cells, and 2 run-ons among 108 warm takes enter the timing data. Seeds do not explain the spread in custom/short (#30). The concern about the capture join is refuted: the time window is filtered first (`playback_capture.py:368-387`).
- **Corrected fix:**
  1. Add a registered diagnostics knob that sets seed = hash(cell, repetition), active only under internal diagnostics plus `QWENVOICE_DEBUG`.
  2. Record the effective seed and add a seed policy to the lineage identity. Use the same knob on iOS.
  3. Add the speaking-rate QC check (#10).
- **Verify:** Two canonical runs on one build give identical lengths and PCM digests per take.

**#30 ui-bench-publication-sample-allocation: takes are spread evenly across cells** (both, medium, M, consent: yes)
- **Evidence:**
  - The matrix has 3 warm repetitions per length and cold takes for custom and design only (`VocelloUIAutomationSupport.swift:1009-1042`).
  - Run-to-run CV of cell medians: long 0.3-0.6%, medium 0.4-1.1%, short 1.8-4.2%.
  - A single cold take stores an IQR of 0 (`benchmark_history.py:1347-1357`).
  - custom/short/warm#0 is the slowest take in 6 of 6 runs (RTF +12.2%, TTFC +24.5%).
- **Mechanism:** An equal allocation ignores the very different variances, and the first warm take after a cold take pays a settling cost.
- **Corrected impact:** Short cells cannot resolve regressions under 5-12%, partly because of that order effect. Cold cells are single samples, and long cells are more precise than any decision needs.
- **Corrected fix:**
  1. Handle the position effect first: flag or exclude the first warm take after a cold take.
  2. Re-measure short-cell spread.
  3. Only then reallocate takes, costed from measured overhead. The proposed per-mode 5/3/2 split is 32 takes, not 29.
  4. Report cold cells through startup metrics, and publish an IQR only when n ≥ 4.
  5. This changes matrixHash and the shared 29-take assertions, so it needs a maintainer decision.
- **Verify:** Two canonical runs under the new matrix.

**#21 ui-bench-publication-validation-retry-loop: validation reruns up to 60 times** (eff, medium, S, consent: no)
- **Evidence:**
  - `ui_test.sh:1205-1218` loops the checker up to 60 times with 1 s sleeps, overwriting its output each time. The loop comes from the XPC-era checker (a9428624).
  - The engine now runs in the app (process IDs match, `check_macos_ui_bench.py:384-391`), and the app has exited before validation starts (`VocelloMacUITestCase.swift:48-52`).
  - Memory is qualified twice per pass (`:1064-1070`, `:640-646`), and the iOS checker does the same (`:371`, `:769`).
  - The iOS path pulls the whole diagnostics tree (`ui_test.sh:1249`).
- **Mechanism:** A wait built for eventual consistency across two processes now only slows down deterministic failures.
- **Corrected impact:** Any deterministic failure costs 60 × (checker time + 1 s), and capture-gate failures are the worst case. Earlier output is lost. A passing run pays one extra memory qualification. The checker's time was not measured.
- **Corrected fix:**
  1. Validate once.
  2. Retry only on a distinct "rows not yet present" exit code (#6), for at most about 10 s.
  3. Pass the gate's memory results into `build_manifest`.
  4. On iOS, pull only engine/, app/ and the run subtree.
- **Verify:** A fixture with an injected QC failure fails in one pass and qualifies memory once.

**#31 ui-bench-publication-per-take-harness-overhead: per-take harness overhead is unmeasured** (eff, medium, M, consent: yes)
- **Evidence:**
  - Each take's manifest goes through a stdout relay followed by up to a 10 s poll (`VocelloMacBenchmarkUITests.swift:139-163`).
  - All waits use XCTNSPredicateExpectation (`VocelloUIAutomationSupport.swift:338-355`).
  - Each take creates a new audio tap, device and ring buffer (`VocelloPlaybackCaptureSession.swift:54-141`).
  - Text is typed one character at a time (`:602-610`).
- **Mechanism:** These serial fixed costs add up on every take.
- **Corrected impact:** The finder's 14 s per take came from a confounded fit; the real figure is at most about 9.5 s and probably 5-9 s. Comparable time goes to waited playback while capturing (about 208 s per canonical run) and to typing (about 75-100 s, inferred). The timed metrics are unaffected.
- **Corrected fix:**
  1. Add per-take stamps for begin, manifest ready, submit, completion and playback end.
  2. Then, in order:
     - capture only one repetition per cell (needs a coverage-gate decision);
     - paste the text instead of typing it, or skip retyping a draft that already matches;
     - poll local checks faster;
     - write the manifest directly, but only when the unsandboxed re-sign succeeded.
- **Verify:** An instrumented run before and after the change, with medians unchanged.

**#72 ui-bench-publication-single-record-public-numbers: public short-cell numbers come from one run** (acc, low, S, consent: no)
- **Evidence:** The README pins record 379db820 (`generate_readme_charts.py:61`), and `--check` repins to the newest canonical record (`:441-447`). The website's short-cell values of 0.69, 0.71 and 0.82 (`Engineering.jsx:23-25`) are the worst of six runs; pooled over all runs they are 0.647 and 0.758.
- **Mechanism:** Each repin copies one record's noise into public copy.
- **Corrected impact:** Three short-cell values can move by 0.02-0.08 at a repin with no code change. Long and medium cells move by less than 1%. All six records are from the XPC era. Repinning to the newest record is itself an explicit contract (release.md:133-136).
- **Corrected fix:** This is a contract change. Pool the medians over the last K canonical records that share a lineage, reset the pool when the lineage changes, keep the newest record as the anchor and show n. Or publish short cells as a range.
- **Verify:** Compute the pooled medians offline and render the charts.

**#71 ui-bench-publication-trend-noise-and-ttfc: HISTORY reports noise as a direction** (acc, low, S, consent: no)
- **Evidence:** `trend_summary` (`benchmark_history.py:2872-2899`) takes the median of per-cell deltas, including single cold takes, and labels any non-zero value as faster or slower. HISTORY.md:1439 reads "RTF +1.1% (slower)" although the cell deltas range from −0.9% to +6.0%, and :1290 reads "+0.0% (faster)". It collects `ttfcMS`, which UI takes do not have.
- **Mechanism:** A flat percentage with no model of noise.
- **Corrected impact:** Readers see noise as a direction, and first-chunk latency never appears for UI runs.
- **Corrected fix:**
  1. Report "within noise" below max(5%, 3×MAD).
  2. Leave cells with n < 3 out of the trend.
  3. Map TTFC to `submitToFirstChunkMS` for UI runs.
  4. Label the RTF column clearly, or make it warm-only.
- **Verify:** An offline rebuild shows "within noise" for dfa37630 and adds a TTFC term.

**#73 ui-bench-publication-rebuild-index-double-validation: the registry is validated twice** (eff, low, S, consent: no)
- **Evidence:** `rebuild_index` validates everything twice (`benchmark_history.py:2968-2976`, `:2842-2847`), and `record_manifest` reads every record again (`:3007-3054`). A measured run made 680 record validations and 82,564 key computations and took 4.12 s, 57% of it in the privacy scan.
- **Mechanism:** The second pass re-validates records that did not change.
- **Corrected impact:** About 2 s per publication and per gate check, growing with the registry.
- **Corrected fix:** Validate each record once, re-validate only records whose comparison block changed, and cache the key and the privacy scan by record digest.
- **Verify:** Time the check before and after.

**#74 ui-bench-publication-capture-pacing-and-take-identity: capture availability changes pacing** (acc, low, S, consent: yes)
- **Evidence:**
  - The wait for playback plus quiet happens only when a tap is live (`VocelloMacBenchmarkUITests.swift:97-107`); without the recording grant the lane still passes (`ui_test.sh:609-621`).
  - Capture state is not part of the comparison key.
  - Take notes are read again at completion from the /tmp file (`BenchRunContext.swift:21-33`).
  - After a relaunch, the tap attaches in the middle of a take.
- **Mechanism:** The idle gap between takes depends on whether capture is available, and take identity is read late from shared state.
- **Corrected impact:** A pacing effect on TTFC of a few percent is plausible but unproven. The late identity read is a latent cause of spurious failures that has never been observed.
- **Corrected fix:**
  1. Pace takes the same way whether or not capture is live.
  2. Put the capture policy in the lineage identity.
  3. Snapshot the take notes at submit (a Sources change, so it needs native tests).
  4. Attach the tap before the first submit after a relaunch.
- **Verify:** An A/B run with capture armed and unarmed, plus a unit test.

**#75 ui-bench-publication-build-skip-fingerprint-scope: the build skip almost never fires** (eff, low, S, consent: no)
- **Evidence:** The skip at `ui_test.sh:1493-1514` compares a fingerprint of the whole tree (`tree_fingerprint.py:60-72`).
- **Mechanism:** Build-input identity is taken to be whole-worktree identity.
- **Corrected impact:** A narrower key would have skipped 3 of 13 builds, each well under a minute. The runner re-sign runs regardless (`:1515-1516`). The shared fingerprint is deliberate (`:1488-1491`), and the 09-15 stale-runner incident shows the risk of skipping wrongly.
- **Corrected fix:** Low priority. Exclude only benchmarks/runs, HISTORY.md, docs/, website/ and config/roadmap.json from the UI build marker.
- **Verify:** The fingerprint does not change after a publication and does change after a Sources edit.

**#76 ui-bench-publication-derived-data-stored: records store derived data** (eff, low, M, consent: no)
- **Evidence:** `cells` must equal `aggregate_cells(takes)` (`benchmark_history.py:2649-2650`) and takes up 35-40% of the bytes.
- **Mechanism:** Derived blocks are serialized into immutable records.
- **Corrected impact:** Repository churn only. The size cap is not binding (largest record 224 KB, about 237 KB estimated in the worst case), and storing the derived data is intentional (`:491-500`).
- **Corrected fix:** Defer until something reaches the cap.
- **Verify:** An offline re-serialization.

Also verified in this area: V-1, V-8, V-14. Per-character typing adds about 1,450 extra keystrokes per canonical run.

---

### 3.5 UI responsiveness

**What is solid (keep)**
- **Honest proxy.** Both probes say they measure main-thread cadence, not compositor presents.
- **Fail-closed structure gate.** Each marker must appear once, blocks must cover at least 90% of the window, blocks must be monotonic, the refresh rate must be in band, and an environment snapshot is required.
- **Cadence check scoped to idle.** On iOS, the 55-65 Hz cadence band fails the run only on the idle sentinel.
- **Correct window accounting.** Blocks at the window edge count only their fractional share.
- **Isolated sessions.** Each probe has a private watchdog, sessions carry tokens, and the display link runs in common mode.
- **Low overhead.** Probes run behind three gates and keep bounded retention.
- **Harness habits.** Scrolls are anchored to the window, generation runs last, the cursor is parked, the host is kept quiet, and only PASS runs publish.
- **Proven sensitivity.** The earlier v2 ceilings caught the 09-05 regression.

**#6 ui-responsiveness-01: the stall gate went live on the M6 with zero tolerance and no calibration** (both, high, M, consent: yes)
- **Evidence:**
  - `check_macos_ui_bench.py:877` defaults the allowed delayed heartbeats to 0, and `ui_test.sh:1204-1216` never overrides it.
  - Before 91998582 the gate compared against "floor8GBMac" while rows are stamped "floor_8gb_mac", so it never ran on the M2. It now applies to mid_16gb_mac (`test_check_macos_ui_bench.py:398-406`).
  - 419 of 464 canonical M2 takes (90.3%) had at least one delayed heartbeat.
  - The watchdog samples every 100 ms, and a stall of D ms reads as somewhere between D−100 and D.
- **Mechanism:** A zero tolerance applied to a sampled counter that was never exercised.
- **Corrected impact:** A single delayed heartbeat above 50 ms in any of 29 takes fails the first canonical M6 benchmark (AV-17 step 2). Retries need a new explicit request. The retry loop adds 1-2 minutes per failure.
- **Corrected fix:**
  1. Before AV-17 step 2, move the tolerance into a config contract that names the statistic and its calibration profile.
  2. Until M6 data exists, gate on a provisional statistic (for example, no heartbeat delayed more than 250 ms), or declare the first run uncalibrated for this gate.
  3. Calibrate on one exploratory M6 run.
  4. Treat a run-loop busy-span probe as a later follow-up with its own definition marker.
  5. Add a distinct "rows not yet present" exit code.
  6. Land this together with #18.
- **Verify:** Checker tests offline, then one exploratory M6 run.

**#18 ui-responsiveness-02: the watchdog discards heartbeats still queued at session end** (acc, medium, S, consent: no)
- **Evidence:**
  - `end()` bumps the session token (`MainThreadStallWatchdog.swift:96-113`) and late completions are dropped (`:141-144`). end() runs on the main thread right after persistence and autoplay (`MacStudioSingleTakeGenerationHooks.swift:40-57`).
  - Heartbeat coverage is below 1.0 in 721 of 959 macOS takes and below 0.9 in 173.
  - 132 takes lost at least 2.5 heartbeats, and 108 of those still report a maximum under 250 ms.
- **Mechanism:** The largest latencies, from the completion phase, are thrown away.
- **Corrected impact:** A downward bias at the generation boundary in about 14% of macOS takes (none measurable on iOS), so a completion-path regression can hide.
- **Corrected fix:** Fold pending heartbeats in as censored lower-bound observations (the oldest pending send time is enough), report `censoredHeartbeatCount`, and mark the definition change.
- **Verify:** `scripts/dev.sh test --only MainThreadStallWatchdogTests` with a ~500 ms block before end(), expecting a maximum of at least about 400 ms.

**#32 ui-responsiveness-03: accessibility queries run inside the confirmatory windows** (acc, medium, M, consent: yes)
- **Evidence:**
  - `navigate()` (`VocelloMacUITestCase.swift:180-195`) polls exists, isEnabled and isHittable, plus an unscoped query and isSelected. Since b23d8a7e it also clicks the Studio sidebar item.
  - delivery-menu queries menu items inside its window (`VocelloMacPerfUITests.swift:135-154`).
  - On iOS, `select(tab:)` and `historyRows()` run inside windows (`VocelloiOSUITestCase.swift:165-176`, `VocelloiOSPerfUITests.swift:232-239`).
  - This contradicts the checker's own stated policy (`check_macos_ui_perf.py:482-486`).
- **Mechanism:** Accessibility snapshots run on the app's main thread.
- **Corrected impact:** The ceilings include an unmeasured share of harness cost, anywhere from minor to dominant; the 121 to 112 ms/s comparison is confounded. Large regressions stay visible, but harness changes can look like app changes (V-3).
- **Corrected fix:**
  1. Measure first: add a harness-only control scenario or take one Time Profiler sample.
  2. On macOS, navigate with the Cmd-1…6 Navigate commands (`QwenVoiceApp.swift:72-101`) with fixed dwell times and check the result after the window.
  3. On iOS, resolve targets before the window.
  4. Add the base test-case files to the harness hash.
- **Verify:** Run old and new variants on the same build.

**#33 ui-responsiveness-04: model warms land inside measured windows** (acc, medium, S, consent: yes)
- **Evidence:**
  - Selection and draft changes schedule warms (`ContentView.swift:309-351`).
  - sidebar-navigation footprint grew by 831-2,196 MB in all 19 records since 09-15, against 30-55 MB before.
  - `QWENVOICE_SUPPRESS_WARMUP` exists and the benchmark lane uses it; the perf lane does not.
  - The checker never flags footprint growth (`check_macos_ui_perf.py:213-235`).
- **Mechanism:** Warm and cancel cycles for three models happen during the scenario's own navigation.
- **Corrected impact:** The scenario measures warm churn that depends on the tier, and nothing records how many warms ran. Whether hitch time is inflated is unproven. Corrections:
  - the setup warm finishes before the window opens;
  - the jump in growth coincides with the in-process move;
  - the generation-active growth is not a cold load;
  - both telemetry modes use the same sampling cadence.
- **Corrected fix:**
  1. Add a warn-only `uiperf.footprint:<scenario>` code and record the footprint at window start.
  2. The maintainer decides whether this scenario is "navigation with product warms" or pure UI. If pure UI, set `QWENVOICE_SUPPRESS_WARMUP=1` and add a separate exploratory scenario for warms.
  3. Record the sampler interval for generation-active.
- **Verify:** Replay offline: the new check flags the 19 records and nothing earlier.

**#79 ui-responsiveness-05: hitch per second is diluted by harness waiting** (acc, low, S, consent: no)
- **Evidence:** Hitch = excess time / covered seconds (`check_macos_ui_perf.py:224-225`). Sidebar cost per action went from 482-510 ms to 569-608 ms while ms/s stayed at 110-117.
- **Mechanism:** In interaction scenarios, harness pace controls the denominator.
- **Corrected impact:** Conceptual only. The 09-22 runs are dirty and not comparable, and they came after a redesign that added one click per Studio step. No hidden regression is shown.
- **Corrected fix:** Derive `uiHitchMSPerAction` from existing fields, with a definition marker and no backfill. Consider per-action ceilings after #32. Keep ms/s for idle and scroll scenarios.
- **Verify:** An offline recompute, plus checker tests.

**#34 ui-responsiveness-06: ceilings are too loose to catch realistic regressions** (acc, medium, M, consent: yes)
- **Evidence:**
  - Ceilings are 2.0× the v3 median (`config/ui-perf-thresholds.json:3-26`).
  - Spread between runs: sidebar 2-10%, delivery 1-6%.
  - The v2 ceilings (86b00667, about 1.25×) caught the 09-05 shift; v3 (55c8cd9b) would miss it.
  - The comparison key includes about 51 shared files, including the thresholds files.
- **Mechanism:** One take per scenario, ceilings at 2×, and deltas only between back-to-back runs.
- **Corrected impact:** Only a hitch regression of about +100% triggers a warning on deterministic scenarios.
- **Corrected fix:**
  1. Derive ceilings from the spread, with a floor of about 1.25-1.3× for scenarios whose spread is under 10%, over at least 3 runs.
  2. Add per-cycle sub-window markers (the checker currently rejects duplicate markers, `:92-93`).
  3. Give ui-perf its own harness path set, including the base test-case files.
  4. Take the thresholds files out of the identity.
  5. Follow the documented 1+5 counted-run protocol.
- **Verify:** Recompute from M2 chains offline; the M6 ceilings come from AV-17 step 3.

**#80 ui-responsiveness-07: the probe watchdog's summary is never published** (both, low, M, consent: yes)
- **Evidence:** None of 378 perf takes carries the heartbeat metrics. The summary is written only in `finish()`, and `app.terminate()` kills the app first (`VocelloUIAutomationSupport.swift:143-145`). The checkers map the summary to generation-scoped key names (`check_macos_ui_perf.py:332-333`).
- **Mechanism:** The summary is flushed only on lifecycle callbacks the test driver never delivers.
- **Corrected impact:** Dead instrumentation, with a latent contract violation if only the flush were fixed.
- **Corrected fix:** Either remove the watchdog and the mapping, or publish per-block counters under window-scoped keys. Until then, stop mapping to the generation-scoped names.
- **Verify:** Checker tests.

**#77 ui-responsiveness-08: M2 ceilings will be applied on the M6** (acc, low, S, consent: no; duplicate: #78)
- **Evidence:**
  - `load_thresholds` never reads `calibrationProfile` (`check_macos_ui_perf.py:246-256`), and the iOS contract has none.
  - Nothing in the identity describes the display.
  - The macOS probe does not pin a refresh rate (`UIPerfFrameProbe.swift:151-156`), and every record so far is 60 Hz.
  - The docs say warm-up plus 5 counted runs; v3 used 3.
- **Mechanism:** Calibration metadata is declared but never checked.
- **Corrected impact:** Until AV-17 step 3, M6 records carry M2 verdicts with no marker, and a display faster than 60 Hz would change what the floors mean.
- **Corrected fix:**
  1. When the profile or refresh rate does not match, emit `uiperf.uncalibrated` instead of ceiling verdicts.
  2. Add the refresh interval to the identity.
  3. Add a macOS cadence check.
  4. Add `calibrationProfile` to the iOS contract.
  5. Add a `--derive-thresholds` mode (#78) that reproduces the committed ceilings from records 0bb33592, 636488c2 and 64610737.
  6. Reconcile the counted-run protocol.
- **Verify:** Fixture tests and a derivation regression test.

**#81 ui-responsiveness-09: p95 comes from bucket edges, and maxGap is not clipped to the window** (acc, low, M, consent: yes)
- **Evidence:** Buckets are fixed multiples of the refresh interval (`UIPerfFrameProbe.swift:57-59`), and p95 is a bucket's upper edge: only 8 distinct values across 378 takes. maxGap spans whole 500 ms blocks (`check_macos_ui_perf.py:168-172`).
- **Mechanism:** Coarse buckets and block granularity.
- **Corrected impact:** p95 is inert because no ceiling uses it. maxGap can include up to one block beyond each window edge, which can raise spurious warnings. Idle CPU also rose after 09-19, so some warnings may be real.
- **Corrected fix:** Log a capped list of hitch events per block so the checker can clip exactly. Use integer vsync bins only after checking raw rows. Rename or drop p95Approx.
- **Verify:** Tests with events straddling the window edge.

**#35 ui-responsiveness-10: the main-thread proxy cannot see render-server hitches** (acc, medium, L, consent: yes)
- **Evidence:** Both probes are main-thread proxies. generation-active says compositing is its subject (`VocelloMacPerfUITests.swift:243-246`). No test uses XCTHitchMetric, which is available on iOS and macOS 26+.
- **Mechanism:** Display-link cadence stays perfect while the render server misses frames.
- **Corrected impact:** Hitches from GPU contention and glass or mask passes are invisible, and the glass-off decision cannot be validated with this lane.
- **Corrected fix:** Add XCTHitchMetric as a separately defined second witness on the scroll and generation-active scenarios. First validate its overhead and measurement semantics in one exploratory run.
- **Verify:** One perf run compared with an Instruments Hitches trace.

**#82 ui-responsiveness-11: most perf-lane time is setup** (eff, low, M, consent: yes)
- **Evidence:** Measured windows are 48-57% of lane time on macOS and 20-34% on iOS, but the duration also covers build, install and pulls. The iOS language walk makes 22 queries twice per launch (`VocelloiOSUITestCase.swift:38, 60, 73-102`). The perf pull copies the whole tree (`ui_test.sh:1292`).
- **Mechanism:** Setup repeats for each of nine launches, the queries are unscoped, and the pull is wider than needed.
- **Corrected impact:** Minutes per counted session; the exact share is unknown until phases are recorded. Correction: idle is not always 0.
- **Corrected fix:** Replace the walk with one predicate query and skip an unchanged restore. Pull only `ui-perf/` and `<runID>/`. Copy the ledger's per-step durations into the run artifacts. Keep the idle window at 15 s.
- **Verify:** Compare wall time before and after.

**#83 ui-responsiveness-12: signposts go unused, and the environment is rebuilt per chunk** (both, low, S, consent: no)
- **Evidence:** `LivePreviewDiagnostics.isEnabled` rebuilds the process environment at each call site (`RuntimeDebugGate.swift:55-58`; `AudioPlayerViewModel.swift:888/894/940`). App intervals such as History Reload are never extracted.
- **Mechanism:** Instrumentation exists without a consumer, and the gate is evaluated eagerly.
- **Corrected impact:** Negligible cost. The missed opportunity is separating app cost from harness cost in the History scenarios.
- **Corrected fix:** Cache the flag in a static let, add an overload that does not read the environment, and optionally add XCTOSSignpostMetric for History Reload.
- **Verify:** A unit test.

Also verified in this area:
- V-3.
- The watchdog timer's lateness is never recorded.
- Model state at window start is not controlled (about 1.4 GB resident vs 59-69 MB).
- The iOS perf contract is stale: calibrated in August, 5 records, the last on 09-05.

---

### 3.6 Audio and language evaluation

**What is solid (keep)**
- **Byte-bound evidence.** WAV digests run through ASR, the cache and the publisher, and scores are recomputed from transcripts.
- **Signed plans.** Plans are immutable and digest-signed, with no retries.
- **Honest witness labelling.** Records that rely on one ASR family are labelled as such.
- **Isolated whisper.** Whisper runs after generation, supervised and deterministic.
- **Reproducible takes.** Fixed seeds reproduce takes byte for byte.
- **QC on the published file.** QC reads the published WAV.
- **Quiet polling.** lang-bench polls only the sentinel file.
- **Warn first.** New signals start as warnings until evidence supports a hard bound.

**#10 audio-language-eval-no-speaking-rate-plausibility: Fast-QC never checks length or speaking rate** (acc, high, M, consent: no)
- **Evidence:**
  - `makeAudioQCReport` (`GenerationOutputAdapter.swift:2743-2897`) never relates duration or token count to the text, although the text is available (`:1927`).
  - The token-cap check only warns, and only at the cap (`GenerationQualityReportProducer.swift:55-58`).
  - Run-ons that passed:
    - db6af858: 14.96 s over 187 tokens, QC pass;
    - 6cb80773: 15.12 s;
    - lang-bench zh: 17.28 s, warn only;
    - lang-bench de: 19.36 s, pass.
- **Mechanism:** Every QC measure is based on amplitude or waveform shape.
- **Corrected impact:** A blind spot for runaway or repeated output. About 0.3% of takes are affected, 2 of them in canonical records, and the bias on medians is small.
- **Corrected fix:**
  1. Add a warn-only speaking-rate flag to Swift QC: tokens, or non-silent seconds, per normalized text unit.
  2. Keep per-language bands in Swift, with a guard for very short texts.
  3. Bump the QC algorithm version and seed the bands offline.
  4. Set any fail bound under the threshold-change authority.
  5. Export the value through `QC_METRIC_MAP`.
- **Verify:** Offline, the flag catches the listed run-ons and at most about 0.5% of other takes; add Swift unit tests.

**#42 audio-language-eval-lid-control-unproven: the language channel is weaker than the records claim** (acc, medium, M, consent: yes)
- **Evidence:**
  - Apple recognition is locked to the expected language (`VoiceClipTranscriber.swift:416-417`), and its languagePass is text language detection run on that locked transcript (`GenerationOutputVerifier.swift:226-230`).
  - Whisper passes on its top guess (`language_metrics.py:227`).
  - The negative control passes if either channel fails (`check_language_output.py:311`).
  - For the control take (English hint on French text), whisper said English with p=0.893 and the WER was 0.5625.
  - Consensus votes on the combined result (`publish_benchmark_history.py:2286-2296`).
- **Mechanism:** A locked recognizer largely decides what language it "hears", so Apple's check is close to unfalsifiable.
- **Corrected impact:** WER still rejects wrong-language output, so gate outcomes are not wrong today. The risk is misattribution and an untested premise: the control take really may be anglicized (176 vs 134 tokens). About 38 takes in 4 records are affected. The finder's proposed detection probe is redundant.
- **Corrected fix:**
  1. Relabel Apple's languagePass as transcript-language consistency.
  2. Make consensus per channel, with an inconclusive result when families disagree.
  3. Re-declare the control take as an accuracy control and publish each family's detected language.
  4. Add a unit test on `score_recognition`.
  5. A second acoustic language detector is research, not a fix.
- **Verify:** Unit tests, then the next lang-bench.

**#43 audio-language-eval-wer-segmentation-artifact: WER counts word-boundary merges as errors** (acc, medium, M, consent: no)
- **Evidence:** In the German cells, WER is 0.1379 (2 substitutions, 2 deletions) while CER is 0.0. A CER of zero proves every word error is a merge, as in "vor Mittag" vs "Vormittag". The gate is 0.15, and the script was already rewritten to fit under it (eaf9d751).
- **Mechanism:** Tokenized WER charges the recognizer's compounding choices as errors.
- **Corrected impact:** A correct German take uses 0.138 of the 0.15 budget, so one more merge fails it. The result is deterministic at fixed seeds, so the risk arrives with a model, seed or OS change.
- **Corrected fix:**
  1. Record `wordBoundaryOnlyEdits` and gate after crediting them, in both Python and Swift with parity fixtures (a new metric version).
  2. Or fail only when both WER and a calibrated CER bound are exceeded.
  3. Keep publishing v1.
- **Verify:** Fixture and parity tests.

**#44 audio-language-eval-cohort-single-witness: the diagnostic cohort runs without whisper** (acc, medium, S, consent: yes)
- **Evidence:** Whisper is skipped when a cohort runs (`ios_device.sh:1405`), and the PASS is printed from Apple alone (`:1439-1441`). Manifest rows are keyed by cellID (`independent_asr.py:218-222`), which repeats across seeds and would be rejected as duplicates (`:128-130`).
- **Mechanism:** A limit in row identity turned into a gap in evidence policy.
- **Corrected impact:** The cohort PASS rests on one family, contrary to the two-family rule, and it was used to accept corpus v2.
- **Corrected fix:** Key rows by childRunID, run whisper for cohorts, and report consensus pass, fail or inconclusive, or label the result as one witness.
- **Verify:** A 15-row unit test.

**#84 audio-language-eval-dropout-under-wer-granularity: a skipped phrase can pass** (acc, low, M, consent: no)
- **Evidence:** Scripts have 17-32 units, so the gate allows 2-4 errors. Dropping "the quiet" gives a WER of 0.1176, which passes. Only aggregate counts are kept (`language_metrics.py:105-138`).
- **Mechanism:** The gate sees total error rate, not runs of deletions.
- **Corrected impact:** A skip of 2-4 units without a silent gap passes, which is plausible but has no instance in evidence. Correction: the English Design "dropout" was an amplitude lead, which QC does see.
- **Corrected fix:** Compute `longestDeletionRun` in Python and Swift, warn at 2 or more consecutive words, and bump the metric version.
- **Verify:** A fixture, plus zero flags on committed passing takes.

**#85 audio-language-eval-click-metric-per-sample: click tolerance grows with take length** (acc, low, M, consent: no)
- **Evidence:** A click is a clamped step larger than 0.42 of full scale (`GenerationOutputAdapter.swift:1086-1092`). Warn and fail are set as fractions of samples (`:2783-2784`), which at 24 kHz means 12 and 120 per second. 264 of the 273 takes with any clamp passed.
- **Mechanism:** Samples are counted instead of events.
- **Corrected impact:** A seam regression of about 1-10 clamps per second would pass. None of the flagged takes has been shown to be audible.
- **Corrected fix:** Add an observational count of clustered events, including a low-energy subcount, and export it. Calibrate on the retained A/B takes before setting any bound.
- **Verify:** Swift tests showing the count does not depend on duration.

**#86 audio-language-eval-pinned-auto-duplicates: Pinned and Auto pairs regenerate identical audio** (both, low, M, consent: yes)
- **Evidence:** Seeds are keyed by mode and script language (`language_bench_evidence.py:110-117`), so all 8 iOS pairs are byte-identical. macOS publishes no output digest, and both identical rows are decoded.
- **Mechanism:** Same prompt plus same seed on deterministic MLX.
- **Corrected impact:** About 30% of iOS full-run takes (6-8 minutes per rare run). The duplication is a documented, deliberate proof of Auto resolution.
- **Corrected fix:** Publish an output digest on macOS and assert that digests match within each group. Making Auto an independent sample needs a maintainer decision.
- **Verify:** Offline tests.

**#87 audio-language-eval-ios-per-take-overhead: iOS lang-bench polls on a fixed 10 s timer** (eff, low, S, consent: yes)
- **Evidence:** A fixed 10 s sleep before every probe (`ios_device.sh:843`), and a relaunch for every take.
- **Mechanism:** Polling quantization plus CoreDevice calls on every loop.
- **Corrected impact:** Only about 1.5-3 minutes per full run can be attributed to polling; the rest is unmeasured.
- **Corrected fix:** Log timestamps for launch, sentinel and pull first. Then make the first probe at the predicted end of generation and probe every 2-3 s after that.
- **Verify:** Compare wall time before and after.

**#88 audio-language-eval-macos-fixture-drift: macOS lang-bench ignores the corpus fixtures** (acc, low, S, consent: yes)
- **Evidence:** The macOS Design brief is hard-coded (`macos_test.sh:924`). No `--speaker` is passed (`:944-957`), so Custom always uses aiden. The comment at `:929-931` claims the takes are comparable with iOS.
- **Mechanism:** Cell selection is re-implemented inline instead of using the plan.
- **Corrected impact:** Every macOS Design take uses a different brief, and zh/ja Custom full runs use a non-native speaker. Publication integrity holds, because duplicate and stray rows are still rejected.
- **Corrected fix:** Drive the lane from plan rows, bind fixture identity on macOS, start a new macOS key and fix the comment.
- **Verify:** Offline tests, then a macOS run.

**#89 audio-language-eval-whisper-evidence-copied-fields: whisper evidence fields are copied or confounded** (acc, low, S, consent: no)
- **Evidence:**
  - Processed duration is the WAV header value (`independent_asr.py:339`), so the mismatch check can never fire.
  - Wall time includes model load: 0.745 s vs 0.483 s on byte-identical takes.
  - Confidence fields are computed and then dropped.
  - The cache identity hashes the whole file.
- **Mechanism:** Fields are filled from inputs instead of from measurement.
- **Corrected impact:** A small timing bias and a check that can never fail; no verdict changes.
- **Corrected fix:**
  1. Return the decoded sample count.
  2. Warm the model before timing.
  3. Publish the no-speech and log-probability values.
  4. Narrow the cache identity to the worker.
- **Verify:** Unit tests with the worker fake.

Also verified in this area:
- No committed record has two-family consensus.
- The Apple side of the negative control has never been measured.
- Apple and whisper define a language pass differently.
- V-10.

---

### 3.7 M6 host and 8 GB floor (gap-1)

**What is solid (keep)**
- Rows stamp the tier, the forced flag and the MLX policy.
- Forced rows are marked exploratory and kept out of comparisons (`publish_benchmark_history.py:755-762`, `benchmark_history.py:1482-1488`).
- The live hardware is verified with sysctl.
- The gate pins the Speed variant and binds the OS and Xcode versions.
- The iOS simulated memory limit (`simulatedProcessLimitBytes`) is a good precedent for floor emulation.
- The per-request MLX peak is exact.

**#11 gap-1-01: no evidence path for the 8 GB floor after AV-17** (acc, high, M, consent: yes)
- **Evidence:**
  - Only the single canonical profile can publish (`publish_benchmark_history.py:137-164, 1258`), and `ui_test.sh:310-314` refuses the UI benchmark on the M2 before building.
  - Memory bands and the GPU ratio use the real RAM (`MacEngineBootstrap.swift:86-106`, `IOSMemorySnapshot.swift:179-180`).
  - On the M2, compressed memory reaches a median of 1.0-1.7 GB.
- **Mechanism:** A forced-floor run on the M6 changes policy values only, not pressure.
- **Corrected impact:** No tracked 8 GB evidence is possible after AV-17. Kernel pressure, compression and the 5.3 GiB Metal budget cannot be reproduced on the M6. Band transitions were never observed on the M2 either, because bands are checked only at admission and after generation. The README claims stay backed by M2 history, but no future regression at the floor would be caught (V-9).
- **Corrected fix:** Settle AV-17(6) explicitly.
  - Option (a), keep the M2:
    - add a support-floor role that publishes only floor-reference records in their own lineage;
    - fix the profile labelling in `check_macos_ui_bench.py:89-99`;
    - judge retention against the record's own profile.
  - Option (b), emulate on the M6:
    - add a registered simulated-memory knob, with claims limited to policy and footprint;
    - a pressure balloon would need a quiet-host exemption (4.4);
    - reuse `QVOICE_IOS_MEMORY_GUARD_FORCE_BAND` for the band paths.

  Either way, fix benchmarking-procedure.md:169 and telemetry-and-benchmarking.md:574-576.
- **Verify:** For (a), a floor-reference record in its own lineage with the chart check passing. For (b), rows show a working set of about 5,461 MB.

**#4 gap-1-06: sampled peaks depend on the tier's sampling cadence** (both, high, S, consent: yes)
- **Evidence:**
  - Sampling runs every 500 ms on the floor, 250 ms on mid and 100 ms on high (`SemanticTypes.swift:1024-1038`).
  - 52% of takes miss the GPU peak. In short warm takes the miss rate is 81% (engine) and 86% (UI).
  - The published footprint peak is below the exact MLX active peak in 320 of 427 and 317 of 392 of those takes, by a median of about 330 MB.
  - The only overhead record is exploratory and legacy.
- **Mechanism:** The sampling rate differs by tier.
- **Corrected impact:** Short-cell peaks read at least 0.33 GB low in 75-86% of takes. The M6's faster cadence changes the size of that shortfall, which confounds tier comparisons. The observer cost at 250 ms is unknown.
- **Corrected fix:**
  1. Do #3 part 1 and publish `peakCapture` (exact or bounded).
  2. Publish `gpuPeakCaptureMissMB` from existing fields.
  3. Change the cadence only if it is still needed; a fixed 250 ms contradicts the documented reasoning.
  4. Run `telemetry_overhead.py` in the AV-17 session.
  5. Land all of this before the re-seed.
- **Verify:** Recompute the miss rate offline. Afterwards, the ledger peak must be at least the sampled peak on every take.

**#19 gap-1-02: records and the gate baseline carry no tier or policy identity** (acc, medium, S, consent: no)
- **Evidence:** Rows stamp the tier and policy (`GenerationOutputAdapter.swift:2382-2387, 2458-2477`), but none of the 340 records carries it. The key and the gate identity leave it out, and save and compare never check forced rows (`summarize_generation_telemetry.py:1562-1566, 1822-1860`).
- **Mechanism:** The tier is only implied by the hardware profile.
- **Corrected impact:** History is protected because forced runs are exploratory. But the gate baseline could be seeded from forced-floor rows without anyone noticing, and a record cannot prove which tier it measured.
- **Corrected fix:**
  1. Refuse forced rows on save and compare.
  2. Add `deviceClass` to the gate identity.
  3. Add a run-level `runtimePolicy` provenance block.
  4. Do not key history on the policy.
- **Verify:** Fixture tests.

**#36 gap-1-03: TTFC, chunk cadence and cold RTF differ by tier policy** (acc, medium, S, consent: yes)
- **Evidence:** The floor raises the streaming interval to 0.6 s while mid keeps 0.32 s (`NativeMemoryPolicyResolver.swift:176-189`), so the first chunk is 7 frames on the floor and 4 on mid. The dedicated custom prewarm is skipped only on the floor.
- **Mechanism:** Policy, not hardware, changes the headline metrics.
- **Corrected impact:** Each record is accurate for its own tier. The risk lies in attributing M2-to-M6 differences: about 6-8% of cold RTF and 15-22% of warm TTFC come from policy. On the M6, cold latency and cold RTF can move in opposite directions. The "0.4 s on mid" figure is wrong.
- **Corrected fix:** An optional bridge run on the M6, native vs `--force-class 8gb` in alternating order, comparing timing only. Stamp the effective frame counts and the prewarm-skip flag in records.
- **Verify:** Minimum queue duration of 320 ms vs 560 ms.

**#26 gap-1-05: retained-memory-v1 misbehaves on the M6** (acc, medium, S, consent: yes). Combine with #25.
- **Evidence:** Growth is measured against 5% of the canonical profile's memory (`publish_benchmark_history.py:1161-1181`): 409.6 MB on the M2 but 819.2 MB on the M6. The end sample on mid comes with no trim.
- **Mechanism:** The threshold doubles, and the end value includes allocator cache.
- **Corrected impact:** The M6 limit becomes 819 MB, and the metric turns into "retained memory plus cache". The added noise is unmeasured.
- **Corrected fix:** retained-memory-v2, per the maintainer decision on AV-17(4):
  1. Subtract the MLX cache at the end.
  2. Use a fixed 410 MB threshold.
  3. Report v1 alongside and use a new policy ID.
- **Verify:** Fixture tests, then the first M6 memory lane.

**#17 gap-1-07: the UI benchmark never pins the model variant** (acc, medium, M, consent: yes)
- **Evidence:** The M6 tier recommends Quality first (`ModelManagerViewModel.swift:472-478`). The benchmark only checks that the Speed packages are ready, and the checker and charts ignore the variant.
- **Mechanism:** Which variant is measured depends on the tier, what is installed and stored preferences.
- **Corrected impact:** If Quality is installed, AV-17(2) would publish Quality numbers under a hardware-only label.
- **Corrected fix:**
  1. Make the checker fail on a variant other than a declared `QVOICE_MAC_BENCH_VARIANT` (default speed), and name the variant in the chart label.
  2. Then select the variant through the visible picker. Do not toggle "Prefer lower-memory", which clears stored choices.
- **Verify:** A checker test, then an M6 run where every take is Speed.

**#37 gap-1-08: the delivery envelope is sized for the floor but measured in a way that cannot qualify it** (both, medium, M, consent: yes). Overlaps #38, #101 and #102.
- **Evidence:** The supervisor polls RSS with `ps` every 50 ms, and its recovery criteria are relative to the host. The contract names the M6. The ASR footprint ceiling is never evaluated.
- **Mechanism:** RSS leaves out compressed memory, and the recovery allowance scales with host RAM.
- **Corrected impact:** Two M6 runs cannot qualify an envelope that claims to be floor-sized. The ASR footprint ceiling is a no-op, and polling costs about 20 process spawns per second.
- **Corrected fix:**
  1. Probe with `proc_pid_rusage` via ctypes and make footprint the binding ceiling.
  2. Fail closed if a ceiling has no sampler.
  3. Use absolute criteria and split the contract's host class into "measured on" and "sized for".
- **Verify:** A child that allocates N MB.

**#23 gap-1-09: key fragmentation, and fixes after the re-seed orphan the M6 baselines** (both, medium, M, consent: no). Merge with #22.
- **Evidence:** Engine sources and project.yml are in the key. Dropping them raises UI baselines from 7 to 18 and ui-perf from 17 to 22. For engine records, fragmentation comes from matrixHash (92 matrices).
- **Mechanism:** Every engine or project edit starts a new lineage.
- **Corrected impact:** Deltas disappear exactly when engine code changes, and any fix after the re-seed starts an M6 lineage with no baseline.
- **Corrected fix:**
  1. Sequence the code fixes, then the key change, then one consent session.
  2. Narrow the key, version it, and prefer a reviewed contract-version bump.
  3. Use canonical engine matrices.
  4. Update the release rules.
- **Verify:** An offline replay.

**#90 gap-1-04** (low, S, no). Same as #24; README.md:128 goes stale at the repin.

**#78 gap-1-10** (low, S, no). Same as #77, plus the derivation tool.

---

### 3.8 CI routing and evidence tests (gap-2)

**What is solid (keep)**
- Each lane is compared against its own last green run.
- The research marker comes from a single source.
- `validate --all` and `rebuild-index --check` run on Linux on every push.
- Local test selection deliberately over-selects.
- The publisher keeps the canonical-host proof separate from run conditions.
- Routing is pinned by tests.

**#8 gap-2-05: no test passes producer output through the history validator** (acc, high, M, consent: no)
- **Evidence:** The recording step is always faked (`test_publish_benchmark_history.py:400-408`), and the round-trip covers only instrument-profile. Four publication refusals (5ca95a73, ee97e92c, f069cee8, fcf2fe93) each forced a new consent-bound run while the darwin tests stayed green.
- **Mechanism:** Producers and the validator are each tested against their own hand-written fixtures.
- **Corrected impact:** Mismatches surface only at publication, at 14-17 minutes plus new run IDs each. Two of the four came from UI checker manifests.
- **Corrected fix:**
  1. Add round-trip tests for each publisher command and for the three UI checker manifests, calling `build_record` and `validate_record` in-process with the host probes mocked.
  2. Use fixture dates after the RTF cutover and realistic memory metrics.
  3. Include one canonical-size UI fixture that checks the 256 KiB cap.
- **Verify:** A mutation (renaming a metric) makes the new tests fail.

**#46 gap-2-01: the darwin-only tests never run in any scheduled job** (acc, medium, S, consent: no)
- **Evidence:**
  - All 55 tests carry skipUnless(darwin) (`test_benchmark_history.py:301-302`).
  - The Linux jobs deselect them (`ci.yml:173`), and the macOS job runs them only when the swift lane routes (`ci.yml:242-246`).
  - Nightly runs on Ubuntu, where they are skipped.
  - The quarantine note claims nightly runs them.
- **Mechanism:** Routing works from file-name lists, not from what the tests import.
- **Corrected impact:** No scheduled coverage at all, and the documented promise is false. The coverage actually lost is narrow, and no push has slipped through since MV-04.
- **Corrected fix:** After #47:
  1. Remove the skip and the DARWIN_ONLY_MODULES entry.
  2. Remove the darwin step from `ci.yml` in the same change, because an empty `-m darwin_only` selection makes pytest exit 5.
  3. Update conftest, pytest.ini, `check_project_inputs.sh`, `development_workflow.py`, development-workflow.md and release.md:24-26.
  4. Pair this with #8.
- **Verify:** 55 passed, 0 skipped on Linux.

**#47 gap-2-02: the darwin tests call real host probes** (both, medium, S, consent: no)
- **Evidence:** `build_record` always probes the host (`benchmark_history.py:1648`) with `swift -e` or `devicectl` (`:964-1015`), and the output is always discarded. One unmocked iOS test takes 8.62 s, and the whole step took 40.69 s in CI run 36098732171.
- **Mechanism:** This one call is the module's entire platform dependency.
- **Corrected impact:** About 35-40 s of macOS CI per push, a query to the paired iPhone from a unit test, and zero coverage of the probe's parsing.
- **Corrected fix:** Patch the probe in setUp and add a parsing test. Optionally probe only when a key is missing.
- **Verify:** Compare `pytest --durations` before and after.

**#91 gap-2-03: evidence and fixture paths send the full macOS lane through CI** (eff, low, S, consent: no)
- **Evidence:** Swift routing covers evidence paths, fixtures and `build_provenance.py`, none of which the macOS job reads. `jsonio` is an exception: every native build uses it indirectly (`build_paths.sh:16-24`). 12 of 19 pushes would have skipped the swift lane.
- **Mechanism:** Inputs of the darwin-only test module force the whole macOS lane to run.
- **Corrected impact:** About 12 avoidable runs in 12 days. That costs latency (3-5 minutes each), not money, and a darwin failure can mask the Swift results.
- **Corrected fix:**
  1. Drop the fixtures clause now.
  2. After #46 and #47, drop the remaining darwin-only inputs.
  3. Make the macOS script routing follow imports, including `jsonio`.
- **Verify:** Run `classify_changes.py` on evidence paths.

**#92 gap-2-04: research tests skip when shared libraries change** (acc, low, S, consent: no)
- **Evidence:** Research routing matches file-name prefixes (`classify_changes.py:117-122`) and misses shared libraries such as `jsonio` and `language_metrics`.
- **Mechanism:** Routing asks which files changed, not which tests import them.
- **Corrected impact:** CI and local routing disagree. Local checks and nightly catch it, and there has been one real exposure.
- **Corrected fix:** Route `scripts/lib/*.py` to research and add rows to the routing tests.
- **Verify:** `classify_changes.py` on a lib file reports research.

**#93 gap-2-06: the local check never selects registry tests for benchmark schema changes** (acc, low, S, consent: no)
- **Evidence:** A change to the benchmark schema or hardware profiles selects no tests locally (`development_workflow.py:98-99`).
- **Mechanism:** `benchmarks/` is not in the local selection inputs.
- **Corrected impact:** An early local signal is missed; CI still runs the tests.
- **Corrected fix:** Include top-level `benchmarks/*.json`, but not `runs/**`.
- **Verify:** `check --dry-run` lists `test_benchmark_history`.

**#94 gap-2-07: validator tests read live records** (both, low, S, consent: no)
- **Evidence:** `test_benchmark_history.py:572-578` and `:1133-1150` glob the newest committed records.
- **Mechanism:** The fixtures change with every publication.
- **Corrected impact:** The tests break if records are pruned, and they are part of why evidence pushes route to the macOS lane.
- **Corrected fix:** Freeze a v3 UI fixture and a ui-perf fixture.
- **Verify:** A new record changes no test input.

---

### 3.9 Instruments profiles and signposts (gap-3)

**What is solid (keep)**
- Traces attach to the exact process ID and are verified per row.
- Every take requires correlation fields.
- Summaries are written before deletion, with a digest re-check.
- The environment passed to the target is allowlisted.
- The fresh build is bound to its digest.
- The macOS Allocations template has an auto-snapshot guard.
- Profile records are never canonical.
- The emitters already carry privacy-safe correlation.
- There is room to extend: about 36 intervals per token, with records of 13-39 KB.

**#12 gap-3-1: the trace summary discards every signpost duration** (acc, high, M, consent: yes)
- **Evidence:**
  - The signpost branch only counts rows (`publish_benchmark_history.py:3086-3124`), and no interval field is allowed (`benchmark_history.py:194-200`).
  - Traces are deleted by default (`macos_test.sh:494-495, 628-647`).
  - Mac traces show 37.06 intervals per token. iOS shows 34.5-34.75 per token (fewer than the 36 emitted) and 29-70 orphan rows.
- **Mechanism:** Extraction was built as a presence gate.
- **Corrected impact:**
  - The only kernel-timestamped per-stage witness is lost every time.
  - As proposed, the GPU wait would show up only as an unlabelled gap (V-2), and iOS statistics would be computed from incomplete sets.
  - All values are taken under CPU Profiler, so they are witnesses within one run only.
- **Corrected fix:**
  1. Parse interval rows and assign uncorrelated intervals to a take by containment.
  2. Require at least 36×(tokens+1) intervals per take, count orphans, and warn or fail on a shortfall.
  3. Publish the uncovered in-loop time, or add a Token Read signpost.
  4. Keep full statistics untracked and publish a small versioned block.
  5. Fix the comment at `macos_test.sh:399-401`.
- **Verify:** A synthetic XML fixture, then one requested `--keep-trace` profile.

**#48 gap-3-2: in-process timings are never reconciled with signposts** (acc, medium, M, consent: yes)
- **Evidence:** `withMirroredSignpost` has no caller. The prepare timing is captured before the interval closes (`NativeEngineRuntime.swift:1027` vs the defer at scope exit). The first-chunk event fires before the chunk is handed off (`GenerationOutputAdapter.swift:1574` vs `:1686`).
- **Mechanism:** The trace and the JSONL are never joined.
- **Corrected impact:** Drift between the pairs and the observer's lag are both unmeasured. The 578 ms vs 479 ms example is confounded. The prepare timing is not published.
- **Corrected fix:**
  1. Capture each timing in the same defer that closes its interval.
  2. Measure observer lag in every bench with no Instruments: `ttfcObserverLagMS` = the CLI's first-chunk uptime minus the v9 chunk-0 `previewPublishedAtNS`.
  3. Add an optional witness block that only warns.
- **Verify:** Join and defer tests.

**#49 gap-3-3: v9 MLX instants are computed backwards** (acc, medium, S, consent: yes). Same as #62.
- **Area notes:** The duration is zero under every policy. The real sync point is the token read at :3759, so recording EOS Read as the wait would still give about 0. Fix: time the token read with a signpost, carry nanoseconds, flag the instants as derived and bump the bridge version. Verify with a test that the wait is above 0 under `.pipelined` and that ordering holds.

**#95 gap-3-4** (acc, low, S, yes). Same as #61.

**#50 gap-3-5: there is no low-perturbation witness profile** (acc, medium, M, consent: yes)
- **Evidence:** Same-binary pairs:

  | Pair | Profiled | Unprofiled |
  |---|---|---|
  | Mac memory profile, warm tokens/s | 3.29 | 12.74-12.98 |
  | CPU profile, cold tokens/s | 13.87 | 19.56 |
  | CPU profile, cold TTFC | 3,563 ms | 2,364 ms |
  | iOS memory profile, cold tokens/s | 4.58 | 22.64 |
  | iOS memory profile, peak footprint | 2,665 MB | 2,628 MB |

  All three memory profiles used VM Tracker auto-snapshots. The records are already labelled instrumented or exploratory.
- **Mechanism:** Instruments perturb the process they measure.
- **Corrected impact:** The metrics are honestly labelled. The real gap is that no low-perturbation witness mode exists.
- **Corrected fix:**
  1. Add `profile --kind witness`: os_signpost only, `--warm 3`, exploratory.
  2. Keep `memoryQualified` (native.md:147) and add a perturbation annotation.
  3. Re-measure Allocations with one post-fix macOS profile.
- **Verify:** Witness warm tokens/s is within about 1% of the gate bench.

**#51 gap-3-6: the iOS memory profile keeps standalone VM Tracker** (acc, medium, S, consent: yes)
- **Evidence:** `ios_device.sh:2133` adds standalone VM Tracker, and the guard is not passed (`publish_benchmark_history.py:3562-3566`). The contract test pins this unguarded setup. Sampler lateness is 414 ms profiled vs 5.7-48 ms unprofiled.
- **Mechanism:** The macOS fix (d52340a0) never reached iOS.
- **Corrected impact:** This is the lane cited as iPhone acceptance evidence. Lateness is about 10× normal, and throughput is contaminated.
- **Corrected fix:** Use the Allocations template with CPU Profiler and os_signpost, pass the guard, flip the test, and confirm on one device capture.
- **Verify:** A guard test, then lateness back near about 50 ms.

**#52 gap-3-7: the iOS profile records its full window, then sleeps 10 s** (both, medium, M, consent: yes)
- **Evidence:** A fixed `--time-limit` with an app that never exits, then a 10 s sleep (`ios_device.sh:2235-2261, 842-845`). A 30 s window recorded a 3.4 s take, and a truncated take still validates.
- **Mechanism:** Recording stops only at the time limit.
- **Corrected impact:** Tens of idle seconds per profile, 60-89% idle samples, and truncation goes undetected.
- **Corrected fix:**
  1. Drop the 10 s sleep.
  2. Optionally stop early: once the success sentinel appears, pull, then terminate the process.
  3. Add the completeness check from #12.
- **Verify:** The trace span roughly equals the take's wall time.

**#96 gap-3-8: summary counts are misnamed** (acc, low, S, consent: no)
- **Evidence:** `signpostEventCount` sums every signpost schema (17,245), and `durationSeconds` is the requested limit (90 s for a 12 s run).
- **Mechanism:** Counts built for a non-empty check are published as if they were measurements.
- **Corrected impact:** Misleading, but nothing reads them.
- **Corrected fix:** A versioned summary with interval, begin, end and point counts, orphan counts and the real trace duration.
- **Verify:** Fixture tests.

**#97 gap-3-9: the two CPU witnesses disagree on the -O Mac profile** (acc, low, M, consent: yes)
- **Evidence:** Cycles per rusage CPU-second: 0.651 GHz on the -O Mac profile vs 2.04-2.43 GHz on -Onone, and 1.04 GHz on the -Onone iOS profile. The -O record also ran a different OS version.
- **Mechanism:** Unknown. The candidates are dropped rows, kernel or E-core effects, or an OS change.
- **Corrected impact:** An unexplained inconsistency that cannot be diagnosed because the trace was deleted.
- **Corrected fix:** Add a per-take plausibility metric and a count of dropped rows. Fail or warn without keeping the trace automatically. Keep symbol frames untracked.
- **Verify:** Fixtures, then one kept trace.

**#98 gap-3-10: no GPU instrument in any lane** (acc, low, L, consent: yes)
- **Evidence:** No lane records a GPU instrument, although Metal System Trace is available. The loop is launch-bound (`Qwen3TTS.swift:3834`).
- **Mechanism:** The lanes were designed for CPU and memory.
- **Corrected impact:** GPU busy and idle time is unmeasured. A per-stage GPU split is not possible anyway because steps are fused, and the in-process token-read timer is cheaper.
- **Corrected fix:** Add the token-read timer first (V-2). Then, if needed, add an exploratory `--kind gpu`.
- **Verify:** One requested GPU profile.

**#99 gap-3-11: profile lanes skip the quiet-host check and record one warm take** (acc, low, S, consent: no)
- **Evidence:** `profile` dispatches straight to cmd_profile (`macos_test.sh:1425`), with `profile_warm="1"`. Five of the six profile records are from dirty trees.
- **Mechanism:** Profile lanes are treated as diagnostics.
- **Corrected impact:** This matters only once profiles are cited as timing witnesses.
- **Corrected fix:** Apply the quiet-host check and `--warm 3` to the witness kind, and refuse a dirty tree without an explicit flag.
- **Verify:** Contract tests.

**#100 gap-3-12: trace export and hashing repeat work** (eff, low, S, consent: no)
- **Evidence:** One export per schema, each parsed into a full DOM, and the bundle hashed twice.
- **Mechanism:** Each step validates on its own.
- **Corrected impact:** Seconds per profile, plus peak Python memory.
- **Corrected fix:** Stream the parse, trial a single multi-table export, and keep the full re-hash, which is an integrity gate.
- **Verify:** Identical summaries, and timing.

---

### 3.10 Delivery and prosody evaluation (gap-4)

**What is solid (keep)**
- Takes come from the immutable manifest, with a check of the instruction-receipt digest and atomic writes.
- The publisher refuses takes that lack verdicts.
- Swift composition fails closed.
- The supervisor's process ownership is careful: an inherited lock, bounded shutdown, and exit confirmed by reaping.
- The statistics are deterministic and exact.
- Separability testing uses seed-grouped folds and a permutation null.
- `analyze_prosody` is fast and already emits semitone features.
- Pairing uses the same seed.

**#9 gap-4-01: deliveryProsodyEffect is absolute, not paired** (acc, high, M, consent: no)
- **Evidence:**
  - `bench_delivery_prosody.py:443-452` passes absolute metrics where deltas are required (`prosody_profile.py:395-409`). The deleted `delivery_adherence.py` computed deltas, so this is a regression.
  - The absolute formula reproduces the published values exactly (error 3.6e-15), while the paired values differ by a median of 8.42.
  - Median published vs paired values: neutral 8.79 vs −0.06, dramatic 8.94 vs 1.11, excited 9.05 vs 1.49.
- **Mechanism:** The wrong dictionary is passed.
- **Corrected impact:** All 902 takes carry a mislabelled metric. No gate reads it, and the promotion contract only checks that it exists. The comment at `EmotionPreset.swift:521-523` cites the wrong numbers.
- **Corrected fix:**
  1. Compute from deltas under a new key, `deliveryPairedProsodyEffect`.
  2. In the same commit, update the contract's `metricKeys`, the allowlist, the summarizer label and the Swift comment.
  3. Add a unit test.
- **Verify:** The new field equals the delta formula, checked offline.

**#7 gap-4-02: the supervisor's swap probe fails under the fr_CA locale** (both, high, S, consent: no)
- **Evidence:**
  - Under `LANG=fr_CA.UTF-8`, `sysctl` prints "0,00M", which the regex at `delivery_resource_supervisor.py:149` rejects. A trivial supervised child then comes back unqualified.
  - Under `LC_ALL=C`, the same child comes back qualified.
  - ASR raises on an unqualified result (`independent_asr.py:419-437`). The compact adapter fails the same way.
- **Mechanism:** The decimal separator follows the locale.
- **Corrected impact:** On the M6, every uncached ASR run and every compact qualification fails closed.
- **Corrected fix:**
  1. Run probes under `LC_ALL=C`, or read the swap struct through ctypes.
  2. Type parse failures separately.
  3. Add tests with fr_CA-formatted output.
  4. Batch this with #38 and #102 before AV-17(5) (V-12).
- **Verify:** Qualified under fr_CA.

**#38 gap-4-03: the supervisor spawns processes on every tick** (both, medium, M, consent: no)
- **Evidence:**
  - `ps` runs every tick, and failures return 0 without being recorded (`delivery_resource_supervisor.py:156-164`).
  - The footprint parser ignores the lifetime peak.
  - The envelope has no sample count.
  - Measured costs: `ps` 1.4 ms, `footprint` 10.7 ms, `proc_pid_rusage` 0.4 µs.
- **Mechanism:** Peaks come from subprocess samples.
- **Corrected impact:** Production callers poll about every 52 ms with `ps` only, and any spike between samples is invisible. `ps` failures silently lower coverage. The 126 ms tick and the 7,000 files apply only to diagnostic footprint runs.
- **Corrected fix:**
  1. Sample in-process with `proc_pid_rusage` at 50 ms.
  2. Take the peak as the maximum of the samples and the lifetime maximum, and record `ru_maxrss` from `wait4` separately.
  3. Add sample count, interval and failure count.
  4. Name this owned-process-probe-v3.
- **Verify:** A child with scripted spikes.

**#101 gap-4-04: the ASR footprint ceiling is never evaluated** (acc, low, S, consent: no)
- **Evidence:** A ceiling is passed with no sampler (`independent_asr.py:419-425`). Whisper runs on the GPU. The envelope already reports that footprint measurement was not requested.
- **Mechanism:** Footprint sampling is opt-in, and ASR never opted in.
- **Corrected impact:** Whisper's Metal memory is unmeasured, which is a modest risk. The printed ceiling is misleading.
- **Corrected fix:** After #38, measure footprint by default for MLX callers. Mark the ceiling not-evaluated when nothing was measured.
- **Verify:** A toy MLX child.

**#102 gap-4-05: post-exit recovery is judged on a host-wide percentage** (both, low, M, consent: no)
- **Evidence:** The supervisor warns below 10% free, while the timing lanes use the kernel pressure level. Recovery must return within 5 points. `memory_pressure` reports `kern.memorystatus_level`. The 5-point rule is a recorded decision.
- **Mechanism:** A whole-host metric is measured after the child has already exited.
- **Corrected impact:** Unqualified results are unattributed rather than proven false. On 8 GB, the rule partly measures the child's own compression.
- **Corrected fix:** Do not relax the rule yet. First add attribution fields and a kernel pressure level, measure on the M6, and only then propose a rule change.
- **Verify:** A synthetic child with a concurrent allocator.

**#39 gap-4-06: per-take adherence flags saturate the warnings** (acc, medium, M, consent: yes)
- **Evidence:** 460 of 902 takes are flagged, and 96 of 108 records warn. Floors derived from the 10th percentile produce flag rates of 9-38%. After 1a0d263d, the derivation rule is stale.
- **Mechanism:** One noisy pair per take is judged against a set of floors.
- **Corrected impact:** A regression is invisible. Many flags are true misses by design.
- **Corrected fix:**
  1. Keep per-take flags as diagnostics.
  2. Add a cell-level summary using `paired_report`.
  3. Re-derive the floors and bump the algorithm version.
  4. This needs a maintainer decision and matching Swift changes.
- **Verify:** Replay DP-22/23 offline, then one pre-registered run.

**#40 gap-4-07: features measured in Hz and seconds were calibrated on one speaker and one text** (acc, medium, L, consent: yes)
- **Evidence:** Arousal and pitch floors use raw Hz and seconds (`prosody_profile.py:413-425, 126-176`) and were calibrated on Aiden at about 146 Hz. They are applied across 9 speakers and 3 lengths.
- **Mechanism:** The same movement in semitones produces larger Hz deltas for higher voices.
- **Corrected impact:** Pass rates plausibly depend on the speaker and the script length. The size of the effect is unmeasured.
- **Corrected fix:** Measure pitch in semitones and duration as ratios, quantify the confound offline, re-fit the floors and version the profile.
- **Verify:** Compare per-speaker distributions.

**#41 gap-4-08: the prosody gate is inert but composes as PASS** (acc, medium, M, consent: no)
- **Evidence:** One flag in 902 takes. Three of the flags need values outside the observed range. The only calibration uses 2+2 clips with a TPR of 0.5. Having no flags maps to a pass.
- **Mechanism:** The thresholds sit outside the data, and sensitivity has never been measured.
- **Corrected impact:** "prosody: pass" claims more than the gate can observe.
- **Corrected fix:** Feed AV-07:
  1. a perturbation suite with a detection curve for each flag;
  2. `calibrationStatus` and fixture TPR fields;
  3. a monotone check in semitones.
- **Verify:** Offline fixtures.

**#103 gap-4-09: the clone identity lane cannot calibrate its bands** (acc, low, M, consent: yes)
- **Evidence:**
  - Only 2 controls, one of them cross-gender.
  - Controls are scored by ECAPA only.
  - `np.interp` resampling (`clone_speaker_similarity.py:156-160`).
  - An upper median.
  - An online model fetch.
- **Mechanism:** Too few and too easy negatives, plus aliasing.
- **Corrected impact:** The lane is advisory and publishes nothing.
- **Corrected fix:**
  1. At least 8 matched controls plus cross-clone negatives.
  2. AUC and EER with confidence intervals.
  3. The pinned resampler and a true median.
  4. Offline model loading.
- **Verify:** Offline code checks, then consented takes.

**#104 gap-4-10: delivery sweeps pay for cold takes, and sidecar joins are loose** (eff, low, M, consent: yes)
- **Evidence:** Cold takes are never paired but cost about 11.5% of run time. Joins use (mode, model, delivery), and parse errors are swallowed.
- **Mechanism:** Defaults built for the timing matrix are reused unchanged.
- **Corrected impact:** About 9-10% of sweep time is wasted, and a stale sidecar is accepted.
- **Corrected fix:** Join on generationID and assert the runID, and report parse errors. A no-cold mode is optional. Batching needs a design note.
- **Verify:** Join tests.

**#105 gap-4-11: the neutral outlier test cannot fire** (acc, low, S, consent: no)
- **Evidence:** A population SD that includes the candidate (`delivery_quality_gate.py:319-329`). By Samuelson's bound, |z| can be at most √(n−1).
- **Mechanism:** The candidate is included in the spread that judges it.
- **Corrected impact:** The check cannot fire at n ≤ 7.
- **Corrected fix:** A leave-one-out robust score, plus tests.
- **Verify:** Unit tests at n=4 and n=8.

**#106 gap-4-12: small-sample statistics discard pairing** (acc, low, S, consent: no)
- **Evidence:** A percentile bootstrap is used where BCa is available, and the overhead lane compares unpaired medians. The exact Wilcoxon test already exists (`delivery_statistics.py:97-150`).
- **Mechanism:** Tiny samples with the pairing thrown away.
- **Corrected impact:** Overhead verdicts carry no uncertainty.
- **Corrected fix:** Report paired intervals as annotations. Estimate between-run noise before changing the gate MAD.
- **Verify:** Unit tests.

---

## 4. Recommended sequence

### 4.1 Code-only first (no consent-bound lane), in this order

**Stage A: stop publishing wrong or misleading numbers**
1. **#1/#2:** single-series memory qualification for macOS UI records, with the test fixture and docs. This includes a rules change (4.4).
2. **#24/#90:** reclassify the routine cache clear.
3. **#3 part 3:** add a validator warning for missed peaks and backfill it offline.
4. **V-1:** fix the iOS checker's identity loop.
5. **#9:** add the paired prosody key and update the contract, allowlist and comment.
6. **#59, #58, #60:** add `ttfcDefinition`, the startup-window keys and the ContinuousClock fix.
7. **#10:** add the warn-only speaking-rate flag (a QC version bump).
8. **V-4:** give the iOS memory thresholds a single source.

**Stage B: make the AV-17 session succeed the first time**

Most of these files are in harnessHash or the baseline identity, so they must land before the re-seed.

- **Engine gate:**
  - #53 (preflight and ledger);
  - #54 (INCONCLUSIVE, the quiet-host re-check, per-take load, low power);
  - #13 (seed);
  - #14 (governed seed mode, identity from evidence);
  - #15 (`engineFirstChunkMS`);
  - #5 (spread floors, `mlxPeakMB`, printed thresholds);
  - #55 (Clone prewarm);
  - #57;
  - V-5 and V-7.
- **CLI bench:**
  - #20 (sidecar budget);
  - #19 (refuse forced rows; provenance);
  - #27 (split the telemetry and debug switches; Swift unit test).
- **Sampler (Swift, unit-testable):**
  - #3 parts 1-2 (ledger fields, per-stage MLX peaks);
  - #4 (the peak-miss metric);
  - #64/#65 (port release, capture duration);
  - #67.
- **UI lanes:**
  - #6 (stall contract plus the "rows not yet present" exit code);
  - #21;
  - #18, after #6;
  - #17 (the checker's variant check);
  - #28 part 1;
  - #77/#78;
  - #33(a);
  - #80 (stop the mis-scoped mapping);
  - V-3.
- **Delivery supervisor, as one batch because of V-12:** #7, #38, #101, and the attribution fields from #102.

**Stage C: CI and evidence tests (independent; can run in parallel)**
- #47, then #46, then #8, then #91; then #92, #93, #94 and #73.

**Stage D: identity changes, last before the re-seed**
1. #22 and #23, with #34(c)(d): per-kind path lists, a project.yml subset, topology in the key, the key versioned by schemaVersion, and the base test files added.
2. Then #71 (noise band and UI TTFC in HISTORY).

**Any time (code only):**
- **Audio:** #43, #84, #85, #89, the code parts of #42 and #44, and part 1 of #86.
- **Delivery:** #105, #106, the join fix in #104, and the code fixes in #103.
- **Profiles:** #96, #99, #100, the V-2 token-read timer, #61/#95, and #62/#49.
- **UI responsiveness:** #83 and #79.
- **Memory:** #70.
- **Telemetry:** the paired statistics from #63.

### 4.2 One explicitly requested AV-17 session validates

Run the lanes serially in the lead session, with nothing else running.

- **Gate bench, at least 3 seeded runs on identical source:** confirms #5, #13, #14, #15 and #16. Optionally add the ABAB tier bridge from #36, timing only.
- **telemetry_overhead.py at the M6 cadence (local verdict):** confirms #27, #63 and #4.
- **First canonical M6 UI benchmark:** confirms #1 (peak over `mlxPeakMB` near 1.0), #6 (calibration), #18, #17 (all Speed) and #28. Update the website copy at the same time (V-9).
- **Three ui-perf sessions:** confirm #77/#78, #33 and #34.
- **Memory lane:** confirms #3 (kernel peak at or above `mlxPeakMB`), #25/#26 (v1 and v2 side by side, terminal cache) and #66.
- **Delivery and compact requalification, AV-17(5):** only after the supervisor batch lands.
- **M6 lang-bench, after #7:** confirms #44, #42 and #10 on live output.

### 4.3 Later consent-bound work (separate requests)

- **UI benchmark:** #29 (seed knob), #30, #31 (runner stamps first), #74.
- **UI responsiveness:** #32, #35, #82.
- **Profiles:** #50, #51, #52, #97, #98 and #12, which needs one kept trace.
- **iOS device polling:** #45, #56, #87.
- **Delivery:** #39, #40, #103, #104.
- **Language:** #88, and #86 part 3.
- **Floor lane:** #11, whichever option is chosen.

### 4.4 Changes to `.claude/rules` contracts (maintainer decision required)

1. **native.md:71-73 and :119.** Currently: "process memory belongs to the process that measured it", and pair samples by uptime. Change to: one process gets one memory series, and the app layer is required only for frontend timings. Needed for #1/#2.
2. **native.md:142-144 and release.md:91-93.** Replace the ≥95% coverage rule with a maximum unobserved gap plus a peak-fidelity criterion (#66).
3. **release.md:109-113 and host_preflight.sh.** Optional stricter per-take load limit that marks timing records exploratory (#28 part 3). Also a recorded quiet-host exemption for any pressure-balloon floor emulation (#11 option b).
4. **release.md:133-136.** Publish medians pooled across recent canonical records instead of repinning to the newest record (#72).
5. **release.md:86-88 and the comparison-key text.** Narrow the comparison key (#22, #23, #34). Legacy keys stay byte-identical, and a rule is added for bumping the contract version.
6. **release.md:84-85.** Keep memory-profile traces by default (#69 option a).
7. **release.md:89** (plus the CONV-21 gate text and benchmarking-procedure.md). Only if the gate moves to 5 warm takes (#5, optional).
8. **release.md:24-26.** Describe the darwin-only lane accurately after #46. Wording only.

Do not change:
- release.md's explicit keep-trace rule: rejected as the #97 auto-keep.
- native.md:147 on `memoryQualified`: rejected as proposed in #50.

#54, #60 and #13 bring the code into line with existing rules (release.md:89-90, native.md:70, release.md:95).

### 4.5 Other maintainer decisions (outside `.claude/rules`)

- **Memory policy:**
  - AV-17(4): retained-memory-v2 (#25, #26).
  - AV-17(6): the floor evidence path (#11).
  - iOS memory gates based on the measured budget (#68).
- **UI lanes:**
  - The statistic and provisional tolerance for the stall gate (#6).
  - Whether sidebar-navigation is "navigation with product warms" or pure UI (#33).
  - The UI matrix reallocation and the 29-take assertion (#30).
  - Capturing only one repetition per cell (#31).
  - The seed knob (knob registry and runtime-security contract, #29).
  - ui-perf ceilings derived from the spread between runs (#34).
- **Audio and delivery, under the threshold-change authority in audio-qc-engineering.md:**
  - Language: per-channel consensus and re-declaring the negative control (#42), seed identity v2 (#86) and WER v2 (#43).
  - Speaking-rate and click fail bounds (#10, #85).
  - Delivery: a cell-level adherence verdict and floor re-derivation (#39), the supervisor recovery rule (#102), and the "uncalibrated" prosody composition (#41).

---

## 5. Proposed roadmap items

| Item | Scope | Gate |
|---|---|---|
| **1. Trustworthy memory evidence** | #1, #2, #3, #4, #16, #24, #25, #26, #64, #65, #66, #67, #68, #70, #90, V-4 | Offline replay puts the 8 in-process macOS UI records near 1.0 (peak over `mlxPeakMB`), routine clears raise no warnings, every committed record reports a peak-missed count, and all legacy records still validate; the next consented memory lane shows the kernel peak at or above `mlxPeakMB` on every take |
| **2. Engine gate and CLI bench ready for the M6 re-seed** | #5, #11, #13, #14, #15, #19, #20, #27, #36, #53, #54, #55, #57, #58, #59, #63, V-5, V-6, V-7 | Offline comparator replay shows no false regression and flags a synthetic +6% RTF, a gate with a missing model stops within seconds with a finalized ledger, and the AV-17 session seeds the M6 baseline from at least 3 seeded runs on identical source with the thresholds printed |
| **3. UI benchmark and ui-perf lanes ready for the M6** | #6, #17, #18, #21, #28-#35, #72, #74, #75, #77-#83, V-1, V-3, V-8, V-9 | The first canonical M6 UI benchmark validates in one pass under a declared stall contract with every take on the Speed variant, and M6 perf records carry an M6 calibration profile rather than M2 verdicts |
| **4. Lineage identity, history and CI evidence tests** | #8, #22, #23, #46, #47, #71, #73, #76, #91-#94 | Offline key replay links at least 9 of 16 canonical macOS UI records with legacy keys unchanged, `test_benchmark_history` runs 55 passed and 0 skipped on Linux, and every manifest producer round-trips through `validate_record` |
| **5. Audio, language and delivery QC accuracy** | #7, #9, #10, #37-#44, #84-#86, #88, #89, #101-#106, V-10, V-11, V-12 | Offline replay flags the known run-on takes and reproduces the paired prosody effects from the deliveryD* deltas exactly, a supervised run under fr_CA returns qualified, and the next lang-bench publishes a per-channel verdict from two families |
| **6. Timing attribution, profiles and device-lane observers** | #12, #45, #48-#52, #56, #60-#62, #69, #87, #95-#100, V-2 | The token read has its own timer and signpost, a kept-trace macOS profile publishes per-take interval statistics that pass the 36×(tokens+1) completeness check, the iOS memory profile passes the VM auto-snapshot guard, and the iOS memory, clone-conditioning and gate waits poll only the sentinel and check that the process is alive |

Items 1-4 (and the supervisor batch in item 5) must land before the AV-17 consent session. Items 5 and 6 then continue as normal code-only work plus separately requested runs.

### Addendum: findings whose sections were lost

The surviving body keeps only one-line stubs for these five duplicates. Their fuller sections follow. Each should be fixed together with the finding it duplicates.

**#2 memory-probes-macos-inprocess-double-count: macOS UI memory totals count one process twice** (acc, high, S, consent: no; duplicate of #1)
- **Evidence:**
  - `benchmark_memory.py:886-901` sums the engine and app resident, footprint, compressed and GPU values for each uptime pair. `qualify_take_memory` (`:971-996`) takes that path when `require_app_layer=True`, which `check_macos_ui_bench.py:640-646` and `:1064-1070` pass.
  - `check_macos_ui_bench.py:723` then overwrites the engine-only values computed at `:453-462`, while the same checker requires app PID == engine PID (`:383-391`).
  - `AppGenerationTimeline.swift:303-315` still builds a macOS-only app sampler. `IOSMemorySnapshot.capture` (`IOSMemorySnapshot.swift:156-183`) reads the calling task and the default Metal device, so both samplers report the same process.
  - The median ratio of peak footprint to mlxPeakMB is 1.022 before CONV-03 (914 takes) and 1.837 after it (14 takes in 8 records).
  - Correction: memoryContractVersion is not part of `comparison_key` (`benchmark_history.py:1429-1470`). harnessHash already covers `benchmark_memory.py`, so the 8 doubled records started their own lineage, and no doubled RAM delta against the earlier era was ever published.
- **Mechanism:** After the XPC engine was removed, the app sampler and the engine sampler measure the same task and Metal device, and pairing them by uptime adds the two.
- **Corrected impact:**
  - The absolute memory values in the 8 records are about 1.8× the real values, and Metal ratios exceed 1.0 on an 8 GB Mac. Percentage trends inside the doubled era roughly hold, because both terms double.
  - The next canonical macOS UI record would publish doubled absolutes as the headline Mac memory figure.
  - The memory-qualification lane (ratios 0.91-1.06) and iOS (`check_ios_ui_benchmark.py:371`) are engine-only and unaffected.
- **Corrected fix:** The same as #1: when the process IDs match, build one series from the union of both layers' samples and never sum. Editing `benchmark_memory.py` already changes harnessHash, so no contract-version bump is needed to separate lineages. Leave the 8 records as they are.
- **Verify:** As for #1.

**#65 memory-probes-probe-cost-threads: thread ports leak, and the probe's own cost is unmeasured** (both, low, S, consent: no; duplicate of #64)
- **Evidence:**
  - `NativeTelemetrySampler.swift:1245-1262` frees the task_threads array but never releases the per-thread send rights. `mach_port_deallocate` appears nowhere in Sources or Packages.
  - Only threadCaptureFailureCount uses the thread data (`:959`, `:1061`).
  - About 19-20 boundary samples per take are awaited inline, each through two actor hops.
  - The sampler runs only when TelemetryGate is enabled (`TelemetryGate.swift:31-36`), so shipped users are unaffected.
  - Correction: the only overhead record (schema v7, exploratory) uses the legacy speedup RTF, where higher is faster. Lightweight was therefore about 2.3% slower than off, not faster.
- **Mechanism:** Each task_threads call adds a reference to every thread's send right, and nothing releases them. The capture cost on the generation path is never recorded.
- **Corrected impact:** A minor leak in telemetry-enabled processes, bounded by thread churn. The critical-path cost of boundary captures in v8 records is unmeasured, and the only hint (legacy and noisy) is about a 2% cost.
- **Corrected fix:**
  1. Deallocate each returned thread port, or capture the thread count only in the start and stop samples. The second option also removes the heaviest call from each tick.
  2. Add `captureDurationNS` to each sample and `boundaryCaptureTotalNS` to each take, timed with ContinuousClock.
  3. Add a schema note, because the thread-coverage fields change meaning.
- **Verify:** A unit test that the reference count of `mach_thread_self()` does not grow across 100 samples.

**#78 gap-1-10: ui-perf declares an M2 calibration profile that no code checks** (acc, low, S, consent: no; duplicate of #77)
- **Evidence:**
  - `config/ui-perf-thresholds.json` sets calibrationProfile "mac-mini-m2-8gb" and describes itself as provisional on mac-mini-m6-16gb. No code consumes the field. `load_thresholds` validates only schemaVersion, warnOnly and scenario coverage (`check_macos_ui_perf.py:246-256`).
  - All 333 M2 perf cells ran at a refresh interval of 16.67 ms (60 Hz).
  - The documented rule reproduces the committed ceilings from records 0bb33592, 636488c2 and 64610737:
    - hitch 224.42, 232.90 and 36.73 become 224.5, 233.0 and 37.0;
    - gap 345.3, 117.68, 155.31 and 45.46 become 350, 120, 160 and 50.
  - No tool performs this derivation.
- **Mechanism:** Calibration metadata is declared but never checked, and the display refresh rate is not bound.
- **Corrected impact:** Until AV-17(3) is done by hand, M6 perf sessions are scored warn-only against M2 ceilings, which a faster host rarely breaches. The ms-based gap floors change meaning if the attached display runs above 60 Hz.
- **Corrected fix:**
  1. Emit one uncalibrated warning, shared with #77, when calibrationProfile differs from the verified profile, or when the observed refresh interval differs from a new calibrationRefreshIntervalMS.
  2. Add `--derive-thresholds <record ids>` to reproduce the committed ceilings.
- **Verify:** A fixture with a mismatched profile emits the warning, and a regression test shows the derivation reproduces the ceilings from the three records.

**#90 gap-1-04: the routine cache clear reads as pressure on the floor** (acc, low, S, consent: no; duplicate of #24)
- **Evidence:**
  - `GenerationOutputAdapter.swift:2003-2016` emits a softTrim with reason post_generation_cache_clear and source `.postGeneration` only when clearCacheAfterGeneration is set. That is the floor single-take case (`NativeMemoryPolicyResolver.swift:47`); on mid the flag is false (`:57`).
  - `benchmark_memory.py:311-314` and `:337-343` raise the pressure level and add the warning for every softTrim, ignoring the source and reasonCode that the typed event carries (`GenerationTelemetryRecord.swift:666-675`).
  - All 3,029 macOS takes are qualifiedWithWarnings. 3,027 of them have one trim, no pressure event and pressure level 1.
  - README.md:128 explains the pinned record's warnings as "accepted memory soft trims".
  - Corrections:
    - Real pressure signals are counted separately (`benchmark_memory.py:315-316`), so the 2 takes with real pressure can be told apart today.
    - The M6's flip to "passed" is the accurate reading, and M2 and M6 records are never compared.
- **Mechanism:** A policy-driven cache clear is recorded as a trim action, and every trim counts as pressure.
- **Corrected impact:** Floor records overstate pressure on every take. The first M6 records will read "passed", which is correct for that tier. The README.md:128 explanation must be rewritten at the AV-17(2) repin anyway.
- **Corrected fix:**
  1. Merge into #24: classify trim events by source and reasonCode, and publish routine clears as a count with no pressure level.
  2. Apply this to new records only, and land it before the re-seed, because `benchmark_memory.py` is in harnessHash.
  3. Rewrite README.md:128 at the repin. The rule in release.md:91-94 is unaffected.
- **Verify:** As for #24.

**#95 gap-3-4: per-step integer-ms rounding biases the substage sums** (acc, low, S, consent: yes; duplicate of #61)
- **Evidence:**
  - `Qwen3TTS.swift:6174-6185` rounds per-step values to whole milliseconds, and they are summed per step at `:3670` and `:3697`. `Engine.swift:1827-1832` truncates instead.
  - Refuted parts:
    - The per-step bias does not reach `qwen_token_loop_unattributed`. That key (`:3423-3433`) subtracts the loop-level code-predictor total, which is rounded once per token.
    - The per-step keys and the enqueue/wait keys have no consumer anywhere; only the producer lines at `:3441-3446` reference them.
    - The Engine.swift truncation applies to single observations of 1 ms or less, so it is negligible.
    - Under `.pipelined`, "unattributed" is dominated by the untimed GPU wait at `:3759` (V-2), not by rounding.
- **Mechanism:** Repeated sub-millisecond steps round the same way, so the error builds up with token count instead of averaging out.
- **Corrected impact:** Rounding biases two diagnostic keys that nothing consumes. "Unattributed" is affected only by per-token rounding of about 8 top-level terms, which is small next to the untimed token read. The finder's claim of misdirecting 9% of decode is overstated.
- **Corrected fix:**
  1. Accumulate Duration or nanoseconds and round once at export, adding `*_ns` keys. This is additive and safe for integer consumers.
  2. Make Engine.swift round instead of truncate, for consistency only.
  3. Rank this below the token-read timer (V-2), which is what actually empties "unattributed".
- **Verify:** An accumulator unit test: 15 × 0.4 ms must sum to 6 ms, not 0.
