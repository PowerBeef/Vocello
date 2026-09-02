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
