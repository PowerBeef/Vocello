import React, { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon.jsx";
import { REPO, TESTFLIGHT } from "../data/credits.js";

// Section links in page order. `tier` is the narrowest layout tier whose bar
// still shows the link (website/DESIGN.md): "tablet" links show from 900 px,
// "desktop" links from 1200 px. Below the desktop tier the menu sheet lists
// every link, so nothing depends on the bar's width.
const SECTION_LINKS = [
  { href: "#workflows", label: "Workflows", tier: "tablet" },
  { href: "#listen", label: "Listen", tier: "tablet" },
  { href: "#how-it-runs", label: "How it runs", tier: "desktop" },
  { href: "#cli", label: "Command line", tier: "tablet" },
  { href: "#iphone", label: "iPhone", tier: "tablet" },
  { href: "#engineering", label: "Engineering", tier: "desktop" },
];

const MENU_LINKS = [
  { href: "#whats-new", label: "What's new" },
  ...SECTION_LINKS,
  { href: "#limitations", label: "Limitations" },
];

const Brand = () => (
  <a className="brand" href="#main-content">
    <img className="brand-mark" src="assets/vocello-header-mark.png" width={84} height={72} alt="" />
    <span className="brand-name">Vocello</span>
    <span className="brand-rebrand">formerly QwenVoice</span>
    <span className="sr-only"> (top of the page)</span>
  </a>
);

export const Nav = () => {
  const [progress, setProgress] = useState(0);
  const [current, setCurrent] = useState(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef(/** @type {HTMLDialogElement | null} */ (null));
  const menuButtonRef = useRef(/** @type {HTMLButtonElement | null} */ (null));

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

  // The bar marks the section crossing the middle of the viewport; sections
  // without a bar link (the hero, What's new, the download block) clear it.
  useEffect(() => {
    if (!("IntersectionObserver" in window)) return;
    const linked = new Set(SECTION_LINKS.map((link) => link.href));
    const sections = document.querySelectorAll("main > section, main > div[id]");
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const id = entry.target.id ? `#${entry.target.id}` : null;
          setCurrent(id && linked.has(id) ? id : null);
        });
      },
      { rootMargin: "-45% 0px -54% 0px" },
    );
    sections.forEach((section) => io.observe(section));
    return () => io.disconnect();
  }, []);

  const openMenu = () => {
    menuRef.current?.showModal();
    setMenuOpen(true);
  };
  const closeMenu = () => menuRef.current?.close();

  return (
    <nav className="nav" aria-label="Main">
      <div className="container nav-inner">
        <Brand />
        <div className="nav-links">
          {SECTION_LINKS.map((link) => (
            <a
              key={link.href}
              className={`nav-link nav-link--${link.tier}`}
              href={link.href}
              aria-current={current === link.href ? "location" : undefined}
            >
              {link.label}
            </a>
          ))}
          <a className="nav-link nav-link--wide" href={REPO} target="_blank" rel="noreferrer">
            Open source
          </a>
        </div>
        <div className="nav-actions">
          <a className="nav-cta" href="#download">
            <span className="nav-cta-pill">
              <Icon name="apple" size={14} />
              Download
            </span>
          </a>
          <button
            ref={menuButtonRef}
            type="button"
            className="nav-menu-button"
            aria-label="Menu"
            aria-haspopup="dialog"
            aria-expanded={menuOpen}
            aria-controls="site-menu"
            onClick={openMenu}
          >
            <Icon name="menu" size={22} />
          </button>
        </div>
      </div>
      <span className="nav-progress" style={{ transform: `scaleX(${progress})` }} aria-hidden="true" />

      <dialog
        id="site-menu"
        className="menu-sheet"
        ref={menuRef}
        aria-label="Site menu"
        onClose={() => {
          setMenuOpen(false);
          // Safari never focuses a tapped button, so the dialog has nothing to
          // restore focus to: hand it back to the menu button explicitly.
          menuButtonRef.current?.focus({ preventScroll: true });
        }}
        onClick={(event) => {
          // A click that lands on the dialog itself is on its backdrop.
          if (event.target === event.currentTarget) closeMenu();
        }}
      >
        <div className="menu-sheet-inner">
          <div className="menu-sheet-head">
            <span className="menu-sheet-title">Vocello</span>
            <button type="button" className="nav-menu-button" aria-label="Close menu" onClick={closeMenu}>
              <Icon name="close" size={22} />
            </button>
          </div>
          <ul className="menu-links">
            {MENU_LINKS.map((link) => (
              <li key={link.href}>
                <a href={link.href} onClick={closeMenu}>{link.label}</a>
              </li>
            ))}
          </ul>
          <ul className="menu-secondary">
            <li><a href={REPO} target="_blank" rel="noreferrer">Open source</a></li>
            <li><a href="/support/">Support</a></li>
            <li><a href="/privacy/">Privacy</a></li>
          </ul>
          <div className="menu-ctas">
            <a className="btn btn-primary" href="#download" onClick={closeMenu}>
              <Icon name="apple" size={16} />
              Download for macOS&nbsp;26
            </a>
            <a className="btn btn-secondary" href={TESTFLIGHT} target="_blank" rel="noreferrer">
              Join the iPhone beta
            </a>
          </div>
        </div>
      </dialog>
    </nav>
  );
};
