import React from "react";
import { MAC_DMG, RELEASE_NOTES } from "../data/credits.js";
import {
  IPHONE_NOTE,
  MAC_HIGHLIGHTS,
  SHARED_HIGHLIGHTS,
  UPGRADE_NOTE,
  WHATS_NEW_VERSION,
} from "../data/whatsnew.js";

// The home page keeps the shared changes people notice first; the release
// notes link carries the rest, and the take-quality note lives with the
// limitations further down the page.
const SHARED_ON_HOME = ["Generated audio is marked", "Takes read the whole script first", "Interface in ten languages"];
const sharedHighlights = SHARED_ON_HOME
  .map((k) => SHARED_HIGHLIGHTS.find((item) => item.k === k))
  .filter((item) => item !== undefined);

export const WhatsNew = () => (
  <section className="section whatsnew-section" id="whats-new" aria-labelledby="whatsnew-title">
    <div className="container">
      <header className="whatsnew-head">
        <p className="section-note">Released October 2026</p>
        <h2 id="whatsnew-title" className="section-title">What's new in {WHATS_NEW_VERSION}</h2>
        <p className="section-sub">
          A redesigned Mac app that runs its engine inside the app and updates itself, and a new
          command line for scripts and AI agents. Everything still runs locally on Apple Silicon;
          no audio leaves your Mac unless you export it.
        </p>
      </header>

      <div className="whatsnew-layout">
        <div className="whatsnew-mac">
          <h3 className="whatsnew-group-title">On the Mac</h3>
          <ol className="whatsnew-lead">
            {MAC_HIGHLIGHTS.map((item, i) => (
              <li className="whatsnew-lead-item" key={item.k}>
                <span className="whatsnew-lead-num" aria-hidden="true">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <p className="whatsnew-lead-k">{item.k}</p>
                  <p className="whatsnew-lead-v">{item.v}</p>
                </div>
              </li>
            ))}
          </ol>

          <a className="whatsnew-cli" href="#cli">
            <span className="whatsnew-cli-prompt" aria-hidden="true">$</span>
            <span className="whatsnew-cli-copy">
              <span className="whatsnew-cli-k">New: the vocello command line</span>
              <span className="whatsnew-cli-v">
                A signed installer package, a machine contract for scripts, and an MCP server for
                AI agents.
              </span>
            </span>
          </a>
        </div>

        <div className="whatsnew-shared">
          <h3 className="whatsnew-group-title">In both apps</h3>
          <p className="whatsnew-shared-note">{IPHONE_NOTE}</p>
          <dl className="whatsnew-list">
            {sharedHighlights.map((item) => (
              <div className="whatsnew-row" key={item.k}>
                <dt className="whatsnew-k">{item.k}</dt>
                <dd className="whatsnew-v">{item.v}</dd>
              </div>
            ))}
          </dl>
        </div>
      </div>

      <div className="whatsnew-upgrade">
        <h3 className="whatsnew-upgrade-title">Before you upgrade</h3>
        <div className="whatsnew-upgrade-body">
          <p>{UPGRADE_NOTE}</p>
          <p className="whatsnew-upgrade-links">
            <a className="cta-meta-link" href={MAC_DMG}>Download the Mac app</a>
            <span className="cta-meta-sep" aria-hidden="true">·</span>
            <a className="cta-meta-link" href={RELEASE_NOTES} target="_blank" rel="noreferrer">
              Read the full release notes, with every change
            </a>
          </p>
        </div>
      </div>
    </div>
  </section>
);
