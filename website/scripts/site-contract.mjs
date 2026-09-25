#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const websiteRoot = path.resolve(scriptDir, "..");
const repositoryRoot = path.resolve(websiteRoot, "..");

const walk = (root, suffixes) => {
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root, { withFileTypes: true }).flatMap((entry) => {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) return walk(target, suffixes);
    return suffixes.some((suffix) => entry.name.endsWith(suffix)) ? [target] : [];
  });
};

export const validateText = ({ indexHTML, sources, publicFacts, publicRoot }) => {
  const errors = [];
  const combined = sources.map(({ text }) => text).join("\n");
  const visibleVersion = publicFacts?.stableMacRelease?.version;
  const publicDisplayVersion = visibleVersion?.replace(/\.0$/, "");
  if (!visibleVersion || !indexHTML.includes(`Vocello ${publicDisplayVersion}`)) {
    errors.push("index metadata does not match the public stable Mac release");
  }
  for (const [label, pattern] of [
    ["English document language", /<html\s+lang=["']en["']/],
    ["description metadata", /<meta\s+[^>]*name=["']description["']/s],
    ["viewport metadata", /<meta\s+[^>]*name=["']viewport["']/s],
    ["Open Graph title", /<meta\s+[^>]*property=["']og:title["']/s],
    ["Open Graph URL", /<meta\s+[^>]*property=["']og:url["']/s],
    ["Open Graph image alternative", /<meta\s+[^>]*property=["']og:image:alt["']/s],
    ["Twitter card", /<meta\s+[^>]*name=["']twitter:card["']/s],
    ["canonical URL", /<link\s+[^>]*rel=["']canonical["']/s],
    ["robots directive", /<meta\s+[^>]*name=["']robots["']/s],
    ["document title", /<title>/],
  ]) {
    if (!pattern.test(indexHTML)) errors.push(`index.html is missing ${label}`);
  }
  for (const { name, text } of sources) {
    if (text.includes("—")) errors.push(`${name} contains a prohibited em dash`);
    if (/faster than (?:real[ -]?time|playback)/i.test(text)) {
      errors.push(`${name} contains an unqualified performance claim`);
    }
    for (const match of text.matchAll(/<img\b([^>]*?)\/?\s*>/gs)) {
      if (!/\balt\s*=/.test(match[1])) errors.push(`${name} contains an image without alt text`);
    }
    for (const match of text.matchAll(/<a\b([^>]*target=["']_blank["'][^>]*)>/gs)) {
      if (!/rel=["'][^"']*noreferrer/.test(match[1])) {
        errors.push(`${name} contains a target=_blank link without rel=noreferrer`);
      }
    }
  }

  const ids = new Set([...combined.matchAll(/\bid=["'`]([^"'`]+)["'`]/g)].map((match) => match[1]));
  for (const match of combined.matchAll(/href=["'`]#([^"'`]+)["'`]/g)) {
    if (!ids.has(match[1])) errors.push(`internal link #${match[1]} has no static target`);
  }
  for (const match of combined.matchAll(/(?:src|shot):?\s*=\s*["'`]\/?(assets\/[^"'`]+)["'`]/g)) {
    if (!fs.existsSync(path.join(publicRoot, match[1]))) errors.push(`missing public asset: ${match[1]}`);
  }
  return [...new Set(errors)].sort();
};

// WEB-03 (PA-20): every text token keeps WCAG AA contrast (4.5:1) on every
// surface token, in the dark default and the light override.
const TEXT_TOKENS = ["--fg-primary", "--fg-secondary", "--fg-tertiary"];
const SURFACE_TOKENS = ["--bg-canvas", "--bg-stage", "--bg-rail", "--bg-card", "--bg-inline", "--bg-field"];

const tokenBlock = (css, selector) => {
  const start = css.indexOf(`${selector} {`);
  if (start < 0) return {};
  const body = css.slice(start, css.indexOf("\n}", start));
  return Object.fromEntries([...body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map((match) => [match[1], match[2].trim()]));
};

const resolveToken = (tokens, value, depth = 0) => {
  const reference = /^var\((--[\w-]+)\)$/.exec(value ?? "");
  return reference && depth < 8 ? resolveToken(tokens, tokens[reference[1]], depth + 1) : value;
};

const parseColor = (value) => {
  const hex = /^#([0-9a-f]{6})$/i.exec(value ?? "");
  if (hex) return { rgb: [0, 2, 4].map((index) => parseInt(hex[1].slice(index, index + 2), 16)), alpha: 1 };
  const rgba = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(value ?? "");
  if (rgba) return { rgb: rgba.slice(1, 4).map(Number), alpha: rgba[4] === undefined ? 1 : Number(rgba[4]) };
  return null;
};

const relativeLuminance = (rgb) => {
  const [red, green, blue] = rgb.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
};

// WCAG 2 contrast of (possibly translucent) text composited over an opaque surface.
export const contrastRatio = (text, surface) => {
  const composite = text.rgb.map((channel, index) => text.alpha * channel + (1 - text.alpha) * surface[index]);
  const [lighter, darker] = [relativeLuminance(composite), relativeLuminance(surface)].sort((a, b) => b - a);
  return (lighter + 0.05) / (darker + 0.05);
};

export const validateTokenContrast = (css) => {
  const errors = [];
  const dark = tokenBlock(css, ":root");
  const light = { ...dark, ...tokenBlock(css, '[data-theme="light"]') };
  for (const [theme, tokens] of [["dark", dark], ["light", light]]) {
    for (const textToken of TEXT_TOKENS) {
      const text = parseColor(resolveToken(tokens, tokens[textToken]));
      if (!text) {
        errors.push(`${theme} ${textToken} is not a parseable color`);
        continue;
      }
      for (const surfaceToken of SURFACE_TOKENS) {
        const surface = parseColor(resolveToken(tokens, tokens[surfaceToken]));
        if (!surface || surface.alpha !== 1) {
          errors.push(`${theme} ${surfaceToken} is not an opaque color`);
          continue;
        }
        const ratio = contrastRatio(text, surface.rgb);
        if (ratio < 4.5) {
          errors.push(`${theme} ${textToken} on ${surfaceToken} is ${ratio.toFixed(2)}:1, below WCAG AA 4.5:1`);
        }
      }
    }
  }
  return [...new Set(errors)].sort();
};

export const validateRepository = () => {
  const sources = walk(path.join(websiteRoot, "src"), [".jsx", ".js"]).map((file) => ({
    name: path.relative(repositoryRoot, file),
    text: fs.readFileSync(file, "utf8"),
  }));
  const textErrors = validateText({
    indexHTML: fs.readFileSync(path.join(websiteRoot, "index.html"), "utf8"),
    sources,
    publicFacts: JSON.parse(fs.readFileSync(path.join(repositoryRoot, "config/public-product-facts.json"), "utf8")),
    publicRoot: path.join(websiteRoot, "public"),
  });
  const contrastErrors = validateTokenContrast(fs.readFileSync(path.join(websiteRoot, "src/tokens.css"), "utf8"));
  return [...textErrors, ...contrastErrors].sort();
};

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const errors = validateRepository();
  if (errors.length) {
    errors.forEach((error) => console.error(`error: ${error}`));
    process.exitCode = 1;
  } else {
    console.log("Website contract: PASS");
  }
}
