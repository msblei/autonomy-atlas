import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import "@fontsource-variable/atkinson-hyperlegible-next";
import { foodIcon } from "./icons.js";
import { SEASONS, forHowLong, lastDay, lasts, months, season, strip } from "./calendar.js";

// ------------------------------------------------------------------------------------------------
// state
//
// The panel is a stack of levels; each one has its own URL hash so Back works and links can be
// shared. Every level adds detail to the one before it:
//   #               intro       pick a country
//   #DEU            country     one date: how long its own food would last
//   #DEU/foods      foods       the same date for every food
//   #DEU/cereals    food        one food: trend, per person, where the harvest goes
//   #DEU/cereals/trade          who it buys from (map: partners and arcs)
//   #DEU/cereals/sells          who it sells to
//   #DEU/cereals/used           what it is used for, per person
//   #DEU/cereals/sources        how do we know: FAO figures, the sum, check-it-yourself
//   #DEU/cereals/table          all the numbers (SSR, IDR, tonnes/kcal, FAO items)
//   #about                      sources without a country

const state = {
  iso3: null,
  group: "all", // "all" = protein-weighted across every food, else a products.yaml group key
  level: "intro", // intro | country | foods | food | trade | used | sources | table | about
  flow: "imports", // imports | exports (trade level)
  grown: false, // imports traced back to where they were grown, instead of who sold them
  indicator: "ssr", // ssr | idr (table level only)
  basis: "tonnes", // tonnes | kcal (table level only)
  bloc: false, // zoomed out: EU members are coloured with the EU27 bloc's figures (see EU_ZOOM)
  data: null, // ssr.json
  items: null, // items.json (table level), loaded on first use
  trade: null, // trade.json (food and trade levels), loaded on first use
  names: {}, // iso3 -> name for every polygon, including places without FAO data
  iso3By2: {}, // ISO2 -> ISO3, to preselect the reader's country from the browser language
  bbox: {}, // iso3 -> [w, s, e, n]
  centre: {}, // iso3 -> [lon, lat] inside the largest polygon: label, trade arcs
  area: {}, // iso3 -> size of the largest polygon (square degrees at its latitude), for label ranks
};

const EU = "EU27";
// Below this zoom the EU is coloured as one country; above it, its members appear.
const EU_ZOOM = 2.3;

// Gradients for the table level, where readers choose indicator and basis.
const SCALES = {
  ssr: { stops: [0, 50, 100, 150, 200], colors: ["#b84a2a", "#e8a46a", "#f2efe6", "#7fb58b", "#1e6b45"], ticks: ["0%", "100%", "200%+"] },
  idr: { stops: [0, 25, 50, 75, 100], colors: ["#f2efe6", "#f6d1a8", "#e89a62", "#c95f33", "#7a2a12"], ticks: ["0%", "50%", "100%"] },
  share: { stops: [20, 50, 75, 90, 100], colors: ["#b84a2a", "#e8a46a", "#f2efe6", "#7fb58b", "#1e6b45"], ticks: ["20% or less", "75%", "100%"] },
};

// Where a food goes once it is in the country ("domestic supply"), in display order.
const USES = [
  { key: "food", label: "eaten by people", color: "#c9822f" },
  { key: "feed", label: "fed to animals", color: "#e3b47a" },
  { key: "processing", label: "made into other foods (oil, sugar, beer…)", color: "#9c7bb0" },
  { key: "other_uses", label: "industry & biofuel", color: "#6f8fa8" },
  { key: "seed", label: "kept as seed", color: "#9bb07a" },
  { key: "losses", label: "lost after harvest", color: "#b9b2a3" },
];

const NO_DATA = "#ebe9e3";

// pipeline/checks.py and export.py flags in plain words (table level).
const FLAG_TEXT = {
  supply_missing: "No figure: FAO publishes no domestic supply for this food.",
  supply_nonpositive: "No figure: FAO's domestic supply is zero or negative, so the balance contradicts itself.",
  exports_exceed_available: "No figure: FAO lists more exported than was produced, imported and taken from stocks.",
  food_exceeds_supply: "No figure: FAO lists more eaten than there is left for use at home.",
  parts_contradict: "No figure: the total rests on single foods whose figures contradict themselves.",
  jrc_group_only: "Dairy comes from the European Commission's balance in milk equivalent, for dairy as a whole: no ratio per product and none weighted by calories.",
};

// Short names for the food buttons; the full label is in their tooltip and on every page.
const SHORT = {
  all: "All food", potatoes_roots: "Potatoes", sugar: "Sugar", oilseeds: "Oilseeds",
  vegetable_oils: "Oils", fish: "Fish", stimulants: "Coffee, tea", wine_beer: "Wine, beer",
};
const EXAMPLES = ["DEU", "USA", "BRA", "EGY"];
// The map key as a ruler in months, one short label per colour (SEASONS, in the same order).
const SEASON_SHORT = ["0–6", "6–9", "9–11", "11–12", "12", "12+"];

// ------------------------------------------------------------------------------------------------
// map

// No base map: the ocean is the background, the countries are our own shapes, and the labels are
// ours too, so tiny places (Vatican, Guernsey) never crowd the big ones. The label font is the
// site's own, as glyph tiles in public/fonts (scripts/build-glyphs.mjs): nothing comes from a
// third-party server.
const map = new maplibregl.Map({
  container: "map",
  style: {
    version: 8,
    glyphs: `${new URL("fonts/", document.baseURI).href}{fontstack}/{range}.pbf`,
    sources: {},
    layers: [{ id: "ocean", type: "background", paint: { "background-color": "#d6dfe0" } }],
  },
  center: [15, 30],
  zoom: 1.5,
  minZoom: 1,
  maxZoom: 7,
  attributionControl: false,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "tip", offset: 14 });

async function loadJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.json();
}

// Diagonal hatching for "no figures", so it never looks like a colour on the scale.
function hatch() {
  const n = 8;
  const c = document.createElement("canvas");
  c.width = c.height = n;
  const ctx = c.getContext("2d");
  ctx.fillStyle = NO_DATA;
  ctx.fillRect(0, 0, n, n);
  ctx.strokeStyle = "#b9b5aa";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, n); ctx.lineTo(n, 0);
  ctx.moveTo(-1, 1); ctx.lineTo(1, -1);
  ctx.moveTo(n - 1, n + 1); ctx.lineTo(n + 1, n - 1);
  ctx.stroke();
  return { width: n, height: n, data: ctx.getImageData(0, 0, n, n).data };
}

function bboxOf(geometry) {
  const b = [180, 90, -180, -90];
  const walk = (c) => {
    if (typeof c[0] === "number") {
      b[0] = Math.min(b[0], c[0]); b[1] = Math.min(b[1], c[1]);
      b[2] = Math.max(b[2], c[0]); b[3] = Math.max(b[3], c[1]);
    } else c.forEach(walk);
  };
  walk(geometry.coordinates);
  return b;
}

// A point well inside a country's largest polygon: the grid point farthest from its edges, refined
// twice. Labels go there and trade arcs start and end there. The middle of the bounding box would
// put Norway's label in Sweden and France's arcs in the Atlantic (French Guiana).
function insideRing(ring, x, y) {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

function edgeDistance(rings, x, y, k) {
  let best = Infinity;
  for (const ring of rings) {
    for (let i = 1; i < ring.length; i++) {
      const ax = ring[i - 1][0] * k, ay = ring[i - 1][1], bx = ring[i][0] * k, by = ring[i][1];
      const dx = bx - ax, dy = by - ay, px = x * k;
      const t = dx || dy ? Math.max(0, Math.min(1, ((px - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy))) : 0;
      const ex = ax + t * dx - px, ey = ay + t * dy - y;
      best = Math.min(best, ex * ex + ey * ey);
    }
  }
  return best;
}

function anchorOf(geometry) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  let rings = null, area = -1;
  for (const poly of polys) {
    const r = poly[0];
    let a = 0;
    for (let i = 1; i < r.length; i++) a += r[i - 1][0] * r[i][1] - r[i][0] * r[i - 1][1];
    const lat = r.reduce((t, p) => t + p[1], 0) / r.length;
    a = Math.abs(a / 2) * Math.cos((lat * Math.PI) / 180);
    if (a > area) { area = a; rings = poly; }
  }
  const [w, s, e, n] = bboxOf({ coordinates: rings[0] });
  const k = Math.cos((((s + n) / 2) * Math.PI) / 180);
  let pt = [(w + e) / 2, (s + n) / 2], best = -1;
  let cx = pt[0], cy = pt[1], sx = e - w, sy = n - s;
  const N = 14;
  for (let pass = 0; pass < 3; pass++) {
    for (let i = 0; i < N; i++) {
      for (let j = 0; j < N; j++) {
        const x = cx - sx / 2 + ((i + 0.5) * sx) / N, y = cy - sy / 2 + ((j + 0.5) * sy) / N;
        if (!insideRing(rings[0], x, y) || rings.slice(1).some((h) => insideRing(h, x, y))) continue;
        const d = edgeDistance(rings, x, y, k);
        if (d > best) { best = d; pt = [x, y]; }
      }
    }
    [cx, cy] = pt;
    sx = (sx / N) * 3; sy = (sy / N) * 3;
  }
  return { pt, area };
}

// Data starts loading straight away, in parallel with the background map (whose demo tile server
// can take seconds). The panel renders as soon as the data is in; the map is painted once both
// are ready.
const geoReady = loadJSON("data/countries.geojson");
const dataReady = Promise.all([geoReady, loadJSON("data/ssr.json")]).then(([geo, data]) => {
  // export.py drops empty fields to keep the file small; restore the ones the code walks.
  for (const c of Object.values(data.countries)) {
    c.indicators ??= {};
    c.trend ??= {};
  }
  state.data = data;
  for (const f of geo.features) {
    const { iso3, iso2, name } = f.properties;
    state.names[iso3] = name;
    if (iso2) state.iso3By2[iso2] = iso3;
    state.bbox[iso3] = bboxOf(f.geometry);
    const { pt, area } = anchorOf(f.geometry);
    state.centre[iso3] = pt;
    state.area[iso3] = area;
  }
  buildCountryPicker();
  window.addEventListener("hashchange", () => route());
  route();
  return geo;
}).catch((e) => {
  document.getElementById("view").innerHTML =
    `<p class="hint">No data yet. Run <code>make all</code> in the repo root to download FAOSTAT and build <code>web/public/data/</code>.</p>`;
  console.error(e);
  return null;
});

map.on("load", async () => {
  const geo = await dataReady;
  if (!geo) return;

  map.addImage("hatch", hatch());
  map.addSource("countries", { type: "geojson", data: geo, promoteId: "iso3" });
  map.addLayer({ id: "atlas-fill", type: "fill", source: "countries", paint: { "fill-color": NO_DATA } });
  map.addLayer({
    id: "atlas-nodata", type: "fill", source: "countries",
    paint: { "fill-pattern": "hatch" }, filter: ["in", ["get", "iso3"], ["literal", []]],
  });
  map.addLayer({
    id: "atlas-line", type: "line", source: "countries",
    paint: { "line-color": "#f8f6f1", "line-width": ["interpolate", ["linear"], ["zoom"], 1, 0.4, 5, 1.2] },
  });
  map.addSource("arcs", { type: "geojson", data: emptyFC(), lineMetrics: true });
  map.addLayer({
    id: "atlas-arcs", type: "line", source: "arcs",
    layout: { "line-cap": "round" },
    paint: {
      "line-width": ["get", "w"],
      // Faint where the food leaves, strong where it arrives: the direction without arrowheads.
      "line-gradient": ["interpolate", ["linear"], ["line-progress"],
        0, "rgba(31,74,110,0.15)", 1, "rgba(31,74,110,0.9)"],
    },
  });
  map.addLayer({
    id: "atlas-hover", type: "line", source: "countries",
    paint: { "line-color": "#1c2420", "line-width": 1.4 }, filter: ["==", ["get", "iso3"], ""],
  });
  map.addLayer({
    id: "atlas-selected", type: "line", source: "countries",
    paint: { "line-color": "#1c2420", "line-width": 2.6 }, filter: ["==", ["get", "iso3"], ""],
  });
  addLabels();

  state.mapReady = true;
  state.bloc = map.getZoom() < EU_ZOOM;
  paintMap();
  renderLegend();
  if (state.level === "trade") fitTrade();
  else if (state.iso3) flyTo(state.iso3);
  else showWorld(0);

  map.on("zoom", () => {
    const bloc = map.getZoom() < EU_ZOOM;
    if (bloc !== state.bloc) { state.bloc = bloc; paintMap(); renderLegend(); }
  });
  // Hover only shows a small label; the panel changes on a click, so it never jumps around
  // while the mouse moves. The label follows the map too: zooming or panning under a still mouse
  // updates it (crossing EU_ZOOM turns "France" into "European Union" and back).
  let mouse = null; // last pointer position over the map, in pixels
  const hoverAt = (point) => {
    const f = map.queryRenderedFeatures(point, { layers: ["atlas-fill"] })[0];
    if (!f) {
      map.getCanvas().style.cursor = "";
      map.setFilter("atlas-hover", ["==", ["get", "iso3"], ""]);
      popup.remove();
      return;
    }
    const iso3 = f.properties.iso3;
    map.getCanvas().style.cursor = "pointer";
    const members = state.level !== "trade" && entity(iso3) === EU ? state.data.meta.eu_members : [iso3];
    map.setFilter("atlas-hover", ["in", ["get", "iso3"], ["literal", members]]);
    popup.setLngLat(map.unproject(point)).setHTML(tooltip(iso3)).addTo(map);
  };
  map.on("mousemove", (e) => { mouse = e.point; hoverAt(e.point); });
  map.getCanvas().addEventListener("mouseleave", () => { mouse = null; hoverAt([-1, -1]); });
  let queued = false;
  map.on("move", () => {
    if (!mouse || queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; if (mouse) hoverAt(mouse); });
  });
  map.on("click", "atlas-fill", (e) => select(e.features[0].properties.iso3));
});

// Country names, in four ranks by size: the big ones from the start, the small ones only zoomed
// in, so the map never turns into a page of text. Zoomed out, the EU gets one label.
const LABEL_RANKS = [[40, 1], [5, 2], [0.5, 2.9], [0, 4.2]]; // [min area, min zoom]
function addLabels() {
  const features = Object.entries(state.centre).map(([iso3, pt]) => ({
    type: "Feature", geometry: { type: "Point", coordinates: pt },
    properties: { iso3, name: state.names[iso3], area: state.area[iso3] },
  }));
  features.push({ type: "Feature", geometry: { type: "Point", coordinates: [10, 50] },
    properties: { iso3: EU, name: "European Union", area: 1e6 } });
  map.addSource("labels", { type: "geojson", data: { type: "FeatureCollection", features } });
  LABEL_RANKS.forEach(([min, minzoom], i) => {
    const max = i ? LABEL_RANKS[i - 1][0] : Infinity;
    map.addLayer({
      id: `atlas-label-${i}`, type: "symbol", source: "labels", minzoom,
      filter: ["all", [">=", ["get", "area"], min], ["<", ["get", "area"], max]],
      layout: {
        "text-field": ["get", "name"],
        "text-font": ["Atkinson Hyperlegible Next SemiBold"],
        "text-size": ["interpolate", ["linear"], ["zoom"], 1, i ? 10 : 11, 6, i ? 13 : 15],
        "text-max-width": 7,
        "text-letter-spacing": 0.02,
        "symbol-sort-key": ["-", ["get", "area"]],
        "text-padding": 4,
      },
      paint: { "text-color": "#23201b", "text-halo-color": "rgba(248,246,241,.85)", "text-halo-width": 1.4 },
    });
  });
}

// Labels follow the colours: zoomed out the EU is one shape with one name.
function filterLabels() {
  const members = state.data.meta.eu_members;
  const bloc = state.bloc && state.level !== "trade";
  LABEL_RANKS.forEach(([min], i) => {
    const max = i ? LABEL_RANKS[i - 1][0] : Infinity;
    const hide = bloc ? members : [EU];
    map.setFilter(`atlas-label-${i}`, ["all", [">=", ["get", "area"], min], ["<", ["get", "area"], max],
      ["!", ["in", ["get", "iso3"], ["literal", hide]]]]);
  });
}

// Time zones to countries, for suggesting where to start. The device's time zone says where the
// reader is, without asking anyone else (no IP lookup); a zone not listed falls back to the
// browser's languages.
const TZ = Object.fromEntries(`
  Amsterdam NLD Andorra AND Athens GRC Belgrade SRB Berlin DEU Bratislava SVK Brussels BEL
  Bucharest ROU Budapest HUN Busingen DEU Chisinau MDA Copenhagen DNK Dublin IRL Helsinki FIN
  Istanbul TUR Kaliningrad RUS Kiev UKR Kyiv UKR Lisbon PRT Ljubljana SVN London GBR Luxembourg LUX
  Madrid ESP Malta MLT Mariehamn FIN Minsk BLR Monaco MCO Moscow RUS Nicosia CYP Oslo NOR Paris FRA
  Podgorica MNE Prague CZE Riga LVA Rome ITA Samara RUS San_Marino SMR Sarajevo BIH Simferopol UKR
  Skopje MKD Sofia BGR Stockholm SWE Tallinn EST Tirane ALB Uzhgorod UKR Vaduz LIE Vienna AUT
  Vilnius LTU Volgograd RUS Warsaw POL Zagreb HRV Zaporozhye UKR Zurich CHE Reykjavik ISL
  Canary ESP Madeira PRT Azores PRT Faroe FRO
  New_York USA Chicago USA Denver USA Los_Angeles USA Phoenix USA Anchorage USA Detroit USA
  Indianapolis USA Honolulu USA Toronto CAN Vancouver CAN Edmonton CAN Winnipeg CAN Halifax CAN
  St_Johns CAN Regina CAN Montreal CAN Mexico_City MEX Monterrey MEX Tijuana MEX Cancun MEX
  Sao_Paulo BRA Manaus BRA Fortaleza BRA Recife BRA Bahia BRA Belem BRA Buenos_Aires ARG
  Santiago CHL Bogota COL Lima PER Caracas VEN La_Paz BOL Asuncion PRY Montevideo URY
  Guayaquil ECU Havana CUB Panama PAN Costa_Rica CRI Guatemala GTM
  Tokyo JPN Seoul KOR Shanghai CHN Taipei TWN Kolkata IND Calcutta IND Karachi PAK Dhaka BGD
  Jakarta IDN Manila PHL Bangkok THA Ho_Chi_Minh VNM Saigon VNM Kuala_Lumpur MYS Singapore SGP
  Dubai ARE Riyadh SAU Tehran IRN Baghdad IRQ Jerusalem ISR Tel_Aviv ISR Amman JOR Beirut LBN
  Kabul AFG Kathmandu NPL Colombo LKA Tashkent UZB Almaty KAZ Tbilisi GEO Yerevan ARM Baku AZE
  Yangon MMR Qatar QAT Kuwait KWT
  Cairo EGY Lagos NGA Johannesburg ZAF Nairobi KEN Casablanca MAR Algiers DZA Tunis TUN Accra GHA
  Addis_Ababa ETH Dar_es_Salaam TZA Kampala UGA Khartoum SDN Kinshasa COD Luanda AGO Abidjan CIV
  Dakar SEN Harare ZWE Lusaka ZMB Maputo MOZ Tripoli LBY
  Sydney AUS Melbourne AUS Brisbane AUS Perth AUS Adelaide AUS Hobart AUS Darwin AUS Auckland NZL`
  .trim().split(/\s+/).reduce((a, w, i, all) => (i % 2 ? a : [...a, [w, all[i + 1]]]), []));

// The reader's country: from the time zone (Europe/Berlin -> Germany), else from the browser
// languages (de-DE -> Germany). An English-language browser in Berlin says en-US, so a language
// whose country is on another continent than the time zone is skipped.
function readersCountry() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  const continent = zone.split("/")[0];
  const byZone = TZ[zone.split("/").pop()];
  if (byZone && country(byZone)) return byZone;
  for (const lang of navigator.languages ?? [navigator.language]) {
    try {
      const iso3 = state.iso3By2[new Intl.Locale(lang).maximize().region];
      if (!iso3 || !country(iso3)) continue;
      const europe = country(iso3).europe === true;
      if ((continent === "Europe" && !europe) || (continent === "America" && europe)) continue;
      return iso3;
    } catch { /* malformed tag */ }
  }
  return null;
}

// ------------------------------------------------------------------------------------------------
// routing

function parseHash() {
  const [a, b, c] = decodeURIComponent(location.hash.slice(1)).split("/");
  const intro = { iso3: null, group: "all", level: "intro" };
  if (a === "about") return { ...intro, level: "about" };
  if (!a || !(country(a) || state.names[a])) return intro;
  if (!b) return { iso3: a, group: "all", level: "country" };
  if (b === "foods") return { iso3: a, group: "all", level: "foods" };
  const group = state.data.groups.some((g) => g.key === b) ? b : "all";
  if (c === "used" && group === "all") return { iso3: a, group, level: "country" };
  if (c === "trade" || c === "sells") return { iso3: a, group, level: "trade", flow: c === "sells" ? "exports" : "imports" };
  if (["sources", "table", "used"].includes(c)) return { iso3: a, group, level: c };
  return group === "all" ? { iso3: a, group, level: "country" } : { iso3: a, group, level: "food" };
}

function hashFor({ iso3, group = "all", level, flow = "imports" }) {
  if (level === "about") return "#about";
  if (!iso3 || level === "intro") return "#";
  if (level === "country") return `#${iso3}`;
  if (level === "foods") return `#${iso3}/foods`;
  if (level === "food") return `#${iso3}/${group}`;
  if (level === "trade") return `#${iso3}/${group}/${flow === "exports" ? "sells" : "trade"}`;
  return `#${iso3}/${group}/${level}`;
}

function link(view) {
  return hashFor({ iso3: state.iso3, group: state.group, level: state.level, flow: state.flow, ...view });
}

function route() {
  const prev = `${state.iso3}/${state.group}/${state.level}/${state.flow}`;
  const next = parseHash();
  // Without a country the food is not in the hash; keep the one picked for the map.
  if (!next.iso3 && next.level === "intro") next.group = state.group;
  Object.assign(state, next);
  render();
  // The map follows the country (Back, Forward, links), except after a click on the map itself,
  // where the reader already sees it and a jump would only disorient.
  const before = prev.split("/")[0];
  if (state.level === "intro" && before !== "null") showWorld();
  else if (state.iso3 && state.iso3 !== before && state.level !== "trade" && !clickedOnMap) flyTo(state.iso3);
  clickedOnMap = false;
  if (state.level === "trade" && prev !== `${state.iso3}/${state.group}/${state.level}/${state.flow}`) fitTrade();
}

// A click on the map keeps the reader on the same level (and food) for the new country.
let clickedOnMap = false;
function select(clicked) {
  // Zoomed out, the tooltip names the EU for its members, so a click picks the EU too. The trade
  // map colours every country on its own, so there a click picks the member.
  const iso3 = state.level === "trade" ? clicked : entity(clicked);
  // Trade partners without food balances (Japan, Singapore) can still be looked at in trade view.
  const tradeOnly = state.level === "trade" && state.trade?.countries[iso3];
  const level = ["intro", "about"].includes(state.level) || (!country(iso3) && !tradeOnly)
    ? "country" : state.level;
  const hash = hashFor({ iso3, group: level === "country" || level === "foods" ? "all" : state.group, level, flow: state.flow });
  clickedOnMap = location.hash !== hash; // no hashchange (and no reset) when it is the same place
  location.hash = hash;
}

// The part of the map not covered by the panel (left), the food menu (right) and the key (bottom).
function openArea(extra = 0) {
  const wide = window.innerWidth > 760;
  const panel = document.getElementById("panel");
  const rail = document.getElementById("foodrail");
  const key = document.getElementById("legend");
  return wide
    ? { left: panel.offsetWidth + 40 + extra, right: rail.offsetWidth + 40 + extra, top: 40 + extra,
      bottom: key.offsetHeight + 40 + extra }
    : { left: 20, right: 20, top: rail.offsetHeight + key.offsetHeight + 30, bottom: panel.offsetHeight + 20 };
}

// Trade view: frame the country and its biggest partners (the ones with arcs).
function fitTrade() {
  if (!state.trade || !state.mapReady) return; // loadTrade() calls back here once the figures are in
  const pts = [state.iso3 === EU ? [10, 50] : state.centre[state.iso3],
    ...shares(state.iso3).slice(0, ARCS).map((r) => state.centre[r.id])].filter(Boolean);
  if (pts.length < 2) { flyTo(state.iso3); return; }
  // Shift partners by ±360° the same way the arcs go, so the US and Japan frame the Pacific.
  const x0 = pts[0][0];
  const lons = pts.map(([x]) => (x - x0 > 180 ? x - 360 : x0 - x > 180 ? x + 360 : x));
  const lats = pts.map((p) => p[1]);
  map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], {
    padding: openArea(20), maxZoom: 4, duration: 900,
  });
}

// The inhabited world, between the panel and the food menu.
function showWorld(duration = 900) {
  if (!state.mapReady) return;
  map.fitBounds([[-125, -40], [150, 62]], { padding: openArea(), duration });
}

function flyTo(iso3) {
  if (!state.mapReady) return; // the map flies there itself once it has loaded
  // The EU only reads as one shape when zoomed out past EU_ZOOM.
  if (iso3 === EU) { map.flyTo({ center: [10, 50], zoom: EU_ZOOM - 0.2, padding: openArea(), duration: 900 }); return; }
  const b = state.bbox[iso3];
  if (!b) return;
  // Wide or antimeridian-crossing countries (Russia, the US) would zoom out to the whole world.
  if (b[2] - b[0] > 180) return;
  map.fitBounds([[b[0], b[1]], [b[2], b[3]]], { padding: openArea(), maxZoom: 4, duration: 900 });
}

// ------------------------------------------------------------------------------------------------
// data access

// Zoomed out, every member state is coloured with the EU27 bloc's figures.
function entity(iso3) {
  if (state.bloc && state.data.meta.eu_members.includes(iso3) && state.data.countries[EU]) return EU;
  return iso3;
}

function country(id) {
  return state.data?.countries[id];
}

function nameOf(id) {
  return country(id)?.name ?? state.names[id] ?? state.trade?.names[id] ?? id;
}

function groupInfo(group = state.group) {
  return state.data.groups.find((x) => x.key === group) ?? { label: group };
}

// The figure every month strip is built from: for "all food" the protein produced vs used in
// total (a wheat surplus may make up for missing soy: what a country needs to get by), else the
// tonnes SSR of that food.
function pctFor(id, group = state.group) {
  const ind = country(id)?.indicators?.[group];
  const v = group === "all" ? ind?.protein?.ssr : ind?.tonnes?.ssr;
  return v == null || Number.isNaN(v) ? null : v;
}

// "Today's menu": the same protein figure with every food capped at 100%, so nothing is swapped.
function menuFor(id) {
  const v = country(id)?.indicators?.all?.protein?.share;
  return v == null || Number.isNaN(v) ? null : v;
}

// The foods that would run out first, for "… like fruit and soy" (at most `n`, below 9 months).
function shortest(id, n = 2) {
  return state.data.groups
    .filter((g) => g.key !== "all")
    .map((g) => ({ g, v: pctFor(id, g.key) }))
    .filter((r) => r.v != null && r.v < 75)
    .sort((a, b) => a.v - b.v)
    .slice(0, n)
    .map((r) => r.g.label.toLowerCase());
}

// Table level: the reader picks indicator and basis.
function tableIndicator() {
  // "All food" has coverage only: no import dependency is computed across foods.
  if (state.group === "all") return "share";
  return state.indicator;
}

function tableBasis() {
  if (state.group === "all") return state.basis === "kcal" ? "kcal" : "protein";
  return state.basis;
}

function valueFor(id, indicator = tableIndicator(), basis = tableBasis()) {
  const v = country(id)?.indicators?.[state.group]?.[basis]?.[indicator];
  return v == null || Number.isNaN(v) ? null : v;
}

function mapValue(id) {
  return state.level === "table" ? valueFor(id) : pctFor(id);
}

// kg/person/year from 1000 t and 1000 persons: kt * 1000 / population_k.
function perCapita(id, group = state.group) {
  const comp = country(id)?.indicators?.[group]?.components_kt;
  const pop = country(id)?.population_k;
  if (!comp || !pop) return null;
  return Object.fromEntries(Object.entries(comp).map(([k, v]) => [k, (v * 1000) / pop]));
}

// FAO balances that contradict themselves (pipeline/checks.py) carry no ratio and no
// components_kt, only FAO's raw lines under `withheld`, so no ranking, map or chart can use them.
function withheld(id, group = state.group) {
  return country(id)?.indicators?.[group]?.withheld ?? null;
}

// Why: in FAO's own words and figures, for the food page and the receipt.
function whyWithheld(id, group = state.group) {
  const w = withheld(id, group);
  if (!w) return "";
  const c = w.components_kt ?? {};
  const P = c.production ?? 0, M = c.imports ?? 0, X = c.exports ?? 0, S = c.stock_variation ?? 0;
  const who = id === EU ? "the EU" : nameOf(id);
  if (w.reason === "supply_missing" || c.supply == null) {
    return `FAO publishes no complete balance for ${food(group)} in ${who}.`;
  }
  const what = {
    food_exceeds_supply: `FAO counts more ${food(group)} eaten (${tonnes(c.food)}) than there is left for use at home (${tonnes(c.supply)})`,
    parts_contradict: `the total rests on ${w.items?.length ? `figures for ${w.items.map((i) => i.toLowerCase()).join(", ")} that contradict themselves` : "single foods whose figures contradict themselves"}, and it changes a lot depending on how they are read`,
  }[w.reason] ?? (X > P + M - S
    ? `they list more ${food(group)} sold abroad (${tonnes(X)}) than was produced (${tonnes(P)}) and bought abroad (${tonnes(M)}) together${S ? "" : ", with nothing taken out of storage"}`
    : `production (${tonnes(P)}) plus imports (${tonnes(M)}) minus exports (${tonnes(X)}) leaves ${tonnes(c.supply)} for use at home`);
  const resid = c.residuals && w.reason !== "parts_contradict"
    ? ` FAO closes the gap with an unexplained “Residuals” line of ${tonnes(c.residuals)}.` : "";
  return `FAO's figures for ${food(group)} in ${who} do not add up: ${what}.${resid}`;
}

// What still holds when a figure is withheld: both readings (as published, and with the
// contradictory parts read generously) on the same side of 100%.
function robustWords(range, id, what) {
  if (!range) return "";
  const [lo, hi] = range;
  const who = id === EU ? "the EU" : nameOf(id);
  if (lo >= 104.17) return `On any reading of FAO's figures, ${who} produces more ${what} than it uses.`;
  if (hi != null && hi < 99.5) return `On any reading of FAO's figures, ${who} produces less ${what} than it uses.`;
  return "";
}

// FAO item names in plain words: "Wheat and products" -> "wheat".
function itemName(item) {
  return item.replace(/ and products$/, "").replace(/ \(.*\)$/, "").replace(/^Sugar$/, "sugar").toLowerCase();
}

// A second source (USDA PSD, pipeline/usda.py) that puts an important item far from FAO's figure.
function secondOpinion(id, group = state.group) {
  const d = country(id)?.indicators?.[group]?.usda;
  if (!d?.length) return "";
  const who = id === EU ? "the EU" : nameOf(id);
  const s = state.data.meta.sources.usda_psd;
  const lines = d.map((x) => {
    const flips = (x.fao >= 100) !== (x.usda >= 100);
    return `for ${itemName(x.item)}, USDA's figures give ${Math.round(x.usda)}% of what is used, FAO's
      ${Math.round(x.fao)}%${flips ? ` (by USDA's, ${who} would produce ${x.usda >= 100 ? "more" : "less"} than it uses)` : ""}`;
  });
  return `<details class="aside"><summary>Another source disagrees</summary>${cap(lines.join("; "))}.
    The two compile their figures separately and do not always count the same things; we cannot tell
    which is right, and show FAO's, which covers every food.
    <a href="${s.url}" target="_blank" rel="noopener">USDA ${s.title}</a>.</details>`;
}

// "Fruit in Germany", above the titles of a food's deeper pages.
function kickerFor(id, group = state.group) {
  return `${group === "all" ? "All food" : groupInfo(group).label} in ${whoOf(id)}`;
}

function isMember(iso3) {
  return state.data.meta.eu_members.includes(iso3);
}

// ------------------------------------------------------------------------------------------------
// formatting

function fmt(v) {
  return v == null ? "no data" : `${v.toFixed(0)}%`;
}

function food(group = state.group) {
  return group === "all" ? "food" : groupInfo(group).label.toLowerCase();
}

function kg(v) {
  if (v == null) return "–";
  if (v > 0 && v < 1) return "<1 kg";
  return `${Math.round(v).toLocaleString("en-GB")} kg`;
}

// 1000 t -> "42.1 million tonnes" / "350 thousand tonnes" / "800 tonnes"
function tonnes(kt) {
  if (kt == null) return "–";
  const a = Math.abs(kt);
  if (a >= 1000) return `${(kt / 1000).toLocaleString("en-GB", { maximumFractionDigits: 1 })} million tonnes`;
  if (a >= 1) return `${Math.round(kt).toLocaleString("en-GB")} thousand tonnes`;
  return `${Math.round(kt * 1000).toLocaleString("en-GB")} tonnes`;
}

function people(popK) {
  if (popK == null) return "–";
  return popK >= 1000
    ? `${(popK / 1000).toLocaleString("en-GB", { maximumFractionDigits: 1 })} million people`
    : `${Math.round(popK).toLocaleString("en-GB")} thousand people`;
}

function longDate(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric", timeZone: "UTC",
  });
}

function years() {
  const [a, b] = state.data.meta.years.split("-").map(Number);
  return Array.from({ length: b - a + 1 }, (_, i) => a + i);
}

function kt(v) {
  return v == null ? "–" : `${Math.round(v).toLocaleString("en-GB")} kt`;
}

function pop(c) {
  return c.population_k == null ? "–" : `${(c.population_k / 1000).toFixed(1)} m`;
}

function bar(value, max, color) {
  const w = max > 0 && value > 0 ? Math.min(100, (value / max) * 100) : 0;
  return `<span class="bar" style="width:${w}%;background:${color}"></span>`;
}

const CHEVRON = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 5 7 7-7 7" /></svg>`;

function tooltip(iso3) {
  if (state.level === "trade") return tradeTooltip(iso3);
  const id = entity(iso3);
  if (!country(id)) return `<strong>${nameOf(iso3)}</strong><span class="v"><i class="hatch"></i>No data from FAO</span>`;
  const v = mapValue(id);
  const contradicts = state.group === "all"
    ? country(id)?.indicators?.all?.protein?.withheld : withheld(id);
  if (v == null) {
    return `<strong>${nameOf(id)}</strong><span class="v"><i class="hatch"></i>${contradicts
      ? "No reliable data from FAO" : "No data from FAO"}</span>`;
  }
  if (state.level === "table") return `<strong>${nameOf(id)}</strong>${fmt(v)}`;
  const what = state.group === "all" ? "Own food lasts" : `Own ${food()} lasts`;
  return `<strong>${nameOf(id)}</strong>
    <span class="v"><i style="background:${season(v).color}"></i>${what} ${lasts(v)}</span>`;
}

// ------------------------------------------------------------------------------------------------
// rendering

function render() {
  paintMap();
  renderLegend();
  renderCrumbs();
  renderControls();
  const views = { intro: viewIntro, about: viewAbout, country: viewCountry, foods: viewFoods,
    food: viewFood, trade: viewTrade, used: viewUsed, sources: viewSources, table: viewTable };
  const el = document.getElementById("view");
  const noData = state.iso3 && !country(state.iso3) && state.level !== "about"
    && !(state.level === "trade" && state.trade?.countries[state.iso3]);
  el.innerHTML = noData ? viewNoData() : views[state.level]();
  el.scrollTop = 0;
  wire(el);
  renderFoot();
  renderPeek();
}

// ------------------------------------------------------------------------------------------------
// phones: the panel is a sheet. Its handle folds it down to the search box and one line about the
// place on screen, so the map can be seen; the handle or that line unfold it again.

const panel = document.getElementById("panel");
const grab = document.getElementById("grab");

function setFolded(folded) {
  panel.classList.toggle("folded", folded);
  grab.setAttribute("aria-expanded", String(!folded));
  grab.setAttribute("aria-label", folded ? "Show details" : "Hide details");
  // The visible map grew or shrank: frame the place again.
  if (state.level === "trade") fitTrade();
  else if (state.iso3) flyTo(state.iso3);
  else showWorld();
}
grab.onclick = () => setFolded(!panel.classList.contains("folded"));
document.getElementById("peek").onclick = () => setFolded(false);

// Swipes: down folds the sheet, up unfolds it. On the handle, the search bar, the breadcrumbs and
// the folded line from anywhere; on the content only when it is scrolled to the top, so that a
// swipe there still scrolls. While folding, the sheet follows the finger a little.
function swipeToFold(el, { fromTop = false } = {}) {
  let y0 = null, x0 = 0, dy = 0;
  const reset = () => { y0 = null; panel.classList.remove("dragging"); panel.style.transform = ""; };
  el.addEventListener("touchstart", (e) => {
    if (!matchMedia("(max-width: 760px)").matches || e.touches.length > 1) return;
    if (fromTop && el.scrollTop > 0) return;
    y0 = e.touches[0].clientY; x0 = e.touches[0].clientX; dy = 0;
  }, { passive: true });
  el.addEventListener("touchmove", (e) => {
    if (y0 == null) return;
    dy = e.touches[0].clientY - y0;
    const dx = e.touches[0].clientX - x0;
    // Sideways (the food menu) or, on the content, upwards (scrolling): not a fold.
    if (Math.abs(dx) > Math.abs(dy) || (fromTop && dy < 0)) { reset(); return; }
    if (dy > 0 && !panel.classList.contains("folded")) {
      panel.classList.add("dragging");
      panel.style.transform = `translateY(${Math.min(dy, 240) * 0.6}px)`;
    }
  }, { passive: true });
  el.addEventListener("touchend", () => {
    if (y0 == null) return;
    const folded = panel.classList.contains("folded");
    reset();
    if (dy > 50 && !folded) setFolded(true);
    else if (dy < -40 && folded) setFolded(false);
  });
  el.addEventListener("touchcancel", reset);
}
for (const el of [grab, document.querySelector(".head"), document.getElementById("crumbs"), document.getElementById("peek")]) {
  swipeToFold(el);
}
swipeToFold(document.getElementById("view"), { fromTop: true });

function renderPeek() {
  const id = state.iso3;
  let line = "Could your country feed itself?";
  if (id && state.level === "trade") {
    line = `<b>${nameOf(id)}</b>: where it ${state.flow === "imports" ? "buys" : "sells"} ${food()}`;
  } else if (id) {
    const v = country(id) ? pctFor(id) : null;
    const what = state.group === "all" ? "own food" : `own ${food()}`;
    line = `<b>${nameOf(id)}</b>${v == null ? "" : `: ${what} lasts ${lasts(v, { short: true })}`}`;
  }
  document.getElementById("peek").innerHTML = `<span>${line}</span>
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 15 7-7 7 7" /></svg>`;
}

function paintMap() {
  if (!state.mapReady) return;
  filterLabels();
  if (state.level === "trade") { paintTrade(); return; }
  map.getSource("arcs").setData(emptyFC());
  let paint;
  if (state.level === "table") {
    const { stops, colors } = SCALES[tableIndicator()] ?? SCALES.ssr;
    paint = ["interpolate", ["linear"], ["feature-state", "v"]];
    stops.forEach((s, i) => paint.push(s, colors[i]));
  } else {
    paint = ["step", ["feature-state", "v"], SEASONS[0].color];
    SEASONS.slice(1).forEach((s, i) => paint.push(SEASONS[i].max, s.color));
  }
  map.setPaintProperty("atlas-fill", "fill-color", [
    "case", ["==", ["typeof", ["feature-state", "v"]], "number"], paint, NO_DATA,
  ]);
  const noData = [];
  for (const iso3 of Object.keys(state.names)) {
    const v = country(entity(iso3)) ? mapValue(entity(iso3)) : null;
    map.setFeatureState({ source: "countries", id: iso3 }, { v });
    if (v == null) noData.push(iso3);
  }
  map.setFilter("atlas-nodata", ["in", ["get", "iso3"], ["literal", noData]]);
  // Zoomed out, drop borders between EU members so the bloc reads as one shape.
  map.setFilter("atlas-line", state.bloc
    ? ["!", ["in", ["get", "iso3"], ["literal", state.data.meta.eu_members]]]
    : null);
  // The EU is not outlined: its members' outlines would draw every inner border again.
  map.setFilter("atlas-selected", ["in", ["get", "iso3"], ["literal", state.iso3 === EU ? [] : [state.iso3 ?? ""]]]);
}

// A row of colour boxes with a few words under each, plus "no figures".
function scaleRow(items) {
  return `<div class="scale">${items.map((s, i) => `<span class="${i === items.length - 1 ? "last" : ""}">
      <i style="background:${s.color}"></i><em>${s.label}</em></span>`).join("")}
    <span class="gap"></span><span class="nodata"><i class="hatch"></i><em>no data</em></span></div>`;
}

function seasonScale() {
  return scaleRow(SEASONS.map((s, i) => ({ color: s.color, label: SEASON_SHORT[i] })));
}

// The key sits right under the food buttons: what the map shows, then what the colours mean.
function renderLegend() {
  const el = document.getElementById("legend");
  if (state.level === "trade") {
    const [title, body] = tradeLegend();
    el.innerHTML = `<p class="title">${title}</p>${body}`;
    return;
  }
  // Zoomed out, the EU is one shape; the title says so in three words.
  const bloc = state.bloc ? ` <span class="bloc" title="Zoom in to see each member">(EU as one)</span>` : "";
  if (state.level === "table") {
    const { colors, ticks } = SCALES[tableIndicator()] ?? SCALES.ssr;
    el.innerHTML = `<p class="title"><b>${tableIndicator().toUpperCase()}</b>, ${tableBasis()}${bloc}</p>
      <div class="grad" style="background: linear-gradient(90deg, ${colors.join(",")})"></div>
      <div class="ticks">${ticks.map((t) => `<span>${t}</span>`).join("")}</div>`;
    return;
  }
  el.innerHTML = `<p class="title">How long <b>its own ${food()}</b> would last, in months${bloc}</p>${seasonScale()}`;
}

// The food buttons belong to the map: they change what it shows. Each choice keeps the country
// and the level, so switching from coffee imports to meat imports is a single tap.
function renderControls() {
  const foods = document.getElementById("foods");
  foods.innerHTML = state.data.groups.map((g, i) => `
    ${i === 1 ? `<span class="sep" aria-hidden="true"></span>` : ""}
    <button type="button" data-food="${g.key}" title="${g.label}" class="${g.key === "all" ? "all" : ""}"
      aria-pressed="${g.key === state.group}">${foodIcon(g.key)}<span>${SHORT[g.key] ?? g.label}</span></button>`).join("");
  for (const b of foods.querySelectorAll("[data-food]")) b.onclick = () => chooseFood(b.dataset.food);
  foods.querySelector('[aria-pressed="true"]')?.scrollIntoView({ block: "nearest", inline: "nearest" });
}

function chooseFood(group) {
  if (!state.iso3 || !country(state.iso3) && state.level !== "trade") {
    state.group = group; // no country yet: only the map changes
    render();
    return;
  }
  let level = state.level;
  if (["country", "foods", "food", "intro", "about"].includes(level)) level = group === "all" ? "country" : "food";
  if (level === "used" && group === "all") level = "country";
  location.hash = hashFor({ iso3: state.iso3, group, level, flow: state.flow });
}

function renderCrumbs() {
  const el = document.getElementById("crumbs");
  if (state.level === "intro") { el.innerHTML = ""; return; }
  const trail = [["World", "#"]];
  if (state.iso3) {
    trail.push([nameOf(state.iso3), link({ level: "country", group: "all" })]);
    if (["foods", "food"].includes(state.level)) {
      trail.push(["Food by food", link({ level: "foods", group: "all" })]);
    }
    if (state.group !== "all" && country(state.iso3)) trail.push([groupInfo().label, link({ level: "food" })]);
  }
  if (["sources", "table", "about"].includes(state.level)) {
    trail.push(["How do we know?", state.iso3 ? link({ level: "sources" }) : "#about"]);
  }
  if (state.level === "table") trail.push(["All the numbers", link({ level: "table" })]);
  if (state.level === "trade") trail.push([state.flow === "imports" ? "Buys" : "Sells", link({ level: "trade" })]);
  if (state.level === "used") trail.push(["Uses", link({ level: "used" })]);
  const up = trail[trail.length - 2][1];
  el.innerHTML = `
    <a class="back" href="${up}" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d="m15 5-7 7 7 7" /></svg></a>
    <ol>${trail.map(([t, h], i) => i === trail.length - 1
      ? `<li aria-current="page">${t}</li>` : `<li><a href="${h}">${t}</a></li>`).join("")}</ol>`;
}

function renderFoot() {
  const m = state.data.meta;
  const el = document.getElementById("foot");
  const here = (level) => (state.level === level ? ` aria-current="page"` : "");
  const tools = state.iso3 && country(state.iso3)
    ? `<div class="tools"><a href="${link({ level: "sources" })}"${here("sources")}>How do we know?</a>
       <a href="${link({ level: "table" })}"${here("table")}>All the numbers</a></div>`
    : `<div class="tools"><a href="#about"${here("about")}>How do we know?</a></div>`;
  if (state.level === "trade") {
    const t = state.data.meta.sources.fao_tm;
    el.innerHTML = `${tools}Trade figures: <a href="${t.url}" target="_blank"
      rel="noopener">FAO ${t.title}</a>, ${(state.trade?.meta.years ?? m.years).replace("-", "–")} averages.
      Licence: <a href="${t.licence_url}" target="_blank" rel="noopener">${t.licence}</a>.`;
    return;
  }
  el.innerHTML = `${tools}Figures: UN Food and Agriculture Organization (FAO), ${m.years.replace("-", "–")} averages.`;
}

// Clickable rows (foods, rankings, examples) navigate; selects in the table level re-render.
function wire(el) {
  for (const b of el.querySelectorAll("[data-go]")) {
    b.onclick = () => { location.hash = b.dataset.go; };
  }
  for (const b of el.querySelectorAll("[data-grown]")) {
    b.onclick = () => { state.grown = b.dataset.grown === "1"; render(); fitTrade(); };
  }
  const ind = el.querySelector("#indicator");
  if (ind) ind.onchange = () => { state.indicator = ind.value; render(); };
  const basis = el.querySelector("#basis");
  if (basis) basis.onchange = () => { state.basis = basis.value; render(); };
}

// ------------------------------------------------------------------------------------------------
// views

function viewIntro() {
  const own = readersCountry();
  return `
    <h1 class="hero">Could your country feed itself?</h1>
    <p class="lede">How long its own food would last, if it bought nothing from abroad.</p>
    ${own ? `<button type="button" class="primary" data-go="#${own}">
      <span>Start with ${nameOf(own)}</span>${CHEVRON}</button>` : ""}
    <div class="chips">${EXAMPLES.filter((id) => country(id) && id !== own)
      .concat(country(EU) ? [EU] : [])
      .map((id) => `<button type="button" data-go="#${id}">${id === EU ? "European Union" : nameOf(id)}</button>`)
      .join("")}</div>`;
}

// Links to the next page, as cards: a title and a hint of what is behind it.
function explore(items) {
  const rows = items.filter(Boolean);
  if (!rows.length) return "";
  return `<ul class="explore">${rows.map((r) => `
    <li><a href="${r.href}"><span class="t">${r.t}</span>${r.s ? `<span class="s">${r.s}</span>` : ""}${CHEVRON}</a></li>`)
    .join("")}</ul>`;
}

// No food balance (Japan, Singapore): say so, but trade records may still show who it buys from.
function viewNoData() {
  const id = state.iso3;
  return `
    <h2>${nameOf(id)}</h2>
    <p class="lead-none">No food balance from FAO.</p>
    ${state.trade?.countries[id] ? flowCard(id, "all") : (loadTrade(), "")}`;
}

// For EU members: the EU as a whole, one row to compare and click.
function euLine(iso3, group = state.group) {
  if (!isMember(iso3)) return "";
  const v = pctFor(EU, group);
  if (v == null) return "";
  return `<a class="eurow" href="${hashFor({ iso3: EU, group, level: group === "all" ? "country" : "food" })}">
    <i style="background:${season(v).color}"></i><span>European Union</span>
    <strong>${lasts(v, { short: true })}</strong>${CHEVRON}</a>`;
}

function viewCountry() {
  const id = state.iso3;
  const v = pctFor(id, "all");
  const who = id === EU ? "the 27 EU countries" : nameOf(id);
  const wAll = country(id)?.indicators?.all?.protein?.withheld;
  const few = shortest(id);
  const foods = explore([{ href: link({ level: "foods" }), t: "Food by food",
    s: few.length ? `Runs out first: ${few.join(" and ")}` : "" }]);
  // The same top as a food's page (icon, small line, title), with the plate for all food.
  const title = `<span class="foodbadge">${foodIcon("all")}</span><p class="kicker">All food</p><h2>${nameOf(id)}</h2>`;
  if (v == null && wAll) {
    return `${title}
      <p class="lead-none">No reliable data from FAO.</p>
      ${robustWords(wAll.range, id, "protein") ? `<p>${robustWords(wAll.range, id, "protein")}</p>` : ""}
      <details class="notes"><summary>Why?</summary><p>For some foods, FAO's figures for ${nameOf(id)}
        contradict themselves, and the total changes a lot depending on how they are read.</p></details>
      ${flowCard(id)}${foods}`;
  }
  if (v == null) return `${title}<p class="lead-none">Not enough data from FAO.</p>${flowCard(id)}${foods}`;
  return `
    ${title}
    <p class="q">Food produced ${id === EU ? "in the EU" : `in ${who}`} alone would give enough protein …</p>
    <p class="answer"><a href="${link({ level: "sources", group: "all" })}" title="How do we know?">${forHowLong(v)}</a>.</p>
    ${strip(v)}
    ${euLine(id, "all")}
    ${flowCard(id)}
    ${foods}`;
}

// Level 1: the same date for every food, plus how the country compares.
function viewFoods() {
  const id = state.iso3;
  const c = country(id);
  const rows = state.data.groups
    .filter((g) => g.key !== "all")
    .map((g) => ({ g, v: pctFor(id, g.key) }))
    .filter((r) => r.v != null)
    .sort((a, b) => a.v - b.v);
  const who = id === EU ? "the EU" : c.name;
  return `
    <p class="kicker">${nameOf(id)}</p>
    <h2>Food by food</h2>
    <p class="q">Each food, produced ${id === EU ? "in the EU" : `in ${who}`} alone, would last:</p>
    <ul class="foodlist">${rows.map(({ g, v }) => `
      <li><a href="${hashFor({ iso3: id, group: g.key, level: "food" })}">
        ${foodIcon(g.key)}
        <span class="name">${g.label}</span>
        ${strip(v, { small: true })}
        <span class="when">${lasts(v, { short: true })}</span>
      </a></li>`).join("")}</ul>
    ${compareAll(id)}`;
}

// Countries ranked by the "all food" date.
function compareAll(id) {
  const rows = rankable()
    .map((r) => ({ ...r, v: pctFor(r.id, "all") }))
    .filter((r) => r.v != null)
    .sort((a, b) => b.v - a.v);
  const me = pctFor(id, "all");
  if (!rows.length || me == null) return "";
  const shorter = rows.filter((r) => r.v < me - 0.5).length;
  return `
    <h3>How does ${id === EU ? "the EU" : nameOf(id)} compare?</h3>
    <p>Its own food would last longer than in <strong>${shorter}</strong> of ${rows.length} countries.</p>
    <div class="cols">
      <div><p class="small">Runs out soonest</p>${rankList(rows.slice(-5).reverse(), (v) => lasts(v, { short: true }))}</div>
      <div><p class="small">Lasts longest</p>${rankList(rows.slice(0, 5), (v) => lasts(v, { short: true }))}</div>
    </div>`;
}

// Countries one by one; on the EU's own pages the EU takes part as one country instead of its
// members. Rankings never change with the map's zoom: a list that reshuffles while zooming confuses.
function rankable() {
  const members = state.data.meta.eu_members;
  const bloc = state.iso3 === EU;
  return Object.entries(state.data.countries)
    .filter(([id]) => (bloc ? !members.includes(id) : id !== EU))
    .map(([id, c]) => ({ id, c }));
}

function rankList(rows, fmtV) {
  return `<ol class="rank">${rows
    .map((r) => `<li><a href="#${r.id}${state.group === "all" ? "" : `/${state.group}`}">${r.c.name}</a> <strong>${fmtV(r.v)}</strong></li>`)
    .join("")}</ol>`;
}

// Level 2: one food.
function viewFood() {
  const id = state.iso3;
  const v = pctFor(id);
  const g = groupInfo();
  const who = id === EU ? "the EU" : nameOf(id);
  const w = withheld(id);
  const head = w
    ? `<p class="lead-none">No reliable data from FAO.</p>
       ${robustWords(w.range, id, food()) ? `<p>${robustWords(w.range, id, food())}</p>` : ""}
       <details class="notes"><summary>Why?</summary><p>${whyWithheld(id)} So we show no figure for
         it here, and leave ${who} out of every comparison for ${food()}.</p></details>`
    : v == null
    ? `<p class="lead-none">No data from FAO.</p>`
    : `<p class="q">${cap(food())} produced ${id === EU ? "in the EU" : `in ${who}`} alone${v < 0.5 ? ":" : " would last …"}</p>
       <p class="answer"><a href="${link({ level: "sources" })}" title="How do we know?">${forHowLong(v)}</a>.</p>
       ${strip(v)}`;
  return `
    <span class="foodbadge">${foodIcon(g.key)}</span>
    <p class="kicker">${nameOf(id)}</p>
    <h2>${g.label}</h2>
    ${head}
    ${g.plain ? `<p class="small">${g.plain}</p>` : ""}
    ${euLine(id)}
    ${w ? "" : secondOpinion(id)}
    ${flowCard(id)}
    ${w ? "" : trend(id)}
    ${compareFood(id)}`;
}

// Year by year since the first FBS year. The scale follows the data (at least a tenth of a year
// high, so noise never looks like a trend); the dashed "full year" line is drawn only when the
// values come near it, otherwise a flat line at the bottom would say nothing.
function trend(id) {
  const values = country(id)?.trend?.[state.group] ?? [];
  const yrs = state.data.meta.trend_years;
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2 || pts.every(([, v]) => v < 1)) return ""; // a flat line at zero says nothing
  const vals = pts.map(([, v]) => v);
  // Every year reads the same ("1 week"): a sentence says it better than a flat line.
  if (new Set(vals.map((v) => lasts(v, { short: true }))).size === 1) {
    return `<h3>Year by year</h3>
      <p>Every year from ${yrs[pts[0][0]]} to ${yrs[pts[pts.length - 1][0]]}: ${lasts(vals[0])}.</p>`;
  }
  const showRef = Math.max(...vals) >= 60;
  let lo = Math.min(...vals), hi = Math.max(...vals, showRef ? 100 : -Infinity);
  const span = Math.max(hi - lo, 10);
  const mid = (hi + lo) / 2;
  lo = Math.max(0, mid - span * 0.65);
  hi = lo + span * 1.3;
  const W = 320, H = 86, PT = 8, PB = 18, PL = 4, PR = 96;
  const x = (i) => PL + (i / (yrs.length - 1)) * (W - PL - PR);
  const y = (v) => PT + (1 - (v - lo) / (hi - lo)) * (H - PT - PB);
  const path = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const area = `${path}L${x(pts[pts.length - 1][0]).toFixed(1)},${H - PB}L${x(pts[0][0]).toFixed(1)},${H - PB}Z`;
  const [fi, fv] = pts[0];
  const [li, lv] = pts[pts.length - 1];
  const lowest = pts.reduce((m, p) => (p[1] < m[1] ? p : m));
  const highest = pts.reduce((m, p) => (p[1] > m[1] ? p : m));
  // Lowest and highest year, unless they read the same as the latest (a flat line).
  const said = lasts(lv, { short: true });
  const extremes = [lowest, highest].filter(([i, v]) => i !== li && lasts(v, { short: true }) !== said);
  return `
    <h3>Year by year</h3>
    <div class="spark">
      <svg viewBox="0 0 ${W} ${H}" width="100%" role="img"
        aria-label="${pts.map(([i, v]) => `${yrs[i]}: ${lasts(v, { short: true })}`).join(", ")}">
        <path d="${area}" class="area" />
        ${showRef ? `<line x1="${PL}" x2="${W - PR}" y1="${y(100)}" y2="${y(100)}" class="ref" />
          ${Math.abs(y(lv) - y(100)) > 12 ? `<text x="${W - PR + 6}" y="${y(100) + 4}" class="refl">full year</text>` : ""}` : ""}
        <path d="${path}" class="line" />
        ${pts.map(([i, v]) => `<circle cx="${x(i)}" cy="${y(v)}" r="2" class="yeardot"><title>${yrs[i]}: ${lasts(v, { short: true })}</title></circle>`).join("")}
        <circle cx="${x(li)}" cy="${y(lv)}" r="3.2" class="dot" />
        ${extremes.map(([i, v]) => `<text x="${x(i)}" y="${y(v) + (v === highest[1] ? -6 : 13)}" class="tick" text-anchor="middle">${lasts(v, { short: true })}</text>`).join("")}
        <text x="${x(fi) + 2}" y="${H - 3}" class="yr">${yrs[fi]}</text>
        <text x="${x(li)}" y="${H - 3}" class="yr" text-anchor="end">${yrs[li]}</text>
        <text x="${x(li) + 8}" y="${y(lv) + 4}" class="val">${lasts(lv, { short: true })}</text>
      </svg>
    </div>`;
}

function perPerson(id) {
  const pc = perCapita(id);
  if (!pc || pc.supply == null) return "";
  const max = Math.max(pc.production ?? 0, pc.supply ?? 0);
  // FAO's uses do not add up to what is used (pipeline/checks.py): no breakdown, no kg eaten.
  if (country(id)?.indicators?.[state.group]?.uses_withheld) {
    return `
    <h3>Per person, per year</h3>
    <div class="row"><span>Produces</span><strong>${kg(pc.production)}</strong></div>
    <div class="track">${bar(pc.production, max, "var(--accent)")}</div>
    <div class="row"><span>Uses</span><strong>${kg(pc.supply)}</strong></div>
    <div class="track">${bar(pc.supply, max, "var(--muted)")}</div>
    <p class="small">FAO's breakdown of uses for ${food()} (eaten, fed to animals, …) does not
      add up to this total: a large part is left unexplained. So we do not show it.</p>`;
  }
  const uses = USES.map((u) => ({ ...u, v: pc[u.key] ?? 0 })).filter((u) => u.v >= 0.5);
  const tenths = pc.supply > 0 ? Math.round(((pc.food ?? 0) / pc.supply) * 10) : null;
  const eaten =
    tenths == null ? ""
    : tenths >= 9 ? "Almost all of it is eaten by people."
    : tenths === 0 ? "Hardly any of it is eaten by people directly."
    : `Of every 10 kg used here, ${tenths} ${tenths === 1 ? "is" : "are"} eaten by people directly.`;
  const eur = state.data.meta.europe_avg?.[state.group]?.food_kg_pc;
  const world = state.data.meta.world_avg?.[state.group]?.food_kg_pc;
  const avgs = [eur != null ? `Europe ${kg(eur)}` : null, world != null ? `world ${kg(world)}` : null]
    .filter(Boolean).join(", ");
  const perDay = pc.food != null ? Math.round((pc.food * 1000) / 365) : null;
  const where = id === EU ? "in the EU" : `in ${nameOf(id)}`;
  const trade = id === EU
    ? `<p class="small">Trade between EU countries is not counted here, only what the EU as a whole produces and uses.</p>`
    : `<p class="small">Per person, it buys <strong>${kg(pc.imports)}</strong> abroad and sells <strong>${kg(pc.exports)}</strong>.</p>`;
  return `
    <h3>Per person, per year</h3>
    <div class="row"><span>Produces</span><strong>${kg(pc.production)}</strong></div>
    <div class="track">${bar(pc.production, max, "var(--accent)")}</div>
    <div class="row"><span>Uses</span><strong>${kg(pc.supply)}</strong></div>
    <div class="track">${uses.map((u) => bar(u.v, max, u.color)).join("")}</div>
    <ul class="uses">${uses
      .map((u) => `<li><i style="background:${u.color}"></i>${kg(u.v)} ${u.label}</li>`)
      .join("")}</ul>
    ${eaten ? `<p class="small">${eaten}</p>` : ""}
    ${perDay != null ? `<p class="small">The average person ${where} eats <strong>${kg(pc.food)}</strong> of ${food()} a year,
      about ${perDay.toLocaleString("en-GB")} g a day${avgs ? ` (averages: ${avgs})` : ""}.</p>` : ""}
    ${trade}`;
}

// What a food is used for once it is in the country (the "Used" row of the balance card).
function viewUsed() {
  const id = state.iso3;
  return `
    <span class="foodbadge">${foodIcon(state.group)}</span>
    <p class="kicker">${kickerFor(id)}</p>
    <h2>What it is used for</h2>
    ${flowCard(id)}
    ${perPerson(id)}`;
}

// Biggest surplus and shortfall per person for one food (produced minus used, kg/person/year).
function compareFood(id) {
  const rows = rankable()
    .map((r) => {
      const pc = perCapita(r.id);
      return { ...r, v: pc?.production != null && pc?.supply != null ? pc.production - pc.supply : null };
    })
    .filter((r) => r.v != null)
    .sort((a, b) => b.v - a.v);
  if (rows.length < 10) return "";
  const signed = (v) => `${v > 0 ? "+" : "−"}${kg(Math.abs(v))}`;
  return `
    <h3>Who has ${food()} to spare?</h3>
    <p class="small">Produced minus used, per person a year</p>
    <div class="cols">
      <div><p class="small">Most to spare</p>${rankList(rows.slice(0, 5), signed)}</div>
      <div><p class="small">Most missing</p>${rankList(rows.slice(-5).reverse(), signed)}</div>
    </div>`;
}

// Level 3: the receipt. Every figure behind the date, the sum, and how to look it up at FAO.
// Dairy for EU countries comes from the EU's own balance sheets instead of FAO (pipeline/jrc.py).
function fromJrc(id, group = state.group) {
  return country(id)?.indicators?.[group]?.source === "jrc_bal";
}

function viewSources() {
  const id = state.iso3;
  const g = groupInfo();
  const v = pctFor(id);
  const jrc = fromJrc(id);
  return `
    <p class="kicker">${kickerFor(id)}</p>
    <h2>How do we know?</h2>
    ${jrc ? aboutJrc(id) : aboutFao()}
    ${jrcItems(id)}
    ${state.group === "all" ? receiptAll(id, v) : receiptGroup(id, v)}
    ${state.group === "all" ? "" : secondOpinion(id)}
    ${jrc ? checkJrc(id) : checkYourself(id)}
    ${caveats(id, g)}
    ${mapSource()}`;
}

function viewAbout() {
  return `
    <h2>How do we know?</h2>
    ${aboutFao()}
    <h3>The sum</h3>
    <p>For each country and food we divide what is produced there (farmed, fished or made, like wine) by what the
      country uses, then turn that share into months of the year: 85% of 12 months is about
      10 months. Choose a country to see its own figures worked out.</p>
    ${checks()}
    ${caveats(null, groupInfo("all"))}
    ${mapSource()}`;
}

// How the figures are checked (Makefile `verify`), with the count of left-out figures taken
// from the data itself.
function checks() {
  const n = Object.values(state.data.countries)
    .reduce((a, c) => a + Object.values(c.indicators ?? {}).filter((i) => i.withheld).length, 0);
  return `
    <h3>How we check the figures</h3>
    <p>Before anything goes online, the files we download are compared with FAO's own website; a
      second program, written separately from the first, works out every number again from those
      files and must agree on every number we publish; and we test that this page shows exactly those
      numbers. We also compare FAO's figures with an independent source, the US Department of
      Agriculture's, and say so where the two disagree a lot.</p>
    <p>FAO's figures for ${n} combinations of country and food contradict themselves, for example
      more sold abroad than there was. We leave those out, say so where they would appear, and show
      FAO's own lines so you can see why.</p>`;
}

function aboutJrc(id) {
  const s = state.data.meta.sources.jrc_bal;
  return `
    <p>The dairy figures for ${whoOf(id)} are built from the
      <a href="${s.url}" target="_blank" rel="noopener">${s.title}</a> of the European Commission
      (DG AGRI and the Joint Research Centre): the raw milk produced, and the trade in milk, cheese,
      butter, cream and milk powder, which the Commission converts into one unit, “milk equivalent”,
      counting trade between EU countries only once.</p>
    ${pubDairy(id)}
    <p class="aside">FAO's own dairy figures for many EU countries do not add up: they turn countries
      that sell cheese and milk powder abroad, like Germany or Denmark, into buyers, and put Ireland
      at barely self-sufficient instead of almost twice over. So for
      dairy in EU countries we use the Commission's figures; everything else comes from FAO.</p>
    <p class="small">Average of ${years().join(", ")}. Downloaded ${s.downloaded ? longDate(s.downloaded) : "–"}.
      Licence: <a href="${s.licence_url}" target="_blank" rel="noopener">${s.licence}</a>.</p>`;
}

// The Commission's own dairy ratio differs from the one its production and trade figures give.
function pubDairy(id) {
  const pub = country(id)?.indicators?.dairy?.jrc_published_ssr;
  const ours = country(id)?.indicators?.dairy?.tonnes?.ssr;
  if (pub == null || ours == null || Math.abs(pub - ours) < 2) return "";
  return `<p class="aside">The Commission's file also lists its own dairy ratio for ${whoOf(id)}:
    ${Math.round(pub)}% instead of our ${Math.round(ours)}%. It works out how much milk is used at
    home in a way the file does not explain, so we cannot check it. We show the share that follows
    from its production and trade figures, which you can add up yourself (see below).</p>`;
}

// Foods that are one item of a group and come from the Commission (tomatoes in vegetables, ...),
// with the reason in plain words (docs/methodology.md has the figures).
const JRC_WHY = {
  tomatoes: "tomato paste and sauce sold abroad were not counted back as tomatoes",
  "olive oil": "FAO's olive oil trade figures disagree with the EU's customs records",
  wine: "FAO's wine figures disagree with the EU's own statistics (for Germany, FAO counts a little over half the wine made)",
};
function jrcItems(id) {
  const parts = country(id)?.indicators?.[state.group]?.jrc_items;
  if (!parts?.length) return "";
  const s = state.data.meta.sources.jrc_bal;
  const what = parts.length > 1 ? `${parts.slice(0, -1).join(", ")} and ${parts[parts.length - 1]}` : parts[0];
  return `<p class="aside">One part is different: for ${whoOf(id)}, the figures for <strong>${what}</strong>
    come from the European Commission's <a href="${s.url}" target="_blank" rel="noopener">${s.title}</a>,
    because FAO's do not add up: ${parts.map((p) => JRC_WHY[p]).filter(Boolean).join("; ")}.
    The rest is FAO's.</p>`;
}

function checkJrc(id) {
  const s = state.data.meta.sources.jrc_bal;
  return `
    <h3>Check it yourself</h3>
    <ol class="steps">
      <li>Open the <a href="${s.url}" target="_blank" rel="noopener">EU agricultural balance sheets</a>
        and download the EU-27 file.</li>
      <li>Country: <strong>${id === EU ? "EU" : nameOf(id)}</strong>, years ${years().join(", ")}.</li>
      <li>Produced: “RAW MILK”, column “Production”.</li>
      <li>Bought and sold: for drinking milk, acidified milk, cream, buttermilk, total butter, total
        cheese, skimmed and whole milk powder and whey powder, add up the imports and exports
        “(MILK EQ.)”${id === EU ? " outside the EU (Extra-EU)" : ", both within and outside the EU"}.</li>
      <li>Used = produced + bought − sold; take the average of the years.</li>
    </ol>`;
}

function aboutFao() {
  const s = state.data.meta.sources[state.data.meta.source];
  return `
    <p>All food figures come from the <a href="${s.url}" target="_blank" rel="noopener">Food Balances</a>
      of the UN Food and Agriculture Organization (FAO). Countries report what they produce and
      trade; FAO builds the food balances from that and from its own estimates, and marks every
      figure in them as estimated or imputed. We take them as published, check them, and leave out
      figures that contradict themselves.</p>
    <p class="small">Edition used: released ${s.released ? longDate(s.released) : "–"}.
      We use the average of ${years().join(", ")}.
      Licence: <a href="${s.licence_url}" target="_blank" rel="noopener">${s.licence}</a>
      (free to reuse with credit).</p>`;
}

function receiptGroup(id, v) {
  const comp = country(id)?.indicators?.[state.group]?.components_kt ?? {};
  const el = state.data.meta.elements;
  const jrc = fromJrc(id);
  const row = (label, fao, val) => val == null ? ""
    : `<tr><td>${label}<br><small>${jrc && fao !== el.population ? "in milk equivalent (European Commission)" : `FAO: “${fao}”`}</small></td><td>${val}</td></tr>`;
  const w = withheld(id);
  if (w) {
    const raw = w.components_kt ?? {};
    return `
    <h3>FAO's figures for ${nameOf(id)}, ${food()}</h3>
    <p class="small">Per year, average of ${years().join(", ")}, exactly as FAO publishes them.</p>
    <table class="receipt">
      ${row("Produced", el.production, tonnes(raw.production))}
      ${row("Bought abroad", el.imports, tonnes(raw.imports))}
      ${row("Sold abroad", el.exports, tonnes(raw.exports))}
      ${raw.stock_variation ? row("Change in stocks", el.stock_variation, tonnes(raw.stock_variation)) : ""}
      ${row("Left for use at home", el.supply, tonnes(raw.supply))}
      ${raw.residuals ? row("Unexplained remainder", el.residuals, tonnes(raw.residuals)) : ""}
    </table>
    <h3>Why we show no figure</h3>
    <p>${whyWithheld(id)} A share worked out from these figures would not mean anything, so we
      leave ${food()} in ${whoOf(id)} out of the map and all comparisons.</p>`;
  }
  // The share is the precomputed one (`v`), so this page and the map can never disagree.
  const sum = v == null ? "" : `
    <h3>The sum</h3>
    <p class="sum">${tonnes(comp.production)} produced<br>÷ ${tonnes(comp.supply)} used<br>= <strong>${Math.round(v)}%</strong> of what is used</p>
    ${inMonths(id, v)}`;
  return `
    <h3>The figures for ${nameOf(id)}, ${food()}</h3>
    <p class="small">Per year, average of ${years().join(", ")}.</p>
    <table class="receipt">
      ${row("Produces", el.production, tonnes(comp.production))}
      ${row("Buys abroad", el.imports, tonnes(comp.imports))}
      ${row("Sells abroad", el.exports, tonnes(comp.exports))}
      ${row("Uses", el.supply, tonnes(comp.supply))}
      ${row("Population", el.population, people(country(id)?.population_k))}
    </table>
    ${sum}`;
}

// From the share to the months on the front page, and the same share as a date.
function inMonths(id, v) {
  if (v >= 99.5) {
    return `<p>That is at least a whole year's worth${v > 104 ? `: ${lasts(v)}` : ""}.</p>`;
  }
  const whose = id === EU ? "the EU's" : `${nameOf(id)}'s`;
  return `
    <p>${Math.round(v)}% of 12 months is ${months(v).toFixed(1)} months, so ${lasts(v)}.</p>
    <p class="aside">Put as a date: if ${whose} own ${food()} were eaten from 1 January onwards,
      it would run out on <strong>${lastDay(v)}</strong>.</p>`;
}

function receiptAll(id, v) {
  const p = country(id)?.indicators?.all?.protein;
  if (v == null && p?.withheld) {
    const r = p.withheld.range;
    return `
    <h3>Why we show no figure for ${nameOf(id)}</h3>
    <p>For some foods, FAO's figures contradict themselves: more is sold abroad or eaten than there
      was. Leaving those foods out gives ${r ? `${Math.round(r[0])}%` : "one figure"}; counting them with at
      least what FAO says people eat gives ${r?.[1] != null ? `${Math.round(r[1])}%` : "another"}. The two
      are too far apart to show either as the answer. ${robustWords(r, id, "protein")}</p>`;
  }
  if (v == null) return "";
  return `
    <h3>The sum for ${nameOf(id)}</h3>
    <p>“All food” cannot be added up in tonnes: a tonne of lettuce is not a tonne of cheese. So we
      count protein, the part of food that is hardest to replace. People ${id === EU ? "in the EU" : `in ${nameOf(id)}`}
      get about <strong>${Math.round(p?.g_per_day ?? 0)} g</strong> of protein a day.</p>
    ${country(id)?.indicators?.all?.n_withheld ? `<p class="aside">${country(id).indicators.all.n_withheld}
      ${country(id).indicators.all.n_withheld === 1 ? "food is" : "foods are"} left out because FAO's figures for
      ${country(id).indicators.all.n_withheld === 1 ? "it contradict" : "them contradict"} themselves (more sold or eaten
      than there was). Their protein still counts in the daily total.</p>` : ""}
    <p>For each of the ${country(id)?.indicators?.all?.n_foods ?? "–"} foods that provide protein ${id === EU ? "in the EU" : `in ${nameOf(id)}`} we take what is produced at home divided by what is used, and
      weigh it by how much of that protein the food provides. A surplus of one food can make up for
      a shortage of another: wheat or meat can stand in for imported soy or fish. Together that
      gives <strong>${Math.round(v)}%</strong>.</p>
    ${inMonths(id, v)}
    ${menuFor(id) != null ? `<h3>Keeping today's menu</h3>
    <p>If no food may stand in for another (each food counts at most 100%), it is
      <strong>${Math.round(menuFor(id))}%</strong>: ${forHowLong(menuFor(id))}. That is the stricter
      question of eating exactly as today.</p>` : ""}
    <p class="small">Food by food, with tonnes for each, is on the
      <a href="${link({ level: "foods", group: "all" })}">food-by-food page</a>.</p>`;
}

function checkYourself(id) {
  const s = state.data.meta.sources[state.data.meta.source];
  const el = state.data.meta.elements;
  const g = groupInfo();
  const items = state.group === "all"
    ? "all items"
    : `${g.items.map((i) => `“${i}”`).join(", ")}, then add them up`;
  const elements = state.group === "all"
    ? `“${el.production}”, “${el.supply}” and “Protein supply quantity (g/capita/day)”`
    : `“${el.production}” and “${el.supply}”`;
  return `
    <h3>Check it yourself</h3>
    <ol class="steps">
      <li>Open <a href="${s.url}" target="_blank" rel="noopener">FAOSTAT Food Balances</a>.</li>
      <li>Countries: <strong>${id === EU ? "European Union (27)" : nameOf(id)}</strong>
        <span class="small">(FAO sometimes uses the longer official name).</span></li>
      <li>Elements: ${elements}.</li>
      <li>Items: ${items}.</li>
      <li>Years: ${years().join(", ")}, then take the average.</li>
    </ol>
    <p class="small">Or download the whole table:
      <a href="${s.file_url}">FAO data file</a> (zip, ${s.size_mb ? `about ${s.size_mb} MB` : "large"}).</p>
    ${id === EU ? `<p class="aside">Our EU figures differ from FAO's own “European Union (27)” row on purpose.
      FAO adds up the member countries, but they report buying much more from each other than they
      report selling to each other${dairyGap()}, so the EU seems
      to use more than it has. We count only the EU's trade with the rest of the world, using FAO's
      trade records to tell the two apart. Production is the same in both.</p>` : ""}`;
}

// "(for dairy, 99 against 59 million tonnes a year)", from meta.claims (export.eu_intra_dairy).
function dairyGap() {
  const d = state.data.meta.claims?.eu_intra_dairy_mt;
  return d ? ` (for dairy, ${d.imports} against ${d.exports} million tonnes of milk a year)` : "";
}

function caveats(id, g) {
  return `
    <h3>What this leaves out</h3>
    <ul class="caveats">
      <li>It is a thought experiment. It treats a year's harvest as one big store, although fresh
        food cannot be kept all year.</li>
      <li>It assumes people keep eating the same mix of foods.</li>
      ${g.plain ? `<li>${g.plain}</li>` : ""}
      ${id === EU ? `<li>For the EU, trade between member countries is left out: only what the EU as a whole produces and uses counts.</li>` : ""}
      ${id && isMember(id) ? `<li>Food it buys from other EU countries counts as buying abroad.</li>` : ""}
    </ul>`;
}

function mapSource() {
  const s = state.data.meta.sources.gisco_countries;
  if (!s) return "";
  return `
    <h3>The map</h3>
    <p class="small">Borders: <a href="${s.url}" target="_blank" rel="noopener">${s.publisher}, ${s.title}</a>.
      Licence: <a href="${s.licence_url}" target="_blank" rel="noopener">${s.licence}</a>.
      Typeface, also on the map: Atkinson Hyperlegible Next, Braille Institute
      (<a href="fonts/OFL.txt" target="_blank" rel="noopener">SIL Open Font License</a>).</p>`;
}

// Level 4: everything, in the vocabulary of the methodology (SSR, IDR, tonnes, kcal).
function viewTable() {
  const id = state.iso3;
  const c = country(id);
  const g = groupInfo();
  const isAll = state.group === "all";
  return `
    <p class="kicker">${kickerFor(id)}</p>
    <h2>All the numbers</h2>
    <div class="controls">
      <label>Indicator
        <select id="indicator">
          <option value="ssr" ${state.indicator === "ssr" ? "selected" : ""}>${isAll ? "Coverage (capped SSR)" : "Self-sufficiency ratio (SSR)"}</option>
          ${isAll ? "" : `<option value="idr" ${state.indicator === "idr" ? "selected" : ""}>Import dependency ratio (IDR)</option>`}
        </select>
      </label>
      <label>Basis
        <select id="basis">
          <option value="tonnes" ${state.basis === "tonnes" ? "selected" : ""}>${isAll ? "Protein" : "Tonnes"}</option>
          <option value="kcal" ${state.basis === "kcal" ? "selected" : ""}>Calories</option>
        </select>
      </label>
    </div>
    <p class="small">The map now shows this indicator.</p>
    ${expertDetail(id)}
    ${g.notes ? `<p class="note">${g.notes}</p>` : ""}
    ${c.notes ? `<p class="note">Note: ${c.notes}</p>` : ""}`;
}

function expertDetail(id) {
  const c = country(id);
  if (state.group === "all") {
    const a = c.indicators.all ?? {};
    return `
      <div class="big">${fmt(valueFor(id))}<small>coverage, ${tableBasis()}</small></div>
      <table>
        <tr><td>Protein: coverage (capped) / SSR</td><td>${fmt(a.protein?.share)} / ${fmt(a.protein?.ssr)}</td></tr>
        <tr><td>Calories: coverage (capped) / SSR</td><td>${fmt(a.kcal?.share)} / ${fmt(a.kcal?.ssr)}</td></tr>
        <tr><td>Protein supply</td><td>${a.protein?.g_per_day ?? "–"} g/cap/day</td></tr>
        <tr><td>Food supply</td><td>${a.kcal?.per_day ?? "–"} kcal/cap/day</td></tr>
        <tr><td>Population</td><td>${pop(c)}</td></tr>
      </table>
      <p class="note">Coverage = Σ wᵢ·min(SSRᵢ, 100) / Σ wᵢ over FBS commodities, w = protein or kcal
        per capita. SSR = same without the cap.</p>`;
  }
  const g = c.indicators[state.group] ?? {};
  const t = g.tonnes ?? {};
  const k = g.kcal ?? {};
  const comp = g.components_kt ?? {};
  if (!state.items) loadItems();
  const items = (state.items?.[id]?.[state.group] ?? [])
    .filter((i) => i.ssr != null)
    .sort((a, b) => (b.supply_kt ?? 0) - (a.supply_kt ?? 0))
    .slice(0, 8);

  return `
    <div class="big">${fmt(valueFor(id))}<small>${tableIndicator().toUpperCase()}, ${tableBasis()}</small></div>
    <table>
      <tr><td>SSR (tonnes / kcal)</td><td>${fmt(t.ssr)} / ${fmt(k.ssr)}</td></tr>
      <tr><td>IDR (tonnes / kcal)</td><td>${fmt(t.idr)} / ${fmt(k.idr)}</td></tr>
      <tr><td>Production</td><td>${kt(comp.production)}</td></tr>
      <tr><td>Imports</td><td>${kt(comp.imports)}</td></tr>
      <tr><td>Exports</td><td>${kt(comp.exports)}</td></tr>
      <tr><td>Domestic supply</td><td>${kt(comp.supply)}</td></tr>
      <tr><td>food / feed / seed</td><td>${kt(comp.food)} / ${kt(comp.feed)} / ${kt(comp.seed)}</td></tr>
      <tr><td>processing / other uses</td><td>${kt(comp.processing)} / ${kt(comp.other_uses)}</td></tr>
      <tr><td>losses / residuals</td><td>${kt(comp.losses)} / ${kt(comp.residuals)}</td></tr>
      <tr><td>Population</td><td>${pop(c)}</td></tr>
    </table>
    ${g.withheld ? `<p class="note">${whyWithheld(id)}</p>` : ""}
    ${g.uses_withheld ? `<p class="note">Uses (food, feed, …) not shown: FAO's residuals exceed a quarter of domestic supply.</p>` : ""}
    ${(state.items?.[id]?.[state.group] ?? []).some((i) => i.flag === "jrc_group_only")
      ? `<p class="note">${FLAG_TEXT.jrc_group_only}</p>` : ""}
    ${items.length ? `<h3>Largest items</h3><table>${items
      .map((i) => `<tr><td>${i.item}</td><td>${fmt(i.ssr)}</td></tr>`)
      .join("")}</table>` : ""}
    <p class="note">SSR = production / domestic supply. IDR = imports / domestic supply.
      ${id === EU ? "EU bloc: production summed over members; imports and exports are trade with non-members only (members' FBS trade × extra-EU share from the trade matrix); supply = P + M − X − ΔS." : "National view: imports from other EU countries count as imports."}</p>
    ${t.flag || k.flag ? `<p class="note">${FLAG_TEXT[t.flag ?? k.flag] ?? `Flag: ${t.flag ?? k.flag}`}</p>` : ""}`;
}

// ------------------------------------------------------------------------------------------------
// The flow card: produced, bought, sold, used in a year. It is also the menu of a food's pages:
// each row opens the page about it, and the row of the page on screen is marked. With a food
// balance the bars form a waterfall (each starts where the sum so far ends), so produced + bought
// − sold (± storage) = used. Without one in tonnes ("all food", or no FAO balance as for Japan)
// it shows bought and sold only, from the trade records by weight as shipped.

function flowCard(id, group = state.group) {
  // A withheld balance (FAO's figures contradict themselves) gets no card: trade records by
  // weight as shipped would sit next to FAO's balance figures and disagree with them.
  if (withheld(id, group)) return "";
  const c = country(id)?.indicators?.[group]?.components_kt;
  const go = (level, flow) => hashFor({ iso3: id, group, level, flow });
  const out = id === EU ? " outside the EU" : " abroad";
  let rows, note = "";
  if (group !== "all" && c && c.supply > 0) {
    // For the EU, imports and exports are its trade with the rest of the world (compute.py), so
    // the rows add up like any country's. Fish has no trade records: then only produced and used.
    const P = c.production ?? 0, M = c.imports ?? 0, X = c.exports ?? 0, D = c.supply;
    const noTrade = c.imports == null && c.exports == null;
    const store = D - (P + M - X); // > 0: taken out of storage, < 0: put into storage
    const top = Math.max(P + M, D, P + M - X + Math.max(store, 0)) || 1;
    const pct = (x) => (Math.max(0, x) / top) * 100;
    // No trade records for fish (FAO's trade matrix leaves it out): nothing to open behind its rows.
    const tradeGo = (flow) => (group === "fish" ? null : go("trade", flow));
    rows = [
      { key: "food", cls: "prod", label: "Produces", value: P, bar: [0, pct(P)], href: go("food") },
      ...(noTrade ? [] : [
        { key: "imports", cls: "in", sign: "+", label: `Buys${out}`, value: M, bar: [pct(P), pct(M)], href: tradeGo("imports") },
        { key: "exports", cls: "out", sign: "−", label: `Sells${out}`, value: X, bar: [pct(P + M - X), pct(X)], href: tradeGo("exports") },
      ]),
      { key: "used", cls: "used", sign: "=", label: "Uses", value: D, bar: [0, pct(D)], href: go("used") },
    ];
    const notes = [];
    if (!noTrade && Math.abs(store) >= Math.max(1, 0.005 * (P + M))) {
      notes.push(`${shortTonnes(Math.abs(store))} ${store > 0 ? "taken out of" : "put into"} storage`);
    }
    if (!noTrade && group === "fish") notes.push("Trading partners: no data from FAO for fish");
    note = notes.join("<br>");
  } else {
    if (group === "fish") return "";
    if (!state.trade) { loadTrade(); return ""; } // drawn again once the trade figures are in
    const M = tradeFor(id, group, "imports")?.[0], X = tradeFor(id, group, "exports")?.[0];
    if (M == null && X == null) return "";
    const top = Math.max(M ?? 0, X ?? 0) || 1;
    rows = [
      { key: "imports", cls: "in", label: `Buys${out}`, value: (M ?? 0) / 1000, bar: [0, ((M ?? 0) / top) * 100], href: go("trade", "imports") },
      { key: "exports", cls: "out", label: `Sells${out}`, value: (X ?? 0) / 1000, bar: [0, ((X ?? 0) / top) * 100], href: go("trade", "exports") },
    ];
  }
  const here = state.level === "trade" ? state.flow : state.level === "used" ? "used" : state.level === "food" ? "food" : null;
  return `
    <nav class="sumcard wf" aria-label="Produced, bought, sold, used: a year in tonnes">${rows.map((r) => {
      const tag = r.href ? "a" : "div";
      return `
      <${tag} class="sum-row ${r.cls}"${r.href ? ` href="${r.href}"` : ""}${r.key === here ? ` aria-current="page"` : ""}>
        <span class="wf-head"><span><b>${r.sign ?? ""}</b>${r.label}</span><strong>${shortTonnes(r.value)}${r.href ? CHEVRON : ""}</strong></span>
        <span class="wf-track"><span style="left:${r.bar[0]}%;width:${r.bar[1]}%"></span></span>
      </${tag}>`;
    }).join("")}
      ${note ? `<p class="sum-note">${note}</p>` : ""}</nav>`;
}

// ------------------------------------------------------------------------------------------------
// trade: who a country buys its food from and sells it to

// Map shades for a partner's share of the selected country's trade, in percent.
const TRADE_STEPS = [
  { min: 20, color: "#1f4a6e", label: "20%+" },
  { min: 10, color: "#3d6f96", label: "10–20%" },
  { min: 5, color: "#6f9cc0", label: "5–10%" },
  { min: 2, color: "#a9c6de", label: "2–5%" },
  { min: 0, color: "#d8e5f0", label: "<2%" },
];
const HOME = "#e8b84a";
// Transit hubs: food "bought from" these countries often only arrived there by ship.
const PORTS = { NLD: "Rotterdam", BEL: "Antwerp" };
const ARCS = 5; // lines for the biggest partners only; more would turn into spaghetti

function emptyFC() {
  return { type: "FeatureCollection", features: [] };
}

let tradeLoading = null;
function loadTrade() {
  tradeLoading ??= loadJSON("data/trade.json")
    .then((d) => {
      state.trade = d;
      if (state.iso3) render();
      if (state.level === "trade") fitTrade();
    })
    .catch((e) => console.error(e));
}

// [total tonnes, [[partner, tonnes], ...]] or null.
// The flow the trade view shows: imports by seller, imports by where they were grown, or exports.
function tradeFlow() {
  return state.flow === "imports" && state.grown ? "grown" : state.flow;
}

function tradeFor(id, group = state.group, flow = tradeFlow()) {
  return state.trade?.countries[id]?.[group]?.[flow] ?? null;
}

// Partner shares in percent, largest first.
function shares(id, group = state.group, flow = tradeFlow()) {
  const t = tradeFor(id, group, flow);
  if (!t || !t[0]) return [];
  return t[1].map(([p, v]) => ({ id: p, share: (v / t[0]) * 100, tonnes: v }));
}

// Names as used inside a sentence: "the Netherlands", "the United States".
const WITH_THE = new Set(["NLD", "USA", "GBR", "ARE", "PHL", "BHS", "GMB", "MDV", "MHL", "SLB",
  "DOM", "CAF", "COD", "SYC", "COM"]);
function inText(id) {
  if (id === EU) return "the EU";
  return WITH_THE.has(id) ? `the ${nameOf(id)}` : nameOf(id);
}

function namesList(ids) {
  const n = ids.map(inText);
  return n.length > 1 ? `${n.slice(0, -1).join(", ")} and ${n[n.length - 1]}` : n[0];
}

function whoOf(id) {
  return inText(id);
}

function viewTrade() {
  const id = state.iso3;
  const g = groupInfo();
  const head = `<span class="foodbadge">${foodIcon(state.group)}</span>
    <p class="kicker">${kickerFor(id)}</p>
    <h2>${state.flow === "imports" ? `Where ${whoOf(id)} buys ${food()}` : `Where ${whoOf(id)} sells ${food()}`}</h2>
    ${flowCard(id)}`;
  if (!state.trade) { loadTrade(); return `${head}<p class="hint">Loading…</p>`; }
  if (state.group === "fish") return `${head}<p class="hint">No trade data for fish from FAO.</p>`;
  const imports = state.flow === "imports";
  const grown = imports && state.grown;
  const t = tradeFor(id);
  const rows = shares(id);
  const toggle = imports ? `
    <div class="seg sub" role="group" aria-label="Who sold it or where it was grown">
      <button type="button" data-grown="0" aria-pressed="${!grown}">Who sold it</button>
      <button type="button" data-grown="1" aria-pressed="${grown}">Where it was grown</button>
    </div>` : "";
  if (!t || !t[0] || !rows.length) {
    // No trade record is not the same as no trade: say what we have, not what we infer.
    return `${head}${toggle}<p class="hint">No ${imports ? "purchases" : "sales"} in FAO's trade records.</p>`;
  }
  // Totals from the food balance where there is one, so they match the other pages; the trade
  // records give the split by country.
  const comp = country(id)?.indicators?.[state.group]?.components_kt;
  const fbsTotal = state.group !== "all" ? comp?.[imports ? "imports" : "exports"] : null;
  const top = rows.slice(0, 8);
  const rest = Math.max(0, 100 - top.reduce((a, r) => a + r.share, 0));
  const max = top[0].share;
  const members = state.data.meta.eu_members;
  const fromEu = isMember(id) ? rows.filter((r) => members.includes(r.id)).reduce((a, r) => a + r.share, 0) : null;
  const hubs = grown ? [] : top.slice(0, 5).filter((r) => ["NLD", "BEL"].includes(r.id) && r.id !== id);
  const mirror = state.trade.meta.mirror.includes(id);
  return `
    ${head}
    ${toggle}
    <ol class="partners">${top.map((r) => `
      <li><a href="${hashFor({ iso3: r.id, group: state.group, level: "trade", flow: state.flow })}">
        <span class="name">${nameOf(r.id)}</span>
        <span class="track"><span class="bar" style="width:${(r.share / max) * 100}%"></span></span>
        <span class="pct">${r.share < 1 ? "<1" : Math.round(r.share)}%</span>
      </a></li>`).join("")}
      ${rest >= 1 ? `<li class="rest"><span class="name">Other countries</span><span></span><span class="pct">${Math.round(rest)}%</span></li>` : ""}
    </ol>
    ${fromEu != null && fromEu >= 1 ? `<p class="small">${grown ? "Grown in" : imports ? "From" : "To"} other EU countries: <strong>${Math.round(fromEu)}%</strong></p>` : ""}
    ${hubs.length && imports ? `<p class="aside">Much of what comes from ${namesList(hubs.map((r) => r.id))} only passes
      through the port of ${hubs.map((r) => PORTS[r.id]).join(" or ")}.
      <button type="button" class="linkish" data-grown="1">Where was it grown? ›</button></p>` : ""}
    <details class="notes"><summary>About these figures</summary>
    <ul class="caveats">
      ${grown ? `<li>Traced back by assuming that every country sells on an even mix of what it grows and what it buys. It is an estimate, not a shipping record.</li>
        <li>Shares are of the food as grown: processed goods such as flour or juice are counted back to the grain or fruit, as in FAO's food balances.</li>` : ""}
      ${grown ? "" : fbsTotal != null
        ? `<li>The totals come from FAO's food balances, like the rest of this site. The split by country comes from FAO's trade records, which count tonnes as shipped (a tonne of juice counts like a tonne of fruit).</li>`
        : `<li>Counted in tonnes as shipped: a tonne of juice or cheese counts the same as a tonne of fruit or milk.${state.group === "all" ? " All foods are added up by weight." : ""}</li>`}
      ${mirror ? `<li>${nameOf(id)} did not report all of its trade, so for some years we use what other countries say they sold to it or bought from it.</li>` : ""}
      <li>Fish is not included in FAO's trade figures.</li>
    </ul></details>`;
}

// "2.4 million tonnes" / "350 thousand tonnes" for the balance card and the cards' hints.
function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function shortTonnes(kt) {
  const a = Math.abs(kt);
  // From 100 thousand t on in millions, so the rows of one sum share a unit (2.4 − 1.8 = 0.6).
  if (a >= 100) return `${(kt / 1000).toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} million tonnes`;
  if (a >= 1) return `${Math.round(kt).toLocaleString("en-GB")} thousand tonnes`;
  return `${Math.round(kt * 1000).toLocaleString("en-GB")} tonnes`;
}

function tradeTooltip(iso3) {
  const id = state.iso3;
  const home = id === EU ? isMember(iso3) : iso3 === id;
  if (home) return `<strong>${nameOf(id === EU ? EU : iso3)}</strong>`;
  const r = shares(id).find((x) => x.id === iso3);
  const what = tradeFlow() === "grown"
    ? `of the ${food()} ${whoOf(id)} buys abroad was grown here`
    : state.flow === "imports"
      ? `of the ${food()} ${whoOf(id)} buys abroad`
      : `of the ${food()} ${whoOf(id)} sells abroad`;
  return `<strong>${nameOf(iso3)}</strong><br>${r ? `${r.share < 1 ? "<1" : Math.round(r.share)}% ${what}` : "little or none"}`;
}

function tradeLegend() {
  const id = state.iso3;
  const title = tradeFlow() === "grown"
    ? `Where the ${food()} ${whoOf(id)} buys was <b>grown</b>`
    : state.flow === "imports"
      ? `Where ${whoOf(id)} <b>buys</b> its ${food()}`
      : `Where ${whoOf(id)} <b>sells</b> its ${food()}`;
  const steps = [...TRADE_STEPS].reverse().map((s) => ({ color: s.color, label: s.label }));
  const body = `<div class="scale">
      <span class="home"><i style="background:${HOME}"></i><em>${nameOf(id)}</em></span><span class="gap"></span>
      ${steps.map((s, i) => `<span class="${i === steps.length - 1 ? "last" : ""}"><i style="background:${s.color}"></i><em>${s.label}</em></span>`).join("")}
      <span class="gap"></span><span class="nodata"><i style="background:${NO_DATA}"></i><em>none</em></span></div>`;
  return [title, body];
}

function paintTrade() {
  const id = state.iso3;
  const rows = shares(id);
  const byId = Object.fromEntries(rows.map((r) => [r.id, r.share]));
  const members = state.data.meta.eu_members;
  const step = ["step", ["feature-state", "v"], TRADE_STEPS[TRADE_STEPS.length - 1].color];
  [...TRADE_STEPS].reverse().slice(1).forEach((s) => step.push(s.min, s.color));
  map.setPaintProperty("atlas-fill", "fill-color", [
    "case",
    ["==", ["feature-state", "v"], -1], HOME,
    ["==", ["typeof", ["feature-state", "v"]], "number"], step,
    NO_DATA,
  ]);
  for (const iso3 of Object.keys(state.names)) {
    const home = id === EU ? members.includes(iso3) : iso3 === id;
    map.setFeatureState({ source: "countries", id: iso3 }, { v: home ? -1 : byId[iso3] ?? null });
  }
  map.setFilter("atlas-nodata", ["in", ["get", "iso3"], ["literal", []]]);
  map.setFilter("atlas-line", id === EU ? ["!", ["in", ["get", "iso3"], ["literal", members]]] : null);
  // The EU is already one yellow shape; outlining each member would draw its inner borders again.
  map.setFilter("atlas-selected", ["in", ["get", "iso3"], ["literal", id === EU ? [] : [id ?? ""]]]);

  const here = id === EU ? [10, 50] : state.centre[id];
  const features = !here ? [] : rows.slice(0, ARCS)
    .filter((r) => state.centre[r.id])
    .map((r) => {
      const there = state.centre[r.id];
      const coords = state.flow === "imports" ? arc(there, here) : arc(here, there);
      return { type: "Feature", properties: { w: Math.min(9, 1.5 + r.share / 4) },
        geometry: { type: "LineString", coordinates: coords } };
    });
  map.getSource("arcs").setData({ type: "FeatureCollection", features });
}

// A gentle curve from `a` to `b` (quadratic Bézier in lon/lat), the short way round the globe.
function arc(a, b) {
  const [x1, y1] = a;
  let [x2, y2] = b;
  if (x2 - x1 > 180) x2 -= 360;
  else if (x1 - x2 > 180) x2 += 360;
  const cx = (x1 + x2) / 2 - (y2 - y1) * 0.2;
  const cy = Math.max(-80, Math.min(80, (y1 + y2) / 2 + (x2 - x1) * 0.2));
  const pts = [];
  for (let i = 0; i <= 40; i++) {
    const t = i / 40, u = 1 - t;
    pts.push([u * u * x1 + 2 * u * t * cx + t * t * x2, u * u * y1 + 2 * u * t * cy + t * t * y2]);
  }
  return pts;
}

let itemsLoading = null;
function loadItems() {
  itemsLoading ??= loadJSON("data/items.json")
    .then((d) => { state.items = d; if (state.level === "table") render(); })
    .catch((e) => console.error(e));
}

// ------------------------------------------------------------------------------------------------
// controls

// Type a few letters, pick with a click or Enter. Matches at the start of a name come first;
// accents are ignored ("cote" finds Côte d'Ivoire).
function buildCountryPicker() {
  const input = document.getElementById("country");
  const list = document.getElementById("country-list");
  const plain = (t) => t.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLowerCase();
  const all = Object.entries(state.data.countries)
    .map(([id, c]) => ({ id, name: id === EU ? "European Union (all 27)" : c.name }))
    .map((r) => ({ ...r, key: plain(r.name) }))
    .sort((a, b) => a.name.localeCompare(b.name, "en"));
  let hits = [], at = 0;

  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); };
  const show = () => {
    const q = plain(input.value.trim());
    if (!q) { close(); return; }
    hits = [...all.filter((r) => r.key.startsWith(q)), ...all.filter((r) => !r.key.startsWith(q) && r.key.includes(q))].slice(0, 8);
    at = 0;
    list.innerHTML = hits.length
      ? hits.map((r, i) => {
        const v = pctFor(r.id, "all");
        return `<li role="option" id="opt-${r.id}" data-id="${r.id}" aria-selected="${i === at}">
          <span>${r.name}</span>${v == null ? "" : `<small>${lasts(v, { short: true })}</small>`}</li>`;
      }).join("")
      : `<li class="none">No country by that name</li>`;
    list.hidden = false;
    input.setAttribute("aria-expanded", "true");
    mark();
  };
  const mark = () => {
    list.querySelectorAll("[data-id]").forEach((li, i) => li.setAttribute("aria-selected", i === at));
    input.setAttribute("aria-activedescendant", hits[at] ? `opt-${hits[at].id}` : "");
  };
  const pick = (id) => {
    input.value = "";
    close();
    input.blur();
    const level = ["food", "trade", "sources", "table", "foods"].includes(state.level) ? state.level : "country";
    location.hash = hashFor({ iso3: id, group: level === "foods" ? "all" : state.group, level, flow: state.flow });
  };
  input.addEventListener("input", show);
  input.addEventListener("focus", show);
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && hits.length) { at = (at + 1) % hits.length; mark(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && hits.length) { at = (at - 1 + hits.length) % hits.length; mark(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[at] && !list.hidden) { pick(hits[at].id); e.preventDefault(); }
    else if (e.key === "Escape") { input.value = ""; close(); }
  });
  // mousedown, not click: it fires before the input loses focus and closes the list.
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest("[data-id]");
    if (li) { e.preventDefault(); pick(li.dataset.id); }
  });
  input.addEventListener("blur", () => setTimeout(close, 100));
}
