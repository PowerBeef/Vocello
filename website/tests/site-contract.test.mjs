import assert from "node:assert/strict";
import test from "node:test";
import { validateRepository, validateText } from "../scripts/site-contract.mjs";

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
