import React from "react";
import { renderToString } from "react-dom/server";
import App, { PAGES } from "./App.jsx";

/* Build-time entry: scripts/prerender.mjs renders each page into its HTML
   file so crawlers and preview scrapers receive real HTML. CSS is owned by
   the client bundle; this entry renders markup only. */
export const PAGE_NAMES = Object.keys(PAGES);

/** @param {string} page */
export const render = (page = "home") =>
  renderToString(
    <React.StrictMode>
      <App page={page} />
    </React.StrictMode>,
  );
