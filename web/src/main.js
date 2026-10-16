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
//   #DEU/cereals/sources        how do we know: FAO figures, the sum, check-it-yourself
//   #DEU/cereals/table          all the numbers (SSR, IDR, tonnes/kcal, FAO items)
//   #about                      sources without a country

const state = {
  iso3: null,
  group: "all", // "all" = protein-weighted across every food, else a products.yaml group key
  level: "intro", // intro | country | foods | food | trade | sources | table | about
  flow: "imports", // imports | exports (trade level)
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

map.on("load", async () => {
  let geo, data;
  try {
    [geo, data] = await Promise.all([loadJSON("data/countries.geojson"), loadJSON("data/ssr.json")]);
  } catch (e) {
    document.getElementById("view").innerHTML =
      `<p class="hint">No data yet. Run <code>make all</code> in the repo root to download FAOSTAT and build <code>web/public/data/</code>.</p>`;
    console.error(e);
    return;
  }
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

  buildCountryPicker();
  state.bloc = map.getZoom() < EU_ZOOM;

  if (!location.hash) {
    const own = readersCountry();
    if (own) history.replaceState(null, "", `#${own}`);
  }
  window.addEventListener("hashchange", () => route());
  route({ fly: true });

  map.on("zoom", () => {
    const bloc = map.getZoom() < EU_ZOOM;
    if (bloc !== state.bloc) { state.bloc = bloc; paintMap(); renderLegend(); }
  });
  // Hover only shows a small label; the panel changes on a click, so it never jumps around
  // while the mouse moves.
  map.on("mousemove", "atlas-fill", (e) => {
    const iso3 = e.features[0].properties.iso3;
    map.getCanvas().style.cursor = "pointer";
    const members = entity(iso3) === EU ? state.data.meta.eu_members : [iso3];
    map.setFilter("atlas-hover", ["in", ["get", "iso3"], ["literal", members]]);
    popup.setLngLat(e.lngLat).setHTML(tooltip(iso3)).addTo(map);
  });
  map.on("mouseleave", "atlas-fill", () => {
    map.getCanvas().style.cursor = "";
    map.setFilter("atlas-hover", ["==", ["get", "iso3"], ""]);
    popup.remove();
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
  if (c === "sources" || c === "table" || c === "trade") return { iso3: a, group, level: c };
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

function route({ fly = false } = {}) {
  const prev = `${state.iso3}/${state.group}/${state.level}`;
  const prevIso3 = state.iso3;
  Object.assign(state, parseHash());
  render();
  document.getElementById("panel").scrollTop = 0;
  if (state.level === "trade" && prev !== `${state.iso3}/${state.group}/${state.level}`) fitTrade();
  else if (fly && state.iso3 && state.iso3 !== prevIso3) flyTo(state.iso3);
}

// A click on the map keeps the reader on the same level (and food) for the new country.
function select(iso3) {
  // Trade partners without food balances (Japan, Singapore) can still be looked at in trade view.
  const tradeOnly = state.level === "trade" && state.trade?.countries[iso3];
  const level = ["intro", "about"].includes(state.level) || (!country(iso3) && !tradeOnly)
    ? "country" : state.level;
  location.hash = hashFor({ iso3, group: level === "country" || level === "foods" ? "all" : state.group, level });
}

// Trade view: frame the country and its biggest partners (the ones with arcs).
function fitTrade() {
  if (!state.trade) return; // loadTrade() calls back here once the figures are in
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
  if (state.group === "all") return state.indicator === "idr" ? "idr" : "share";
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
  const text = v == null ? "no figures for this food"
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
  document.getElementById("country").value = country(state.iso3) ? state.iso3 : "";
  const views = { intro: viewIntro, about: viewAbout, country: viewCountry, foods: viewFoods,
    food: viewFood, trade: viewTrade, sources: viewSources, table: viewTable };
  const el = document.getElementById("view");
  const noData = state.iso3 && !country(state.iso3) && state.level !== "about"
    && !(state.level === "trade" && state.trade?.countries[state.iso3]);
  el.innerHTML = noData ? viewNoData() : views[state.level]();
  wire(el);
  renderFoot();
}

function paintMap() {
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
  if (state.level === "trade") trail.push(["Bought and sold", link({ level: "trade" })]);
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
  const href = state.iso3 && country(state.iso3) ? link({ level: "sources" }) : "#about";
  document.getElementById("foot").innerHTML = ["sources", "table", "about"].includes(state.level)
    ? `Figures: UN Food and Agriculture Organization (FAO), ${m.years.replace("-", "–")} averages.`
    : `Figures: UN Food and Agriculture Organization (FAO), ${m.years.replace("-", "–")} averages.
       <a href="${href}">How do we know? ›</a>`;
}

// Clickable rows (foods, rankings, examples) navigate; selects in the table level re-render.
function wire(el) {
  for (const b of el.querySelectorAll("[data-go]")) {
    b.onclick = () => { location.hash = b.dataset.go; if (b.dataset.fly) flyTo(b.dataset.fly); };
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
    <p>For each country we work out how long the food from its own farms would last its people,
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
  return `<p class="aside">All 27 EU countries together would have enough ${forHowLong(v)}.
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
  if (v == null) {
    return `<h2>${nameOf(id)}</h2><p>There are not enough figures for ${nameOf(id)} to work this out.</p>
      <a class="next" href="${link({ level: "foods" })}">Look food by food ›</a>`;
  }
  return `
    <h2>${nameOf(id)}</h2>
    <p class="q">If ${who} ate only food from ${id === EU ? "their" : "its"} own farms, there would be enough protein …</p>
    <p class="answer"><a href="${link({ level: "sources", group: "all" })}" title="How do we know?">${forHowLong(v)}</a>.</p>
    ${strip(v)}
    ${menuLine(id, v)}
    ${euLine(id, "all")}
    <a class="next" href="${link({ level: "foods" })}">Which foods run out first? ›</a>
    <a class="more" href="${link({ level: "trade", group: "all" })}">Who does ${id === EU ? "the EU" : nameOf(id)} buy food from? ›</a>`;
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
    <p class="q">If ${who} used only what ${id === EU ? "its" : "its own"} farms and fishing boats produce, there would be enough …</p>
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
  const head = v == null
    ? `<p>There are no reliable figures for ${food()} in ${who}.</p>`
    : `<p class="q">If ${who} used only ${food()} produced ${id === EU ? "in the EU" : `in ${who}`}, there would be enough …</p>
       <p class="answer"><a href="${link({ level: "sources" })}" title="How do we know?">${forHowLong(v)}</a>.</p>
       ${strip(v)}`;
  return `
    <h2>${nameOf(id)} · ${g.label}</h2>
    ${head}
    ${g.plain ? `<p class="aside">${g.plain}</p>` : ""}
    ${euLine(id)}
    ${trend(id)}
    ${perPerson(id)}
    ${tradeTeaser(id)}
    ${compareFood(id)}
    <a class="next" href="${link({ level: "sources" })}">How do we know? ›</a>`;
}

// "Was it always like this?": single years since 2010, labelled with the same short dates.
function trend(id) {
  const values = country(id)?.trend?.[state.group] ?? [];
  const yrs = state.data.meta.trend_years;
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2) return "";
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
        <text x="${PX}" y="${y(100) - 4}" class="refl">whole year</text>
        <path d="${path}" class="line" />
        <circle cx="${x(fi)}" cy="${y(fv)}" r="3" class="dot" />
        <circle cx="${x(li)}" cy="${y(lv)}" r="3" class="dot" />
        <text x="${x(fi)}" y="${H + 12}" class="yr" text-anchor="middle">${yrs[fi]}</text>
        <text x="${x(li)}" y="${H + 12}" class="yr" text-anchor="middle">${yrs[li]}</text>
        <text x="${x(fi) - 6}" y="${y(fv) + 4}" class="val" text-anchor="end">${lasts(fv, { short: true })}</text>
        <text x="${x(li) + 6}" y="${y(lv) + 4}" class="val">${lasts(lv, { short: true })}</text>
      </svg>
    </div>
    <p class="small">One year at a time. Droughts and good harvests can move it by weeks; the
      figure above is the ${state.data.meta.years.replace("-", "–")} average.</p>`;
}

function perPerson(id) {
  const pc = perCapita(id);
  if (!pc || pc.supply == null) return "";
  const max = Math.max(pc.production ?? 0, pc.supply ?? 0);
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
    : `<p class="small">Bought from abroad: <strong>${kg(pc.imports)}</strong> · Sold abroad: <strong>${kg(pc.exports)}</strong> per person.</p>`;
  return `
    <h3>Per person, per year</h3>
    <div class="row"><span>Produced here</span><strong>${kg(pc.production)}</strong></div>
    <div class="track">${bar(pc.production, max, "var(--accent)")}</div>
    <div class="row"><span>Used here</span><strong>${kg(pc.supply)}</strong></div>
    <div class="track">${uses.map((u) => bar(u.v, max, u.color)).join("")}</div>
    <ul class="uses">${uses
      .map((u) => `<li><i style="background:${u.color}"></i>${kg(u.v)} ${u.label}</li>`)
      .join("")}</ul>
    ${eaten ? `<p class="small">${eaten}</p>` : ""}
    ${perDay != null ? `<p class="small">The average person ${where} eats <strong>${kg(pc.food)}</strong> of ${food()} a year,
      about ${perDay.toLocaleString("en-GB")} g a day${avgs ? ` (averages: ${avgs})` : ""}.</p>` : ""}
    ${trade}`;
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
function viewSources() {
  const id = state.iso3;
  const g = groupInfo();
  const v = pctFor(id);
  return `
    <h2>How do we know?</h2>
    ${aboutFao()}
    ${state.group === "all" ? receiptAll(id, v) : receiptGroup(id, v)}
    ${checkYourself(id)}
    ${caveats(id, g)}
    ${mapSource()}
    <a class="next" href="${link({ level: "table" })}">Show all the numbers ›</a>`;
}

function viewAbout() {
  return `
    <h2>How do we know?</h2>
    ${aboutFao()}
    <h3>The sum</h3>
    <p>For each country and food we divide what its farms and fishing boats produce by what the
      country uses, then turn that share into months of the year: 85% of 12 months is about
      10 months. Choose a country to see its own figures worked out.</p>
    ${caveats(null, groupInfo("all"))}
    ${mapSource()}`;
}

function aboutFao() {
  const s = state.data.meta.sources[state.data.meta.source];
  return `
    <p>All food figures come from the <a href="${s.url}" target="_blank" rel="noopener">Food Balances</a>
      of the UN Food and Agriculture Organization (FAO). Every country reports what it produces,
      buys, sells and uses each year; FAO checks the figures and publishes them for free.</p>
    <p class="small">Edition used: released ${s.released ? longDate(s.released) : "–"}.
      We use the average of ${years().join(", ")}.
      Licence: <a href="${s.licence_url}" target="_blank" rel="noopener">${s.licence}</a>
      (free to reuse with credit).</p>`;
}

function receiptGroup(id, v) {
  const comp = country(id)?.indicators?.[state.group]?.components_kt ?? {};
  const el = state.data.meta.elements;
  const row = (label, fao, val) => val == null ? ""
    : `<tr><td>${label}<br><small>FAO: “${fao}”</small></td><td>${val}</td></tr>`;
  const ratio = comp.production != null && comp.supply > 0 ? (comp.production / comp.supply) * 100 : null;
  const sum = v == null || ratio == null ? "" : `
    <h3>The sum</h3>
    <p class="sum">${tonnes(comp.production)} produced<br>÷ ${tonnes(comp.supply)} used<br>= <strong>${Math.round(ratio)}%</strong> of what is used</p>
    ${inMonths(id, v)}`;
  return `
    <h3>The figures for ${nameOf(id)}, ${food()}</h3>
    <p class="small">Per year, average of ${years().join(", ")}.</p>
    <table class="receipt">
      ${row("Produced here", el.production, tonnes(comp.production))}
      ${row("Bought from abroad", el.imports, tonnes(comp.imports))}
      ${row("Sold abroad", el.exports, tonnes(comp.exports))}
      ${row("Used here", el.supply, tonnes(comp.supply))}
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
  if (v == null) return "";
  return `
    <h3>The sum for ${nameOf(id)}</h3>
    <p>“All food” cannot be added up in tonnes: a tonne of lettuce is not a tonne of cheese. So we
      count protein, the part of food that is hardest to replace. People ${id === EU ? "in the EU" : `in ${nameOf(id)}`}
      get about <strong>${Math.round(p?.g_per_day ?? 0)} g</strong> of protein a day.</p>
    <p>For each of about 85 foods we take what is produced at home divided by what is used, and
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
      <a href="${s.file_url}">FAO data file</a> (zip, about 55 MB).</p>`;
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
      ${id && isMember(id) ? `<li>Food bought from other EU countries counts as bought from abroad.</li>` : ""}
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
          <option value="idr" ${state.indicator === "idr" ? "selected" : ""}>Import dependency ratio (IDR)</option>
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
    ${c.notes ? `<p class="note">⚠ ${c.notes}</p>` : ""}`;
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
      <tr><td>IDR (tonnes / kcal)</td><td>${id === EU ? "n/a" : `${fmt(t.idr)} / ${fmt(k.idr)}`}</td></tr>
      <tr><td>Production</td><td>${kt(comp.production)}</td></tr>
      <tr><td>Imports</td><td>${kt(comp.imports)}</td></tr>
      <tr><td>Exports</td><td>${kt(comp.exports)}</td></tr>
      <tr><td>Domestic supply</td><td>${kt(comp.supply)}</td></tr>
      <tr><td>food / feed / seed</td><td>${kt(comp.food)} / ${kt(comp.feed)} / ${kt(comp.seed)}</td></tr>
      <tr><td>processing / other uses</td><td>${kt(comp.processing)} / ${kt(comp.other_uses)}</td></tr>
      <tr><td>losses / residuals</td><td>${kt(comp.losses)} / ${kt(comp.residuals)}</td></tr>
      <tr><td>Population</td><td>${pop(c)}</td></tr>
    </table>
    ${items.length ? `<h3>Largest FAO items</h3><table>${items
      .map((i) => `<tr><td>${i.item}</td><td>${fmt(i.ssr)}</td></tr>`)
      .join("")}</table>` : ""}
    <p class="note">SSR = production / domestic supply. IDR = imports / domestic supply.
      ${id === EU ? "EU bloc: members summed; intra-EU trade cancels out of supply." : "National view: imports from other EU countries count as imports."}</p>
    ${t.flag || k.flag ? `<p class="note">Flag: ${t.flag ?? k.flag}</p>` : ""}`;
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
      if (["food", "trade"].includes(state.level)) render();
      if (state.level === "trade") fitTrade();
    })
    .catch((e) => console.error(e));
}

// [total tonnes, [[partner, tonnes], ...]] or null.
function tradeFor(id, group = state.group, flow = state.flow) {
  return state.trade?.countries[id]?.[group]?.[flow] ?? null;
}

// Partner shares in percent, largest first.
function shares(id, group = state.group, flow = state.flow) {
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

// One or two sentences on the food page, linking to the trade level.
function tradeTeaser(id) {
  if (!state.trade) { loadTrade(); return ""; }
  if (state.group === "fish") return "";
  const v = pctFor(id);
  const lines = [];
  const imp = shares(id, state.group, "imports").slice(0, 3);
  if (imp.length && (v == null || v < 104)) {
    lines.push(`Most of the ${food()} ${whoOf(id)} buys abroad comes from ${namesList(imp.map((r) => r.id))}.`);
  }
  const exp = shares(id, state.group, "exports").slice(0, 3);
  if (exp.length && v != null && v >= 96) {
    lines.push(`What ${whoOf(id)} sells abroad goes mostly to ${namesList(exp.map((r) => r.id))}.`);
  }
  if (!lines.length) return "";
  const flow = v != null && v >= 104 && exp.length ? "exports" : "imports";
  return `
    <h3>Bought and sold</h3>
    <p>${lines.join(" ")}</p>
    <a class="more" href="${link({ level: "trade" })}" data-flow="${flow}">See it on the map ›</a>`;
}

function viewTrade() {
  const id = state.iso3;
  const g = groupInfo();
  const head = `<h2>${nameOf(id)} · ${g.label}</h2>
    <div class="seg" role="group" aria-label="Bought or sold">
      <button type="button" data-flow="imports" aria-pressed="${state.flow === "imports"}">Bought from abroad</button>
      <button type="button" data-flow="exports" aria-pressed="${state.flow === "exports"}">Sold abroad</button>
    </div>`;
  if (!state.trade) { loadTrade(); return `${head}<p class="hint">Loading trade figures…</p>`; }
  if (state.group === "fish") {
    return `${head}<p>FAO's trade figures do not include fish and seafood, so we cannot show
      where it comes from.</p>`;
  }
  const imports = state.flow === "imports";
  const who = whoOf(id);
  const t = tradeFor(id);
  const rows = shares(id);
  if (!t || !t[0] || !rows.length) {
    return `${head}<p>${cap(who)} ${imports ? "buys" : "sells"} almost no ${food()} abroad.</p>`;
  }
  const top = rows.slice(0, 8);
  const rest = Math.max(0, 100 - top.reduce((a, r) => a + r.share, 0));
  const max = top[0].share;
  const members = state.data.meta.eu_members;
  const fromEu = isMember(id) ? rows.filter((r) => members.includes(r.id)).reduce((a, r) => a + r.share, 0) : null;
  const hubs = top.slice(0, 5).filter((r) => ["NLD", "BEL"].includes(r.id) && r.id !== id);
  const mirror = state.trade.meta.mirror.includes(id);
  const Who = cap(who);
  return `
    ${head}
    <p class="q">${Who} ${imports ? "buys" : "sells"} about <strong>${tonnes(t[0] / 1000)}</strong> of
      ${food()} ${imports ? "from" : "to"} other countries a year. Most of it ${imports ? "comes from" : "goes to"}:</p>
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
    ${fromEu != null && fromEu >= 1 ? `<p>About <strong>${Math.round(fromEu)}%</strong> of it ${imports ? "comes from" : "goes to"} other EU countries.</p>` : ""}
    ${id === EU ? `<p class="aside">Only trade with countries outside the EU counts here: what the EU as a whole buys and sells.</p>` : ""}
    ${hubs.length && imports ? `<p class="aside">${cap(namesList(hubs.map((r) => r.id)))} ${hubs.length > 1 ? "are" : "is"} often only
      where food arrives by ship: much of it was grown further away and passes through the port of
      ${hubs.map((r) => PORTS[r.id]).join(" or ")}.</p>` : ""}
    <h3>Good to know</h3>
    <ul class="caveats">
      <li>Counted in tonnes as shipped: a tonne of juice or cheese counts the same as a tonne of fruit or milk.${state.group === "all" ? " All foods are added up by weight." : ""}</li>
      ${mirror ? `<li>${nameOf(id)} did not report all of its trade, so for some years we use what other countries say they sold to it or bought from it.</li>` : ""}
      <li>Fish is not included in FAO's trade figures.</li>
    </ul>`;
}

function cap(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function tradeTooltip(iso3) {
  const id = state.iso3;
  const home = id === EU ? isMember(iso3) : iso3 === id;
  if (home) return `<strong>${nameOf(id === EU ? EU : iso3)}</strong>`;
  const r = shares(id).find((x) => x.id === iso3);
  const what = state.flow === "imports"
    ? `of the ${food()} ${whoOf(id)} buys abroad`
    : `of the ${food()} ${whoOf(id)} sells abroad`;
  return `<strong>${nameOf(iso3)}</strong><br>${r ? `${r.share < 1 ? "<1" : Math.round(r.share)}% ${what}` : "little or none"}`;
}

function tradeLegend() {
  const id = state.iso3;
  const title = state.flow === "imports"
    ? `Where ${whoOf(id)}'s ${food()} from abroad comes from`
    : `Where ${whoOf(id)}'s ${food()} sold abroad goes`;
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
