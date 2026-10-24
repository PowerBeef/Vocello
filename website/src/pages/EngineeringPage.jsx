import React from "react";
import { EngineeringDetail } from "../sections/Engineering.jsx";
import { Limitations } from "../sections/Limitations.jsx";
import { FinalCTA } from "../sections/FinalCTA.jsx";

export const EngineeringPage = () => (
  <>
    <EngineeringDetail />
    <Limitations variant="full" />
    <FinalCTA />
  </>
);
