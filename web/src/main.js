import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// ------------------------------------------------------------------------------------------------
// state

const state = {
  group: "cereals",
  indicator: "ssr", // ssr | idr
  basis: "tonnes", // tonnes | kcal
  pinned: null, // iso3
  data: null, // ssr.json
};

const SCALES = {
  // SSR: diverging around 100 (below = net dependent, above = net exporter)
  ssr: { stops: [0, 50, 100, 150, 200], colors: ["#b84a2a", "#e8a46a", "#f2efe6", "#7fb58b", "#1e6b45"], ticks: ["0%", "100%", "200%+"] },
  // IDR: sequential
  idr: { stops: [0, 25, 50, 75, 100], colors: ["#f2efe6", "#f6d1a8", "#e89a62", "#c95f33", "#7a2a12"], ticks: ["0%", "50%", "100%"] },
};

const NO_DATA = "#d9d9d4";

// ------------------------------------------------------------------------------------------------
// map

const map = new maplibregl.Map({
  container: "map",
  style: "https://demotiles.maplibre.org/style.json",
  center: [14, 53],
  zoom: 3.3,
  minZoom: 2.5,
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

map.on("load", async () => {
  let geo, data;
  try {
    [geo, data] = await Promise.all([loadJSON("data/countries.geojson"), loadJSON("data/ssr.json")]);
  } catch (e) {
    document.getElementById("detail").innerHTML =
      `<p class="hint">No data yet. Run <code>make all</code> in the repo root to download FAOSTAT and build <code>web/public/data/</code>.</p>`;
    console.error(e);
    return;
  }
  state.data = data;

  map.addSource("countries", { type: "geojson", data: geo, promoteId: "iso3" });
  map.addLayer({
    id: "atlas-fill",
    type: "fill",
    source: "countries",
    paint: { "fill-color": NO_DATA, "fill-opacity": 0.9 },
  });
  map.addLayer({
    id: "atlas-line",
    type: "line",
    source: "countries",
    paint: { "line-color": "#ffffff", "line-width": 0.8 },
  });
  map.addLayer({
    id: "atlas-hover",
    type: "line",
    source: "countries",
    paint: { "line-color": "#1f2a24", "line-width": 2 },
    filter: ["==", "iso3", ""],
  });

  buildControls();
  render();

  map.on("mousemove", "atlas-fill", (e) => {
    const f = e.features[0];
    map.getCanvas().style.cursor = "pointer";
    map.setFilter("atlas-hover", ["==", "iso3", f.properties.iso3]);
    const v = valueFor(f.properties.iso3);
    popup
      .setLngLat(e.lngLat)
      .setHTML(`<strong>${f.properties.name}</strong><br>${fmt(v)}`)
      .addTo(map);
    if (!state.pinned) showDetail(f.properties.iso3);
  });
  map.on("mouseleave", "atlas-fill", () => {
    map.getCanvas().style.cursor = "";
    map.setFilter("atlas-hover", ["==", "iso3", state.pinned ?? ""]);
    popup.remove();
    if (!state.pinned) showDetail(null);
  });
  map.on("click", "atlas-fill", (e) => {
    const iso3 = e.features[0].properties.iso3;
    state.pinned = state.pinned === iso3 ? null : iso3;
    showDetail(state.pinned);
  });
});

// ------------------------------------------------------------------------------------------------
// data access

function valueFor(iso3) {
  const c = state.data?.countries?.[iso3];
  const ind = c?.indicators?.[state.group]?.[state.basis];
  const v = ind?.[state.indicator];
  return v == null || Number.isNaN(v) ? null : v;
}

function fmt(v) {
  return v == null ? "no data" : `${v.toFixed(0)}%`;
}

// ------------------------------------------------------------------------------------------------
// rendering

function render() {
  const { stops, colors } = SCALES[state.indicator];
  const interp = ["interpolate", ["linear"], ["coalesce", ["feature-state", "v"], -1]];
  stops.forEach((s, i) => interp.push(s, colors[i]));
  map.setPaintProperty("atlas-fill", "fill-color", [
    "case",
    ["==", ["coalesce", ["feature-state", "v"], -1], -1],
    NO_DATA,
    interp,
  ]);
  for (const iso3 of Object.keys(state.data.countries)) {
    map.setFeatureState({ source: "countries", id: iso3 }, { v: valueFor(iso3) });
  }
  renderLegend();
  document.getElementById("meta").textContent =
    `${state.data.meta.source} · ${state.data.meta.years} average · ${state.data.meta.view} view`;
  showDetail(state.pinned);
}

function renderLegend() {
  const { colors, ticks } = SCALES[state.indicator];
  const label = state.indicator === "ssr" ? "Self-sufficiency" : "Import dependency";
  document.getElementById("legend").innerHTML = `
    <div>${label} (${state.basis})</div>
    <div class="bar" style="background: linear-gradient(90deg, ${colors.join(",")})"></div>
    <div class="ticks">${ticks.map((t) => `<span>${t}</span>`).join("")}</div>`;
}

function showDetail(iso3) {
  const el = document.getElementById("detail");
  if (!iso3) {
    el.innerHTML = `<p class="hint">Hover a country for details. Click to pin.</p>`;
    return;
  }
  const c = state.data.countries[iso3];
  const g = c.indicators[state.group] ?? {};
  const t = g.tonnes ?? {};
  const k = g.kcal ?? {};
  const comp = g.components_kt ?? {};
  const items = (c.items?.[state.group] ?? [])
    .filter((i) => i.ssr != null)
    .sort((a, b) => (b.supply_kt ?? 0) - (a.supply_kt ?? 0))
    .slice(0, 8);
  const groupLabel = state.data.groups.find((x) => x.key === state.group)?.label ?? state.group;

  el.innerHTML = `
    <h2>${c.name} <small style="color:var(--muted);font-weight:400">· ${groupLabel}</small></h2>
    <div class="big">${fmt(valueFor(iso3))}<small>${state.indicator.toUpperCase()}, ${state.basis}</small></div>
    <table>
      <tr><td>SSR (tonnes / kcal)</td><td>${fmt(t.ssr)} / ${fmt(k.ssr)}</td></tr>
      <tr><td>IDR (tonnes / kcal)</td><td>${fmt(t.idr)} / ${fmt(k.idr)}</td></tr>
      <tr><td>Production</td><td>${kt(comp.production)}</td></tr>
      <tr><td>Imports</td><td>${kt(comp.imports)}</td></tr>
      <tr><td>Exports</td><td>${kt(comp.exports)}</td></tr>
      <tr><td>Domestic supply</td><td>${kt(comp.supply)}</td></tr>
    </table>
    ${items.length ? `<table style="margin-top:8px">${items
      .map((i) => `<tr><td>${i.item}</td><td>${fmt(i.ssr)}</td></tr>`)
      .join("")}</table>` : ""}
    ${c.notes ? `<p class="note">⚠ ${c.notes}</p>` : ""}
    ${t.flag || k.flag ? `<p class="note">Flag: ${t.flag ?? k.flag}</p>` : ""}`;
}

function kt(v) {
  return v == null ? "–" : `${Math.round(v).toLocaleString()} kt`;
}

// ------------------------------------------------------------------------------------------------
// controls

function buildControls() {
  const sel = document.getElementById("group");
  sel.innerHTML = state.data.groups
    .map((g) => `<option value="${g.key}">${g.label}</option>`)
    .join("");
  sel.value = state.group;
  sel.onchange = () => { state.group = sel.value; render(); };

  const ind = document.getElementById("indicator");
  ind.value = state.indicator;
  ind.onchange = () => { state.indicator = ind.value; render(); };

  const basis = document.getElementById("basis");
  basis.value = state.basis;
  basis.onchange = () => { state.basis = basis.value; render(); };
}
