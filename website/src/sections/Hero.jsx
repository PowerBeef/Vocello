import React from "react";
import { Icon } from "../components/Icon.jsx";
import { RELEASE_LATEST, TESTFLIGHT } from "../data/credits.js";

export const Hero = () => (
  <section className="hero">
    <div className="container hero-split">
      <div className="hero-copy">
        <div className="hero-eyebrow">
          <span className="dot" aria-hidden="true" />
          Vocello 2.2.2 · macOS 26+ · Apple Silicon
        </div>
        <h1 className="hero-title">
          A voice studio that <span className="accent-gold">never leaves</span> your Mac.
        </h1>
        <p className="hero-sub">
          Write a script, pick a preset or describe a voice, and generate speech locally
          on your Apple Silicon Mac. Ten languages and responsive native generation after
          a one-time model download.
        </p>
        <div className="hero-ctas">
          <a className="btn btn-primary" href={RELEASE_LATEST} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Download for macOS&nbsp;26
            <span className="platform-mini">· 2.2.2</span>
          </a>
          <a className="btn btn-secondary" href="#listen">
            <Icon name="play" size={14} />
            Listen to samples
          </a>
        </div>
        <p className="hero-meta">Signed + notarized Mac download · MIT app code · Swift + MLX</p>
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
          <img
            src="assets/screens/custom-voice.png"
            alt="Vocello Custom Voice screen showing speaker, delivery, model, and script controls"
          />
        </div>
      </div>
    </div>
  </section>
);
