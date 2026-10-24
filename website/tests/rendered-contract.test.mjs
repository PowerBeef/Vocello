import assert from "node:assert/strict";
import test from "node:test";
import { renderRepositoryPages, validateRenderedMarkup } from "../scripts/rendered-contract.mjs";
import { SITE_PAGES } from "../scripts/site-pages.mjs";

test("every rendered page satisfies the accessibility contract", async () => {
  const pages = await renderRepositoryPages();
  assert.deepEqual(Object.keys(pages).sort(), SITE_PAGES.map(({ page }) => page).sort());
  for (const [page, markup] of Object.entries(pages)) {
    assert.deepEqual(validateRenderedMarkup(markup), [], page);
  }
});

test("rendered controls and labels fail closed", () => {
  const errors = validateRenderedMarkup(
    '<nav></nav><main id="main-content"><h1>Title</h1><button></button><textarea id="x"></textarea></main><footer></footer>',
  );
  assert.ok(errors.some((error) => error.includes("skip link")));
  assert.ok(errors.some((error) => error.includes("button has no accessible name")));
  assert.ok(errors.some((error) => error.includes("textarea has no accessible label")));
});
