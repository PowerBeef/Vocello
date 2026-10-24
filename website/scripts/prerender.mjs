#!/usr/bin/env node
/* Inject each page's server-rendered body into its HTML file in dist/.

   The site is authored as React, but a client-only bundle serves an empty
   <div id="root"> to every non-JavaScript reader: most crawlers, preview
   scrapers, and AI agents. Rendering the pages at build time keeps the React
   authoring model while shipping real HTML; src/main.jsx hydrates the
   pre-rendered body at runtime. Fails closed if a page's root marker, its
   HTML file or the SSR bundle is missing. */

import { existsSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { SITE_PAGES } from "./site-pages.mjs";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const ssrBundle = path.join(root, "dist-ssr/entry-ssr.js");

const { render, PAGE_NAMES } = await import(ssrBundle);
const listed = SITE_PAGES.map(({ page }) => page).sort().join(",");
if ([...PAGE_NAMES].sort().join(",") !== listed) {
  throw new Error(`prerender: App pages (${PAGE_NAMES}) and scripts/site-pages.mjs (${listed}) differ`);
}

for (const { page, html: htmlFile } of SITE_PAGES) {
  const target = path.join(root, "dist", htmlFile);
  if (!existsSync(target)) throw new Error(`prerender: ${htmlFile} was not built`);
  const body = render(page);
  if (!body || !body.includes("Vocello")) {
    throw new Error(`prerender: ${page} rendered no recognizable page body`);
  }
  const html = readFileSync(target, "utf8");
  const marker = `<div id="root" data-page="${page}"></div>`;
  if (!html.includes(marker)) throw new Error(`prerender: ${marker} not found in ${htmlFile}`);
  writeFileSync(target, html.replace(marker, `<div id="root" data-page="${page}">${body}</div>`));
  console.log(`prerender: ${page} rendered into dist/${htmlFile}`);
}
rmSync(path.join(root, "dist-ssr"), { recursive: true, force: true });
