import React from "react";
import { Icon } from "../components/Icon.jsx";
import { TESTFLIGHT } from "../data/credits.js";

export const IphoneBeta = () => (
  <section className="section iphone-section" id="iphone" aria-labelledby="iphone-title">
    <div className="container iphone-layout">
      <div className="iphone-copy">
        <p className="section-note">Vocello for iPhone</p>
        <h2 id="iphone-title" className="section-title">
          The same studio, in your pocket.
        </h2>
        <p className="section-sub">
          The iPhone app runs the same local engine in-process on the phone: Custom Voice,
          Voice Design, and Voice Cloning with the memory-conscious Speed model, microphone
          recording or a saved Voice Design reference for cloning, and local history.
        </p>
        <div className="hero-ctas">
          <a className="btn btn-primary" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Join the public beta on TestFlight
          </a>
        </div>
        <p className="hero-meta">Public TestFlight beta · iPhone 15 Pro or newer · iOS 26</p>
      </div>
      <figure className="iphone-stage">
        <img
          className="iphone-shot"
          src="assets/screens/ios-studio.png"
          alt="Vocello Studio running on an iPhone, with a script ready to generate with a built-in voice"
        />
      </figure>
    </div>
  </section>
);
