import React from "react";
import { Icon } from "../components/Icon.jsx";
import { FALLBACK_MAC_RELEASE, STABLE_MAC_RELEASE } from "../data/release.js";

const LIMITATIONS = [
  {
    k: "macOS 26+",
    v: `Vocello ${STABLE_MAC_RELEASE.version} and its command line target macOS 26. QwenVoice ${FALLBACK_MAC_RELEASE.version} remains the macOS 15 fallback.`,
  },
  {
    k: "Apple Silicon and memory",
    v: "Vocello needs an Apple Silicon Mac with at least 8 GB of unified memory. Quality models use larger 8-bit packages and need more headroom than Speed models; 16 GB or more is recommended for them and for long projects.",
  },
  {
    k: "Command line install",
    v: "The command line is arm64 only, and its installer package needs an administrator password. Without one, copy the Vocello CLI folder from its disk image and keep its executable and resource bundles together.",
  },
  {
    k: "Command line and History",
    v: "Takes made with the command line, including through vocello mcp, are saved as files and do not appear in History yet; a 3.0 update adds that. The command line reads History only while the Vocello app is closed.",
  },
  {
    k: "Take quality",
    v: "Take quality is not verified by human listening. Automated checks catch gross failures (silence, a cut-off or unfinished take, missing words, the wrong language), but a take can still carry subtle defects, such as a swallowed syllable or delivery that misses the requested style. Generate again for a different take.",
  },
  {
    k: "Rejected takes",
    v: "Some French and Chinese takes fail the mandatory audio check, and rarely a long-form take develops a long silent gap without finishing. Vocello rejects such a take instead of saving it and never regenerates one silently; generate it again.",
  },
  {
    k: "Consistent long-form stalls",
    v: "Long-form projects using the Consistent take variation can still stall, though far less often than in earlier builds: a segment of about a minute may pause for several seconds or never finish. Audio QC rejects that segment instead of saving it, and Resume retries it with a fresh seed. This was not observed with Expressive, the default.",
  },
  {
    k: "Seeds from earlier versions",
    v: "Sampling changed in 3.0, so a seed pinned in an earlier version does not reproduce its old take.",
  },
  {
    k: "iPhone is in beta",
    v: "The iPhone app is a public TestFlight beta that runs version 2.4. Its 3.0 version follows in the coming days through TestFlight and then the App Store. It needs an iPhone 15 Pro or newer with iOS 26 or later.",
  },
  {
    k: "Cloning varies",
    v: "Use voices you own or have permission to use. For local voice cloning workflows, reference quality matters, and subjective similarity can vary by clip and model behavior.",
  },
  {
    k: "AI disclosure",
    v: "From 3.0, generated takes are saved with an inaudible watermark marking them as AI-generated (on iPhone, from its 3.0 version). Reference clips you record or import are not marked, and neither is live preview audio heard before the file is written. If you publish audio of a cloned real voice, tell your audience it is AI-generated. EU law may require this disclosure.",
  },
];

// The home page keeps the limitations that decide whether Vocello fits a Mac
// or a use; /engineering/ lists every one. Neither page hides the rest: the
// summary links to the full list.
const SUMMARY_KEYS = ["macOS 26+", "Apple Silicon and memory", "Take quality", "iPhone is in beta"];

/** @param {{ variant?: "summary" | "full" }} props */
export const Limitations = ({ variant = "full" }) => {
  const summary = variant === "summary";
  const rows = summary ? LIMITATIONS.filter((item) => SUMMARY_KEYS.includes(item.k)) : LIMITATIONS;
  return (
    <section className="section limitations-section" id="limitations" aria-labelledby="limitations-title">
      <div className="container limits-layout">
        <div className="limits-copy">
          <p className="section-note">Current limitations</p>
          <h2 id="limitations-title" className="section-title">
            The honest edges.
          </h2>
          <p className="section-sub">
            Vocello is a stable release on the Mac and in the terminal, not a claim that every
            machine, workflow, or voice reference behaves the same.
          </p>
          {summary ? (
            <p className="section-more">
              <a className="more-link" href="/engineering/#limitations">
                All {LIMITATIONS.length} current limitations
                <Icon name="arrow-right" size={16} />
              </a>
            </p>
          ) : null}
        </div>
        <dl className="limits-list" aria-label="Vocello current limitations">
          {rows.map((item) => (
            <div className="limits-row" key={item.k}>
              <dt className="limits-k">{item.k}</dt>
              <dd className="limits-v">{item.v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </section>
  );
};
