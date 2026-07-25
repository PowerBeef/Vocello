import React from "react";
import { REPO } from "../data/credits.js";

export const Footer = () => (
  <footer className="footer">
    <div className="container">
      <div className="footer-inner">
        <div className="footer-brand">
          <div className="brand">
            <img className="brand-mark" src="assets/vocello-header-mark.png" alt="" style={{ width: 24, height: 24 }} />
            <span className="brand-name" style={{ fontSize: 17 }}>Vocello</span>
          </div>
          <p>
            A local, private AI voice studio for Apple Silicon Macs.
            Vocello is the 2.2 line of QwenVoice, signed for macOS 26.
          </p>
        </div>

        <div className="footer-cols">
          <div className="footer-col">
            <h5>Product</h5>
            <ul>
              <li><a href="#workflows">Workflows</a></li>
              <li><a href="#how-it-runs">How it runs</a></li>
              <li><a href="#listen">Listen</a></li>
              <li><a href="#download">Download</a></li>
            </ul>
          </div>
          <div className="footer-col">
            <h5>Open source</h5>
            <ul>
              <li><a href={REPO} target="_blank" rel="noreferrer">GitHub</a></li>
              <li><a href={`${REPO}/releases`} target="_blank" rel="noreferrer">Releases</a></li>
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
