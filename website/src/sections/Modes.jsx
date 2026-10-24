import React, { useRef, useState } from "react";
import { Screenshot } from "../components/Screenshot.jsx";
import { WORKFLOWS } from "../data/workflows.js";

// The three modes behind one switcher, like the app's own mode control: one
// panel at a time, and the section takes the selected mode's color. Without
// JavaScript, a <noscript> style in index.html hides the switcher and shows
// every panel in a stack, each under its own mode label.
export const Modes = () => {
  const [active, setActive] = useState(0);
  const tabs = useRef([]);

  const select = (index, focus = false) => {
    const next = (index + WORKFLOWS.length) % WORKFLOWS.length;
    setActive(next);
    if (focus) tabs.current[next]?.focus();
  };

  /** @param {React.KeyboardEvent} event */
  const onKeyDown = (event) => {
    const moves = { ArrowRight: active + 1, ArrowLeft: active - 1, Home: 0, End: WORKFLOWS.length - 1 };
    if (!(event.key in moves)) return;
    event.preventDefault();
    select(moves[/** @type {keyof typeof moves} */ (event.key)], true);
  };

  return (
    <section
      className="section modes-section"
      id="workflows"
      aria-labelledby="modes-title"
      style={{ "--mode-current": WORKFLOWS[active].color }}
    >
      <div className="container">
        <header className="section-head section-head--center">
          <p className="section-note">Three ways to make a voice</p>
          <h2 id="modes-title" className="section-title">Pick a voice, describe one, or bring your own.</h2>
        </header>

        <div className="mode-switch" role="tablist" aria-label="Voice modes">
          {WORKFLOWS.map((mode, index) => (
            <button
              key={mode.id}
              ref={(node) => { tabs.current[index] = node; }}
              type="button"
              role="tab"
              id={`mode-tab-${mode.id}`}
              className="mode-tab"
              style={{ "--tab-mode": mode.color }}
              aria-selected={index === active}
              aria-controls={`mode-panel-${mode.id}`}
              tabIndex={index === active ? 0 : -1}
              onClick={() => select(index)}
              onKeyDown={onKeyDown}
              aria-label={mode.tab}
            >
              <span className="mode-dot" aria-hidden="true" />
              {mode.short}
            </button>
          ))}
        </div>

        <div className="mode-panels">
          {WORKFLOWS.map((mode, index) => (
            <div
              key={mode.id}
              id={`mode-panel-${mode.id}`}
              className="mode-panel"
              style={{ "--panel-mode": mode.color }}
              role="tabpanel"
              aria-labelledby={`mode-tab-${mode.id}`}
              hidden={index !== active}
            >
              <div className="mode-copy">
                <p className="mode-label">
                  <span className="mode-dot" aria-hidden="true" />
                  {mode.tab}
                </p>
                <h3 id={`mode-title-${mode.id}`} className="mode-title">{mode.title}</h3>
                <p className="mode-body">{mode.body}</p>
                <ul className="mode-points">
                  {mode.points.map((point) => <li key={point}>{point}</li>)}
                </ul>
              </div>
              <figure className="mode-shot">
                <div className="window">
                  <Screenshot
                    src={mode.shot}
                    width={2080} height={mode.shotHeight}
                    alt={`The Vocello ${mode.tab} screen in the Mac app`}
                  />
                </div>
              </figure>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
};
