// Map label font: Atkinson Hyperlegible Next SemiBold as MapLibre glyph tiles (signed distance
// fields, one .pbf per range of 256 characters), so the map's labels use the site's typeface and
// nothing is fetched from a third-party server.
//
// The glyphs are drawn the way MapLibre draws local glyphs itself: in Chrome, with TinySDF, from
// the self-hosted variable font (@fontsource-variable). Then they are written in the glyph .pbf
// format of maplibre-gl-style-spec (fontstack > glyph: id, bitmap, width, height, left, top, advance).
//
//   node scripts/build-glyphs.mjs        -> public/fonts/<fontstack>/<start>-<end>.pbf
//
// Re-run after changing the font or adding a range; the output is committed.
import { mkdirSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const web = join(dirname(fileURLToPath(import.meta.url)), "..");
const FONTSTACK = "Atkinson Hyperlegible Next SemiBold";
const WEIGHT = 600;
const RANGES = [0, 256]; // Basic Latin + Latin-1 (every country name today), Latin Extended-A
const pkg = join(web, "node_modules/@fontsource-variable/atkinson-hyperlegible-next");

// The normal (upright) faces and their unicode ranges, as fontsource declares them.
const css = readFileSync(join(pkg, "index.css"), "utf8");
const faces = [...css.matchAll(/@font-face\s*{([^}]*)}/g)]
  .map(([, body]) => ({
    file: body.match(/url\(\.\/files\/([^)]+\.woff2)\)/)?.[1],
    style: body.match(/font-style:\s*(\w+)/)?.[1],
    range: body.match(/unicode-range:\s*([^;]+);/)?.[1].trim(),
  }))
  .filter((f) => f.file && f.style === "normal")
  .map((f) => ({ ...f, data: readFileSync(join(pkg, "files", f.file)).toString("base64") }));
if (!faces.length) throw new Error("no font faces found in fontsource's index.css");

// TinySDF is an ES module; hand it to the page as a global.
const tinySdf = readFileSync(join(web, "node_modules/@mapbox/tiny-sdf/index.js"), "utf8")
  .replace("export default class TinySDF", "window.TinySDF = class TinySDF");

const browser = await chromium.launch({ channel: "chrome" });
const page = await browser.newPage();
await page.setContent("<!doctype html><title>glyphs</title>");
await page.addScriptTag({ content: tinySdf });
await page.evaluate(async (faces) => {
  for (const f of faces) {
    const bytes = Uint8Array.from(atob(f.data), (c) => c.charCodeAt(0));
    const face = new FontFace("Atlas Label", bytes, { weight: "200 800", unicodeRange: f.range });
    document.fonts.add(await face.load());
  }
}, faces);

const outDir = join(web, "public/fonts", FONTSTACK);
mkdirSync(outDir, { recursive: true });

for (const start of RANGES) {
  const end = start + 255;
  const glyphs = await page.evaluate(({ start, end, weight }) => {
    // MapLibre's server glyph size: 24 px, 3 px buffer, radius 8, cutoff 0.25.
    const sdf = new window.TinySDF({ fontSize: 24, buffer: 3, radius: 8, cutoff: 0.25, fontFamily: "'Atlas Label'", fontWeight: String(weight) });
    const out = [];
    for (let id = start; id <= end; id++) {
      if (id < 32 || (id >= 127 && id < 160)) continue; // control characters
      const g = sdf.draw(String.fromCharCode(id));
      out.push({ id, data: Array.from(g.data), width: g.glyphWidth, height: g.glyphHeight,
        top: g.glyphTop, left: g.glyphLeft, advance: g.glyphAdvance });
    }
    return out;
  }, { start, end, weight: WEIGHT });
  writeFileSync(join(outDir, `${start}-${end}.pbf`), encode(FONTSTACK, `${start}-${end}`, glyphs));
  console.log(`${FONTSTACK} ${start}-${end}: ${glyphs.length} glyphs`);
}
await browser.close();
copyFileSync(join(pkg, "LICENSE"), join(web, "public/fonts/OFL.txt"));

// ------------------------------------------------------------------------------------------------
// protobuf, just the three messages a glyph file needs

function encode(name, range, glyphs) {
  const stack = [str(1, name), str(2, range), ...glyphs.map((g) => msg(3, glyph(g)))];
  return Buffer.from(msg(1, concat(stack)));
}

function glyph(g) {
  const w = g.width > 0 && g.height > 0;
  return concat([
    uint(1, g.id),
    w ? bytes(2, Uint8Array.from(g.data)) : new Uint8Array(0),
    uint(3, w ? g.width : 0),
    uint(4, w ? g.height : 0),
    sint(5, Math.round(g.left + 0.5)), // MapLibre's own adjustment for TinySDF glyphs
    sint(6, Math.round(g.top - 27.5)), //   (glyph_manager.ts, topAdjustment / leftAdjustment)
    uint(7, Math.round(g.advance)),
  ]);
}

function varint(n) {
  const out = [];
  while (n > 127) { out.push((n & 127) | 128); n = Math.floor(n / 128); }
  out.push(n);
  return Uint8Array.from(out);
}
function key(field, type) { return varint(field * 8 + type); }
function uint(field, n) { return concat([key(field, 0), varint(n)]); }
function sint(field, n) { return concat([key(field, 0), varint(n >= 0 ? n * 2 : -n * 2 - 1)]); }
function bytes(field, b) { return concat([key(field, 2), varint(b.length), b]); }
function str(field, s) { return bytes(field, new TextEncoder().encode(s)); }
function msg(field, b) { return bytes(field, b); }

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let at = 0;
  for (const p of parts) { out.set(p, at); at += p.length; }
  return out;
}
