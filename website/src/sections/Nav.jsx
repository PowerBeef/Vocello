import React, { useEffect, useState } from "react";
import { Icon } from "../components/Icon.jsx";
import { REPO } from "../data/credits.js";

export const Nav = () => {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    const onScroll = () => {
      const h = document.documentElement;
      const max = h.scrollHeight - h.clientHeight;
      setProgress(max > 0 ? Math.min(1, h.scrollTop / max) : 0);
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav className="nav">
      <div className="container nav-inner">
        <div className="brand">
          <img className="brand-mark" src="assets/vocello-header-mark.png" alt="" />
          <span className="brand-name">Vocello</span>
          <span className="brand-rebrand">formerly QwenVoice</span>
        </div>
        <div className="nav-links">
          <a className="nav-link--full" href="#workflows">Workflows</a>
          <a href="#listen">Listen</a>
          <a className="nav-link--full" href="#how-it-runs">How it runs</a>
          <a className="nav-link--full" href="#iphone">iPhone</a>
          <a href="#engineering">Engineering</a>
          <a className="nav-link--full" href={REPO} target="_blank" rel="noreferrer">Open source</a>
        </div>
        <a className="nav-cta" href="#download">
          <Icon name="apple" size={14} />
          Download
        </a>
      </div>
      <span className="nav-progress" style={{ transform: `scaleX(${progress})` }} aria-hidden="true" />
    </nav>
  );
};
