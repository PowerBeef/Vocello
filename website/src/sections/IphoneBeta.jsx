import React from "react";
import { Screenshot } from "../components/Screenshot.jsx";
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
          The iPhone app runs its engine locally, in-process on the phone: Built-in Voice,
          Voice Design, and Voice Cloning with the memory-conscious Speed model, microphone
          recording, audio file import, or a saved voice as the cloning reference, and local
          history.
        </p>
        <p className="section-sub">
          The public TestFlight beta runs version 2.4. The iPhone app's 3.0 version, on the
          same engine as the Mac app, follows in the coming days through TestFlight and then
          the App Store.
        </p>
        <div className="hero-ctas">
          <a className="btn btn-primary" href={TESTFLIGHT} target="_blank" rel="noreferrer">
            <Icon name="apple" size={16} />
            Join the public beta on TestFlight
          </a>
        </div>
        <p className="hero-meta">Public TestFlight beta · iPhone 15 Pro or newer · iOS 26 or later</p>
      </div>
      <figure className="iphone-stage">
        <Screenshot
          className="iphone-shot"
          src="/assets/screens/ios-studio.png"
          width={780} height={1696}
          alt="Vocello Studio running on an iPhone, with a script ready to generate with a built-in voice"
        />
        <figcaption className="iphone-shot-caption">
          An earlier iPhone capture: the screen still says Custom Voice, which the iPhone's 3.0 version renames Built-in Voice.
        </figcaption>
      </figure>
    </div>
  </section>
);
