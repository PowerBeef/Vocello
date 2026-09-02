import test from "node:test";
import assert from "node:assert/strict";
import {
  validateFocusSequence,
  validateHydrationProbe,
  validateInternalTargets,
} from "../scripts/browser-smoke-contract.mjs";

test("hydration probe accepts a client-owned progress update", () => {
  assert.doesNotThrow(() => validateHydrationProbe({
    before: "matrix(0, 0, 0, 1, 0, 0)",
    after: "matrix(0.5, 0, 0, 1, 0, 0)",
    scrollTop: 900,
  }));
});

test("hydration probe rejects an unhydrated page", () => {
  assert.throws(
    () => validateHydrationProbe({ before: "scaleX(0)", after: "scaleX(0)", scrollTop: 900 }),
    /client-owned progress update/,
  );
});

test("focus contract accepts a progressing keyboard walk", () => {
  assert.doesNotThrow(() => validateFocusSequence([
    { signature: "a:#main", visible: true },
    { signature: "a:#listen", visible: true },
    { signature: "button:play", visible: true },
  ]));
});

test("focus contract rejects a keyboard trap", () => {
  assert.throws(
    () => validateFocusSequence([
      { signature: "button:menu", visible: true },
      { signature: "button:menu", visible: true },
      { signature: "button:menu", visible: true },
    ]),
    /trapped/,
  );
});

test("internal target contract rejects missing routes and fragments", () => {
  assert.throws(
    () => validateInternalTargets(["#missing", "/missing/"], ["main-content"], ["/", "/support/"]),
    /#missing, \/missing\//,
  );
});
