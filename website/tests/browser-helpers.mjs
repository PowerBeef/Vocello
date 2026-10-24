// Shared by the Playwright specs.

export function collectBrowserFailures(page) {
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

// Vite preview does not implement Vercel's production analytics endpoint.
// Fulfill only that exact first-party script request so the specs observe
// application console/network failures without changing the production
// bundle or disabling analytics in deployment.
export async function stubAnalytics(page) {
  await page.route("**/_vercel/insights/script.js", (route) => route.fulfill({
    contentType: "application/javascript",
    body: "window.va = window.va || function () {};",
  }));
}

// Runs in the page. Lists elements whose box extends past the viewport and is
// not clipped by a scroll or clip container that itself fits (the comparison
// table's sideways scroller, rounded screenshot frames). html and body never
// count as such containers: the body's sideways clip would hide every case.
export function measureOverflow() {
  const vw = document.documentElement.clientWidth;
  const clipped = (element) => {
    for (let parent = element.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
      if (getComputedStyle(parent).overflowX !== "visible") {
        const rect = parent.getBoundingClientRect();
        if (rect.left >= -1 && rect.right <= vw + 1) return true;
      }
    }
    return false;
  };
  const offenders = [];
  for (const element of document.body.querySelectorAll("*")) {
    const rect = element.getBoundingClientRect();
    if (!rect.width || !rect.height) continue;
    if ((rect.right > vw + 1 || rect.left < -1) && !clipped(element)) {
      const cls = typeof element.className === "string" && element.className ? `.${element.className.split(" ")[0]}` : "";
      offenders.push({ name: `${element.tagName.toLowerCase()}${cls}`, left: Math.round(rect.left), right: Math.round(rect.right) });
    }
  }
  return { vw, offenders, docOverflow: document.documentElement.scrollWidth - vw };
}

// Runs in the page: the bar's visible items and their tap-target boxes.
export function measureBar() {
  const visible = (element) => element.getClientRects().length > 0 && getComputedStyle(element).visibility !== "hidden";
  const box = (element, name) => {
    const rect = element.getBoundingClientRect();
    return {
      name,
      left: Math.round(rect.left),
      right: Math.round(rect.right),
      top: Math.round(rect.top),
      bottom: Math.round(rect.bottom),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  };
  const nav = document.querySelector(".nav-inner");
  if (!nav) return null;
  const items = [];
  const brand = nav.querySelector(".brand");
  if (brand && visible(brand)) items.push(box(brand, "brand"));
  for (const link of nav.querySelectorAll(".nav-link")) {
    if (visible(link)) items.push(box(link, link.textContent.trim()));
  }
  const cta = nav.querySelector(".nav-cta");
  if (cta && visible(cta)) items.push(box(cta, "Download"));
  const menu = nav.querySelector(".nav-menu-button");
  const menuVisible = Boolean(menu && visible(menu));
  if (menuVisible) items.push(box(menu, "Menu"));
  const bar = document.querySelector(".nav").getBoundingClientRect();
  return { items, menuVisible, barBottom: Math.round(bar.bottom) };
}

// Runs in the page: tap-target boxes of the open menu sheet's controls.
export function measureMenuTargets() {
  return [...document.querySelectorAll("#site-menu a, #site-menu button")].map((element) => {
    const rect = element.getBoundingClientRect();
    return {
      name: element.getAttribute("aria-label") || element.textContent.trim(),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    };
  });
}

// Runs in the page: images that have no height before they load. A lazy image
// must reserve its space (width and height attributes on a box with a definite
// width); otherwise the page grows under the reader after an anchor jump.
export function measureUnsizedImages() {
  return [...document.querySelectorAll("main img")]
    .filter((image) => image.getClientRects().length > 0 && image.getBoundingClientRect().height === 0)
    .map((image) => image.getAttribute("src"));
}

// Runs in the page: the height of every top-level block and image in main, so
// a test can name what moved when a jump lands in the wrong place.
export function measureBlockHeights() {
  const entries = [...document.querySelectorAll("main > *, main img")].map((element, index) => {
    const name = element.tagName === "IMG"
      ? `img ${element.getAttribute("src")}`
      : `${index}:${element.id || element.className.split(" ")[0] || element.tagName}`;
    return [name, Math.round(element.getBoundingClientRect().height)];
  });
  return Object.fromEntries(entries);
}

// Runs in the page: loads every image now (lazy ones included) and lists those
// that loaded but cannot be decoded, which a browser shows as alt text.
export async function measureBrokenImages() {
  const images = [...document.querySelectorAll("main img")];
  images.forEach((image) => { image.loading = "eager"; });
  await Promise.all(images.map((image) => (image.complete
    ? Promise.resolve()
    : new Promise((resolve) => {
      image.addEventListener("load", resolve, { once: true });
      image.addEventListener("error", resolve, { once: true });
    }))));
  return images.filter((image) => image.naturalWidth === 0).map((image) => image.currentSrc || image.getAttribute("src"));
}
