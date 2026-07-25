import React, { useMemo } from "react";
import { makeWaveBars } from "./Icon.jsx";

/* Pass `wave` (per-bar amplitudes measured from the audio file, see
   scripts/render-waveforms.mjs) for rows that claim to show a real render.
   The seeded generator remains only as a fallback for decorative uses. */
export const Waveform = ({ bars = 32, playing = false, color = "var(--accent)", seed = 1, wave = null }) => {
  const heights = useMemo(
    () => (wave && wave.length ? wave : makeWaveBars(bars, seed)),
    [wave, bars, seed],
  );
  return (
    <div className="hear-wave">
      {heights.map((h, i) => (
        <div
          key={i}
          className={`bar ${playing ? "animate" : ""}`}
          style={{
            height: `${h * 100}%`,
            background: color,
            animationDelay: `${(i % 8) * 0.08}s`,
          }}
        />
      ))}
    </div>
  );
};
