import React from "react";

const ROWS = [
  {
    k: "Long scripts become projects",
    v: "A script past the single-take limit is planned into segments, generated in order while you listen along, and joined into one finished audio file. History keeps the project with a per-segment map, and a single weak segment can be regenerated without redoing the rest.",
    tone: "var(--gold-300)",
  },
  {
    k: "Faster while you watch",
    v: "The interface now steps aside during generation, so more of the machine goes to the voice. On the same canonical Mac mini, warm generation measured about a third faster than 2.1 in identical conditions.",
    tone: "var(--lavender-300)",
  },
  {
    k: "Downloads that behave",
    v: "Model installs now run three files at a time, retry interrupted transfers automatically, and verify integrity without re-reading multi-gigabyte files. Shared components are stored once across models, saving disk.",
    tone: "var(--terracotta-300)",
  },
];

export const Capabilities = () => (
  <section className="section caps-section" id="whats-new" aria-labelledby="caps-title">
    <div className="container caps-layout">
      <div className="caps-copy">
        <p className="section-note">New in 2.2</p>
        <h2 id="caps-title" className="section-title">Built for long scripts.</h2>
        <p className="section-sub">
          Vocello 2.2 turns long scripts into finished projects, generates faster
          while you watch, and installs models more reliably. Everything still runs
          locally on your Mac.
        </p>

        <dl className="caps-list" aria-label="What is new in Vocello 2.2">
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
            alt="Vocello Generation History listing past takes across Custom Voice, Voice Design, and Voice Cloning"
          />
        </div>
        <figcaption className="caps-shot-caption">
          Generation History keeps every take on your Mac, ready to replay, save, or export.
        </figcaption>
      </figure>
    </div>
  </section>
);
