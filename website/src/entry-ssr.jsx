import React from "react";
import { renderToString } from "react-dom/server";
import App from "./App.jsx";

/* Build-time entry: scripts/prerender.mjs renders the full page into
   dist/index.html so crawlers and preview scrapers receive real HTML.
   CSS is owned by the client bundle; this entry renders markup only. */
export const render = () =>
  renderToString(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
