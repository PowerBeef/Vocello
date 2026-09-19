# Speed versus Quality benchmark — 2026-09-19

All 58 generations completed and all six runs passed the repository evidence validator with soft-trim warnings. The measured source is `b23d8a7e9ff0b8ce42aa11f96ec1c5366699dfe8`, with a clean and unchanged source fingerprint throughout the campaign.

## Method

- Apple M2 Mac mini, 8 GiB unified memory; native device policy; fresh `scripts/build.sh cli-optimized` binary with hash-bound `-O` provenance.
- All three generation modes, Speed (4-bit) and Quality (8-bit); the same fixed English short, medium and long corpus, seed `19790615`, default Built-in speaker and Design brief, and the approved transcript-backed Voice Design clone fixture.
- Six serial, isolated CLI processes, one per mode/preset. Three warm repetitions per text length (54 runs), plus one cold-model medium take for each Built-in/Design preset (four runs). Models and the clone fixture passed repository readiness checks.
- Production streaming and publication marking enabled. Verbose telemetry includes lifecycle boundary captures and periodic memory sampling. No memory-tier or performance overrides.
- Each process has its own local data/diagnostics folder. Clone models are explicitly loaded before measured runs; its first run can still initialize conditioning/decoder caches. Cold means model-unloaded, not an emptied OS file cache.
- Warm timing cells use medians of three runs. RTF is engine synthesis wall time (excluding one-time model load and prewarm) divided by output duration (lower is faster; below 1 synthesizes faster than playback). Peak RAM is the largest sampled process physical footprint, including finalization/marking, expressed in GiB; it is not total system RAM or a sum of independent CPU/GPU peaks.

## Comparison

Normalized time compares the median warm long-text RTF. Peak RAM is the maximum across every measured length and cold/warm state for that mode/preset.

| Mode | Speed RTF | Quality RTF | Quality normalized time increase | Speed peak RAM | Quality peak RAM | Extra peak RAM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Built-in Voice | 0.564 | 0.772 | +36.8% | 2.59 GiB | 3.35 GiB | +0.76 GiB (29.4%) |
| Voice Design | 0.548 | 0.767 | +40.1% | 3.17 GiB | 3.71 GiB | +0.54 GiB (16.9%) |
| Voice Clone | 0.580 | 0.787 | +35.7% | 3.49 GiB | 4.04 GiB | +0.55 GiB (15.9%) |

## Full warm matrix

Output durations can differ between quantizations even with the same text and seed. Raw wall time therefore reflects both throughput and the length of the generated speech. RAM below is the maximum of the three takes, while timing and audio duration are medians.

| Mode | Preset | Text | Audio | Synthesis wall | RTF | First chunk | Peak RAM |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| Built-in Voice | Speed | short | 1.84s | 1.18s | 0.639 | 416 ms | 2.18 GiB |
| Built-in Voice | Speed | medium | 5.84s | 3.40s | 0.582 | 428 ms | 2.52 GiB |
| Built-in Voice | Speed | long | 20.32s | 11.46s | 0.564 | 439 ms | 2.59 GiB |
| Built-in Voice | Quality | short | 1.92s | 1.64s | 0.852 | 545 ms | 3.15 GiB |
| Built-in Voice | Quality | medium | 6.48s | 5.13s | 0.792 | 589 ms | 3.24 GiB |
| Built-in Voice | Quality | long | 24.16s | 18.65s | 0.772 | 620 ms | 3.35 GiB |
| Voice Design | Speed | short | 2.40s | 1.51s | 0.629 | 419 ms | 2.36 GiB |
| Voice Design | Speed | medium | 7.60s | 4.26s | 0.560 | 428 ms | 3.13 GiB |
| Voice Design | Speed | long | 26.40s | 14.45s | 0.548 | 444 ms | 3.17 GiB |
| Voice Design | Quality | short | 2.80s | 2.32s | 0.829 | 613 ms | 3.42 GiB |
| Voice Design | Quality | medium | 6.32s | 4.92s | 0.779 | 566 ms | 3.65 GiB |
| Voice Design | Quality | long | 23.04s | 17.67s | 0.767 | 636 ms | 3.71 GiB |
| Voice Clone | Speed | short | 2.38s | 1.89s | 0.793 | 756 ms | 2.73 GiB |
| Voice Clone | Speed | medium | 7.12s | 4.43s | 0.622 | 821 ms | 3.49 GiB |
| Voice Clone | Speed | long | 22.78s | 13.22s | 0.580 | 926 ms | 3.46 GiB |
| Voice Clone | Quality | short | 2.56s | 2.47s | 0.965 | 941 ms | 3.47 GiB |
| Voice Clone | Quality | medium | 6.72s | 5.71s | 0.850 | 1007 ms | 3.97 GiB |
| Voice Clone | Quality | long | 22.72s | 17.89s | 0.787 | 1084 ms | 4.04 GiB |

## Cold-model starts

One medium-text measurement each; these are descriptive observations, not repeated cold-start medians. Clone cold-start timing is outside the standard harness protocol.

| Mode | Preset | Model load | Total request wall | First chunk | Peak RAM |
| --- | --- | ---: | ---: | ---: | ---: |
| Built-in Voice | Speed | 1.69s | 5.57s | 2528 ms | 2.54 GiB |
| Built-in Voice | Quality | 2.13s | 8.44s | 3786 ms | 3.26 GiB |
| Voice Design | Speed | 1.70s | 6.61s | 2724 ms | 2.18 GiB |
| Voice Design | Quality | 6.86s | 12.64s | 8014 ms | 3.43 GiB |

## Evidence and limits

- 58 accepted outputs; audio QC outcomes: ['pass']. All six run validators passed with qualified memory evidence.
- Minimum sampling coverage: 100%; capture failures: 0; observed crashes: 0.
- Thermal states: nominal. All process starts passed the quiet-host preflight.
- Run warnings: memory.pressure.soft_trim. These are the measured device-policy conditions; the results are not a pressure-free best-case ceiling.
- This compares runtime cost, not perceived audio fidelity, speaker similarity, or linguistic accuracy. It covers one fixed English corpus, one Built-in speaker, one Design brief, and one clone reference; it does not generalize to every voice, language, delivery preset, or long-form/batch workload.
- The headless CLI uses the shared in-process engine. App UI/playback latency, the macOS app baseline footprint, physical iPhone performance, and other hardware were not measured.
- Three warm repeats quantify this session; the fixed Speed-then-Quality order was not counterbalanced. Models were not evicted from the OS file cache. No claim of statistical significance across sessions.
- Raw WAVs, memory sidecars and logs remain untracked under `build/artifacts/macos/speed-quality-20260919/`. The CSV there retains per-take timing and memory values. Qualified summaries are linked below.

| Mode | Preset | Retained record |
| --- | --- | --- |
| Built-in Voice | Speed | [mac-custom-speed-20260919-044142-5f7862eb](../../benchmarks/runs/engine-generation/mac-custom-speed-20260919-044142-5f7862eb.json) |
| Built-in Voice | Quality | [mac-custom-quality-20260919-044236-41a53bcc](../../benchmarks/runs/engine-generation/mac-custom-quality-20260919-044236-41a53bcc.json) |
| Voice Design | Speed | [mac-design-speed-20260919-044402-da647d43](../../benchmarks/runs/engine-generation/mac-design-speed-20260919-044402-da647d43.json) |
| Voice Design | Quality | [mac-design-quality-20260919-044511-f9914b60](../../benchmarks/runs/engine-generation/mac-design-quality-20260919-044511-f9914b60.json) |
| Voice Clone | Speed | [mac-clone-speed-20260919-044640-c0a26f3c](../../benchmarks/runs/engine-generation/mac-clone-speed-20260919-044640-c0a26f3c.json) |
| Voice Clone | Quality | [mac-clone-quality-20260919-044744-a38d2266](../../benchmarks/runs/engine-generation/mac-clone-quality-20260919-044744-a38d2266.json) |
