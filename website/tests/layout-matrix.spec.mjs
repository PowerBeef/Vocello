import { expect, test } from "@playwright/test";
import {
  LANDSCAPE_SIZES,
  LAYOUT_PATHS,
  LAYOUT_PORTRAIT_HEIGHT,
  LAYOUT_WIDTHS,
  validateAnchorLanding,
  validateBarLayout,
  validateMenuButton,
  validateNoOverflow,
  validateTapTargets,
} from "../scripts/browser-smoke-contract.mjs";
import {
  collectBrowserFailures,
  measureBar,
  measureMenuTargets,
  measureOverflow,
  measureUnsizedImages,
  stubAnalytics,
} from "./browser-helpers.mjs";

// The Chromium project walks every width and landscape size; each WebKit
// project is one real iPhone or iPad descriptor at its own size.
const sizesFor = (page, testInfo) => (testInfo.project.use.isMobile
  ? [page.viewportSize()]
  : [
    ...LAYOUT_WIDTHS.map((width) => ({ width, height: LAYOUT_PORTRAIT_HEIGHT })),
    ...LANDSCAPE_SIZES,
  ]);

for (const path of LAYOUT_PATHS) {
  test(`${path} fits every layout tier`, async ({ page }, testInfo) => {
    await stubAnalytics(page);
    const failures = collectBrowserFailures(page);
    await page.goto(path, { waitUntil: "networkidle" });
    for (const size of sizesFor(page, testInfo)) {
      const label = `${path} at ${size.width}x${size.height}`;
      await test.step(label, async () => {
        if (!testInfo.project.use.isMobile) await page.setViewportSize(size);
        const overflow = await page.evaluate(measureOverflow);
        validateNoOverflow(overflow.offenders, label);
        expect(overflow.docOverflow, `${label}: document scrolls sideways`).toBeLessThanOrEqual(1);
        expect(await page.evaluate(measureUnsizedImages), `${label}: images with no reserved height`).toEqual([]);
        const bar = await page.evaluate(measureBar);
        if (!bar) return;
        validateBarLayout(bar.items, size.width, label);
        validateMenuButton(bar.menuVisible, size.width, label);
        validateTapTargets(bar.items, label);
      });
    }
    expect(failures).toEqual([]);
  });
}

test("the menu sheet opens, holds focus, closes, and lands its links below the bar", async ({ page }, testInfo) => {
  const mobile = Boolean(testInfo.project.use.isMobile);
  if (!mobile) await page.setViewportSize({ width: 390, height: 844 });
  if ((page.viewportSize()?.width ?? 0) >= 1200) test.skip(true, "the desktop tier has no menu");
  await stubAnalytics(page);
  const failures = collectBrowserFailures(page);
  await page.goto("/", { waitUntil: "networkidle" });

  const menuButton = page.locator(".nav-actions .nav-menu-button");
  const sheet = page.locator("#site-menu");
  const activate = (locator) => (mobile ? locator.tap() : locator.click());

  await activate(menuButton);
  await expect(sheet).toBeVisible();
  await expect(menuButton).toHaveAttribute("aria-expanded", "true");
  validateTapTargets(await page.evaluate(measureMenuTargets), "menu sheet");

  // WebKit moves Tab between form controls only by default, so the focus walk
  // runs in Chromium. A modal dialog lets Tab pass to the browser's own
  // controls after its last item (the page reports body then), but never to
  // the page behind it.
  if (!mobile) {
    for (let index = 0; index < 32; index += 1) {
      await page.keyboard.press("Tab");
      const held = await page.evaluate(() => {
        const element = document.activeElement;
        return !element || element === document.body || Boolean(element.closest("#site-menu"));
      });
      expect(held, `Tab ${index + 1} reached the page behind the open menu`).toBe(true);
    }
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    await expect(menuButton).toBeFocused();
    await expect(menuButton).toHaveAttribute("aria-expanded", "false");
    await activate(menuButton);
    await expect(sheet).toBeVisible();
  }

  await activate(sheet.getByRole("link", { name: "Listen", exact: true }));
  await expect(sheet).toBeHidden();
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("#listen");
  // The jump runs after the sheet closes, so wait for the scroll to settle.
  const measure = () => page.evaluate(() => ({
    targetTop: Math.round(document.querySelector("#listen").getBoundingClientRect().top),
    barBottom: Math.round(document.querySelector(".nav").getBoundingClientRect().bottom),
  }));
  await expect.poll(async () => {
    const { targetTop, barBottom } = await measure();
    return targetTop - barBottom;
  }, { timeout: 5_000 }).toBeLessThanOrEqual(48);
  validateAnchorLanding(await measure(), "menu link Listen");
  expect(failures).toEqual([]);
});

test("desktop bar links land their sections below the bar", async ({ page }, testInfo) => {
  test.skip(Boolean(testInfo.project.use.isMobile), "the device projects cover the menu");
  await page.setViewportSize({ width: 1440, height: 900 });
  await stubAnalytics(page);
  await page.goto("/", { waitUntil: "networkidle" });
  await page.locator(".nav-links").getByRole("link", { name: "How it runs", exact: true }).click();
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("#how-it-runs");
  const landing = await page.evaluate(() => ({
    targetTop: Math.round(document.querySelector("#how-it-runs").getBoundingClientRect().top),
    barBottom: Math.round(document.querySelector(".nav").getBoundingClientRect().bottom),
  }));
  validateAnchorLanding(landing, "bar link How it runs");
});
