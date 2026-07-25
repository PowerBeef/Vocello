import React, { useRef, useState } from "react";
import { Icon } from "../components/Icon.jsx";
import { Waveform } from "../components/Waveform.jsx";
import { SAMPLES } from "../data/samples.js";

export const Listen = () => {
  const [playing, setPlaying] = useState(null);
  const audioRef = useRef(null);

  const togglePlay = (sample) => {
    const audio = audioRef.current;
    if (!audio) return;
    if (playing === sample.id) {
      audio.pause();
      setPlaying(null);
      return;
    }
    audio.src = sample.src;
    audio.currentTime = 0;
    audio.play().catch(() => setPlaying(null));
    setPlaying(sample.id);
  };

  return (
    <section className="section listen-section" id="listen">
      <audio
        ref={audioRef}
        preload="none"
        onEnded={() => setPlaying(null)}
        onError={() => setPlaying(null)}
      />
      <div className="container">
        <div className="section-head listen-head">
          <p className="section-note">Listen first</p>
          <h2 className="section-title">Three voices.<br />Three ways to ask for them.</h2>
          <p className="section-sub">
            Each row carries the brief or speaker, the script, the delivery setting that
            produced it, and a waveform from the local render. Install Vocello to generate your own.
          </p>
        </div>

        <ul className="listen-rows" role="list">
          {SAMPLES.map((s) => {
            const isPlaying = playing === s.id;
            return (
              <li
                key={s.id}
                className={`listen-row ${isPlaying ? "is-playing" : ""}`}
                style={{ "--row-mode": s.color }}
              >
                <div className="listen-row-meta">
                  <span className="listen-mode">
                    <span className="swatch" aria-hidden="true" />
                    {s.mode}
                  </span>
                  <span className="listen-voice" title={s.voice}>{s.voice}</span>
                </div>
                <blockquote className="listen-quote">
                  &ldquo;{s.quote}&rdquo;
                </blockquote>
                <div className="listen-row-controls">
                  <button
                    className="play-btn"
                    aria-label={`${isPlaying ? "Pause" : "Play"} ${s.mode} sample`}
                    onClick={() => togglePlay(s)}
                  >
                    <Icon name={isPlaying ? "pause" : "play"} size={14} />
                  </button>
                  <div className="listen-row-wave" aria-hidden="true">
                    <Waveform playing={isPlaying} color={s.color} wave={s.wave} bars={40} />
                  </div>
                  <span className="listen-row-stats">
                    {s.delivery}<span className="listen-sep" aria-hidden="true">·</span>{s.duration}
                  </span>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
};
