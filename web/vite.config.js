import { defineConfig } from "vite";

export default defineConfig({
  // Relative base so the built site works from GitHub Pages or any subpath.
  base: "./",
  server: { port: 5173, open: false },
});
