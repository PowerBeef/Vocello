import React from "react";

const POINTS = [
  {
    k: "No subscription meter",
    body: "Install the app, download the model packages you want, and generate on your Mac without paying per line or per character.",
  },
  {
    k: "No cloud queue",
    body: "Generation runs on your Apple Silicon Mac after setup, so you are not waiting on a shared remote render queue.",
  },
  {
    k: "Local storage",
    body: "Scripts, history, saved voices, and generated audio stay in Vocello's local app storage until you export or reveal a file.",
  },
  {
    k: "Setup is not air-gapped",
    body: "Models download from Hugging Face during setup and updates. After that download, generation runs locally.",
  },
];

export const WhyCloud = () => (
  <section className="section cloud-section" id="why-not-cloud-tts" aria-labelledby="cloud-title">
    <div className="container cloud-layout">
      <div className="cloud-copy">
        <p className="section-note">Why not cloud TTS?</p>
        <h2 id="cloud-title" className="section-title">
          Local first, with the setup caveat.
        </h2>
        <p className="section-sub">
          If you arrived looking for an ElevenLabs local alternative for Mac,
          Vocello's answer is narrower and quieter: your scripts become speech
          on your own Mac, and nothing you write or generate leaves it.
        </p>
      </div>

      <div className="cloud-points" aria-label="Reasons to use local text to speech">
        {POINTS.map((point) => (
          <article className="cloud-point" key={point.k}>
            <h3 className="cloud-k">{point.k}</h3>
            <p className="cloud-body">{point.body}</p>
          </article>
        ))}
      </div>
    </div>
  </section>
);
