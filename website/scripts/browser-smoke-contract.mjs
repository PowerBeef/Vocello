export const VIEWPORTS = Object.freeze([
  Object.freeze({ name: "wide", width: 1440, height: 900 }),
  Object.freeze({ name: "narrow", width: 390, height: 844 }),
]);

export function validateHydrationProbe({ before, after, scrollTop }) {
  if (!Number.isFinite(scrollTop) || scrollTop <= 0) {
    throw new Error("hydration probe did not scroll the document");
  }
  if (typeof before !== "string" || typeof after !== "string" || before === after) {
    throw new Error("hydration probe did not observe a client-owned progress update");
  }
}

export function validateFocusSequence(sequence) {
  if (!Array.isArray(sequence) || sequence.length < 3) {
    throw new Error("focus sequence is too short");
  }
  for (const [index, item] of sequence.entries()) {
    if (!item || typeof item !== "object" || !item.signature) {
      throw new Error(`focus sequence item ${index} has no stable signature`);
    }
  }
  const unique = new Set(sequence.map((item) => item.signature));
  if (unique.size < Math.min(3, sequence.length)) {
    throw new Error("keyboard focus is trapped on too few controls");
  }
  if (!sequence.some((item) => item.visible)) {
    throw new Error("keyboard focus never reached a visible control");
  }
}

export function validateInternalTargets(links, ids, paths) {
  const targets = new Set(ids);
  const pages = new Set(paths);
  const missing = [];
  for (const href of links) {
    if (href.startsWith("#") && !targets.has(href.slice(1))) missing.push(href);
    if (href.startsWith("/") && !href.startsWith("//")) {
      const path = href.split("#", 1)[0];
      if (!pages.has(path)) missing.push(href);
    }
  }
  if (missing.length) throw new Error(`unresolved internal targets: ${missing.join(", ")}`);
}

// Layout matrix (tests/layout-matrix.spec.mjs). Widths cover each tier and the
// first pixel past every edge (DESIGN.md: 600, 900, 1200, plus the 1320 px
// Open source link and the 1600 px wide container), where the most content
// meets the least room.
export const LAYOUT_WIDTHS = Object.freeze([
  320, 375, 390, 430, 600, 601, 768, 834, 899, 900, 1024, 1180, 1199, 1200, 1280, 1320, 1440, 1600, 1920,
]);
export const LAYOUT_PORTRAIT_HEIGHT = 900;
export const LANDSCAPE_SIZES = Object.freeze([
  Object.freeze({ width: 667, height: 375 }),
  Object.freeze({ width: 844, height: 390 }),
  Object.freeze({ width: 932, height: 430 }),
]);
export const LAYOUT_PATHS = Object.freeze(["/", "/support/", "/privacy/"]);
export const DESKTOP_MIN_WIDTH = 1200;
export const MIN_TAP = 44;

// Real iPhone and iPad descriptors, run in WebKit (Safari's engine).
export const WEBKIT_DEVICES = Object.freeze([
  "iPhone SE",
  "iPhone 15",
  "iPhone 15 Pro Max landscape",
  "iPad Mini",
  "iPad Pro 11",
  "iPad Pro 11 landscape",
]);

/** @param {Array<{ name: string, left: number, right: number }>} offenders */
export function validateNoOverflow(offenders, label) {
  if (!Array.isArray(offenders)) throw new Error(`${label}: overflow probe returned no list`);
  if (offenders.length) {
    const named = offenders.slice(0, 6).map((item) => `${item.name} [${item.left}, ${item.right}]`);
    throw new Error(`${label}: ${offenders.length} element(s) extend past the viewport: ${named.join("; ")}`);
  }
}

/**
 * The bar's visible items stay inside the viewport and never overlap.
 * @param {Array<{ name: string, left: number, right: number, top: number, bottom: number }>} boxes
 */
export function validateBarLayout(boxes, viewportWidth, label) {
  if (!Array.isArray(boxes) || boxes.length < 2) throw new Error(`${label}: the bar shows fewer than two items`);
  for (const box of boxes) {
    if (box.left < -1 || box.right > viewportWidth + 1) {
      throw new Error(`${label}: ${box.name} leaves the viewport (${box.left} to ${box.right})`);
    }
  }
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i];
      const b = boxes[j];
      const overlapX = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const overlapY = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (overlapX > 1 && overlapY > 1) throw new Error(`${label}: ${a.name} overlaps ${b.name}`);
    }
  }
}

/** The menu button shows exactly below the desktop tier. */
export function validateMenuButton(menuVisible, viewportWidth, label) {
  const expected = viewportWidth < DESKTOP_MIN_WIDTH;
  if (menuVisible !== expected) {
    throw new Error(`${label}: menu button ${menuVisible ? "shown" : "hidden"} at ${viewportWidth} px`);
  }
}

/** @param {Array<{ name: string, width: number, height: number }>} targets */
export function validateTapTargets(targets, label, min = MIN_TAP) {
  const small = targets.filter((target) => target.width < min - 0.5 || target.height < min - 0.5);
  if (small.length) {
    const named = small.map((target) => `${target.name} ${target.width}x${target.height}`);
    throw new Error(`${label}: tap targets under ${min} px: ${named.join(", ")}`);
  }
}

/** An anchor jump lands its target just below the sticky bar, never under it. */
export function validateAnchorLanding({ targetTop, barBottom }, label) {
  if (!Number.isFinite(targetTop) || !Number.isFinite(barBottom)) {
    throw new Error(`${label}: anchor landing was not measured`);
  }
  if (targetTop < barBottom - 1 || targetTop > barBottom + 48) {
    throw new Error(`${label}: target lands at ${targetTop} px with the bar ending at ${barBottom} px`);
  }
}
