import React from "react";
import { Icon } from "../components/Icon.jsx";
import { Screenshot } from "../components/Screenshot.jsx";

const ROWS = [
  {
    icon: "wave-plus",
    k: "Long scripts become projects",
    v: "Paste a whole chapter. Vocello plans it into segments that play while the rest generates, joins them into one file, and lets you redo a single segment.",
  },
  {
    icon: "bubble",
    k: "Ten languages, detected for you",
    v: "Chinese, English, Japanese, Korean, German, French, Russian, Portuguese, Spanish and Italian. The interface comes in ten languages too.",
  },
  {
    icon: "history",
    k: "Your library, kept",
    v: "Saved voices and a searchable History of every take, ready to replay or export. Pin a take's seed to make it again with the same settings.",
  },
];

export const Capabilities = () => (
  <section className="section caps-section" id="capabilities" aria-labelledby="caps-title">
    <div className="container caps-layout">
      <figure className="caps-shot">
        <div className="window">
          <Screenshot
            src="/assets/screens/history.png"
            width={2080} height={1380}
            alt="Vocello Generation History listing past takes across Built-in Voice, Voice Design, and Voice Cloning"
          />
        </div>
      </figure>
      <div className="caps-copy">
        <p className="section-note">Made for real projects</p>
        <h2 id="caps-title" className="section-title">From one line to a whole chapter.</h2>
        <ul className="caps-list" role="list">
          {ROWS.map((row, index) => (
            <li className="caps-row" key={row.k} style={{ "--i": index }}>
              <span className="caps-icon" aria-hidden="true"><Icon name={row.icon} size={20} /></span>
              <div>
                <h3 className="caps-k">{row.k}</h3>
                <p className="caps-v">{row.v}</p>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  </section>
);
