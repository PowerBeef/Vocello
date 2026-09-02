import { expect, test } from "@playwright/test";
import {
  VIEWPORTS,
  validateFocusSequence,
  validateHydrationProbe,
  validateInternalTargets,
} from "../scripts/browser-smoke-contract.mjs";

function collectBrowserFailures(page) {
  const failures = [];
  page.on("pageerror", (error) => failures.push(`pageerror:${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`console:${message.text()}`);
  });
  page.on("requestfailed", (request) => {
    const failure = request.failure()?.errorText ?? "unknown";
    failures.push(`request:${request.url()}:${failure}`);
  });
  return failures;
}

for (const viewport of VIEWPORTS) {
  test(`${viewport.name} production page hydrates, navigates, and has no browser errors`, async ({ page }) => {
    await page.setViewportSize(viewport);
    // Vite preview does not implement Vercel's production analytics endpoint.
    // Fulfill only that exact first-party script request so the browser smoke
    // observes application console/network failures without changing the
    // production bundle or disabling analytics in deployment.
    await page.route("**/_vercel/insights/script.js", (route) => route.fulfill({
      contentType: "application/javascript",
      body: "window.va = window.va || function () {};",
    }));
    const failures = collectBrowserFailures(page);
    await page.goto("/", { waitUntil: "networkidle" });

    await expect(page.locator("main#main-content")).toBeVisible();
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.locator(".listen-row")).toHaveCount(5);
    await expect(page.locator("body")).not.toHaveJSProperty("scrollWidth", 0);

    const overflow = await page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);

    const progress = page.locator(".nav-progress");
    const before = await progress.evaluate((element) => getComputedStyle(element).transform);
    await page.evaluate(() => window.scrollTo(0, Math.max(900, document.body.scrollHeight / 2)));
    await expect.poll(() => page.evaluate(() => window.scrollY)).toBeGreaterThan(0);
    const after = await progress.evaluate((element) => getComputedStyle(element).transform);
    validateHydrationProbe({ before, after, scrollTop: await page.evaluate(() => window.scrollY) });

    await page.goto("/", { waitUntil: "networkidle" });
    const sequence = [];
    for (let index = 0; index < 10; index += 1) {
      await page.keyboard.press("Tab");
      sequence.push(await page.evaluate(() => {
        const element = document.activeElement;
        const rect = element?.getBoundingClientRect?.();
        return {
          signature: `${element?.tagName ?? "none"}:${element?.getAttribute?.("href") ?? element?.getAttribute?.("aria-label") ?? element?.textContent?.trim?.().slice(0, 40) ?? ""}`,
          visible: Boolean(rect && rect.width > 0 && rect.height > 0),
        };
      }));
    }
    validateFocusSequence(sequence);

    await page.goto("/", { waitUntil: "networkidle" });
    await page.keyboard.press("Tab");
    await expect(page.locator(".skip-link")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("#main-content")).toBeFocused();

    const targetInventory = await page.evaluate(() => ({
      links: [...document.querySelectorAll("a[href]")].map((link) => link.getAttribute("href")),
      ids: [...document.querySelectorAll("[id]")].map((element) => element.id),
    }));
    validateInternalTargets(
      targetInventory.links,
      targetInventory.ids,
      ["/", "/support/", "/privacy/"],
    );

    for (const path of ["/support/", "/privacy/"]) {
      const response = await page.goto(path, { waitUntil: "networkidle" });
      expect(response?.status()).toBe(200);
      await expect(page.locator("main")).toBeVisible();
    }
    expect(failures).toEqual([]);
  });
}
