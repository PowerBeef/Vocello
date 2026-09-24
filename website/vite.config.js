import { readFileSync } from "node:fs";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// `vite preview` (and so the Playwright smoke run) serves the production build with the
// same response headers Vercel sends, so a Content-Security-Policy that blocks one of the
// site's own assets fails the browser smoke instead of reaching production.
const vercel = JSON.parse(readFileSync(new URL("./vercel.json", import.meta.url), "utf8"));
const siteRule = vercel.headers?.find((rule) => rule.source === "/(.*)");
if (!siteRule?.headers?.some(({ key }) => key === "Content-Security-Policy")) {
  throw new Error("vercel.json must set a Content-Security-Policy for every path");
}
const siteHeaders = Object.fromEntries(siteRule.headers.map(({ key, value }) => [key, value]));

export default defineConfig({
  plugins: [react()],
  preview: { headers: siteHeaders },
});
