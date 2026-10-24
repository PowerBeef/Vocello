import React from "react";

export const Icon = ({ name, size = 18, stroke = 1.6, className = "" }) => {
  /** @type {React.SVGProps<SVGSVGElement>} */
  const props = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: stroke,
    strokeLinecap: "round",
    strokeLinejoin: "round",
    className,
  };
  switch (name) {
    case "wave-person":
      return (
        <svg {...props}>
          <circle cx="9" cy="8" r="3.2" />
          <path d="M3.5 19.5c.7-3 3-4.6 5.5-4.6s4.8 1.6 5.5 4.6" />
          <path d="M16.5 7c1.6 1.4 1.6 4.6 0 6" />
          <path d="M19 5c2.6 2.4 2.6 7.6 0 10" />
        </svg>
      );
    case "bubble":
      return (
        <svg {...props}>
          <path d="M4 12.5c0-3 2.4-5.4 5.4-5.4h2.4c3 0 5.4 2.4 5.4 5.4 0 3-2.4 5.4-5.4 5.4H7l-3 2.6V12.5z" />
          <path d="M9 12h6" />
        </svg>
      );
    case "wave-plus":
      return (
        <svg {...props}>
          <path d="M3 12h2M7 9v6M11 6v12M15 9v6M19 11v2" />
          <circle cx="20.5" cy="6" r="2.5" />
          <path d="M20.5 4.5v3M19 6h3" />
        </svg>
      );
    case "play":
      return (
        <svg {...props}>
          <path d="M8 5.5v13l11-6.5-11-6.5z" fill="currentColor" stroke="none" />
        </svg>
      );
    case "pause":
      return (
        <svg {...props}>
          <rect x="7" y="5.5" width="3.5" height="13" rx="1" fill="currentColor" stroke="none" />
          <rect x="13.5" y="5.5" width="3.5" height="13" rx="1" fill="currentColor" stroke="none" />
        </svg>
      );
    case "lock":
      return (
        <svg {...props}>
          <rect x="5" y="11" width="14" height="9" rx="2" />
          <path d="M8 11V7.5a4 4 0 1 1 8 0V11" />
        </svg>
      );
    case "cpu":
      return (
        <svg {...props}>
          <rect x="6" y="6" width="12" height="12" rx="2" />
          <rect x="9" y="9" width="6" height="6" rx="1" />
          <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
        </svg>
      );
    case "infinity":
      return (
        <svg {...props}>
          <path d="M5 12c0-2.2 1.8-4 4-4 1.8 0 3.2 1.2 5 4 1.8 2.8 3.2 4 5 4 2.2 0 4-1.8 4-4s-1.8-4-4-4c-1.8 0-3.2 1.2-5 4-1.8 2.8-3.2 4-5 4-2.2 0-4-1.8-4-4z" />
        </svg>
      );
    case "download":
      return (
        <svg {...props}>
          <path d="M12 3v12M7 10l5 5 5-5M5 19h14" />
        </svg>
      );
    case "github":
      return (
        <svg {...props}>
          <path d="M9 19c-4 1.5-4-2.5-6-3m12 5v-3.5a3 3 0 0 0-.9-2.3c3-.4 6.2-1.5 6.2-7a5.4 5.4 0 0 0-1.5-3.8 5 5 0 0 0-.1-3.8s-1.2-.4-3.7 1.4a12.7 12.7 0 0 0-6.5 0C6 .9 4.8 1.3 4.8 1.3a5 5 0 0 0-.1 3.8A5.4 5.4 0 0 0 3.2 9c0 5.5 3.2 6.6 6.2 7a3 3 0 0 0-.9 2.3V22" />
        </svg>
      );
    case "apple":
      return (
        <svg {...props} fill="currentColor" stroke="none">
          <path d="M17.05 12.04c-.03-3 2.47-4.46 2.58-4.53-1.41-2.06-3.6-2.34-4.39-2.37-1.87-.19-3.65 1.1-4.6 1.1-.95 0-2.41-1.07-3.97-1.04-2.04.03-3.94 1.19-4.99 3.02-2.13 3.69-.54 9.14 1.53 12.13 1.02 1.46 2.22 3.1 3.79 3.04 1.53-.06 2.1-.98 3.95-.98 1.84 0 2.36.98 3.97.95 1.64-.03 2.68-1.49 3.69-2.96 1.16-1.7 1.64-3.34 1.67-3.43-.04-.02-3.2-1.23-3.23-4.88zM14.13 3.59c.84-1.02 1.4-2.44 1.25-3.85-1.21.05-2.67.8-3.54 1.81-.78.9-1.46 2.34-1.28 3.72 1.34.1 2.72-.68 3.57-1.68z" />
        </svg>
      );
    case "shield":
      return (
        <svg {...props}>
          <path d="M12 3l8 3v5.5c0 4.7-3.4 8.6-8 9.5-4.6-.9-8-4.8-8-9.5V6l8-3z" />
        </svg>
      );
    case "check":
      return (
        <svg {...props}>
          <path d="M5 12.5l4.5 4.5 9.5-10" />
        </svg>
      );
    case "arrow-right":
      return (
        <svg {...props}>
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      );
    case "menu":
      return (
        <svg {...props}>
          <path d="M4 8h16M4 16h16" />
        </svg>
      );
    case "close":
      return (
        <svg {...props}>
          <path d="M6 6l12 12M18 6L6 18" />
        </svg>
      );
    case "sparkles":
      return (
        <svg {...props}>
          <path d="M12 4l1.7 4.6 4.6 1.7-4.6 1.7L12 16.6l-1.7-4.6L5.7 10.3l4.6-1.7L12 4z" />
          <path d="M19 16l.8 2 2 .8-2 .8L19 22l-.8-2-2-.8 2-.8.8-2z" />
        </svg>
      );
    case "history":
      return (
        <svg {...props}>
          <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
          <path d="M3 3v5h5" />
          <path d="M12 8v5l3 2" />
        </svg>
      );
    case "speed":
      return (
        <svg {...props}>
          <path d="M4 18a8 8 0 1 1 16 0" />
          <path d="M12 14l4-5" />
          <circle cx="12" cy="14" r="1.2" fill="currentColor" />
        </svg>
      );
    case "diamond":
      return (
        <svg {...props}>
          <path d="M6 3h12l4 6-10 12L2 9l4-6z" />
          <path d="M2 9h20M9 3l3 6 3-6" />
        </svg>
      );
    default:
      return null;
  }
};

export const makeWaveBars = (bars, seed = 1) =>
  Array.from({ length: bars }, (_, i) => {
    const carrier = Math.sin((i + 1) * 1.73 + seed * 0.41);
    const detail = Math.sin((i + 1) * 0.47 + seed * 1.9);
    const envelope = Math.sin(((i + 1) / (bars + 1)) * Math.PI);
    return Math.max(0.18, Math.min(1, (0.48 + carrier * 0.28 + detail * 0.16) * (0.72 + envelope * 0.28)));
  });
