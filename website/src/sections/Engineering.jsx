import React from "react";

/*
  Measured performance, from the repository's tracked benchmark records:
  - RTF bars: benchmarks/runs/ui-generation/macos-xcui-benchmark-20260729-023553-111d88c6.json
    (the newest canonical matrix; refresh with every release, see
    docs/reference/macos-release-qa.md "Performance surfaces ship current numbers").
  - The retired gate chart's pinned A/B pair (…-9b6f267b / …-d02005ae) stays as history in
    benchmarks/HISTORY.md and OPTIMIZATION.md §K; per policy it is never re-promoted to a
    chart. The gate survives as one figcaption sentence below.
  Values are warm-take medians on the canonical Mac mini M2 (8 GB).
  This section is a maintained whole-package surface (docs/reference/macos-release-qa.md
  "Technical sections are maintained surfaces"): refresh facts each release, never a
  single-release billboard.
*/
const MODES = [
  { name: "Custom Voice", tone: "var(--mode-custom)", takes: [1.85, 1.97, 2.02] },
  { name: "Voice Design", tone: "var(--mode-design)", takes: [1.92, 2.05, 2.12] },
  { name: "Voice Cloning", tone: "var(--mode-clone)", takes: [1.55, 1.89, 2.03] },
];
const LENGTHS = ["short", "medium", "long"];
const RTF_SCALE_MAX = 2.4;

const LEDGER = [
  {
    k: "Swift end to end",
    v: "Generation runs through Vocello's own Swift runtime on MLX, derived from mlx-audio-swift and narrowed to the Qwen3 voice stack: about 36,000 of 49,000 upstream lines removed, no Python, no local server.",
  },
  {
    k: "One engine, three hosts",
    v: "On the Mac the engine lives in a separate service process that steps away when idle, so heavy engine memory can never take the app down. The iPhone app and the command-line tool run the same engine.",
  },
  {
    k: "Streaming by design",
    v: "Audio leaves the engine chunk by chunk, so memory stays flat however long the script runs: peak use fell from about 8 GB to about 3 GB, and a ten-minute project ends below its starting footprint.",
  },
  {
    k: "Reproducible by construction",
    v: "Every request carries its own seed and sampler state. Performance changes merge only when fixed-seed output stays byte-identical, so speed work can never quietly change the voice.",
  },
  {
    k: "Honest benchmarks",
    v: "Published records are pass-only with a strict privacy allowlist, and each take carries typed quality verdicts. The lane once caught its own measurement bias: disabling the harness's screen recording moved the same take by 55 percent.",
  },
];

const RtfChart = () => {
  const width = 640;
  const left = 96;
  const right = 64;
  const x0 = left;
  const x1 = width - right;
  const xFor = (v) => x0 + ((x1 - x0) * Math.min(v, RTF_SCALE_MAX)) / RTF_SCALE_MAX;
  const barH = 14;
  const inGap = 7;
  const groupGap = 24;
  const top = 16;
  let y = top;
  const rows = [];
  MODES.forEach((mode) => {
    rows.push(
      <g key={`${mode.name}-head`}>
        <circle cx={14} cy={y + 3} r={4.5} fill={mode.tone} />
        <text x={26} y={y + 7} className="perf-mode-label">{mode.name}</text>
      </g>
    );
    y += 18;
    mode.takes.forEach((value, i) => {
      const bw = xFor(value) - x0;
      rows.push(
        <g key={`${mode.name}-${LENGTHS[i]}`}>
          <text x={x0 - 8} y={y + barH - 3} textAnchor="end" className="perf-tick">{LENGTHS[i]}</text>
          <path
            d={`M${x0} ${y} h${bw - 4} a4 4 0 0 1 4 4 v${barH - 8} a4 4 0 0 1 -4 4 h-${bw - 4} z`}
            fill={mode.tone}
          />
          <text x={x0 + bw + 7} y={y + barH - 3} className="perf-value">{`${value.toFixed(2)}×`}</text>
        </g>
      );
      y += barH + inGap;
    });
    y += groupGap - inGap;
  });
  const plotBottom = y - groupGap + 8;
  const gridlines = [0.5, 1.0, 1.5, 2.0].map((v) => (
    <g key={v}>
      <line
        x1={xFor(v)} y1={top - 4} x2={xFor(v)} y2={plotBottom}
        stroke={v === 1.0 ? "var(--fg-tertiary)" : "var(--stroke-inline)"}
        strokeWidth="1"
        strokeDasharray={v === 1.0 ? "" : "3 3"}
      />
      <text x={xFor(v)} y={plotBottom + 18} textAnchor="middle" className="perf-tick">
        {v === 1.0 ? "1.0× · realtime" : `${v.toFixed(1)}×`}
      </text>
    </g>
  ));
  return (
    <svg
      className="perf-chart"
      viewBox={`0 0 ${width} ${plotBottom + 30}`}
      role="img"
      aria-label="Warm generation speed by mode and script length, as a multiple of realtime. Custom Voice 1.85× to 2.02×, Voice Design 1.92× to 2.12×, Voice Cloning 1.55× to 2.03×. Every bar passes the realtime line at 1.0×."
    >
      {gridlines}
      {rows}
    </svg>
  );
};

export const Engineering = () => (
  <section className="section engineering-section" id="engineering" aria-labelledby="eng-title">
    <div className="container">
      <header className="perf-head">
        <p className="section-note">Measured, not promised</p>
        <h2 id="eng-title" className="section-title">A first-party engine, measured on the minimum Mac.</h2>
        <p className="section-sub">
          Vocello is benchmarked on its own support floor, a Mac mini M2 with 8 GB.
          Speeds are multiples of realtime: past 1.0×, audio generates ahead of
          playback, and every number here traces to a tracked record in the open repository.
        </p>
      </header>

      <div className="perf-layout">
        <figure className="perf-panel">
          <RtfChart />
          <figcaption className="perf-caption">
            Warm generation by mode and script length, take medians. Since 2.2,
            translucent app surfaces render solid while audio generates, which
            improved speed on the same take by about a third.
          </figcaption>
        </figure>

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
        Record <span className="perf-mono">111d88c6</span> in{" "}
        <a href="https://github.com/PowerBeef/Vocello/blob/main/benchmarks/HISTORY.md" target="_blank" rel="noreferrer">
          benchmarks/HISTORY.md
        </a>
        , reproducible with the repository's benchmark lanes.
      </p>
    </div>
  </section>
);
