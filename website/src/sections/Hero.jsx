import React from "react";
import { Icon } from "../components/Icon.jsx";
import { Screenshot } from "../components/Screenshot.jsx";
import { RELEASE_STABLE, TESTFLIGHT } from "../data/credits.js";
import { STABLE_MAC_RELEASE } from "../data/release.js";

export const Hero = () => (
  <section className="hero">
    <div className="container hero-split">
      <div className="hero-copy">
        <div className="hero-eyebrow">
          <span className="dot" aria-hidden="true" />
          Vocello {STABLE_MAC_RELEASE.version} · macOS 26+ · Apple Silicon
        </div>
        <h1 className="hero-title">
          Premium voice studio. <span className="accent-gold">Proven performance.</span>{" "}
          Private by design.
        </h1>
        <p className="hero-sub">
          A voice studio that never leaves your Mac. Write a script, pick a preset or
          describe a voice, and generate speech locally on Apple Silicon. Ten languages
          and responsive native generation after a one-time model download.
        </p>
        <div className="hero-ctas">
          <a className="btn btn-primary" href={RELEASE_STABLE} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Download for macOS&nbsp;26
            <span className="platform-mini">· {STABLE_MAC_RELEASE.version}</span>
          </a>
          <a className="btn btn-secondary" href="#listen">
            <Icon name="play" size={14} />
            Listen to samples
          </a>
        </div>
        <p className="hero-meta">Signed + notarized Mac download · MIT app code · Swift + MLX</p>
        <p className="hero-meta">
          Mac screens on this page show the upcoming Vocello 3.0, and features new in 3.0 are
          marked; the iPhone screen is an earlier capture. The 2.4.0 download and that capture
          use Built-in Voice's earlier name, Custom Voice.
        </p>
        <p className="hero-meta">
          Also on iPhone:{" "}
          <a className="cta-meta-link" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            join the public beta on TestFlight
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
