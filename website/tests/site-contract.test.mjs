import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import { contrastRatio, validateReleaseMirror, validateRepository, validateText, validateTokenContrast } from "../scripts/site-contract.mjs";

const fixture = (source) => validateText({
  indexHTML: '<html lang="en"><head><meta name="description"><meta name="viewport"><meta name="robots"><meta property="og:title"><meta property="og:url"><meta property="og:image:alt"><meta name="twitter:card"><link rel="canonical"><title>Vocello 2.2</title></head></html>',
  sources: [{ name: "fixture.jsx", text: source }],
  publicFacts: { stableMacRelease: { version: "2.2.0" } },
  publicRoot: "/definitely/missing",
});

test("the checked-in website satisfies the contract", () => {
  assert.deepEqual(validateRepository(), []);
});

test("images require alt text", () => {
  assert.ok(fixture('<div id="home"><img src={image} /></div>').some((value) => value.includes("without alt")));
});

test("blank-target links require noreferrer", () => {
  assert.ok(fixture('<div id="home"><a target="_blank" href="https://example.invalid">Open</a></div>')
    .some((value) => value.includes("noreferrer")));
});

test("internal links require a target", () => {
  assert.ok(fixture('<a href="#missing">Open</a>').some((value) => value.includes("no static target")));
});

test("unqualified performance claims and em dashes fail", () => {
  const errors = fixture('<div id="home">Faster than realtime — everywhere</div>');
  assert.ok(errors.some((value) => value.includes("performance claim")));
  assert.ok(errors.some((value) => value.includes("em dash")));
});

test("text tokens meet WCAG AA on every surface in both themes", () => {
  const css = fs.readFileSync(new URL("../src/tokens.css", import.meta.url), "utf8");
  assert.deepEqual(validateTokenContrast(css), []);
});

test("contrast is computed over the composited surface", () => {
  assert.equal(contrastRatio({ rgb: [255, 255, 255], alpha: 1 }, [0, 0, 0]).toFixed(1), "21.0");
  // The pre-PA-20 tertiary token: about 3.9:1 on the charcoal canvas.
  const ratio = contrastRatio({ rgb: [245, 246, 248], alpha: 0.42 }, [0x16, 0x18, 0x1e]);
  assert.ok(ratio > 3.7 && ratio < 4.0, `${ratio}`);
});

test("low-contrast text tokens fail", () => {
  const css = `:root {
  --charcoal-900: #16181E;
  --bg-canvas: var(--charcoal-900);
  --bg-stage: #1C1E26;
  --bg-rail: #171920;
  --bg-card: #0D0E12;
  --bg-inline: #111318;
  --bg-field: #2A2C36;
  --fg-primary: #F5F6F8;
  --fg-secondary: rgba(245, 246, 248, 0.65);
  --fg-tertiary: rgba(245, 246, 248, 0.42);
}
`;
  const errors = validateTokenContrast(css);
  assert.ok(errors.some((value) => value.startsWith("dark --fg-tertiary on --bg-canvas")), errors.join("; "));
  assert.ok(!errors.some((value) => value.includes("--fg-secondary")), errors.join("; "));
});

test("the release mirror must match the public facts", () => {
  const facts = { stableMacRelease: { version: "2.4.0", tag: "v2.4.0" }, fallbackMacRelease: { version: "1.2.3", tag: "v1.2.3" } };
  const mirror = (stable) => ({
    name: "website/src/data/release.js",
    text: `export const STABLE_MAC_RELEASE = { version: "${stable}", tag: "v${stable}" };\nexport const FALLBACK_MAC_RELEASE = { version: "1.2.3", tag: "v1.2.3" };\n`,
  });
  assert.deepEqual(validateReleaseMirror({ sources: [mirror("2.4.0")], publicFacts: facts }), []);
  assert.ok(validateReleaseMirror({ sources: [mirror("2.3.0")], publicFacts: facts })
    .some((value) => value.includes("STABLE_MAC_RELEASE does not match")));
  assert.ok(validateReleaseMirror({ sources: [], publicFacts: facts }).some((value) => value.includes("is missing")));
});

test("download links name the stable tag, not the latest release", () => {
  assert.ok(fixture('<a href="https://github.com/PowerBeef/Vocello/releases/latest">Download</a>')
    .some((value) => value.includes("/releases/latest")));
});

test("a screenshot without its AVIF sibling fails", () => {
  const errors = fixture('<div id="home"><img src="assets/screens/none.png" alt="" /></div>');
  assert.ok(errors.some((value) => value.includes("missing AVIF sibling: assets/screens/none.avif")));
});

test("data-module asset references are checked", () => {
  assert.ok(fixture('export const X = { shot: "assets/screens/none.png" };')
    .some((value) => value.includes("missing public asset: assets/screens/none.png")));
});
