import React, { useEffect } from "react";
import { Nav } from "./sections/Nav.jsx";
import { Hero } from "./sections/Hero.jsx";
import { WorkflowBand } from "./sections/WorkflowBand.jsx";
import { Listen } from "./sections/Listen.jsx";
import { Capabilities } from "./sections/Capabilities.jsx";
import { WhyCloud } from "./sections/WhyCloud.jsx";
import { TryIt } from "./sections/TryIt.jsx";
import { HowItRuns } from "./sections/HowItRuns.jsx";
import { Performance } from "./sections/Performance.jsx";
import { Limitations } from "./sections/Limitations.jsx";
import { FinalCTA } from "./sections/FinalCTA.jsx";
import { Footer } from "./sections/Footer.jsx";
import { WORKFLOWS } from "./data/workflows.js";

// Scroll-reveal: sections below the hero fade up as they enter view. The base
// state stays visible (content shows if JS never runs), and the whole effect is
// skipped under prefers-reduced-motion. Targets are selected by class so section
// JSX stays untouched.
const useScrollReveal = () => {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!("IntersectionObserver" in window)) return;

    const targets = document.querySelectorAll(
      ".workflow-band, .listen-section, .caps-section, .cloud-section, " +
        ".try-section, .runs-section, .limitations-section, .final-cta-section",
    );
    if (!targets.length) return;

    targets.forEach((el) => el.classList.add("reveal"));
    document.documentElement.classList.add("reveal-ready");

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            io.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px", threshold: 0.06 },
    );
    targets.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);
};

const App = () => {
  useScrollReveal();
  return (
  <>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <Nav />
    <main id="main-content">
      <Hero />
      <div id="workflows" className="workflows-anchor">
        {WORKFLOWS.map((w, i) => (
          <WorkflowBand key={w.id} workflow={w} index={i} />
        ))}
      </div>
      <Listen />
      <Capabilities />
      <WhyCloud />
      <TryIt />
      <HowItRuns />
      <Performance />
      <Limitations />
      <FinalCTA />
    </main>
    <Footer />
  </>
  );
};

export default App;
