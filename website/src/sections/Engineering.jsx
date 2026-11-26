import React from "react";

/*
  Measured performance, from the repository's tracked benchmark records:
  - RTF bars: the warm-take medians `python3 scripts/generate_readme_charts.py` prints, pooled
    over up to five canonical records that share the comparison key and app build of the newest
    one (the anchor). The provenance line below mirrors the chart footer, as the generator prints
    it: "Record <anchor>" for one record, "Median of N records through <anchor>" for more. Today
    the pool is two records of app 3.2.0 build 32,
    benchmarks/runs/ui-generation/macos-xcui-benchmark-20261126-092027-a9057aef.json and the
    anchor, macos-xcui-benchmark-20261126-154113-ea3610e8.json (a new app build resets the pool);
    the generator's `--check` fails when a new canonical record changes the charts.
    RTF is the standard real-time factor: seconds of generation per second of audio, lower is
    faster, below 1.0 audio is produced quicker than it plays. This record was published after the
    2026-09-12 RTF cutover (`run.rtfDefinition: wall/audio`), so each value is the per-cell median
    of the engine-measured figure; the optimization label comes from the build receipt.
  - The retired gate chart's pinned A/B pair (…-9b6f267b / …-d02005ae) stays as history in
    benchmarks/HISTORY.md and OPTIMIZATION.md §K; per policy it is never re-promoted to a
    chart. The gate survives as one figcaption sentence below.
  Values are warm-take medians measured on the Mac mini M6 (16 GB), the canonical host since
  2026-09-22 (roadmap AV-17). The Mac mini M2 (8 GB) remains the support floor; its records
  (last canonical: 379db820, 0.53 to 0.82) are an earlier series, never compared with the M6's.
  This section is a maintained whole-package surface (docs/reference/macos-release-qa.md
  "Technical sections are maintained surfaces"): refresh facts each release, never a
  single-release billboard.
  Release 3.2.0: the pooled records (sources 7e20e070 and 072d1bd7; app 3.2.0 build 32) measure
  each mode's one model, the hybrid introduced in 3.1 (RF-55, RF-59) and retained unchanged in 3.2;
  its takes carry the variant id `speed`, which public copy never uses as the model's name. Both
  the benchmarked builds and the released Mac app compile with Xcode 27.2 (Swift 6.4.2).
  The translucency gate (+33.6% warm RTF, 9b6f267b to d02005ae) was measured on the Mac mini M2.
  The memory figures are OPTIMIZATION.md §F.1 and long-form smoke run 8f15c1fd, both on the M2.
*/
const MODES = [
  { name: "Built-in Voice", tone: "var(--mode-custom)", takes: [0.36, 0.31, 0.29] },
  { name: "Voice Design", tone: "var(--mode-design)", takes: [0.34, 0.30, 0.29] },
  { name: "Voice Cloning", tone: "var(--mode-clone)", takes: [0.38, 0.32, 0.29] },
];
const LENGTHS = ["short", "medium", "long"];
const RTF_SCALE_MAX = 1.2;
const RTF_TICKS = [0.25, 0.5, 0.75, 1.0];

const LEDGER = [
  {
    k: "Swift end to end",
    v: "Generation runs through Vocello's own Swift runtime on MLX, derived from mlx-audio-swift and narrowed to the Qwen3 voice stack: about 36,000 of 49,000 upstream lines removed, no Python, no local HTTP server.",
  },
  {
    k: "One model per mode",
    v: "Each mode runs a single mixed-precision model, so there is no Speed or Quality choice to make. It keeps the 4-bit model's size and puts its attention layers at 8 bits, about 180 MB more. On the benchmark Mac mini M6 it takes 0.30 s to generate a second of speech, against 0.28 s for the 3.0 Speed model and 0.41 s for Quality; it finished 65 of 72 long-form projects, against 56 and 68; and its download is 2.23 GB per mode, against 2.05 GB and 2.82 GB. It was chosen by machine screens whose decision rules were recorded before their takes were generated: 192 clone takes in six languages, 72 long-form projects and 144 single takes, against both 3.0 models.",
  },
  {
    k: "One engine, three hosts",
    v: "The Mac app runs the engine in-process, with no separate service, as the iPhone app does, so one lifecycle and one memory policy serve both: the engine trims its caches under memory pressure and unloads an idle model. The vocello command line hosts the same engine through the Mac app's engine store, with the same admission and memory checks and no UI.",
  },
  {
    k: "Streaming by design",
    v: "Audio leaves the engine chunk by chunk, so memory stays flat however long the script runs. On the 8 GB Mac mini M2, streaming took the peak of the same take from about 8 GB to about 3 GB, and a 12-segment project with 10.4 minutes of audio ended 1.1 percent below its starting footprint.",
  },
  {
    k: "Reproducible by construction",
    v: "Every request carries its own seed and sampler state, so the same request and seed reproduce a take on the same model. Performance changes are checked against fixed-seed takes, so a speed change that alters the audio shows up before it merges. A seed pinned in 3.1 reproduces its take in 3.2; a seed from 3.0 or earlier does not, because the model changed in 3.1.",
  },
  {
    k: "Honest benchmarks",
    v: "Published records are pass-only with a strict privacy allowlist, and each take carries typed quality verdicts. The lane once caught its own measurement bias: disabling the harness's screen recording moved the same take by 55 percent.",
  },
];

// The speed chart is HTML, not a fixed-width SVG: its bars reflow with the
// panel, so labels keep their size on a phone instead of shrinking with a
// scaled drawing. Bar lengths and gridlines share one scale (--rtf, 0 to 1 of
// RTF_SCALE_MAX).
const scale = (value) => Math.min(value, RTF_SCALE_MAX) / RTF_SCALE_MAX;

const RtfChart = () => (
  <div
    className="rtf-chart"
    role="img"
    aria-label="Warm real-time factor of each mode's model by script length, lower is faster, measured on a Mac mini M6 with 16 GB. Built-in Voice 0.29 to 0.36, Voice Design 0.29 to 0.34, Voice Cloning 0.29 to 0.38. Every bar sits below the real-time line at 1.0."
  >
    {MODES.map((mode) => (
      <div className="rtf-group" key={mode.name} style={{ "--bar-tone": mode.tone }}>
        <p className="rtf-mode">
          <span className="rtf-dot" aria-hidden="true" />
          {mode.name}
        </p>
        {mode.takes.map((value, i) => (
          <div className="rtf-row" key={LENGTHS[i]}>
            <span className="rtf-len">{LENGTHS[i]}</span>
            <span className="rtf-track" style={{ "--rtf": scale(value) }}>
              <span className="rtf-bar" />
              <span className="rtf-val">{value.toFixed(2)}</span>
            </span>
          </div>
        ))}
      </div>
    ))}
    <div className="rtf-row rtf-axis" aria-hidden="true">
      <span />
      <span className="rtf-track">
        {RTF_TICKS.map((tick) => (
          <span
            key={tick}
            className={`rtf-tick${tick === 1.0 ? " rtf-tick--realtime" : ""}`}
            style={{ "--rtf": scale(tick) }}
          >
            {tick === 1.0 ? (
              <>
                1.0<span className="rtf-tick-note"> real time</span>
              </>
            ) : tick.toFixed(2)}
          </span>
        ))}
      </span>
    </div>
  </div>
);

const SpeedPanel = () => (
  <figure className="perf-panel">
    <RtfChart />
    <figcaption className="perf-caption">
      Warm generation by mode and script length, take medians, with each
      mode's one model in Vocello 3.2.0 (build 32). Translucent app surfaces
      render solid while audio generates; on the 8 GB Mac mini M2, that change
      sped up the same take by about a third.
    </figcaption>
  </figure>
);

// /engineering/: the full engineering story.
export const EngineeringDetail = () => (
  <section className="section engineering-section" aria-labelledby="eng-title">
    <div className="container">
      <header className="perf-head page-head">
        <p className="section-note">Measured, not promised</p>
        <h1 id="eng-title" className="section-title page-title">A first-party engine, measured take by take.</h1>
        <p className="section-sub">
          The speed chart pools two records on Vocello's benchmark host, a Mac mini M6
          with 16 GB: Vocello 3.2.0 (build 32) with each mode's one model, measured on
          November 26, 2026 on Xcode 27.2, matching the compiler that builds the release.
          The earlier streaming-reduction figures in the ledger come from records on the
          8 GB Mac mini M2, the support floor.
          Speed is the real-time factor: seconds of generation per second of audio.
          Below 1.0, audio generates ahead of playback, and every number here traces
          to a tracked record in the open repository.
        </p>
      </header>
      <div className="perf-layout">
        <SpeedPanel />
        <dl className="eng-ledger" aria-label="How the Vocello engine is built">
          {LEDGER.map((row) => (
            <div className="eng-row" key={row.k}>
              <dt className="eng-k">{row.k}</dt>
              <dd className="eng-v">{row.v}</dd>
            </div>
          ))}
        </dl>
      </div>
      <p className="perf-provenance">
        Median of 2 records through <span className="perf-mono">ea3610e8</span> in{" "}
        <a href="https://github.com/PowerBeef/Vocello/blob/main/benchmarks/HISTORY.md" target="_blank" rel="noreferrer">
          benchmarks/HISTORY.md
        </a>
        , reproducible with the repository's benchmark lanes.
      </p>
    </div>
  </section>
);
