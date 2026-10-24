import React from "react";
import { Icon } from "../components/Icon.jsx";
import { Screenshot } from "../components/Screenshot.jsx";
import { MAC_DMG, TESTFLIGHT } from "../data/credits.js";
import { STABLE_MAC_RELEASE } from "../data/release.js";

// "3.0.0" reads as "3.0" in the eyebrow; the button keeps the exact version.
const releaseLabel = STABLE_MAC_RELEASE.version.replace(/\.0$/, "");

// Centered: the promise first, then the product. The Mac window carries the
// stage and the iPhone stands in front of it, as in the README art.
export const Hero = () => (
  <section className="hero" aria-labelledby="hero-title">
    <div className="container hero-copy">
      <a className="hero-eyebrow" href="#whats-new">
        <span className="hero-eyebrow-tag">New</span>
        Vocello {releaseLabel} for Mac
        <Icon name="arrow-right" size={14} />
      </a>
      <h1 id="hero-title" className="hero-title">
        Premium voice studio. <span className="accent-gold">Proven performance.</span>{" "}
        Private by design.
      </h1>
      <p className="hero-sub">
        Write a script, pick or describe a voice, and Vocello speaks it. Every take is
        generated locally on your Mac, so your words stay yours.
      </p>
      <div className="hero-ctas">
        <a className="btn btn-primary btn-large" href={MAC_DMG}>
          <Icon name="apple" size={17} />
          Download for Mac
          <span className="platform-mini">{STABLE_MAC_RELEASE.version}</span>
        </a>
        <a className="btn btn-secondary btn-large" href="#listen">
          <Icon name="play" size={14} />
          Listen to samples
        </a>
      </div>
      <ul className="hero-meta meta-list" aria-label="About this download">
        <li>Free and open source</li>
        <li>macOS 26 on Apple Silicon</li>
        <li>
          Also on iPhone,{" "}
          <a className="cta-meta-link" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            in public beta
          </a>
        </li>
      </ul>
    </div>
    <div className="container hero-stage">
      <div className="hero-aura" aria-hidden="true" />
      <div className="window hero-window">
        <Screenshot
          src="/assets/screens/custom-voice.png"
          width={2080} height={1356}
          priority
          sizes="(max-width: 1199.98px) 92vw, 1040px"
          alt="The Vocello Studio on a Mac: a Built-in Voice take ready to play, with its speaker, delivery and language chosen"
        />
      </div>
      <div className="hero-phone" aria-hidden="true">
        <Screenshot
          src="/assets/screens/ios-studio.png"
          width={780} height={1696}
          priority
          alt=""
        />
      </div>
    </div>
  </section>
);
