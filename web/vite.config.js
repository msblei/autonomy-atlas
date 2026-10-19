import { defineConfig } from "vite";

// The stylesheet (14 KB compressed) goes into index.html: the first paint waits for the
// stylesheet, and this saves it a round trip. Its font URLs are relative to assets/, so they are
// rewritten; the separate CSS file is then not written at all.
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
          delete bundle[name];
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
});
