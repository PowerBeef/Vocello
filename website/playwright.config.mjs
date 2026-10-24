import { defineConfig, devices } from "@playwright/test";
import { WEBKIT_DEVICES } from "./scripts/browser-smoke-contract.mjs";

export default defineConfig({
  testDir: "./tests",
  testMatch: "*.spec.mjs",
  fullyParallel: false,
  forbidOnly: true,
  retries: 0,
  workers: 1,
  reporter: [["line"]],
  use: {
    baseURL: "http://127.0.0.1:4173",
    headless: true,
    reducedMotion: "reduce",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    // Chromium runs the smoke test and walks the full layout matrix.
    { name: "chromium", use: { browserName: "chromium" } },
    // WebKit, Safari's engine, checks the layout and the menu on real iPhone
    // and iPad descriptors (touch, device pixel ratio, mobile viewport).
    ...WEBKIT_DEVICES.map((name) => ({
      name: `webkit ${name}`,
      testMatch: "layout-matrix.spec.mjs",
      use: { ...devices[name] },
    })),
  ],
  webServer: {
    command: "npm run preview -- --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 30_000,
  },
});
