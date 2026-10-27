import React from "react";
import { Screenshot } from "../components/Screenshot.jsx";
import { Icon } from "../components/Icon.jsx";
import { TESTFLIGHT } from "../data/credits.js";

export const IphoneBeta = () => (
  <section className="section iphone-section" id="iphone" aria-labelledby="iphone-title">
    <div className="container iphone-layout">
      <div className="iphone-copy">
        <p className="section-note">Vocello for iPhone</p>
        <h2 id="iphone-title" className="section-title">The same studio, in your pocket.</h2>
        <p className="section-sub">
          Built-in Voice, Voice Design and Voice Cloning run locally on the phone, with the
          memory-conscious Speed model, microphone recording and local history.
        </p>
        <p className="iphone-status">
          The public beta runs Vocello 3.0, on the same engine as the Mac app. The App Store
          release follows.
        </p>
        <div className="hero-ctas iphone-ctas">
          <a className="btn btn-primary" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Join the beta on TestFlight
          </a>
        </div>
        <p className="iphone-meta">iPhone 15 Pro or newer · iOS 26 or later</p>
      </div>
      <figure className="iphone-stage">
        <div className="iphone-aura" aria-hidden="true" />
        <div className="phone-frame">
          <Screenshot
            className="iphone-shot"
            src="/assets/screens/ios-studio.png"
            width={780} height={1696}
            alt="Vocello Studio running on an iPhone, with a script ready to generate with a built-in voice"
          />
        </div>
        <figcaption className="iphone-shot-caption">
          An earlier capture: the iPhone's 3.0 version renames Custom Voice to Built-in Voice.
        </figcaption>
      </figure>
    </div>
  </section>
);
