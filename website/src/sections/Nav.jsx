import React, { useEffect, useRef, useState } from "react";
import { Icon } from "../components/Icon.jsx";
import { REPO, TESTFLIGHT } from "../data/credits.js";

// Bar links in page order. A `hash` link is a home-page section; a `path`
// link is its own page (`page` names it). `tier` is the narrowest layout tier
// whose bar still shows the link (website/DESIGN.md): "tablet" links show from
// 900 px, "desktop" links from 1200 px. Below the desktop tier the menu sheet
// lists every link, so nothing depends on the bar's width.
const BAR_LINKS = [
  { hash: "#workflows", label: "Voices", tier: "tablet" },
  { hash: "#listen", label: "Listen", tier: "tablet" },
  { hash: "#how-it-runs", label: "Privacy", tier: "tablet" },
  { hash: "#iphone", label: "iPhone", tier: "tablet" },
  { path: "/cli/", page: "cli", label: "Command line", tier: "desktop" },
  { path: "/engineering/", page: "engineering", label: "Engineering", tier: "desktop" },
];

const MENU_LINKS = [
  { hash: "#whats-new", label: "What's new" },
  ...BAR_LINKS,
  { hash: "#limitations", label: "Limitations" },
];

/** A home section is a plain anchor on the home page and "/#id" elsewhere. */
const hrefFor = (link, page) => link.path ?? (page === "home" ? link.hash : `/${link.hash}`);

const Brand = () => (
  <a className="brand" href="/">
    <img className="brand-mark" src="/assets/vocello-header-mark.png" width={84} height={72} alt="" />
    <span className="brand-name">Vocello</span>
    <span className="brand-rebrand">formerly QwenVoice</span>
    <span className="sr-only"> (home)</span>
  </a>
);

/** @param {{ page?: string }} props */
export const Nav = ({ page = "home" }) => {
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
    if (page !== "home" || !("IntersectionObserver" in window)) return;
    const linked = new Set(BAR_LINKS.map((link) => link.hash).filter(Boolean));
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
  }, [page]);

  /** @param {{ hash?: string, page?: string }} link */
  const currentFor = (link) => {
    if (link.page) return link.page === page ? "page" : undefined;
    return page === "home" && current === link.hash ? "location" : undefined;
  };

  const openMenu = () => {
    menuRef.current?.showModal();
    setMenuOpen(true);
  };
  const closeMenu = () => menuRef.current?.close();

  // A menu link to a section of this page navigates after the sheet has closed:
  // while it is open the page cannot scroll, so a jump made in the same click
  // could land nowhere. Links to another page navigate as usual.
  /** @param {React.MouseEvent<HTMLAnchorElement>} event */
  const followMenuLink = (event) => {
    const href = event.currentTarget.getAttribute("href") ?? "";
    closeMenu();
    if (!href.startsWith("#")) return;
    event.preventDefault();
    window.requestAnimationFrame(() => {
      if (window.location.hash === href) document.querySelector(href)?.scrollIntoView();
      else window.location.hash = href;
    });
  };

  return (
    <nav className="nav" aria-label="Main">
      <div className="container nav-inner">
        <Brand />
        <div className="nav-links">
          {BAR_LINKS.map((link) => (
            <a
              key={link.label}
              className={`nav-link nav-link--${link.tier}`}
              href={hrefFor(link, page)}
              aria-current={currentFor(link)}
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
              <li key={link.label}>
                <a href={hrefFor(link, page)} aria-current={currentFor(link)} onClick={followMenuLink}>
                  {link.label}
                </a>
              </li>
            ))}
          </ul>
          <ul className="menu-secondary">
            <li><a href={REPO} target="_blank" rel="noreferrer">Open source</a></li>
            <li><a href="/support/">Support</a></li>
            <li><a href="/privacy/">Privacy policy</a></li>
          </ul>
          <div className="menu-ctas">
            <a className="btn btn-primary" href="#download" onClick={followMenuLink}>
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
