// Playwright smoke tests for the web app (tests/app/). The static server serves app/ on port 4173.
const { defineConfig, devices } = require('@playwright/test');

module.exports = defineConfig({
  testDir: 'tests/app',
  timeout: 45000,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://localhost:4173/' },
  webServer: { command: 'node scripts/serve.mjs 4173', url: 'http://localhost:4173/', reuseExistingServer: !process.env.CI },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
});
