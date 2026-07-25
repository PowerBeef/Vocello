import React from "react";

/*
  Measured performance, from the repository's tracked benchmark records:
  - RTF bars: benchmarks/runs/ui-generation/macos-xcui-benchmark-20260723-083313-d02005ae.json
  - Gate pair: same cell (Custom, long, warm) in ...-20260723-054315-9b6f267b.json (before)
    and d02005ae (after).
  Values are warm-take medians on the canonical Mac mini M2 (8 GB).
*/
const MODES = [
  { name: "Custom Voice", tone: "var(--mode-custom)", takes: [1.68, 1.82, 1.83] },
  { name: "Voice Design", tone: "var(--mode-design)", takes: [1.78, 1.91, 1.94] },
  { name: "Voice Cloning", tone: "var(--mode-clone)", takes: [1.49, 1.69, 1.84] },
];
const LENGTHS = ["short", "medium", "long"];
const SCALE_MAX = 2.0;

const GATE = { before: 1.37, after: 1.83 };

const RtfChart = () => {
  const width = 640;
  const left = 96;
  const right = 64;
  const x0 = left;
  const x1 = width - right;
  const xFor = (v) => x0 + ((x1 - x0) * Math.min(v, SCALE_MAX)) / SCALE_MAX;
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
          <text x={x0 + bw + 7} y={y + barH - 3} className="perf-value">{value.toFixed(2)}</text>
        </g>
      );
      y += barH + inGap;
    });
    y += groupGap - inGap;
  });
  const plotBottom = y - groupGap + 8;
  const gridlines = [0.5, 1.0, 1.5].map((v) => (
    <g key={v}>
      <line
        x1={xFor(v)} y1={top - 4} x2={xFor(v)} y2={plotBottom}
        stroke={v === 1.0 ? "var(--fg-tertiary)" : "var(--stroke-inline)"}
        strokeWidth="1"
        strokeDasharray={v === 1.0 ? "" : "3 3"}
      />
      <text x={xFor(v)} y={plotBottom + 18} textAnchor="middle" className="perf-tick">
        {v === 1.0 ? "1.0 · realtime" : v.toFixed(1)}
      </text>
    </g>
  ));
  return (
    <svg
      className="perf-chart"
      viewBox={`0 0 ${width} ${plotBottom + 30}`}
      role="img"
      aria-label="Warm real-time factors by mode and script length. Custom Voice 1.68 to 1.83, Voice Design 1.78 to 1.94, Voice Cloning 1.49 to 1.84. Every bar passes the realtime line at 1.0."
    >
      {gridlines}
      {rows}
    </svg>
  );
};

const GateBars = () => {
  const width = 400;
  const x0 = 0;
  const x1 = width - 48;
  const xFor = (v) => x0 + ((x1 - x0) * Math.min(v, SCALE_MAX)) / SCALE_MAX;
  const barH = 14;
  const rows = [
    { label: "Vocello 2.1", value: GATE.before, tone: "var(--fg-tertiary)" },
    { label: "Vocello 2.2", value: GATE.after, tone: "var(--mode-custom)" },
  ];
  return (
    <svg
      className="perf-chart perf-chart--gate"
      viewBox={`0 0 ${width} 96`}
      role="img"
      aria-label="The same warm Custom take: real-time factor 1.37 on Vocello 2.1 and 1.83 on 2.2."
    >
      <line x1={xFor(1.0)} y1={6} x2={xFor(1.0)} y2={78} stroke="var(--fg-tertiary)" strokeWidth="1" />
      <text x={xFor(1.0)} y={94} textAnchor="middle" className="perf-tick">realtime</text>
      {rows.map((row, i) => {
        const y = 14 + i * (barH + 16);
        const bw = xFor(row.value) - x0;
        return (
          <g key={row.label}>
            <text x={x0} y={y - 4} className="perf-tick">{row.label}</text>
            <path
              d={`M${x0} ${y} h${bw - 4} a4 4 0 0 1 4 4 v${barH - 8} a4 4 0 0 1 -4 4 h-${bw - 4} z`}
              fill={row.tone}
            />
            <text x={x0 + bw + 7} y={y + barH - 3} className="perf-value">{row.value.toFixed(2)}</text>
          </g>
        );
      })}
    </svg>
  );
};

export const Performance = () => (
  <section className="section perf-section" id="performance" aria-labelledby="perf-title">
    <div className="container">
      <header className="perf-head">
        <p className="section-note">Measured, not promised</p>
        <h2 id="perf-title" className="section-title">Generation outpaces playback on the minimum Mac.</h2>
        <p className="section-sub">
          Vocello is benchmarked on its own support floor, a Mac mini M2 with 8 GB.
          A real-time factor above 1.0 means audio generates faster than it plays,
          and every number here traces to a tracked record in the open repository.
        </p>
      </header>

      <div className="perf-layout">
        <figure className="perf-panel">
          <RtfChart />
          <figcaption className="perf-caption">
            Warm generation by mode and script length, take medians.
          </figcaption>
        </figure>

        <aside className="perf-gate">
          <p className="perf-gate-figure" aria-hidden="true">+33%</p>
          <p className="perf-gate-copy">
            In 2.2 the interface steps aside while generating, so the machine
            belongs to the voice. Same Mac, same take.
          </p>
          <GateBars />
        </aside>
      </div>

      <p className="perf-provenance">
        Records <span className="perf-mono">d02005ae</span> and <span className="perf-mono">9b6f267b</span> in{" "}
        <a href="https://github.com/PowerBeef/Vocello/blob/main/benchmarks/HISTORY.md" target="_blank" rel="noreferrer">
          benchmarks/HISTORY.md
        </a>
        , reproducible with the repository's benchmark lanes.
      </p>
    </div>
  </section>
);
