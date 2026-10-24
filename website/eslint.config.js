// Correctness lint for the site's JavaScript (workflow audit P3-4): ESLint's
// recommended rules and the React hooks rules. Formatting is not linted.
import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";

export default [
  { ignores: ["dist/", "dist-ssr/", "test-results/", "playwright-report/"] },
  js.configs.recommended,
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      globals: globals.browser,
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      // JSX references count as uses, so imported components are not reported unused.
      "no-unused-vars": ["error", { varsIgnorePattern: "^React$" }],
    },
  },
  {
    files: ["scripts/**/*.mjs", "tests/**/*.mjs", "*.config.{js,mjs}"],
    languageOptions: { globals: globals.node },
  },
  {
    // Playwright specs and their helpers pass callbacks to page.evaluate,
    // which run in the page.
    files: ["tests/**/*.spec.mjs", "tests/browser-helpers.mjs"],
    languageOptions: { globals: { ...globals.node, ...globals.browser } },
  },
];
