import React from "react";
import { Screenshot } from "../components/Screenshot.jsx";

const renderHeadline = (segments, accent) =>
  segments.map((seg, i) =>
    seg.trim() === accent.trim() ? (
      <span key={i} className="mode-word">{seg}</span>
    ) : (
      <React.Fragment key={i}>{seg}</React.Fragment>
    )
  );

export const WorkflowBand = ({ workflow, index }) => {
  const reverse = index % 2 === 1;
  return (
    <section
      className={`workflow-band workflow-band--${workflow.id} ${reverse ? "workflow-band--reverse" : ""}`}
      style={{ "--mode-current": workflow.color }}
      aria-labelledby={`workflow-${workflow.id}-title`}
    >
      <div className="container workflow-band-inner">
        <figure className="workflow-band-shot">
          <div className="window">
            <Screenshot src={workflow.shot} width={2080} height={1380} alt={`Vocello ${workflow.title} screen`} />
          </div>
        </figure>
        <div className="workflow-band-copy">
          <p className="workflow-band-index">{String(index + 1).padStart(2, "0")} · {workflow.eyebrow}</p>
          <h2 id={`workflow-${workflow.id}-title`} className="workflow-band-title">
            {renderHeadline(workflow.headline, workflow.accent)}
          </h2>
          <p className="workflow-band-body">{workflow.body}</p>
          <ol className="workflow-band-points">
            {workflow.points.map(([h, sub], i) => (
              <li key={h}>
                <span className="workflow-band-num">{String(i + 1).padStart(2, "0")}</span>
                <div>
                  <p className="workflow-band-point-title">{h}</p>
                  <p className="workflow-band-point-sub">{sub}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  );
};
