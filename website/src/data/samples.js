/* `wave` arrays are per-bar RMS envelopes computed from the actual sample
   files by scripts/render-waveforms.mjs, so the Listen rows literally show
   the local render. Regenerate them whenever a sample WAV changes. */
export const SAMPLES = [
  {
    id: "narrator",
    mode: "Voice Design",
    color: "var(--lavender-300)",
    voice: "A warm, deep narrator with a subtle British accent.",
    quote: "The valley opens after the last bend, slow, and quieter than the road would suggest.",
    duration: "0:08",
    delivery: "Calm / Subtle",
    src: "assets/voice-samples/voice-design-calm-subtle.wav",
    wave: [0.36, 0.62, 1, 0.73, 0.74, 0.46, 0.54, 0.64, 0.3, 0.59, 0.62, 0.16, 0.75, 0.67, 0.35, 0.06, 0.06, 0.06, 0.07, 0.26, 0.88, 0.62, 0.32, 0.14, 0.34, 0.43, 0.64, 0.78, 0.5, 0.56, 0.51, 0.75, 0.44, 0.29, 0.18, 0.52, 0.43, 0.12, 0.06, 0.06],
  },
  {
    id: "host",
    mode: "Custom Voice",
    color: "var(--gold-300)",
    voice: "Aiden, English native",
    quote: "Hey, welcome back to Field Notes. Today we're walking through the demo build, end to end.",
    duration: "0:06",
    delivery: "Excited / Normal",
    src: "assets/voice-samples/custom-voice-aiden-excited.wav",
    wave: [0.64, 0.57, 0.11, 0.08, 1, 0.61, 0.69, 0.24, 0.12, 0.78, 0.42, 0.33, 0.08, 0.06, 0.06, 0.18, 0.59, 0.57, 0.46, 0.3, 0.24, 0.45, 0.18, 0.4, 0.48, 0.65, 0.71, 0.79, 0.23, 0.06, 0.06, 0.21, 0.52, 0.34, 0.06, 0.42, 0.19, 0.42, 0.23, 0.07],
  },
  {
    id: "documentary",
    mode: "Voice Cloning",
    color: "var(--terracotta-300)",
    voice: "Cloned from internal-narration-v3.wav",
    quote: "Every measurement was logged, every observation written down. Only then could the model be trusted.",
    duration: "0:09",
    delivery: "Mirrors source clip",
    src: "assets/voice-samples/voice-cloning-mirrors-source.wav",
    wave: [0.06, 0.06, 0.06, 0.84, 0.84, 0.71, 0.57, 0.44, 0.27, 0.58, 0.46, 0.06, 0.06, 0.26, 0.81, 0.84, 0.42, 0.7, 0.6, 0.44, 0.51, 0.43, 0.38, 0.28, 0.13, 0.06, 0.06, 0.06, 0.63, 1, 0.73, 0.77, 0.35, 0.34, 0.44, 0.33, 0.27, 0.26, 0.08, 0.13],
  },
];

export const DELIVERIES = [
  { label: "Neutral", color: "var(--emotion-neutral)" },
  { label: "Happy", color: "var(--emotion-happy)" },
  { label: "Sad", color: "var(--emotion-sad)" },
  { label: "Angry", color: "var(--emotion-angry)" },
  { label: "Fearful", color: "var(--emotion-fearful)" },
  { label: "Surprised", color: "var(--emotion-surprised)" },
  { label: "Whisper", color: "var(--emotion-whisper)" },
  { label: "Dramatic", color: "var(--emotion-dramatic)" },
  { label: "Calm", color: "var(--emotion-calm)" },
  { label: "Excited", color: "var(--emotion-excited)" },
];

export const DELIVERY_COLORS = {
  Neutral: "#8C8F9B",
  Happy: "#F2C74D",
  Sad: "#8C9EC7",
  Angry: "#C75233",
  Fearful: "#9E80C7",
  Surprised: "#5FB8C2",
  Whisper: "#9E9EA8",
  Dramatic: "#C785A8",
  Calm: "#9EBC9E",
  Excited: "#EB9452",
};
