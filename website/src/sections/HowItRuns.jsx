import React from "react";

const ROWS = [
  {
    k: "Where generation happens",
    v: "On your Mac",
    note: "After models download from Hugging Face and install, every line renders locally. No scripts uploaded and no generated audio sent to a cloud TTS service.",
    tone: "var(--gold-300)",
  },
  {
    k: "Where data lives",
    v: "Local app storage",
    note: "Scripts, history, saved voices, and generated audio stay in Vocello's local storage until you export or reveal a file yourself.",
    tone: "var(--lavender-300)",
  },
  {
    k: "Pricing",
    v: "Free on Mac",
    note: "The Mac app is free and open-source. Download the Speed or Quality model from Hugging Face once and generate as many lines as your Mac can hold. No subscription, no per-character meter, no queue.",
    tone: "var(--terracotta-300)",
  },
  {
    k: "Speed model",
    v: "4-bit",
    note: "Smaller package, faster startup, lower memory. Vocello defaults to Speed on 8 GB / floor-spec Macs. Manage in Settings, Model Downloads.",
    tone: "var(--status-ready)",
  },
  {
    k: "Quality model",
    v: "8-bit",
    note: "Larger package, slower to warm up, finer timbre and delivery. Vocello defaults to Quality on Macs with more RAM. Speed and Quality can coexist; pick the active variant on each generation screen.",
    tone: "var(--status-warn)",
  },
];

export const HowItRuns = () => (
  <section className="section runs-section" id="how-it-runs">
    <div className="container runs-layout">
      <div className="runs-copy">
        <header className="runs-head">
          <p className="section-note">How it runs</p>
          <h2 className="section-title">Vocello runs on your Mac.</h2>
          <p className="section-sub">
            The privacy story is not a badge on top. It is how the app is built,
            how models install, and where generated audio stays.
          </p>
        </header>

        <figure className="runs-shot">
          <div className="window">
            <img
              src="assets/screens/model-downloads.png"
              alt="Vocello Model Downloads screen showing Speed and Quality models ready"
            />
          </div>
          <figcaption className="runs-shot-caption">
            Model Downloads keeps Speed and Quality variants visible for each workflow.
          </figcaption>
        </figure>
      </div>

      <dl className="runs-table" aria-label="Vocello runtime details">
        {ROWS.map((r) => (
          <div className="runs-row" key={r.k} style={{ "--row-tone": r.tone }}>
            <dt className="runs-k">{r.k}</dt>
            <dd className="runs-v">
              <span className="runs-v-label">{r.v}</span>
            </dd>
            <dd className="runs-note">{r.note}</dd>
          </div>
        ))}
      </dl>
    </div>
  </section>
);
