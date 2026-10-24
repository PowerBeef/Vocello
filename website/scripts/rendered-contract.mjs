#!/usr/bin/env node

import path from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const stripTags = (value) => value
  .replace(/<[^>]*>/gs, " ")
  .replace(/&nbsp;|&#x27;|&quot;|&amp;/g, " ")
  .replace(/\s+/g, " ")
  .trim();

export const validateRenderedMarkup = (markup) => {
  const errors = [];
  const count = (pattern) => [...markup.matchAll(pattern)].length;
  if (count(/<main\b/g) !== 1) errors.push("rendered page must contain exactly one main landmark");
  if (count(/<h1\b/g) !== 1) errors.push("rendered page must contain exactly one h1");
  if (count(/<nav\b/g) < 1) errors.push("rendered page is missing a navigation landmark");
  if (count(/<footer\b/g) !== 1) errors.push("rendered page must contain exactly one footer landmark");
  if (!/<a\b[^>]*href=["']#main-content["'][^>]*>\s*Skip to main content\s*<\/a>/s.test(markup)) {
    errors.push("rendered page is missing its main-content skip link");
  }

  const ids = new Set([...markup.matchAll(/\bid=["']([^"']+)["']/g)].map((match) => match[1]));
  for (const match of markup.matchAll(/\baria-labelledby=["']([^"']+)["']/g)) {
    for (const id of match[1].split(/\s+/)) {
      if (!ids.has(id)) errors.push(`rendered aria-labelledby references missing id ${id}`);
    }
  }

  for (const match of markup.matchAll(/<img\b([^>]*)>/gs)) {
    if (!/\balt=["'][^"']*["']/.test(match[1])) errors.push("rendered image is missing alt text");
  }
  for (const match of markup.matchAll(/<button\b([^>]*)>(.*?)<\/button>/gs)) {
    const attributes = match[1];
    if (!/\baria-label=["'][^"']+["']/.test(attributes) && !stripTags(match[2])) {
      errors.push("rendered button has no accessible name");
    }
  }
  for (const match of markup.matchAll(/<a\b([^>]*)>(.*?)<\/a>/gs)) {
    const attributes = match[1];
    if (!/\bhref=["'][^"']+["']/.test(attributes)) errors.push("rendered link is missing href");
    if (!/\baria-label=["'][^"']+["']/.test(attributes) && !stripTags(match[2])) {
      errors.push("rendered link has no accessible name");
    }
  }
  for (const match of markup.matchAll(/<(input|textarea|select)\b([^>]*)>/gs)) {
    const attributes = match[2];
    const id = attributes.match(/\bid=["']([^"']+)["']/)?.[1];
    const labelled = /\baria-label=["'][^"']+["']/.test(attributes)
      || /\baria-labelledby=["'][^"']+["']/.test(attributes)
      || (id && new RegExp(`<label\\b[^>]*for=["']${id}["']`).test(markup));
    if (!labelled) errors.push(`rendered ${match[1]} has no accessible label`);
  }
  return [...new Set(errors)].sort();
};

// Renders every page App knows (src/App.jsx PAGES), keyed by page name.
export const renderRepositoryPages = async () => {
  const server = await createServer({
    root,
    appType: "custom",
    logLevel: "silent",
    server: { middlewareMode: true },
  });
  try {
    const { default: App, PAGES } = await server.ssrLoadModule("/src/App.jsx");
    return Object.fromEntries(
      Object.keys(PAGES).map((page) => [page, renderToStaticMarkup(React.createElement(App, { page }))]),
    );
  } finally {
    await server.close();
  }
};

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const pages = await renderRepositoryPages();
  const errors = Object.entries(pages).flatMap(([page, markup]) =>
    validateRenderedMarkup(markup).map((error) => `${page}: ${error}`));
  if (errors.length) {
    for (const error of errors) console.error(`error: ${error}`);
    process.exitCode = 1;
  } else {
    console.log("Rendered accessibility contract: PASS");
  }
}
