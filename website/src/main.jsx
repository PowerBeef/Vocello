import React from "react";
import { createRoot, hydrateRoot } from "react-dom/client";
import App from "./App.jsx";
import "./site.css";

// Each HTML entry names its page on the root element (data-page).
const container = document.getElementById("root");
const app = (
  <React.StrictMode>
    <App page={container.dataset.page ?? "home"} />
  </React.StrictMode>
);

// Production HTML ships pre-rendered (scripts/prerender.mjs); hydrate it.
// The dev server still serves an empty root and mounts from scratch.
if (container.hasChildNodes()) {
  hydrateRoot(container, app);
} else {
  createRoot(container).render(app);
}
