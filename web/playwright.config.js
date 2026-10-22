// Browser tests: what the page shows must be what web/public/data says (tests/*.spec.js).
import { defineConfig } from "@playwright/test";

const PORT = 5181; // the dev server, for every test but one
const BUILT = 5182; // the built site (tests/build.spec.js), built into dist-test so dist stays the release
const seen = (port) => ({ cookies: [], origins: [{ origin: `http://localhost:${port}`, localStorage: [{ name: "atlas.landing", value: "seen" }] }] });
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
  use: { viewport: { width: 1280, height: 900 }, channel: "chrome", contextOptions: { reducedMotion: "reduce" } },
  // A first visit to the bare address opens with the tour's start (main.js, landingDue); the tests
  // come as returning readers, except tests/tour.spec.js, which clears this.
  projects: [
    { name: "dev", testIgnore: /build\.spec\.js/, use: { baseURL: `http://localhost:${PORT}/`, storageState: seen(PORT) } },
    { name: "built", testMatch: /build\.spec\.js/, use: { baseURL: `http://localhost:${BUILT}/`, storageState: seen(BUILT) } },
  ],
  webServer: [
    {
      command: `node_modules/.bin/vite --port ${PORT} --strictPort`,
      url: `http://localhost:${PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    {
      command: `node_modules/.bin/vite build --outDir dist-test --emptyOutDir --logLevel warn`
        + ` && node_modules/.bin/vite preview --outDir dist-test --port ${BUILT} --strictPort`,
      url: `http://localhost:${BUILT}/`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
