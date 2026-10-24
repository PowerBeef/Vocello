// The site's React pages: each has an HTML entry whose root names the page
// (<div id="root" data-page="...">) and a path it is served at. The build
// (vite.config.js), the prerender, the site contract and the browser tests
// all read this list.
export const SITE_PAGES = Object.freeze([
  Object.freeze({ page: "home", html: "index.html", path: "/" }),
  Object.freeze({ page: "cli", html: "cli/index.html", path: "/cli/" }),
  Object.freeze({ page: "engineering", html: "engineering/index.html", path: "/engineering/" }),
]);

// Static pages served from public/ (no React).
export const STATIC_PAGES = Object.freeze(["/support/", "/privacy/"]);
