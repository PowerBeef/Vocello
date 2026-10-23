import React from "react";
import { Icon } from "../components/Icon.jsx";
import {
  CLI_DMG,
  CLI_PKG,
  CREDITS,
  MAC_DMG,
  RELEASES,
  RELEASE_FALLBACK,
  RELEASE_NOTES,
  REPO,
  TESTFLIGHT,
} from "../data/credits.js";
import { FALLBACK_MAC_RELEASE, STABLE_MAC_RELEASE } from "../data/release.js";

export const FinalCTA = () => (
  <section id="download" className="final-cta-section" aria-labelledby="download-title">
    <div className="container">
      <div className="cta-block">
        <h2 id="download-title" className="cta-title">Local by design. Yours to keep.</h2>
        <p className="cta-body">
          Vocello {STABLE_MAC_RELEASE.version} for macOS 26 and Apple Silicon, free and open
          source. Three ways in, one local engine.
        </p>
      </div>

      <ul className="ways-in" role="list">
        <li className="way way--mac">
          <div className="way-copy">
            <h3 className="way-k">Mac app</h3>
            <p className="way-v">
              Open the DMG and drag Vocello to Applications. From 3.0 on, the app updates itself:
              choose Vocello &gt; Check for Updates.
            </p>
            <p className="way-meta">Vocello-macos26.dmg · Signed and notarized</p>
          </div>
          <a className="btn btn-primary" href={MAC_DMG}>
            <Icon name="apple" size={16} />
            Download for Mac
          </a>
        </li>
        <li className="way way--cli">
          <div className="way-copy">
            <h3 className="way-k">Command line</h3>
            <p className="way-v">
              The installer package links <code className="cli-inline">vocello</code> in
              /usr/local/bin and asks for an administrator password; install a newer package to
              update it. Or copy the Vocello CLI folder from the{" "}
              <a className="cta-meta-link" href={CLI_DMG}>folder DMG</a>.
            </p>
            <p className="way-meta">Vocello-macos26-cli.pkg · Apple Silicon only</p>
          </div>
          <a className="btn btn-secondary" href={CLI_PKG}>
            <Icon name="download" size={16} />
            Download the package
          </a>
        </li>
        <li className="way way--iphone">
          <div className="way-copy">
            <h3 className="way-k">iPhone</h3>
            <p className="way-v">
              The public TestFlight beta runs version 2.4. The iPhone app's 3.0 version, on the
              same engine, follows in the coming days through TestFlight and then the App Store.
            </p>
            <p className="way-meta">iPhone 15 Pro or newer · iOS 26.0 or later</p>
          </div>
          <a className="btn btn-secondary" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Join on TestFlight
          </a>
        </li>
      </ul>

      <div className="cta-block">
        <p className="cta-models">
          Models are not bundled: each downloads once from Hugging Face, so installing one needs
          an internet connection. Check the model sizes and your free storage first. The three
          Speed models take about 4.8 GB together, because they share one speech tokenizer,
          stored once. Generation then runs locally.
        </p>
        <p className="cta-meta">
          macOS 26.0+
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          Apple Silicon with 8 GB memory or more (16 GB recommended for Quality models)
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          <a href={RELEASE_NOTES} target="_blank" rel="noreferrer" className="cta-meta-link">
            Release notes
          </a>
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          <a href={RELEASES} target="_blank" rel="noreferrer" className="cta-meta-link">
            All releases
          </a>
          <span className="cta-meta-sep" aria-hidden="true">·</span>
          Stable build for macOS 15:{" "}
          <a href={RELEASE_FALLBACK} target="_blank" rel="noreferrer" className="cta-meta-link">
            QwenVoice {FALLBACK_MAC_RELEASE.version}
          </a>
        </p>
        <p className="cta-meta cta-meta--source">
          <a href={REPO} target="_blank" rel="noreferrer" className="cta-source-link">
            <Icon name="github" size={14} />
            View the source on GitHub
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
