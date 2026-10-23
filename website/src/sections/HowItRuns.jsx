import React from "react";
import { Screenshot } from "../components/Screenshot.jsx";

const ROWS = [
  {
    k: "Where generation happens",
    v: "On your Mac",
    note: "After models download from Hugging Face and install, every line renders locally, in the app or in the terminal. No scripts uploaded and no generated audio sent to a cloud TTS service.",
    tone: "var(--gold-300)",
  },
  {
    k: "Ways to run it",
    v: "App or terminal",
    note: (
      <>
        The Mac app and the vocello command line host the same engine in-process, as the
        iPhone app does on the phone. The command line shares the app's models, saved voices,
        and settings, reads its History, and can serve AI agents over MCP. See{" "}
        <a href="#cli">command line and agents</a>.
      </>
    ),
    tone: "var(--lavender-300)",
  },
  {
    k: "Where data lives",
    v: "Local app storage",
    note: "Scripts, history, saved voices, and generated audio stay in Vocello's local storage until you export or reveal a file yourself. The command line saves its takes as files in that same folder unless you name another, and they do not appear in History yet.",
    tone: "var(--terracotta-300)",
  },
  {
    k: "Pricing",
    v: "Free on Mac",
    note: "The Mac app and the command line are free and open source. Download the Speed or Quality model from Hugging Face once and generate as many lines as your Mac can hold. No subscription, no per-character meter, no queue.",
    tone: "var(--gold-300)",
  },
  {
    k: "Speed model",
    v: "4-bit",
    note: "Smaller package, faster startup, lower memory. Vocello defaults to Speed on 8 GB Macs. Manage models in Settings, Models & Files, or with vocello models in the terminal.",
    tone: "var(--status-ready)",
  },
  {
    k: "Quality model",
    v: "8-bit",
    note: "Larger package, slower to warm up, finer timbre and delivery. Vocello defaults to Quality on Macs with more memory. Speed and Quality can coexist; pick the active one for each mode in Studio.",
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
            The privacy story is not a badge on top. It is how the app and the command
            line are built, how models install, and where generated audio stays.
          </p>
        </header>

        <figure className="runs-shot">
          <div className="window">
            <Screenshot
              src="assets/screens/model-downloads.png"
              width={2080} height={1380}
              alt="The Vocello model manager showing Speed and Quality models ready"
            />
          </div>
          <figcaption className="runs-shot-caption">
            The model manager keeps Speed and Quality variants visible for each mode.
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
