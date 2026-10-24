import React from "react";
import { Hero } from "../sections/Hero.jsx";
import { WhatsNew } from "../sections/WhatsNew.jsx";
import { WorkflowBand } from "../sections/WorkflowBand.jsx";
import { Listen } from "../sections/Listen.jsx";
import { Capabilities } from "../sections/Capabilities.jsx";
import { WhyCloud } from "../sections/WhyCloud.jsx";
import { HowItRuns } from "../sections/HowItRuns.jsx";
import { CommandLineTeaser } from "../sections/CommandLine.jsx";
import { IphoneBeta } from "../sections/IphoneBeta.jsx";
import { EngineeringTeaser } from "../sections/Engineering.jsx";
import { Limitations } from "../sections/Limitations.jsx";
import { FinalCTA } from "../sections/FinalCTA.jsx";
import { WORKFLOWS } from "../data/workflows.js";

// The home page summarizes; /cli/ and /engineering/ carry the full detail.
export const HomePage = () => (
  <>
    <Hero />
    <WhatsNew />
    <div id="workflows" className="workflows-anchor">
      {WORKFLOWS.map((w, i) => (
        <WorkflowBand key={w.id} workflow={w} index={i} />
      ))}
    </div>
    <Listen />
    <Capabilities />
    <WhyCloud />
    <HowItRuns />
    <CommandLineTeaser />
    <IphoneBeta />
    <EngineeringTeaser />
    <Limitations variant="summary" />
    <FinalCTA />
  </>
);
