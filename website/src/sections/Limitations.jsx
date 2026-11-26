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
    v: "Vocello needs an Apple Silicon Mac with at least 8 GB of unified memory; 16 GB or more is recommended for long projects. Each mode has one model, the same on an 8 GB Mac as on a larger one.",
  },
  {
    k: "Command line install",
    v: "The command line is arm64 only, and its installer package needs an administrator password. Without one, copy the Vocello CLI folder from its disk image and keep its executable and resource bundles together.",
  },
  {
    k: "Command line and History",
    v: "Takes made with the command line, including through vocello mcp, are saved as files and do not appear in History yet; a later update adds that. The command line reads History only while the Vocello app is closed.",
  },
  {
    k: "Take quality",
    v: "Take quality is not verified by human listening. Automated checks catch gross failures (silence, a cut-off or unfinished take, missing words, the wrong language), but a take can still carry subtle defects, such as a swallowed syllable or delivery that misses the requested style. Generate again for a different take.",
  },
  {
    k: "Rejected takes",
    v: "The mandatory audio check can still refuse a take in any language, and rarely a take says its text and then runs on in silence: Vocello stops it after three seconds and the check refuses it. Vocello rejects such a take instead of saving it and never silently regenerates, substitutes or accepts one; generate it again.",
  },
  {
    k: "Korean long-form projects",
    v: "Korean long-form projects still stop on about half the scripts in Vocello's automated screens, so Studio shows a caution before you start one. When a segment is refused, Resume continues with a new take of it.",
  },
  {
    k: "Against 3.0's models",
    v: "Each mode's model (introduced in 3.1 and kept unchanged in 3.2) clones a voice about as closely as the 3.0 Speed model, not as closely as Quality, and its long-form error rate sits between the two.",
  },
  {
    k: "Seeds from earlier versions",
    v: "A seed pinned in 3.1 reproduces its take in 3.2; a seed pinned with 3.0 or earlier does not, because the model changed in 3.1.",
  },
  {
    k: "iPhone is in beta",
    v: "The iPhone app is a public TestFlight beta that runs Vocello 3.0; its 3.2 version follows through TestFlight and the App Store. It needs an iPhone 15 Pro or newer (or an eligible Apple silicon or A17 Pro iPad with 8 GB+ memory in portrait compatibility mode) with iOS 26 or later.",
  },
  {
    k: "Cloning varies",
    v: "Use voices you own or have permission to use. For local voice cloning workflows, reference quality matters, and subjective similarity can vary by clip and model behavior.",
  },
  {
    k: "AI disclosure",
    v: "From 3.0, generated takes are saved with an inaudible AudioSeal watermark and WAV provenance metadata marking them as AI-generated (on iPhone, from its 3.0 version). Reference clips you record or import are not marked, and neither is live preview audio heard before the file is written. If you publish audio of a cloned real voice, tell your audience it is AI-generated; applicable laws or platform rules may require this disclosure. Standard open-source AudioSeal tools can inspect exported WAV files, though external transcoding or heavy compression after export may degrade the watermark.",
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
            {summary ? "Good to know." : "The honest edges."}
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
