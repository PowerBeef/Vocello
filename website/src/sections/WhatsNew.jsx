import React from "react";
import { Icon } from "../components/Icon.jsx";
import { RELEASE_NOTES } from "../data/credits.js";
import { MAC_HIGHLIGHTS, SHARED_HIGHLIGHTS, UPGRADE_NOTE, WHATS_NEW_VERSION } from "../data/whatsnew.js";

// The home page names the changes people notice; the release notes carry every one.
const SHARED_ON_HOME = ["Generated audio is marked", "Takes read the whole script first", "Interface in ten languages"];
const highlights = [
  ...MAC_HIGHLIGHTS,
  ...SHARED_ON_HOME.map((k) => SHARED_HIGHLIGHTS.find((item) => item.k === k)).filter((item) => item !== undefined),
];

export const WhatsNew = () => (
  <section className="section whatsnew-section" id="whats-new" aria-labelledby="whatsnew-title">
    <div className="container">
      <header className="section-head">
        <p className="section-note">Released October 2026</p>
        <h2 id="whatsnew-title" className="section-title">What's new in {WHATS_NEW_VERSION}</h2>
        <p className="section-sub">
          A redesigned Mac app that updates itself, and a command line for scripts and AI agents.
          The iPhone app's 3.0 version is in the public TestFlight beta.
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
