// Browser tests: what the page shows must be what web/public/data says (tests/*.spec.js).
import { defineConfig } from "@playwright/test";

const PORT = 5181;
export default defineConfig({
  testDir: "tests",
  timeout: 120_000,
  // One worker: two Chrome instances drawing the WebGL map side by side wait on each other (with the
  // accessibility scans the suite took 16 minutes on two workers, 47 seconds on one).
  workers: 1,
  reporter: [["list"]],
  // The installed Google Chrome (own temporary profile); no browser download needed.
  // Reduced motion: the panel hands details over instantly, so the data tests need not wait out the
  // fades (the animation itself is checked by hand).
  use: { baseURL: `http://localhost:${PORT}/`, viewport: { width: 1280, height: 900 }, channel: "chrome",
    contextOptions: { reducedMotion: "reduce" } },
  webServer: {
    command: `node_modules/.bin/vite --port ${PORT} --strictPort`,
    url: `http://localhost:${PORT}/`,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
