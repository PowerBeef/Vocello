// What's new in Vocello 3.2. Every line restates docs/releases/v3.2.0.md, the
// published release notes; change this module only with those notes. The
// content is 3.2's own, so its version label is literal, not the stable mirror.

export const WHATS_NEW_VERSION = "3.2";

// The release's changes, in the release notes' order. `short` is the home page's
// one-line summary of each; `v` is the full account. 3.2 is the Mac app's and the
// command line's release: the iPhone app's 3.2 version follows (IPHONE_NOTE).
export const HIGHLIGHTS = [
  {
    k: "A leaner, steadier engine",
    short: "Hoisted predictor plans, fixed-shape GPU masking and Mimi encoder fixes trim warm memory and move median speed to 18 s per minute of speech, with identical audio.",
    v: "The code predictor's compiled execution plan is hoisted and prewarmed with weights passed as compile inputs so cross-thread MLX compile caches are not retained between takes, talker repetition penalties use a fixed-shape GPU seen-mask, per-step introspection is gated behind diagnostics, Mimi encoder KV retention and causal-mask handling are fixed, and quantization and fusion invariants fail closed. Audio samples are identical to 3.1 on the same seeds; on the benchmark Mac mini M6, warm median real-time factor moves from 0.315 to 0.308 (about 18 seconds to make one minute of speech, down from 19 seconds) with lower warm retained memory.",
  },
  {
    k: "Smooth live streaming preview",
    short: "The live preview's elapsed counter and waveform bar now advance smoothly while a clip is still generating, and stay monotonic through the handoff.",
    v: "Fixed a timer-starvation bug where incoming audio chunks reset the live preview's 3 Hz playhead timer, leaving elapsed time stuck at 0:00 and the waveform bar immobile while a clip was still generating. The elapsed time counter and waveform bar now advance smoothly throughout generation in both Studio and the sidebar player, hold monotonic progress across arriving chunks and the live-to-final handoff, and scrub back immediately once the take finishes.",
  },
  {
    k: "Long-form, cloning and storage reliability",
    short: "Unspeakable long-form paragraphs fold cleanly, control-token-only scripts are rejected early, and downloads, outbox writes and output errors are hardened.",
    v: "Unspeakable or punctuation-only paragraphs in long-form scripts are folded cleanly instead of stalling a segment, scripts containing only control tokens are rejected before generation starts, Korean long-form cautions surface clearly in Studio and the command line, model downloads and History outbox writes are hardened against partial or corrupted state, and an unwritable output folder reports a storage failure instead of an engine fault.",
  },
  {
    k: "Clearer transparency and AI safeguards",
    short: "Settings adds an AudioSeal watermark disclosure, Terms of Use and Report an Issue links, 10-language impersonation guardrails, and Meta AudioSeal licensing.",
    v: "Mac Settings > Voice Cloning now includes an AudioSeal watermarking disclosure alongside the jurisdiction-neutral cloning consent note; Settings > Updates links directly to Terms of Use and Report an Issue; voice-imitation guardrails are localized across all ten interface languages; and Meta AudioSeal (MIT) is listed in Open Source & Licenses.",
  },
  {
    k: "Same models, no re-download from 3.1",
    short: "Vocello 3.2 keeps 3.1's single model per mode unchanged, so upgrading from 3.1 downloads only the app and preserves pinned 3.1 seeds.",
    v: "Pre-registered automated screens evaluated candidate mixed-precision alternatives against the 3.1 models and did not clear the promotion bar, so Vocello 3.2 keeps the single model per mode introduced in 3.1 unchanged. Upgrading from 3.1 downloads only the app and CLI package, and seeds pinned in 3.1 reproduce their takes in 3.2.",
  },
  {
    k: "Hardened command line and 8 GB coordination",
    short: "Cleaner forced exits, hardened 8 GB single-engine leases and model-deletion gates, hybrid telemetry, and explicit Korean long-form warnings.",
    v: "Forced exits use _exit so teardown hooks do not contend with an active engine, 8 GB single-engine host leases and model-deletion gates are hardened, benchmark telemetry records the hybrid quantization tier directly, and long-form scripts sent as Korean emit long_form_korean before model work.",
  },
];

// The iPhone app's current status (matches IphoneBeta.jsx): the public
// TestFlight beta runs 3.0, and the next iPhone release targets 3.2.
export const IPHONE_NOTE =
  "The iPhone app's 3.2 version, on the same engine and also admitting eligible 8 GB+ iPads in portrait compatibility mode, follows through TestFlight and the App Store. The public TestFlight beta still runs 3.0.";

export const UPGRADE_NOTE =
  "Upgrading from 3.1? Choose Vocello > Check for Updates, or install the new DMG as usual. History, saved voices, settings and installed models carry over with no new model download. Upgrading from 3.0? Choose Vocello > Check for Updates; on first launch Vocello replaces your 3.0 models by the one model per mode on an unmetered network (about 4.7 GB for all three; Not Now stops it). Upgrading from 2.x? Install the new DMG by hand once, then install each mode's model from Settings > Models & Files.";

export const QUALITY_NOTE =
  "Take quality in 3.2 is not verified by human listening. Automated checks catch gross failures (silence, a cut-off or unfinished take, missing words, the wrong language), and a take can still carry subtle defects; generate again for a different take. A seed pinned in 3.1 reproduces its take in 3.2; a seed from 3.0 or earlier does not, because the model changed in 3.1.";
