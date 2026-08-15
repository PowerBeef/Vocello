import React from "react";

const ROWS = [
  {
    k: "Long scripts become projects",
    v: "A script past the single-take limit is planned into segments, generated in order while you listen along, and joined into one finished audio file. History keeps the project with a per-segment map, and a single weak segment can be regenerated without redoing the rest.",
    tone: "var(--gold-300)",
  },
  {
    k: "Ten languages, detected automatically",
    v: "Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish, and Italian. Vocello detects the script's language on its own, and a manual language choice is always available.",
    tone: "var(--lavender-300)",
  },
  {
    k: "Downloads that behave",
    v: "Model installs run three files at a time, retry interrupted transfers automatically, and verify integrity without re-reading multi-gigabyte files. Shared components are stored once across models, saving disk.",
    tone: "var(--terracotta-300)",
  },
];

export const Capabilities = () => (
  <section className="section caps-section" id="capabilities" aria-labelledby="caps-title">
    <div className="container caps-layout">
      <div className="caps-copy">
        <p className="section-note">In the studio</p>
        <h2 id="caps-title" className="section-title">Built for long scripts.</h2>
        <p className="section-sub">
          Vocello turns long scripts into finished projects, speaks ten languages,
          and installs models reliably. Everything runs locally on your Mac.
        </p>

        <dl className="caps-list" aria-label="Vocello capabilities">
          {ROWS.map((r) => (
            <div className="caps-row" key={r.k} style={{ "--row-tone": r.tone }}>
              <dt className="caps-k">{r.k}</dt>
              <dd className="caps-v">{r.v}</dd>
            </div>
          ))}
        </dl>
      </div>

      <figure className="caps-shot">
        <div className="window">
          <img
            src="assets/screens/history.png"
            alt="Vocello Generation History listing past takes across Built-in Voice, Voice Design, and Voice Cloning"
          />
        </div>
        <figcaption className="caps-shot-caption">
          Generation History keeps every take on your Mac, ready to replay, save, or export.
        </figcaption>
      </figure>
    </div>
  </section>
);
