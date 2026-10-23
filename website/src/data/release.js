// Mirrors stableMacRelease and fallbackMacRelease in config/public-product-facts.json;
// the site contract fails when they drift (WEB-07).
export const STABLE_MAC_RELEASE = { version: "3.0.0", tag: "v3.0.0" };
export const FALLBACK_MAC_RELEASE = { version: "1.2.3", tag: "v1.2.3" };
