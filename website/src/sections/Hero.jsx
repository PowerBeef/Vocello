import React from "react";
import { Icon } from "../components/Icon.jsx";
import { Screenshot } from "../components/Screenshot.jsx";
import { MAC_DMG, TESTFLIGHT } from "../data/credits.js";
import { STABLE_MAC_RELEASE } from "../data/release.js";

// "3.0.0" reads as "3.0" in the eyebrow; buttons keep the exact version.
const releaseLabel = STABLE_MAC_RELEASE.version.replace(/\.0$/, "");

export const Hero = () => (
  <section className="hero">
    <div className="container hero-split">
      <div className="hero-copy">
        <a className="hero-eyebrow" href="#whats-new">
          <span className="dot" aria-hidden="true" />
          Vocello {releaseLabel} · macOS 26+ · Apple Silicon
          <span className="sr-only"> (see what's new in {releaseLabel})</span>
        </a>
        <h1 className="hero-title">
          Premium voice studio. <span className="accent-gold">Proven performance.</span>{" "}
          Private by design.
        </h1>
        <p className="hero-sub">
          A voice studio that never leaves your Mac. Write a script, pick a preset or
          describe a voice, and generate speech locally on Apple Silicon, in ten languages,
          after a one-time model download. In {releaseLabel}, a command line brings the same
          engine to scripts and AI agents.
        </p>
        <div className="hero-ctas">
          <a className="btn btn-primary" href={MAC_DMG}>
            <Icon name="apple" size={16} />
            Download for macOS&nbsp;26
            <span className="platform-mini">· {STABLE_MAC_RELEASE.version}</span>
          </a>
          <a className="btn btn-secondary" href="#cli">
            <span className="btn-prompt" aria-hidden="true">$_</span>
            Command line
          </a>
        </div>
        <p className="hero-meta">
          Signed and notarized · Updates itself · MIT app code · Swift + MLX
        </p>
        <p className="hero-meta">
          On iPhone, Vocello is in public TestFlight until its App Store release:{" "}
          <a className="cta-meta-link" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            join the beta
          </a>
        </p>
      </div>
      <div className="hero-stage">
        <div className="hero-stage-glow" aria-hidden="true" />
        <div className="window hero-window">
          <Screenshot
            src="assets/screens/custom-voice.png"
            width={2080} height={1380}
            priority
            alt="Vocello Built-in Voice screen showing speaker, delivery, model, and script controls"
          />
        </div>
      </div>
    </div>
  </section>
);
