import React from "react";
import { Icon } from "../components/Icon.jsx";
import {
  CLI_PKG,
  CREDITS,
  MAC_DMG,
  RELEASES,
  RELEASE_FALLBACK,
  RELEASE_NOTES,
  TESTFLIGHT,
} from "../data/credits.js";
import { FALLBACK_MAC_RELEASE, STABLE_MAC_RELEASE } from "../data/release.js";

export const FinalCTA = () => (
  <section id="download" className="final-cta-section" aria-labelledby="download-title">
    <div className="container cta-block">
      <div className="cta-aura" aria-hidden="true" />
      <img className="cta-icon" src="/assets/apple-touch-icon.png" width={180} height={180} alt="" />
      <h2 id="download-title" className="cta-title">Local by design. Yours to keep.</h2>
      <p className="cta-body">
        Vocello {STABLE_MAC_RELEASE.version} for Mac. Free and open source, signed and notarized,
        and it updates itself.
      </p>
      <div className="hero-ctas cta-actions">
        <a className="btn btn-primary btn-large" href={MAC_DMG}>
          <Icon name="apple" size={17} />
          Download for Mac
        </a>
      </div>
      <p className="cta-alt">
        <a className="cta-meta-link" href={TESTFLIGHT} target="_blank" rel="noreferrer">Join the iPhone beta</a>
        <span className="cta-meta-sep" aria-hidden="true">·</span>
        <a className="cta-meta-link" href={CLI_PKG}>Get the command line package</a>
      </p>
      <p className="cta-models">
        Needs macOS 26 on Apple Silicon with 8 GB of memory, 16 GB or more for the Quality models.
        Open the disk image and drag Vocello to Applications. Models are not bundled: each
        downloads once from Hugging Face, and the three Speed models take about 4.8 GB together.
      </p>
      <p className="cta-meta">
        <a href={RELEASE_NOTES} target="_blank" rel="noreferrer" className="cta-meta-link">Release notes</a>
        <span className="cta-meta-sep" aria-hidden="true">·</span>
        <a href={RELEASES} target="_blank" rel="noreferrer" className="cta-meta-link">All releases</a>
        <span className="cta-meta-sep" aria-hidden="true">·</span>
        <span>
          On macOS 15:{" "}
          <a href={RELEASE_FALLBACK} target="_blank" rel="noreferrer" className="cta-meta-link">
            QwenVoice {FALLBACK_MAC_RELEASE.version}
          </a>
        </span>
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
  </section>
);
