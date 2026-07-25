import React from "react";

const LIMITATIONS = [
  {
    k: "macOS 26+",
    v: "Vocello 2.2.0 targets macOS 26. QwenVoice 1.2.3 remains the macOS 15 fallback.",
  },
  {
    k: "Apple Silicon only",
    v: "The app is built around Swift, MLX, and local model packages for Apple Silicon Macs.",
  },
  {
    k: "iPhone not public yet",
    v: "The iPhone app is maintained in the repository, but public distribution is not attached to this Mac release.",
  },
  {
    k: "Quality is heavier",
    v: "Quality models use larger 8-bit packages and need more memory headroom than Speed models.",
  },
  {
    k: "Cloning varies",
    v: "Use voices you own or have permission to use. For offline voice cloning Mac workflows, reference quality matters, and subjective similarity can vary by clip and model behavior.",
  },
];

export const Limitations = () => (
  <section className="section limitations-section" id="limitations" aria-labelledby="limitations-title">
    <div className="container limits-layout">
      <div className="limits-copy">
        <p className="section-note">Current limitations</p>
        <h2 id="limitations-title" className="section-title">
          The honest edges.
        </h2>
        <p className="section-sub">
          Vocello is a stable Mac release, not a claim that every machine,
          workflow, or voice reference behaves the same.
        </p>
      </div>

      <dl className="limits-list" aria-label="Vocello current limitations">
        {LIMITATIONS.map((item) => (
          <div className="limits-row" key={item.k}>
            <dt className="limits-k">{item.k}</dt>
            <dd className="limits-v">{item.v}</dd>
          </div>
        ))}
      </dl>
    </div>
  </section>
);
