import React from "react";
import { Icon } from "../components/Icon.jsx";
import { RELEASE_NOTES } from "../data/credits.js";
import { HIGHLIGHTS, IPHONE_NOTE, UPGRADE_NOTE, WHATS_NEW_VERSION } from "../data/whatsnew.js";

// The home page names the changes people notice; the release notes carry every one.
const ON_HOME = [
  "A leaner, steadier engine",
  "Smooth live streaming preview",
  "Long-form, cloning and storage reliability",
  "Clearer transparency and AI safeguards",
  "Same models, no re-download from 3.1",
  "Hardened command line and 8 GB coordination",
];
const highlights = ON_HOME.map((k) => HIGHLIGHTS.find((item) => item.k === k)).filter((item) => item !== undefined);

export const WhatsNew = () => (
  <section className="section whatsnew-section" id="whats-new" aria-labelledby="whatsnew-title">
    <div className="container">
      <header className="section-head">
        <p className="section-note">Released November 2026</p>
        <h2 id="whatsnew-title" className="section-title">What's new in {WHATS_NEW_VERSION}</h2>
        <p className="section-sub">
          A leaner engine, smooth live streaming preview progress, hardened reliability and clearer
          AI safeguards in the Mac app and command line, with no model re-download from 3.1.{" "}
          {IPHONE_NOTE}
        </p>
      </header>
      <ul className="whatsnew-grid" role="list">
        {highlights.map((item, index) => (
          <li className="whatsnew-item" key={item.k} style={{ "--i": index }}>
            <h3 className="whatsnew-k">{item.k}</h3>
            <p className="whatsnew-v">{item.short}</p>
          </li>
        ))}
      </ul>
      <p className="whatsnew-upgrade">{UPGRADE_NOTE}</p>
      <p className="section-more">
        <a className="more-link" href={RELEASE_NOTES} target="_blank" rel="noreferrer">
          Read every change in the release notes
          <Icon name="arrow-right" size={16} />
        </a>
      </p>
    </div>
  </section>
);
