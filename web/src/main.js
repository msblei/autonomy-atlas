import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { SEASONS, forHowLong, lastDay, lasts, months, strip } from "./calendar.js";

// ------------------------------------------------------------------------------------------------
// state
//
// The panel is a stack of levels; each one has its own URL hash so Back works and links can be
// shared. Every level adds detail to the one before it:
//   #               intro       pick a country
//   #DEU            country     one date: how long its own food would last
//   #DEU/foods      foods       the same date for every food
//   #DEU/cereals    food        one food: trend, per person, where the harvest goes
//   #DEU/cereals/trade          who it buys from and sells to (map: partners and arcs)
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
  centre: {}, // iso3 -> [lon, lat] of the largest polygon, where trade arcs start and end
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

// Short names for the food buttons; the full label is shown below them.
const SHORT = {
  all: "All food", potatoes_roots: "Potatoes", sugar: "Sugar", oilseeds: "Oilseeds",
  vegetable_oils: "Oils", fish: "Fish", stimulants: "Coffee, tea", wine_beer: "Wine, beer",
};
const EXAMPLES = ["DEU", "USA", "BRA", "EGY"];

// ------------------------------------------------------------------------------------------------
// map

const map = new maplibregl.Map({
  container: "map",
  style: "https://demotiles.maplibre.org/style.json",
  center: [15, 30],
  zoom: 1.5,
  minZoom: 1,
  maxZoom: 7,
  attributionControl: { compact: true },
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false });

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

// Centre of a country's largest polygon (by bounding box), so France's arcs end in France, not in
// the Atlantic between Europe and French Guiana.
function centreOf(geometry) {
  const polys = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  let best = null, bestArea = -1;
  for (const poly of polys) {
    const [w, s, e, n] = bboxOf({ coordinates: poly[0] });
    if ((e - w) * (n - s) > bestArea) { bestArea = (e - w) * (n - s); best = [(w + e) / 2, (s + n) / 2]; }
  }
  return best;
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
    state.centre[iso3] = centreOf(f.geometry);
  }
  buildCountryPicker();
  if (!location.hash) {
    const own = readersCountry();
    if (own) history.replaceState(null, "", `#${own}`);
  }
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

  // The base style colours every country and draws coastlines and equator/tropics; ours replace
  // them.
  for (const id of ["countries-fill", "countries-boundary", "crimea-fill", "coastline", "geolines", "geolines-label"]) {
    if (map.getLayer(id)) map.setLayoutProperty(id, "visibility", "none");
  }
  const labels = map.getStyle().layers.find((l) => l.type === "symbol" && l.layout?.visibility !== "none")?.id;

  map.addImage("hatch", hatch());
  map.addSource("countries", { type: "geojson", data: geo, promoteId: "iso3" });
  map.addLayer({ id: "atlas-fill", type: "fill", source: "countries", paint: { "fill-color": NO_DATA } }, labels);
  map.addLayer({
    id: "atlas-nodata", type: "fill", source: "countries",
    paint: { "fill-pattern": "hatch" }, filter: ["in", ["get", "iso3"], ["literal", []]],
  }, labels);
  map.addLayer({
    id: "atlas-line", type: "line", source: "countries",
    paint: { "line-color": "#ffffff", "line-width": 0.8 },
  }, labels);
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
  }, labels);
  map.addLayer({
    id: "atlas-hover", type: "line", source: "countries",
    paint: { "line-color": "#1f2a24", "line-width": 1.2 }, filter: ["==", ["get", "iso3"], ""],
  }, labels);
  map.addLayer({
    id: "atlas-selected", type: "line", source: "countries",
    paint: { "line-color": "#1f2a24", "line-width": 2.5 }, filter: ["==", ["get", "iso3"], ""],
  }, labels);

  state.mapReady = true;
  state.bloc = map.getZoom() < EU_ZOOM;
  paintMap();
  renderLegend();
  if (state.level === "trade") fitTrade();
  else if (state.iso3) flyTo(state.iso3);

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

// The reader's country, guessed from the browser languages (de-DE -> Germany, de -> Germany).
// An English-language browser in Berlin says en-US, so a language whose country is on another
// continent than the time zone is skipped.
function readersCountry() {
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  const continent = zone.split("/")[0];
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
  if (["sources", "table", "trade", "used"].includes(c)) return { iso3: a, group, level: c };
  return group === "all" ? { iso3: a, group, level: "country" } : { iso3: a, group, level: "food" };
}

function hashFor({ iso3, group = "all", level }) {
  if (level === "about") return "#about";
  if (!iso3 || level === "intro") return "#";
  if (level === "country") return `#${iso3}`;
  if (level === "foods") return `#${iso3}/foods`;
  if (level === "food") return `#${iso3}/${group}`;
  return `#${iso3}/${group}/${level}`;
}

function link(view) {
  return hashFor({ iso3: state.iso3, group: state.group, level: state.level, ...view });
}

function route() {
  const prev = `${state.iso3}/${state.group}/${state.level}`;
  const next = parseHash();
  // Without a country the food is not in the hash; keep the one picked for the map.
  if (!next.iso3 && next.level === "intro") next.group = state.group;
  Object.assign(state, next);
  render();
  document.getElementById("panel").scrollTop = 0;
  if (state.level === "trade" && prev !== `${state.iso3}/${state.group}/${state.level}`) fitTrade();
}

// A click on the map keeps the reader on the same level (and food) for the new country.
function select(clicked) {
  // Zoomed out, the tooltip names the EU for its members, so a click picks the EU too. The trade
  // map colours every country on its own, so there a click picks the member.
  const iso3 = state.level === "trade" ? clicked : entity(clicked);
  // Trade partners without food balances (Japan, Singapore) can still be looked at in trade view.
  const tradeOnly = state.level === "trade" && state.trade?.countries[iso3];
  const level = ["intro", "about"].includes(state.level) || (!country(iso3) && !tradeOnly)
    ? "country" : state.level;
  location.hash = hashFor({ iso3, group: level === "country" || level === "foods" ? "all" : state.group, level });
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
  const panel = document.getElementById("panel");
  const wide = window.innerWidth > 640;
  map.fitBounds([[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]], {
    padding: { left: wide ? panel.offsetWidth + 60 : 30, right: wide ? 280 : 30, top: 60,
      bottom: wide ? 60 : panel.offsetHeight + 30 },
    maxZoom: 4, duration: 900,
  });
}

function flyTo(iso3) {
  if (!state.mapReady) return; // the map flies there itself once it has loaded
  // The EU only reads as one shape when zoomed out past EU_ZOOM.
  if (iso3 === EU) { map.flyTo({ center: [10, 50], zoom: EU_ZOOM - 0.2, duration: 900 }); return; }
  const b = state.bbox[iso3];
  if (!b) return;
  // Wide or antimeridian-crossing countries (Russia, the US) would zoom out to the whole world.
  if (b[2] - b[0] > 180) return;
  const panel = document.getElementById("panel");
  const left = window.innerWidth > 640 ? panel.offsetWidth + 40 : 20;
  const bottom = window.innerWidth > 640 ? 20 : panel.offsetHeight + 20;
  map.fitBounds([[b[0], b[1]], [b[2], b[3]]], {
    padding: { left, right: 60, top: 40, bottom }, maxZoom: 4, duration: 900,
  });
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
  return `<p class="aside">Another source disagrees: ${lines.join("; ")}. The two compile their figures
    separately and do not always count the same things; we cannot tell which is right, and show FAO's,
    which covers every food.
    <a href="${s.url}" target="_blank" rel="noopener">USDA ${s.title}</a>.</p>`;
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

function tooltip(iso3) {
  if (state.level === "trade") return tradeTooltip(iso3);
  const id = entity(iso3);
  if (!country(id)) return `<strong>${nameOf(iso3)}</strong><br>No figures from FAO.`;
  const v = mapValue(id);
  const contradicts = state.group === "all"
    ? country(id)?.indicators?.all?.protein?.withheld : withheld(id);
  const text = v == null ? (contradicts ? "FAO's figures contradict themselves" : "no figures for this food")
    : state.level === "table" ? fmt(v)
    : `${state.group === "all" ? "Own food" : groupInfo().label}: ${lasts(v, { short: true })}`;
  return `<strong>${nameOf(id)}</strong><br>${text}`;
}

// ------------------------------------------------------------------------------------------------
// rendering

function render() {
  paintMap();
  renderLegend();
  renderCrumbs();
  renderControls();
  document.getElementById("country").value = country(state.iso3) ? state.iso3 : "";
  const views = { intro: viewIntro, about: viewAbout, country: viewCountry, foods: viewFoods,
    food: viewFood, trade: viewTrade, used: viewUsed, sources: viewSources, table: viewTable };
  const el = document.getElementById("view");
  const noData = state.iso3 && !country(state.iso3) && state.level !== "about"
    && !(state.level === "trade" && state.trade?.countries[state.iso3]);
  el.innerHTML = noData ? viewNoData() : views[state.level]();
  wire(el);
  renderFoot();
}

function paintMap() {
  if (!state.mapReady) return;
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
  const sel = state.iso3 === EU ? state.data.meta.eu_members : [state.iso3 ?? ""];
  map.setFilter("atlas-selected", ["in", ["get", "iso3"], ["literal", sel]]);
}

// The key is a <details> box: open on desktop, folded on phones where it would cover the map.
function renderLegend() {
  const el = document.getElementById("legend");
  state.legendOpen ??= !matchMedia("(max-width: 640px)").matches;
  const bloc = state.bloc
    ? "Zoomed out, the EU is coloured as one. Zoom in to see each country."
    : "";
  const hatchKey = `<li><i class="hatch"></i>no figures</li>`;
  let title, body;
  if (state.level === "trade") {
    [title, body] = tradeLegend();
    el.innerHTML = `<details ${state.legendOpen ? "open" : ""}><summary>${title}</summary>${body}</details>`;
    el.querySelector("details").ontoggle = (e) => { state.legendOpen = e.target.open; };
    return;
  }
  if (state.level === "table") {
    const { colors, ticks } = SCALES[tableIndicator()] ?? SCALES.ssr;
    title = `${tableIndicator().toUpperCase()}, ${tableBasis()}`;
    body = `
      <div class="grad" style="background: linear-gradient(90deg, ${colors.join(",")})"></div>
      <div class="ticks">${ticks.map((t) => `<span>${t}</span>`).join("")}</div>
      <ul>${hatchKey}</ul>`;
  } else {
    const seasons = SEASONS;
    title = state.group === "all"
      ? "If each country had only its own food, the protein would last…"
      : `If each country had only its own ${food()}, it would last…`;
    body = `<ul>${seasons.map((s) => `<li><i style="background:${s.color}"></i>${s.label}</li>`).join("")}${hatchKey}</ul>`;
  }
  el.innerHTML = `<details ${state.legendOpen ? "open" : ""}>
    <summary>${title}</summary>${body}${bloc ? `<p>${bloc}</p>` : ""}</details>`;
  el.querySelector("details").ontoggle = (e) => { state.legendOpen = e.target.open; };
}

// The one menu at the top of the panel: country, food, and what to show. Each choice keeps the
// other two, so switching from coffee imports to meat imports is a single tap.
function renderControls() {
  const foods = document.getElementById("foods");
  foods.innerHTML = state.data.groups.map((g) => `
    <button type="button" data-food="${g.key}" title="${g.label}"
      aria-pressed="${g.key === state.group}">${SHORT[g.key] ?? g.label}</button>`).join("");
  // The full name only where the button had to shorten it ("Coffee, tea" -> "Coffee, cocoa, tea").
  const label = groupInfo().label;
  document.getElementById("foodname").textContent = (SHORT[state.group] ?? label) === label ? "" : label;
  for (const b of foods.querySelectorAll("[data-food]")) b.onclick = () => chooseFood(b.dataset.food);
  renderSummary();
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
  location.hash = hashFor({ iso3: state.iso3, group, level });
}

function renderCrumbs() {
  const el = document.getElementById("crumbs");
  if (state.level === "intro") { el.innerHTML = ""; return; }
  const trail = [];
  if (state.iso3) {
    trail.push([nameOf(state.iso3), link({ level: "country", group: "all" })]);
    if (["foods", "food"].includes(state.level) || (state.group !== "all" && country(state.iso3))) {
      trail.push(["Food by food", link({ level: "foods", group: "all" })]);
    }
    if (state.group !== "all" && country(state.iso3)) trail.push([groupInfo().label, link({ level: "food" })]);
  }
  if (["sources", "table", "about"].includes(state.level)) {
    trail.push(["How do we know?", state.iso3 ? link({ level: "sources" }) : "#about"]);
  }
  if (state.level === "table") trail.push(["All the numbers", link({ level: "table" })]);
  if (state.level === "trade") trail.push(["Buys and sells", link({ level: "trade" })]);
  if (state.level === "used") trail.push(["Uses", link({ level: "used" })]);
  const up = trail.length > 1 ? trail[trail.length - 2][1] : "#";
  el.innerHTML = `
    <a class="back" href="${up}">‹ Back</a>
    <ol>${trail.map(([t, h], i) => i === trail.length - 1
      ? `<li aria-current="page">${t}</li>` : `<li><a href="${h}">${t}</a></li>`).join("")}</ol>`;
}

function renderFoot() {
  const m = state.data.meta;
  if (state.level === "trade") {
    const t = state.data.meta.sources.fao_tm;
    document.getElementById("foot").innerHTML = `Trade figures: <a href="${t.url}" target="_blank"
      rel="noopener">FAO ${t.title}</a>, ${(state.trade?.meta.years ?? m.years).replace("-", "–")} averages.
      Licence: <a href="${t.licence_url}" target="_blank" rel="noopener">${t.licence}</a>.`;
    return;
  }
  document.getElementById("foot").innerHTML = state.iso3 || state.level === "about"
    ? `Figures: UN Food and Agriculture Organization (FAO), ${m.years.replace("-", "–")} averages.`
    : `Figures: UN Food and Agriculture Organization (FAO), ${m.years.replace("-", "–")} averages.
       <a href="#about">How do we know? ›</a>`;
}

// Clickable rows (foods, rankings, examples) navigate; selects in the table level re-render.
function wire(el) {
  for (const b of el.querySelectorAll("[data-go]")) {
    b.onclick = () => { location.hash = b.dataset.go; if (b.dataset.fly) flyTo(b.dataset.fly); };
  }
  for (const b of el.querySelectorAll("[data-grown]")) {
    b.onclick = () => { state.grown = b.dataset.grown === "1"; render(); fitTrade(); };
  }
  for (const b of el.querySelectorAll("[data-flow]")) {
    b.onclick = () => {
      const changed = state.flow !== b.dataset.flow;
      state.flow = b.dataset.flow;
      if (b.tagName === "BUTTON") { render(); if (changed) fitTrade(); }
    };
  }
  const ind = el.querySelector("#indicator");
  if (ind) ind.onchange = () => { state.indicator = ind.value; render(); };
  const basis = el.querySelector("#basis");
  if (basis) basis.onchange = () => { state.basis = basis.value; render(); };
}

// ------------------------------------------------------------------------------------------------
// views

function viewIntro() {
  return `
    <p class="lead">Choose your country above, or tap it on the map.</p>
    <p>For each country we work out how long the food produced there would last its people,
      if it had to manage without buying anything from abroad, counted in months of the year.</p>
    <p class="small">For example:</p>
    <div class="chips">${EXAMPLES.filter(country)
      .map((id) => `<button type="button" data-go="#${id}" data-fly="${id}">${nameOf(id)}</button>`)
      .join("")}</div>`;
}

function viewNoData() {
  return `
    <h2>${nameOf(state.iso3)}</h2>
    <p>The UN Food and Agriculture Organization publishes no food figures for this country or
      territory, so we cannot show anything here.</p>`;
}

function euLine(iso3, group = state.group) {
  if (!isMember(iso3)) return "";
  const v = pctFor(EU, group);
  if (v == null) return "";
  const what = v < 0.5 ? `would produce practically no ${food(group)} either` : `would have enough ${forHowLong(v)}`;
  return `<p class="aside">All 27 EU countries together ${what}.
    <a href="${hashFor({ iso3: EU, group, level: group === "all" ? "country" : "food" })}">See the EU ›</a></p>`;
}

// Level 0: one date.
// Second line: the total can hide that some foods would be missing.
function menuLine(id, v) {
  const m = menuFor(id);
  const few = shortest(id);
  if (m == null || few.length === 0) return "";
  const like = few.join(" and ");
  return v >= 99.5
    ? `<p class="small">Protein is what people need most. But meals would change: ${like} would run out much sooner.</p>`
    : `<p class="small">Protein is what people need most. Some foods would run out much sooner, like ${like}.</p>`;
}

function viewCountry() {
  const id = state.iso3;
  const v = pctFor(id, "all");
  const who = id === EU ? "the 27 EU countries" : nameOf(id);
  const wAll = country(id)?.indicators?.all?.protein?.withheld;
  if (v == null && wAll) {
    return `<h2>${nameOf(id)}</h2>
      <p>For some foods, FAO's figures for ${nameOf(id)} contradict themselves, and the total changes a
        lot depending on how they are read, so we show no figure.
        ${robustWords(wAll.range, id, "protein")}</p>
      <a class="next" href="${link({ level: "foods" })}">Look food by food ›</a>`;
  }
  if (v == null) {
    return `<h2>${nameOf(id)}</h2><p>There are not enough figures for ${nameOf(id)} to work this out.</p>
      <a class="next" href="${link({ level: "foods" })}">Look food by food ›</a>`;
  }
  return `
    <h2>${nameOf(id)}</h2>
    <p class="q">If ${who} ate only food produced ${id === EU ? "in the EU" : `in ${who}`}, there would be enough protein …</p>
    <p class="answer"><a href="${link({ level: "sources", group: "all" })}" title="How do we know?">${forHowLong(v)}</a>.</p>
    ${strip(v)}
    ${menuLine(id, v)}
    ${euLine(id, "all")}
    <a class="next" href="${link({ level: "foods" })}">Which foods run out first? ›</a>`;
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
    <h2>${nameOf(id)}: food by food</h2>
    <p class="q">If ${who} used only food produced ${id === EU ? "in the EU" : `in ${who}`}, there would be enough …</p>
    <ul class="foodlist">${rows.map(({ g, v }) => `
      <li><a href="${hashFor({ iso3: id, group: g.key, level: "food" })}">
        <span class="name">${g.label}</span>
        ${strip(v, { small: true })}
        <span class="when">${lasts(v, { short: true })}</span>
      </a></li>`).join("")}</ul>
    <p class="small">Tap a food to see more.</p>
    ${compareAll(id)}`;
}

// Countries ranked by the "all food" date; zoomed out the EU takes part as one country.
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

function rankable() {
  const members = state.data.meta.eu_members;
  return Object.entries(state.data.countries)
    .filter(([id]) => (state.bloc ? !members.includes(id) : id !== EU))
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
    ? `<p>${whyWithheld(id)} So we show no figure for it here, and leave ${who} out of every
        comparison for ${food()}.</p>
       ${robustWords(w.range, id, food()) ? `<p>${robustWords(w.range, id, food())}</p>` : ""}`
    : v == null
    ? `<p>There are no figures for ${food()} in ${who}.</p>`
    : `<p class="q">If ${who} used only ${food()} produced ${id === EU ? "in the EU" : `in ${who}`}, there would be ${v < 0.5 ? "…" : "enough …"}</p>
       <p class="answer"><a href="${link({ level: "sources" })}" title="How do we know?">${forHowLong(v)}</a>.</p>
       ${strip(v)}`;
  return `
    <h2>${nameOf(id)} · ${g.label}</h2>
    ${head}
    ${g.plain ? `<p class="aside">${g.plain}</p>` : ""}
    ${w ? "" : secondOpinion(id)}
    ${euLine(id)}
    ${w ? "" : trend(id)}
    ${compareFood(id)}
    <a class="next" href="${link({ level: "sources" })}">How do we know? ›</a>`;
}

// "Was it always like this?": single years since 2010, labelled with the same short dates.
function trend(id) {
  const values = country(id)?.trend?.[state.group] ?? [];
  const yrs = state.data.meta.trend_years;
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2 || pts.every(([, v]) => v < 1)) return ""; // a flat line at zero says nothing
  const vals = pts.map(([, v]) => v);
  const lo = Math.max(0, Math.min(100, ...vals) - 10);
  const hi = Math.max(100, ...vals) + 10;
  const W = 300, H = 70, P = 8, PX = 58;
  const x = (i) => PX + (i / (yrs.length - 1)) * (W - 2 * PX);
  const y = (v) => H - P - ((v - lo) / (hi - lo)) * (H - 2 * P);
  const path = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const [fi, fv] = pts[0];
  const [li, lv] = pts[pts.length - 1];
  return `
    <h3>Was it always like this?</h3>
    <div class="spark">
      <svg viewBox="0 0 ${W} ${H + 14}" width="100%" height="${H + 14}" role="img"
        aria-label="${yrs[fi]}: ${lasts(fv)}; ${yrs[li]}: ${lasts(lv)}">
        <line x1="${PX}" x2="${W - PX}" y1="${y(100)}" y2="${y(100)}" class="ref" />
        <path d="${path}" class="line" />
        <circle cx="${x(fi)}" cy="${y(fv)}" r="3" class="dot" />
        <circle cx="${x(li)}" cy="${y(lv)}" r="3" class="dot" />
        <text x="${x(fi)}" y="${H + 12}" class="yr" text-anchor="middle">${yrs[fi]}</text>
        <text x="${x(li)}" y="${H + 12}" class="yr" text-anchor="middle">${yrs[li]}</text>
        <text x="${x(fi) - 6}" y="${y(fv) + 4}" class="val" text-anchor="end">${lasts(fv, { short: true })}</text>
        <text x="${x(li) + 6}" y="${y(lv) + 4}" class="val">${lasts(lv, { short: true })}</text>
      </svg>
    </div>
    <p class="small">One year at a time; the dashed line is the whole year. Droughts and good
      harvests can move it by weeks; the figure above is the ${state.data.meta.years.replace("-", "–")} average.</p>`;
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
    : `<p class="small">Buys abroad: <strong>${kg(pc.imports)}</strong> · Sells abroad: <strong>${kg(pc.exports)}</strong> per person.</p>`;
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
    <h2>${nameOf(id)} · ${groupInfo().label}: what it is used for</h2>
    <p>What ${whoOf(id)} uses is everything that stays in the country: eaten, fed to animals, made into other
      foods, kept as seed or lost after harvest.</p>
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
    <p class="small">Produced minus used, per person per year.</p>
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
    <h2>How do we know?</h2>
    ${jrc ? aboutJrc(id) : aboutFao()}
    ${jrcItems(id)}
    ${state.group === "all" ? receiptAll(id, v) : receiptGroup(id, v)}
    ${state.group === "all" ? "" : secondOpinion(id)}
    ${jrc ? checkJrc(id) : checkYourself(id)}
    ${caveats(id, g)}
    ${mapSource()}
    <a class="next" href="${link({ level: "table" })}">Show all the numbers ›</a>`;
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
      Background map: MapLibre demo tiles.</p>`;
}

// Level 4: everything, in the vocabulary of the methodology (SSR, IDR, tonnes, kcal).
function viewTable() {
  const id = state.iso3;
  const c = country(id);
  const g = groupInfo();
  const isAll = state.group === "all";
  return `
    <h2>${nameOf(id)} · ${g.label}</h2>
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
// balance card: produced, bought, sold, used. A summary and the navigation in one: each row opens
// the page that digs into it. Bars form a waterfall (each starts where the sum so far ends), from
// the food balance, so produced + bought − sold (± storage) = used.

function summaryRows(id) {
  const c = country(id)?.indicators?.[state.group]?.components_kt;
  const go = (level, extra = {}) => ({ hash: hashFor({ iso3: id, group: state.group, level }), ...extra });
  const prodGo = go(state.group === "all" ? "country" : "food");
  const tm = (flow) => tradeFor(id, state.group, flow);
  // A withheld balance (FAO's figures contradict themselves) gets no card: trade records by
  // weight as shipped would sit next to FAO's balance figures and disagree with them.
  if (withheld(id)) return { rows: [] };
  if (state.group === "all" || !c || !(c.supply > 0)) {
    // No single tonnes figure for "all food" (or no food balance at all, as for Japan): months for
    // own production, trade totals by weight as shipped.
    if (!state.trade) loadTrade();
    const rows = [];
    const v = pctFor(id, "all");
    if (state.group === "all" && v != null) {
      rows.push({ key: "produced", label: "Own food lasts", value: lasts(v, { short: true }), bar: [0, Math.min(v, 100)],
        title: "How long the protein produced here would last", ...prodGo });
    }
    const M = tm("imports")?.[0], X = tm("exports")?.[0];
    const top = Math.max(M ?? 0, X ?? 0) || 1;
    const t = (x) => (x == null ? (state.trade ? "–" : "…") : shortTonnes(x / 1000));
    if (state.trade ? M != null || X != null : true) {
      rows.push({ key: "imports", sign: "+", label: "Buys", value: t(M), bar: [0, ((M ?? 0) / top) * 100], ...go("trade", { flow: "imports" }) });
      rows.push({ key: "exports", sign: "−", label: "Sells", value: t(X), bar: [0, ((X ?? 0) / top) * 100], ...go("trade", { flow: "exports" }) });
    }
    return { rows };
  }
  // For the EU, imports and exports are its trade with the rest of the world (compute.py), so the
  // rows add up like any country's. Fish has no trade records: then only produced and used.
  const P = c.production ?? 0, M = c.imports ?? 0, X = c.exports ?? 0, D = c.supply;
  const noTrade = c.imports == null && c.exports == null;
  const store = D - (P + M - X); // > 0: taken out of storage, < 0: put into storage
  const showStore = !noTrade && Math.abs(store) >= Math.max(1, 0.005 * (P + M));
  const top = Math.max(P + M, D, P + M - X + Math.max(store, 0)) || 1;
  const pct = (x) => (Math.max(0, x) / top) * 100;
  const out = id === EU ? " outside the EU" : "";
  const trade = noTrade ? [] : [
    { key: "imports", sign: "+", label: `Buys${out}`, value: shortTonnes(M), bar: [pct(P), pct(M)], ...go("trade", { flow: "imports" }) },
    { key: "exports", sign: "−", label: `Sells${out}`, value: shortTonnes(X), bar: [pct(P + M - X), pct(X)], ...go("trade", { flow: "exports" }) },
  ];
  return {
    rows: [
      { key: "produced", label: "Produces", value: shortTonnes(P), bar: [0, pct(P)], ...prodGo },
      ...trade,
      { key: "used", sign: "=", label: "Uses", value: shortTonnes(D), bar: [0, pct(D)],
        title: "Eaten, fed to animals, made into other foods or lost", ...go("used") },
    ],
    note: showStore ? `${shortTonnes(Math.abs(store))} ${store > 0 ? "taken out of" : "put into"} storage` : "",
  };
}

function activeRow() {
  if (state.level === "trade") return state.flow;
  if (state.level === "used") return "used";
  if (state.level === "food" || (state.level === "country" && state.group === "all")) return "produced";
  return null;
}

function renderSummary() {
  const el = document.getElementById("summary");
  const sub = document.getElementById("sublinks");
  const id = state.iso3;
  if (!id || state.level === "about") { el.innerHTML = ""; sub.innerHTML = ""; return; }
  const { rows, note } = summaryRows(id);
  const active = activeRow();
  el.innerHTML = rows.length ? `<div class="sumcard wf">${rows.map((r) => `
    <button type="button" class="sum-row ${{ produced: "prod", imports: "in", exports: "out", used: "used" }[r.key]}"
      data-hash="${r.hash}" ${r.flow ? `data-flow="${r.flow}"` : ""} ${r.title ? `title="${r.title}"` : ""}
      aria-current="${r.key === active}">
      <span class="wf-head"><span><b>${r.sign ?? ""}</b>${r.label}</span><strong>${r.value}</strong></span>
      <span class="wf-track"><span style="left:${r.bar[0]}%;width:${r.bar[1]}%"></span></span>
    </button>`).join("")}
    ${note ? `<p class="sum-note">${note}</p>` : ""}</div>` : "";
  sub.innerHTML = country(id)
    ? `<a href="${link({ level: "sources" })}">How do we know? ›</a>
       <a href="${link({ level: "table" })}">All the numbers ›</a>`
    : "";
  for (const b of el.querySelectorAll(".sum-row")) {
    b.onclick = () => {
      if (b.dataset.flow) state.flow = b.dataset.flow;
      // Bought and Sold share a hash; switching between them only repaints.
      if (location.hash === b.dataset.hash) { render(); if (state.level === "trade") fitTrade(); }
      else location.hash = b.dataset.hash;
    };
  }
}

// ------------------------------------------------------------------------------------------------
// trade: who a country buys its food from and sells it to

// Map shades for a partner's share of the selected country's trade, in percent.
const TRADE_STEPS = [
  { min: 20, color: "#1f4a6e", label: "a fifth or more" },
  { min: 10, color: "#3d6f96", label: "10 to 20%" },
  { min: 5, color: "#6f9cc0", label: "5 to 10%" },
  { min: 2, color: "#a9c6de", label: "2 to 5%" },
  { min: 0, color: "#d8e5f0", label: "less than 2%" },
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
  const head = `<h2>${nameOf(id)} · ${g.label}, ${state.flow === "imports" ? "what it buys abroad" : "what it sells abroad"}</h2>`;
  if (!state.trade) { loadTrade(); return `${head}<p class="hint">Loading trade figures…</p>`; }
  if (state.group === "fish") {
    return `${head}<p>FAO's trade figures do not include fish and seafood, so we cannot show
      where it comes from.</p>`;
  }
  const imports = state.flow === "imports";
  const grown = imports && state.grown;
  const who = whoOf(id);
  const t = tradeFor(id);
  const rows = shares(id);
  const toggle = imports ? `
    <div class="seg two" role="group" aria-label="Who sold it or where it was grown">
      <button type="button" data-grown="0" aria-pressed="${!grown}">Bought from</button>
      <button type="button" data-grown="1" aria-pressed="${grown}">Grown in</button>
    </div>` : "";
  if (!t || !t[0] || !rows.length) {
    // No trade record is not the same as no trade: say what we have, not what we infer.
    return `${head}${toggle}<p>FAO's trade records list no ${food()} ${imports ? "bought" : "sold"}
      abroad by ${who} for ${state.trade.meta.years.replace("-", "–")}.</p>`;
  }
  // Totals from the food balance where there is one, so they match the other pages; the trade
  // records give the split by country.
  const comp = country(id)?.indicators?.[state.group]?.components_kt;
  const fbsTotal = state.group !== "all" ? comp?.[imports ? "imports" : "exports"] : null;
  const total = fbsTotal ?? t[0] / 1000;
  const top = rows.slice(0, 8);
  const rest = Math.max(0, 100 - top.reduce((a, r) => a + r.share, 0));
  const max = top[0].share;
  const members = state.data.meta.eu_members;
  const fromEu = isMember(id) ? rows.filter((r) => members.includes(r.id)).reduce((a, r) => a + r.share, 0) : null;
  const hubs = grown ? [] : top.slice(0, 5).filter((r) => ["NLD", "BEL"].includes(r.id) && r.id !== id);
  const mirror = state.trade.meta.mirror.includes(id);
  const Who = cap(who);
  return `
    ${head}
    ${toggle}
    <p class="q">${grown
      ? `Where the ${food()} ${who} buys abroad was grown, following it back through the countries that sold it on:`
      : `${Who} ${imports ? "buys" : "sells"} about <strong>${tonnes(total)}</strong> of ${food()}
        ${imports ? "from" : "to"} other countries a year. Most of it ${imports ? "comes from" : "goes to"}:`}</p>
    <ol class="partners">${top.map((r) => `
      <li><a href="${hashFor({ iso3: r.id, group: state.group, level: "trade" })}">
        <span class="name">${nameOf(r.id)}</span>
        <span class="track"><span class="bar" style="width:${(r.share / max) * 100}%"></span></span>
        <span class="pct">${r.share < 1 ? "<1" : Math.round(r.share)}%</span>
      </a></li>`).join("")}
      ${rest >= 1 ? `<li class="rest"><span class="name">Other countries</span><span></span><span class="pct">${Math.round(rest)}%</span></li>` : ""}
    </ol>
    <p class="small">On the map: the darker the blue, the bigger the share. Lines show the ${Math.min(ARCS, top.length)} biggest.
      Tap a country to see its own trade.</p>
    ${fromEu != null && fromEu >= 1 ? `<p>About <strong>${Math.round(fromEu)}%</strong> of it ${grown ? "was grown in" : imports ? "comes from" : "goes to"} other EU countries.</p>` : ""}
    ${id === EU ? `<p class="aside">Only trade with countries outside the EU counts here: what the EU as a whole buys and sells.</p>` : ""}
    ${hubs.length && imports ? `<p class="aside">${cap(namesList(hubs.map((r) => r.id)))} ${hubs.length > 1 ? "are" : "is"} often only
      where food arrives by ship: much of it was grown further away and passes through the port of
      ${hubs.map((r) => PORTS[r.id]).join(" or ")}.
      <button type="button" class="linkish" data-grown="1">See where it was grown ›</button></p>` : ""}
    <h3>Good to know</h3>
    <ul class="caveats">
      ${grown ? `<li>Traced back by assuming that every country sells on an even mix of what it grows and what it buys. It is an estimate, not a shipping record.</li>
        <li>Shares are of the food as grown: processed goods such as flour or juice are counted back to the grain or fruit, as in FAO's food balances.</li>` : ""}
      ${grown ? "" : fbsTotal != null
        ? `<li>The totals come from FAO's food balances, like the rest of this site. The split by country comes from FAO's trade records, which count tonnes as shipped (a tonne of juice counts like a tonne of fruit).</li>`
        : `<li>Counted in tonnes as shipped: a tonne of juice or cheese counts the same as a tonne of fruit or milk.${state.group === "all" ? " All foods are added up by weight." : ""}</li>`}
      ${mirror ? `<li>${nameOf(id)} did not report all of its trade, so for some years we use what other countries say they sold to it or bought from it.</li>` : ""}
      <li>Fish is not included in FAO's trade figures.</li>
    </ul>`;
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// "2.4 million t" / "350 thousand t" for the balance card.
function shortTonnes(kt) {
  const a = Math.abs(kt);
  // From 100 thousand t on in millions, so the rows of one sum share a unit (2.4 − 1.8 = 0.6).
  if (a >= 100) return `${(kt / 1000).toLocaleString("en-GB", { maximumFractionDigits: 1, minimumFractionDigits: 1 })} million t`;
  if (a >= 1) return `${Math.round(kt).toLocaleString("en-GB")} thousand t`;
  return `${Math.round(kt * 1000).toLocaleString("en-GB")} t`;
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
    ? `Where the ${food()} ${whoOf(id)} buys was grown`
    : state.flow === "imports"
      ? `Where ${whoOf(id)} buys its ${food()}`
      : `Where ${whoOf(id)} sells its ${food()}`;
  const body = `<ul>${TRADE_STEPS.map((s) => `<li><i style="background:${s.color}"></i>${s.label}</li>`).join("")}
    <li><i style="background:${HOME}"></i>${nameOf(id)}</li>
    <li><i style="background:${NO_DATA}"></i>little or none</li></ul>`;
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

function buildCountryPicker() {
  const sel = document.getElementById("country");
  const opts = Object.entries(state.data.countries)
    .map(([id, c]) => [id, c.name])
    .sort((a, b) => a[1].localeCompare(b[1], "en"));
  sel.innerHTML = `<option value="">Choose a country…</option>` +
    opts.map(([id, name]) => `<option value="${id}">${name}</option>`).join("");
  sel.onchange = () => {
    if (!sel.value) return;
    const level = ["food", "trade", "sources", "table"].includes(state.level) ? state.level : state.level === "foods" ? "foods" : "country";
    location.hash = hashFor({ iso3: sel.value, group: state.group, level });
    flyTo(sel.value);
  };
}
