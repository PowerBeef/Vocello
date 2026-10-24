import React, { useRef, useState } from "react";
import { Icon } from "../components/Icon.jsx";
import { Waveform } from "../components/Waveform.jsx";
import { SAMPLES, DELIVERIES, DELIVERY_GROUPS } from "../data/samples.js";

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
          <h2 className="section-title">Hear it before you install.</h2>
          <p className="section-sub">
            Four takes made locally, from a built-in speaker or a voice described in words,
            including a Japanese line and a 31 second narration. They were made with versions
            before 3.0, so one uses Excited, a delivery 3.0 folds into Happy.
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
                    aria-label={`Play ${s.mode} sample: ${s.name}`}
                    aria-pressed={isPlaying}
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

        <div className="listen-deliveries">
          <p className="listen-deliveries-sub">
            Built-in Voice and Voice Design shape each take with a delivery preset, or one you
            describe in your own words. The hints shape energy and pace; the named emotion may
            not come through on every take.
          </p>
          {DELIVERY_GROUPS.map((group) => (
            <React.Fragment key={group.id}>
              <div className="vc-label" id={`delivery-${group.id}-label`}>{group.label}</div>
              <div className="try-chips" role="list" aria-labelledby={`delivery-${group.id}-label`}>
                {DELIVERIES.filter((d) => d.group === group.id).map((d) => (
                  <span key={d.label} role="listitem" className="chip" style={{ "--chip-color": d.color }}>
                    <span className="swatch" aria-hidden="true" />
                    {d.label}
                  </span>
                ))}
              </div>
            </React.Fragment>
          ))}
        </div>
      </div>
    </section>
  );
};
