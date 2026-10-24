import React from "react";
import { Icon } from "../components/Icon.jsx";

// One promise, four plain facts and an honest comparison. The section keeps the
// ids older links use: #how-it-runs on the section, #why-not-cloud-tts on the
// comparison.
const FACTS = [
  {
    icon: "lock",
    k: "Nothing is uploaded",
    v: "Scripts, recordings, voices and takes stay in local storage until you export them.",
  },
  {
    icon: "shield",
    k: "No account",
    v: "Open the app and start. There is nothing to sign up for.",
  },
  {
    icon: "infinity",
    k: "No meter",
    v: "No subscription, credits or price per character. Generate as much as your Mac can hold.",
  },
  {
    icon: "github",
    k: "Free and open source",
    v: "The Mac app and the command line are MIT licensed, and every line is on GitHub.",
  },
];

const COMPARE = [
  { k: "Price", vocello: "Free", cloud: "Subscription or credits" },
  { k: "Where speech is made", vocello: "On your Mac", cloud: "On the provider's servers" },
  { k: "Your script", vocello: "Stays in local storage", cloud: "Uploaded to generate" },
  { k: "Account", vocello: "None", cloud: "Required" },
  { k: "English naturalness", vocello: "Varies by take; hear the samples", cloud: "The best cloud voices still lead" },
];

export const Privacy = () => (
  <section className="section privacy-section" id="how-it-runs" aria-labelledby="privacy-title">
    <div className="container">
      <header className="section-head section-head--center">
        <p className="section-note">Private by design</p>
        <h2 id="privacy-title" className="section-title privacy-title">Your words stay on your Mac.</h2>
        <p className="section-sub">
          Vocello generates speech on your own Apple Silicon. The privacy is not a setting:
          it is how the app is built.
        </p>
      </header>

      <ul className="privacy-facts" role="list">
        {FACTS.map((fact, index) => (
          <li key={fact.k} className="privacy-fact" style={{ "--i": index }}>
            <span className="privacy-icon" aria-hidden="true"><Icon name={fact.icon} size={20} /></span>
            <h3 className="privacy-k">{fact.k}</h3>
            <p className="privacy-v">{fact.v}</p>
          </li>
        ))}
      </ul>

      <div className="privacy-compare" id="why-not-cloud-tts">
        <table className="compare-table">
          <caption className="compare-caption">Vocello and cloud voice services</caption>
          <thead>
            <tr>
              <td className="compare-corner" aria-hidden="true" />
              <th scope="col">Vocello</th>
              <th scope="col">Cloud voice services</th>
            </tr>
          </thead>
          <tbody>
            {COMPARE.map((row) => (
              <tr key={row.k}>
                <th scope="row">{row.k}</th>
                <td data-label="Vocello">{row.vocello}</td>
                <td data-label="Cloud voice services">{row.cloud}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="privacy-footnote">
          Setup needs the internet once: each model downloads from Hugging Face, and the Mac app
          checks GitHub for updates when you allow it. After that, generation runs locally.
        </p>
      </div>
    </div>
  </section>
);
