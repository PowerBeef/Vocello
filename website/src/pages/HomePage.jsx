import React from "react";
import { Hero } from "../sections/Hero.jsx";
import { Modes } from "../sections/Modes.jsx";
import { Listen } from "../sections/Listen.jsx";
import { Privacy } from "../sections/Privacy.jsx";
import { Capabilities } from "../sections/Capabilities.jsx";
import { IphoneBeta } from "../sections/IphoneBeta.jsx";
import { WhatsNew } from "../sections/WhatsNew.jsx";
import { Developers } from "../sections/Developers.jsx";
import { Limitations } from "../sections/Limitations.jsx";
import { FinalCTA } from "../sections/FinalCTA.jsx";

// The home page is for people who want to make voices: what Vocello does, how it
// sounds, why it is private and how to get it. /cli/ and /engineering/ carry the
// developer detail, behind the For developers tiles.
export const HomePage = () => (
  <>
    <Hero />
    <Modes />
    <Listen />
    <Privacy />
    <Capabilities />
    <IphoneBeta />
    <WhatsNew />
    <Developers />
    <Limitations variant="summary" />
    <FinalCTA />
  </>
);
