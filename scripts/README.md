# Scripts

- `serve.mjs`: a minimal static server for `app/`, used for the local preview (`npm run serve`) and by Playwright.
- `vendor.mjs`: copies the pinned front-end libraries from `node_modules` into `app/vendor/`, so the app needs no
  CDN at runtime and no build step.
