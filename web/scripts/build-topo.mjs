// countries.geojson -> countries.topojson (run by `atlas export`, pipeline/export.py): every border
// shared by two countries is stored once, coordinates as integer steps. Quantization 360,000 over
// the world's extent: steps of 0.001° in longitude, as fine as the GeoJSON's three decimals.
// The page decodes it with topojson-client; pipeline/validate.py checks it against the GeoJSON.
//
// Also silhouette.svg: the same countries as one grey shape (the map's NO_DATA colour) in Web
// Mercator, simplified to about two pixels at the start zoom. index.html shows it over the map area
// from the page's first paint, before the map library has even arrived; main.js removes it once
// the map has drawn its colours.
import { readFileSync, writeFileSync } from "node:fs";
import { topology } from "topojson-server";

const dir = new URL("../public/data/", import.meta.url);
const geo = JSON.parse(readFileSync(new URL("countries.geojson", dir), "utf8"));
const topo = topology({ countries: geo }, 360000);
writeFileSync(new URL("countries.topojson", dir), JSON.stringify(topo));
console.log(`countries.topojson: ${geo.features.length} countries, ${topo.arcs.length} arcs`);

// ---- silhouette ---------------------------------------------------------------------------------
const GRID = 2048; // the world is GRID x GRID units (the SVG's viewBox), integer coordinates
const TOLERANCE = 3; // units; the start view shows the world 1448 px wide, so about 2 px
const MAX_LAT = 85.0511; // Web Mercator's edge

function project(lon, lat) {
  const la = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat));
  const x = ((lon + 180) / 360) * GRID;
  const y = ((180 - (180 / Math.PI) * Math.log(Math.tan(Math.PI / 4 + (la * Math.PI) / 360))) / 360) * GRID;
  return [Math.round(x), Math.round(y)];
}

// A quantized arc is delta-encoded: undo that, then project.
const { scale, translate } = topo.transform;
function decode(arc) {
  let x = 0, y = 0;
  return arc.map(([dx, dy]) => {
    x += dx; y += dy;
    return project(x * scale[0] + translate[0], y * scale[1] + translate[1]);
  });
}

// Douglas-Peucker with both end points kept: a border shared by two countries is one arc, so the
// two sides stay identical and no cracks open between neighbours.
function simplify(pts, tol) {
  if (pts.length <= 2) return pts;
  const keep = new Uint8Array(pts.length);
  keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    const [ax, ay] = pts[a], [bx, by] = pts[b];
    const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
    let imax = -1, dmax = 0;
    for (let i = a + 1; i < b; i++) {
      const [px, py] = pts[i];
      let d;
      if (len2 === 0) d = Math.hypot(px - ax, py - ay);
      else {
        const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2));
        d = Math.hypot(px - ax - t * dx, py - ay - t * dy);
      }
      if (d > dmax) { dmax = d; imax = i; }
    }
    if (dmax > tol) { keep[imax] = 1; stack.push([a, imax], [imax, b]); }
  }
  return pts.filter((_, i) => keep[i]);
}

const arcs = topo.arcs.map((a) => simplify(decode(a), TOLERANCE));

// A ring is a list of arc indices (~i means arc i reversed); joints share a point, the ring closes
// on its first point. Returns the ring's distinct points, or null if it is too small to see.
function ring(indices) {
  const out = [];
  for (const i of indices) {
    const pts = i < 0 ? arcs[~i].slice().reverse() : arcs[i];
    for (const p of pts) {
      const last = out[out.length - 1];
      if (!last || last[0] !== p[0] || last[1] !== p[1]) out.push(p);
    }
  }
  const first = out[0], last = out[out.length - 1];
  if (out.length > 1 && first[0] === last[0] && first[1] === last[1]) out.pop();
  if (out.length < 3) return null;
  const xs = out.map((p) => p[0]), ys = out.map((p) => p[1]);
  if (Math.max(...xs) - Math.min(...xs) < 3 && Math.max(...ys) - Math.min(...ys) < 3) return null;
  return out;
}

const d = [];
let polygons = 0;
for (const g of topo.objects.countries.geometries) {
  const polys = g.type === "Polygon" ? [g.arcs] : g.type === "MultiPolygon" ? g.arcs : [];
  for (const poly of polys) {
    const outer = ring(poly[0]);
    if (!outer) continue;
    polygons++;
    for (const r of [outer, ...poly.slice(1).map(ring).filter(Boolean)]) {
      d.push(`M${r[0][0]},${r[0][1]}L${r.slice(1).map((p) => `${p[0]},${p[1]}`).join(" ")}Z`);
    }
  }
}
// Three copies of the world side by side: the map repeats it too when the screen is wide.
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="-${GRID} 0 ${3 * GRID} ${GRID}" preserveAspectRatio="none">`
  + `<defs><path id="land-w" fill="#ebe9e3" fill-rule="evenodd" d="${d.join("")}"/></defs>`
  + `<use href="#land-w" x="-${GRID}"/><use href="#land-w"/><use href="#land-w" x="${GRID}"/></svg>\n`;
writeFileSync(new URL("silhouette.svg", dir), svg);
const points = arcs.reduce((n, a) => n + a.length, 0);
console.log(`silhouette.svg: ${polygons} shapes, ${points} points, ${(svg.length / 1024).toFixed(0)} KB`);
