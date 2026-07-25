#!/usr/bin/env node
/* Inject the server-rendered page body into dist/index.html.

   The site is authored as a React SPA, but a client-only bundle serves an
   empty <div id="root"> to every non-JavaScript reader: most crawlers,
   preview scrapers, and AI agents. Rendering the page at build time keeps
   the React authoring model while shipping real HTML; src/main.jsx hydrates
   the pre-rendered body at runtime. Fails closed if the root marker or the
   SSR bundle is missing. */

import { readFileSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const ssrBundle = path.join(root, "dist-ssr/entry-ssr.js");
const indexPath = path.join(root, "dist/index.html");

const { render } = await import(ssrBundle);
const body = render();
if (!body || !body.includes("Vocello")) {
  throw new Error("prerender: server render produced no recognizable page body");
}

const html = readFileSync(indexPath, "utf8");
const marker = '<div id="root"></div>';
if (!html.includes(marker)) {
  throw new Error("prerender: #root marker not found in dist/index.html");
}
writeFileSync(indexPath, html.replace(marker, `<div id="root">${body}</div>`));
rmSync(path.join(root, "dist-ssr"), { recursive: true, force: true });
console.log("prerender: server-rendered body injected into dist/index.html");
