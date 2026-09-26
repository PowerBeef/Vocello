import { FALLBACK_MAC_RELEASE, STABLE_MAC_RELEASE } from "./release.js";

export const CREDITS = [
  { name: "Qwen3-TTS", href: "https://github.com/QwenLM/Qwen3-TTS" },
  { name: "MLX", href: "https://github.com/ml-explore/mlx" },
  { name: "mlx-audio-swift", href: "https://github.com/Blaizzy/mlx-audio-swift" },
  { name: "GRDB.swift", href: "https://github.com/groue/GRDB.swift" },
  { name: "Swift", href: "https://www.swift.org" },
];

export const REPO = "https://github.com/PowerBeef/Vocello";
// WEB-07: download buttons name the stable tag the page describes, never the latest release.
export const RELEASE_STABLE = `${REPO}/releases/tag/${STABLE_MAC_RELEASE.tag}`;
export const RELEASE_FALLBACK = `${REPO}/releases/tag/${FALLBACK_MAC_RELEASE.tag}`;
export const TESTFLIGHT = "https://testflight.apple.com/join/Cvp6yCv7";
