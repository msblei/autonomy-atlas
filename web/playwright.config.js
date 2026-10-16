// Browser tests: what the page shows must be what web/public/data says (tests/*.spec.js).
import { defineConfig } from "@playwright/test";

const PORT = 5181;
export default defineConfig({
  testDir: "tests",
  timeout: 120_000,
  workers: 2,
  reporter: [["list"]],
  // The installed Google Chrome (own temporary profile); no browser download needed.
  use: { baseURL: `http://localhost:${PORT}/`, viewport: { width: 1280, height: 900 }, channel: "chrome" },
  webServer: {
    command: `node_modules/.bin/vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
