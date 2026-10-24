import React, { useEffect } from "react";
import { Analytics } from "@vercel/analytics/react";
import { Nav } from "./sections/Nav.jsx";
import { Footer } from "./sections/Footer.jsx";
import { HomePage } from "./pages/HomePage.jsx";
import { CliPage } from "./pages/CliPage.jsx";
import { EngineeringPage } from "./pages/EngineeringPage.jsx";

// Each HTML entry (index.html, cli/index.html, engineering/index.html) names
// its page on the root element; main.jsx and the prerender pass it here.
export const PAGES = Object.freeze({
  home: HomePage,
  cli: CliPage,
  engineering: EngineeringPage,
});

// Scroll-reveal: sections below the first fade up as they enter view. The base
// state stays visible (content shows if JS never runs), and the whole effect is
// skipped under prefers-reduced-motion. Targets are selected by class so section
// JSX stays untouched; a page's leading section is already in view and never
// fades.
const useScrollReveal = () => {
  useEffect(() => {
    if (typeof window === "undefined") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (!("IntersectionObserver" in window)) return;

    const targets = [...document.querySelectorAll(
      ".whatsnew-section, .workflow-band, .listen-section, .caps-section, .cloud-section, " +
        ".runs-section, .cli-section, .iphone-section, .engineering-section, .limitations-section, " +
        ".final-cta-section",
    )].filter((el) => el !== document.querySelector("main > :first-child"));
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

    // Anchor jumps land instantly; reveal the target section without the fade
    // so in-page navigation never arrives on a still-transparent viewport.
    const revealHashTarget = () => {
      const { hash } = window.location;
      if (!hash || hash.length < 2) return;
      let target;
      try {
        target = document.querySelector(hash);
      } catch {
        return;
      }
      const section = target?.closest?.(".reveal") ?? target;
      if (section?.classList?.contains("reveal")) section.classList.add("is-in");
    };
    revealHashTarget();
    window.addEventListener("hashchange", revealHashTarget);
    return () => {
      window.removeEventListener("hashchange", revealHashTarget);
      io.disconnect();
    };
  }, []);
};

/** @param {{ page?: string }} props */
const App = ({ page = "home" }) => {
  useScrollReveal();
  const name = Object.hasOwn(PAGES, page) ? page : "home";
  const Page = PAGES[name];
  return (
  <>
    <a className="skip-link" href="#main-content">Skip to main content</a>
    <Nav page={name} />
    <main id="main-content" tabIndex={-1}>
      <Page />
    </main>
    <Footer page={name} />
    <Analytics />
  </>
  );
};

export default App;
