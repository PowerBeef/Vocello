import test from "node:test";
import assert from "node:assert/strict";
import {
  validateAnchorLanding,
  validateBarLayout,
  validateFocusSequence,
  validateHydrationProbe,
  validateInternalTargets,
  validateMenuButton,
  validateNoOverflow,
  validateTapTargets,
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

test("overflow contract names elements past the viewport", () => {
  assert.doesNotThrow(() => validateNoOverflow([], "390"));
  assert.throws(
    () => validateNoOverflow([{ name: "div.perf-chart", left: 0, right: 412 }], "390"),
    /1 element\(s\) extend past the viewport: div.perf-chart/,
  );
});

test("bar contract rejects overlapping or escaping items", () => {
  const brand = { name: "brand", left: 20, right: 120, top: 6, bottom: 50 };
  const cta = { name: "Download", left: 230, right: 330, top: 6, bottom: 50 };
  assert.doesNotThrow(() => validateBarLayout([brand, cta], 390, "390"));
  assert.throws(() => validateBarLayout([brand, { ...cta, left: 100 }], 390, "390"), /brand overlaps Download/);
  assert.throws(() => validateBarLayout([brand, { ...cta, right: 400 }], 390, "390"), /Download leaves the viewport/);
  assert.throws(() => validateBarLayout([brand], 390, "390"), /fewer than two/);
});

test("menu button shows only below the desktop tier", () => {
  assert.doesNotThrow(() => validateMenuButton(true, 1199, "1199"));
  assert.doesNotThrow(() => validateMenuButton(false, 1200, "1200"));
  assert.throws(() => validateMenuButton(false, 390, "390"), /hidden at 390/);
  assert.throws(() => validateMenuButton(true, 1440, "1440"), /shown at 1440/);
});

test("tap target contract enforces the minimum on both sides", () => {
  assert.doesNotThrow(() => validateTapTargets([{ name: "menu", width: 44, height: 44 }], "390"));
  assert.throws(
    () => validateTapTargets([{ name: "Listen", width: 37, height: 19 }], "390"),
    /tap targets under 44 px: Listen 37x19/,
  );
});

test("anchor landing contract keeps targets below the bar", () => {
  assert.doesNotThrow(() => validateAnchorLanding({ targetTop: 81, barBottom: 65 }, "listen"));
  assert.throws(() => validateAnchorLanding({ targetTop: 20, barBottom: 65 }, "listen"), /lands at 20/);
  assert.throws(() => validateAnchorLanding({ targetTop: 400, barBottom: 65 }, "listen"), /lands at 400/);
});
