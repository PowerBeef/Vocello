import React from "react";
import { Icon } from "../components/Icon.jsx";
import { CREDITS, REPO, RELEASE_LATEST, RELEASE_V1, TESTFLIGHT } from "../data/credits.js";

export const FinalCTA = () => (
  <section id="download" className="final-cta-section">
    <div className="container">
      <div className="cta-block">
        <h2 className="cta-title">Local by design. Yours to keep.</h2>
        <p className="cta-body">
          Vocello 2.2.2 for macOS 26 and Apple Silicon. Free, open-source,
          ready to install in under a minute.
        </p>
        <div className="hero-ctas hero-ctas--center">
          <a className="btn btn-primary" href={RELEASE_LATEST} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Download Vocello
          </a>
          <a className="btn btn-secondary" href={REPO} target="_blank" rel="noreferrer">
            <Icon name="github" size={14} />
            View on GitHub
          </a>
        </div>
        <p className="cta-meta">
          macOS 26.0+
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          Apple Silicon required
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          iPhone beta on{" "}
          <a href={TESTFLIGHT} target="_blank" rel="noreferrer" className="cta-meta-link">
            TestFlight
          </a>
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          Stable build for macOS 15:{" "}
          <a href={RELEASE_V1} target="_blank" rel="noreferrer" className="cta-meta-link">
            QwenVoice 1.2.3
          </a>
        </p>
        <div className="cta-credits">
          <span className="cta-credits-label">Built on</span>
          <ul className="cta-credits-list" role="list">
            {CREDITS.map((c) => (
              <li key={c.name}>
                <a href={c.href} target="_blank" rel="noreferrer">{c.name}</a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  </section>
);
