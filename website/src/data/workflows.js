// The three ways to make a voice, shown by the home page's mode switcher (src/sections/Modes.jsx).
// Each mode keeps its app color, its name in full and as the app's mode control shows it, a
// screenshot of its Studio screen and three short points.
export const WORKFLOWS = [
  {
    id: "custom",
    color: "var(--mode-custom)",
    tab: "Built-in Voice",
    short: "Built-in",
    title: "Pick a voice and a delivery.",
    body: "Nine built-in speakers in ten languages. Choose how a line should sound with a delivery preset, or describe the delivery in your own words.",
    points: [
      "Nine speakers, with English, Chinese, Japanese and Korean natives",
      "Neutral, Calm, Whisper or Sad, and hints such as Happy or Surprised",
      "Each take reads the whole script before it speaks",
    ],
    shot: "/assets/screens/custom-voice.png",
    shotHeight: 1356,
  },
  {
    id: "design",
    color: "var(--mode-design)",
    tab: "Voice Design",
    short: "Design",
    title: "Describe a voice in plain words.",
    body: "Write a voice brief, such as \"a warm, deep narrator with a subtle British accent,\" and Vocello shapes a new voice around it. Keep the ones you like.",
    points: [
      "One sentence on timbre, accent or style",
      "Save designed voices and use them in any script",
      "Your brief never leaves your Mac",
    ],
    shot: "/assets/screens/voice-design.png",
    shotHeight: 1380,
  },
  {
    id: "clone",
    color: "var(--mode-clone)",
    tab: "Voice Cloning",
    short: "Clone",
    title: "Clone a voice from a clip you own.",
    body: "Record a short clip, import an audio file, or start from a saved voice. Voice Cloning follows the reference voice, so the clip sets its character.",
    points: [
      "Record in the app, or import WAV, MP3, AIFF or M4A",
      "Add the clip's words, or transcribe them locally, for the strongest clone",
      "Only for voices you own or have permission to use",
    ],
    shot: "/assets/screens/voice-cloning.png",
    shotHeight: 1380,
  },
];
