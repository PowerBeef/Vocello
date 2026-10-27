// What's new in Vocello 3.0. Every line restates docs/releases/v3.0.0.md, the
// published release notes; change this module only with those notes. The
// content is 3.0's own, so its version label is literal, not the stable mirror.

export const WHATS_NEW_VERSION = "3.0";

// The Mac app's three headline changes, in the release notes' order. `short` is the home page's
// one-line summary of each; `v` is the full account.
export const MAC_HIGHLIGHTS = [
  {
    k: "A redesigned Mac app",
    short: "The iPhone app's look comes to the Mac: a new window, the Studio canvas and mode colors.",
    v: "The Mac app adopts the iPhone app's visual language: a new window with four sidebar destinations, the Studio canvas with the phone's setup chips, dock and mode colors, and Settings organized in categories. Custom Voice is now called Built-in Voice, as it is in the iPhone app's 3.0 version.",
  },
  {
    k: "The engine runs inside the app",
    short: "One engine inside the app, as on iPhone, with one memory policy for both.",
    v: "The separate engine service is gone. The Mac app hosts the engine in-process, as the iPhone app does, so one lifecycle and one memory policy serve both: the engine trims its caches under memory pressure, and an idle model unloads according to the Mac's memory tier.",
  },
  {
    k: "The app updates itself",
    short: "Signed updates from Vocello > Check for Updates, or on its own schedule.",
    v: "Vocello looks for new versions with Sparkle, on its own schedule or when you choose Vocello > Check for Updates, and installs one when you accept it. Automatic checks are a setting you can turn off. Every update is signed, and the app checks that signature before installing.",
  },
];

// The iPhone app's 3.0 status. The release notes keep the timing they were published with;
// since October 26, 2026 the public TestFlight beta runs 3.0.
export const IPHONE_NOTE =
  "The iPhone app's 3.0 version brings the same engine and these changes. It is in the public TestFlight beta, and the App Store release follows.";

// Shared changes, in both apps (on iPhone, with its 3.0 version).
export const SHARED_HIGHLIGHTS = [
  {
    k: "Generated audio is marked",
    short: "Every generated take carries an inaudible watermark marking it as AI-generated.",
    v: "Every generated WAV, in the apps and the command line, carries an inaudible AudioSeal watermark and a machine-readable provenance note naming the generator, version, model and mode. Only generated takes are marked: reference clips you record or import are not, and neither is live preview audio heard before the file is written. Publishing a cloned real voice still calls for your own disclosure.",
  },
  {
    k: "Interface in ten languages",
    short: "Choose the interface language in Settings, apart from the speech language.",
    v: "English, French, Spanish, German, Italian, Brazilian Portuguese, Simplified Chinese, Japanese, Korean and Russian, chosen in Settings independently of the ten speech languages.",
  },
  {
    k: "Pin a take's seed",
    v: "Every finished take records its seed. Pin it from History, and later generations with the same settings reproduce the take; leave it unpinned for a fresh take each time.",
  },
  {
    k: "Clearer delivery roster",
    v: "Neutral, Sad, Calm and Whisper form the measured group. Happy, Angry, Fearful and Surprised remain directional hints that shape energy and pace, not promises of an exact emotion.",
  },
  {
    k: "Takes read the whole script first",
    short: "Built-in Voice and Voice Design takes see their full text before they speak.",
    v: "Built-in Voice and Voice Design takes now see their full text before speaking, as the reference Qwen3-TTS does. In an automated screen, with no listening, takes with wrong or missing words fell by about half. Long-form projects keep the previous layout.",
  },
  {
    k: "Delivery for curated cloned voices",
    v: "A cloned voice with a curated emotion reference bank offers a delivery choice, each delivery backed by its own verified reference clip rather than an engine instruction.",
  },
];

export const UPGRADE_NOTE =
  "Upgrading from 2.4? Install the new DMG by hand this one time, since 2.4 has no updater. History, saved voices and settings carry over. 3.0 uses updated model packages that include the audio-marking weights, so the model manager offers an update for each model you installed with 2.x. From 3.0 on, the app updates itself with Vocello > Check for Updates.";

export const QUALITY_NOTE =
  "Take quality in 3.0 is not verified by human listening. Automated checks catch gross failures (silence, a cut-off take, missing words, the wrong language), and a take can still carry subtle defects; generate again for a different take. A seed from an earlier version does not reproduce the same take.";
