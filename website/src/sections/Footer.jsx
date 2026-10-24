import React from "react";
import { RELEASES, RELEASE_NOTES, REPO } from "../data/credits.js";

export const Footer = () => (
  <footer className="footer">
    <div className="container">
      <div className="footer-inner">
        <div className="footer-brand">
          <div className="brand">
            <img className="brand-mark brand-mark--footer" src="assets/vocello-header-mark.png" width={84} height={72} alt="" />
            <span className="brand-name brand-name--footer">Vocello</span>
          </div>
          <p>
            A local, private AI voice studio for Apple Silicon Macs, with a command line
            for scripts and AI agents. Vocello is the continuation of QwenVoice, signed for
            macOS 26.
          </p>
        </div>

        <div className="footer-cols">
          <div className="footer-col">
            <h2>Product</h2>
            <ul>
              <li><a href="#workflows">Workflows</a></li>
              <li><a href="#listen">Listen</a></li>
              <li><a href="#whats-new">What's new</a></li>
              <li><a href="#how-it-runs">How it runs</a></li>
              <li><a href="#cli">Command line</a></li>
              <li><a href="#iphone">iPhone</a></li>
              <li><a href="#engineering">Engineering</a></li>
              <li><a href="#download">Download</a></li>
              <li><a href="/support/">Support</a></li>
              <li><a href="/privacy/">Privacy</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h2>Open source</h2>
            <ul>
              <li><a href={REPO} target="_blank" rel="noreferrer">GitHub</a></li>
              <li><a href={RELEASE_NOTES} target="_blank" rel="noreferrer">Release notes</a></li>
              <li><a href={RELEASES} target="_blank" rel="noreferrer">Releases</a></li>
              <li><a href={`${REPO}/blob/main/docs/qwen_tone.md`} target="_blank" rel="noreferrer">Docs</a></li>
              <li><a href={`${REPO}/blob/main/LICENSE`} target="_blank" rel="noreferrer">MIT License</a></li>
            </ul>
          </div>
        </div>
      </div>

      <div className="footer-legal">
        <span>© 2026 Vocello. Released under the MIT License.</span>
        <span>Voice cloning is for voices you own or have permission to use.</span>
      </div>
    </div>
  </footer>
);
