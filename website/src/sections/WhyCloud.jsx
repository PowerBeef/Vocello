import React from "react";

const COMPARE = [
  { k: "Price", vocello: "Free, MIT licensed", cloud: "Subscription or credit packs" },
  { k: "Where speech is generated", vocello: "On your Mac", cloud: "On the provider's servers" },
  { k: "Your script", vocello: "Stays in local app storage", cloud: "Uploaded to generate" },
  { k: "Metering", vocello: "None", cloud: "Per character or per minute" },
  { k: "Account", vocello: "None", cloud: "Required" },
  {
    k: "Automation and agents",
    vocello: "The vocello command line and its MCP server, run locally",
    cloud: "A web API called with an account key",
  },
  {
    k: "Raw English naturalness",
    vocello: "Varies by take; listen to the samples above",
    cloud: "The best cloud voices still lead",
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

      <div className="cloud-compare">
        <table className="compare-table">
          <thead>
            <tr>
              <td className="compare-corner" aria-hidden="true" />
              <th scope="col">Vocello</th>
              <th scope="col">Cloud TTS services</th>
            </tr>
          </thead>
          <tbody>
            {COMPARE.map((row) => (
              <tr key={row.k}>
                <th scope="row">{row.k}</th>
                <td>{row.vocello}</td>
                <td>{row.cloud}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="compare-footnote">
          Setup is not air-gapped: models download from Hugging Face during setup and
          updates, and the Mac app checks GitHub for new versions when you allow it. After
          the model download, generation runs locally.
        </p>
      </div>
    </div>
  </section>
);
