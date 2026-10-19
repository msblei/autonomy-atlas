import { defineConfig } from "vite";

// The stylesheet (14 KB compressed) goes into index.html: the first paint waits for the
// stylesheet, and this saves it a round trip. Its font URLs are relative to assets/, so they are
// rewritten. The file itself stays in assets/ (nothing links to it any more): a chunk's loader may
// still list it, and a missing file would make the import() fail.
function inlineCss() {
  return {
    name: "atlas-inline-css",
    apply: "build",
    enforce: "post",
    transformIndexHtml: {
      order: "post",
      handler(html, { bundle }) {
        for (const [name, asset] of Object.entries(bundle ?? {})) {
          if (asset.type !== "asset" || !name.endsWith(".css")) continue;
          const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
          const tag = new RegExp(`<link[^>]*href="\\./${escaped}"[^>]*>\\s*`);
          if (!tag.test(html)) continue;
          const css = asset.source.toString().replaceAll("url(./", "url(./assets/");
          html = html.replace(tag, `<style>${css}</style>\n`);
        }
        return html;
      },
    },
  };
}

export default defineConfig({
  // Relative base so the built site works from GitHub Pages or any subpath.
  base: "./",
  server: { port: 5173, open: false },
  plugins: [inlineCss()],
  build: {
    // One stylesheet for everything (inlined above), so no chunk has a stylesheet of its own to
    // fetch before it can run.
    cssCodeSplit: false,
    rollupOptions: {
      // main.js imports the map library on its own (import()), so the page's code runs before it;
      // its own chunk, which Vite lists as a modulepreload so both download from the start.
      output: { manualChunks: (id) => (id.includes("node_modules/maplibre-gl/") ? "maplibre" : undefined) },
    },
  },
});
