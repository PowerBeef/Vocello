// What's new in Vocello 3.1. Every line restates docs/releases/v3.1.0.md, the
// published release notes; change this module only with those notes. The
// content is 3.1's own, so its version label is literal, not the stable mirror.

export const WHATS_NEW_VERSION = "3.1";

// The release's changes, in the release notes' order. `short` is the home page's
// one-line summary of each; `v` is the full account. 3.1 is the Mac app's and the
// command line's release: the iPhone app's 3.1 version follows (IPHONE_NOTE).
export const HIGHLIGHTS = [
  {
    k: "One improved model per mode",
    short: "One model per mode replaces Speed and Quality: close to Speed's pace, fewer mistakes on long scripts, and nothing to choose.",
    v: "Built-in Voice, Voice Design and Voice Cloning each use a single model that keeps the 4-bit model's size and puts its attention layers at 8 bits (about 180 MB more). In Vocello's automated screens it makes fewer mistakes than the 3.0 Speed model on single takes and long projects, finishes more long projects, and clones a voice as closely as Speed did. On the benchmark Mac mini M6 it takes about 9% more time than the 3.0 Speed model and about 27% less than Quality. The Speed/Quality switch and the \"Prefer lower-memory models\" setting are gone, and each mode's package row reads Model.",
  },
  {
    k: "Your models update themselves",
    short: "After an update from 3.0, the models you installed update on their own on an unmetered network. Not Now stops it.",
    v: "After an update from 3.0, the modes whose models you installed read Update required and update on their own on an unmetered network, one or two at a time; a mode you never installed stays a first install. A banner above every page shows the progress, offers Update Now or Not Now, and ends with the space your earlier models freed. Each mode downloads about 2.2 GB on its own; updating all three downloads about 4.7 GB, because the speech tokenizer they share with your earlier models is reused. On a disk too full to keep the earlier models meanwhile, Vocello offers to remove them first, and says so on the button. A cancelled or failed update waits for you to choose Update; Vocello never restarts it on its own.",
  },
  {
    k: "Voice cloning follows its reference more faithfully",
    short: "A reference clip is prepared the same way every time: stereo is mixed down and silent edges are trimmed.",
    v: "A reference clip is prepared the same way every time, a stereo clip is mixed down as the reference implementation does, and silent edges are trimmed. A cloned take that plays while it is generated now hears the reference's own speech first, which in Vocello's screens brought it measurably closer to the reference voice. Chinese and Japanese targets join the reference transcript as the reference implementation joins them.",
  },
  {
    k: "Clearer feedback on references",
    short: "Saving a voice checks the recording and names what is wrong with it: a low sample rate, near-silence or clipping.",
    v: "Saving a voice checks the original recording and names what is wrong with it (a low sample rate, near-silence or clipping). A recognized transcript that does not cover the whole clip waits for your review instead of saving as Ready, enrollment asks the recognizer for punctuation, and Use audio only on a saved voice is never overridden by its stored transcript.",
  },
  {
    k: "One way to sample a take",
    short: "The Variation setting is retired: every take samples as the former Expressive did.",
    v: "The Variation setting is retired: every take samples as the model's reference implementation does (the former Expressive). A saved Balanced or Consistent preference reads as Expressive, and History still shows an older take's recorded variation. In the long-form screens Consistent stopped far more projects than Expressive and showed no benefit.",
  },
  {
    k: "A caution for Korean long-form scripts",
    short: "Studio shows a caution under a long script that Auto sends as Korean, before you start.",
    v: "Korean long-form projects stop more often than other languages, so Studio shows a caution under a script that Auto sends as Korean, before you start.",
  },
  {
    k: "A leaner, quicker engine",
    short: "About 315 MB less resident memory and fewer GPU launches per frame, with identical samples. The live preview starts sooner.",
    v: "About 400 fewer GPU kernel launches per frame and the text embedding read from the model file by row (about 315 MB less resident memory), both with identical samples; the live preview starts sooner; the watermark pass finishes faster, and every long-form segment is joined on the watermark's frame so the joined file reads as marked.",
  },
  {
    k: "Stricter automatic checks",
    short: "A take far too short for its script fails the audio check, and one that runs on in silence stops after three seconds.",
    v: "A take far too short for its script now fails Vocello's audio check, silence is judged before the watermark is applied, and a take that runs on in silence stops after three seconds instead of filling its length limit.",
  },
];

// The iPhone app's current status (matches IphoneBeta.jsx): the public
// TestFlight beta runs 3.0, and the next iPhone release targets 3.2.
export const IPHONE_NOTE =
  "The iPhone app's 3.2 version, on the same engine, follows through TestFlight and the App Store. The public TestFlight beta still runs 3.0.";

export const UPGRADE_NOTE =
  "Upgrading from 3.0? Choose Vocello > Check for Updates, or install the new DMG as usual. History, saved voices and settings carry over. On first launch Vocello replaces the models you installed with 3.0 by the new one for each mode, on its own on an unmetered network: a banner shows the progress, and Not Now stops it. Updating all three modes downloads about 4.7 GB. Upgrading from 2.x? Install the new DMG, then install each mode's new model from Settings > Models & Files.";

export const QUALITY_NOTE =
  "Take quality in 3.1 is not verified by human listening. Automated checks catch gross failures (silence, a cut-off or unfinished take, missing words, the wrong language), and a take can still carry subtle defects; generate again for a different take. A seed pinned with 3.0 no longer reproduces its take, because the model changed.";
