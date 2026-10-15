import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// ------------------------------------------------------------------------------------------------
// state

const state = {
  mode: "simple", // simple | expert
  group: "cereals",
  indicator: "ssr", // ssr | idr (expert only; simple mode is always SSR in tonnes)
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
  renderSources();
  render();

  map.on("mousemove", "atlas-fill", (e) => {
    const f = e.features[0];
    map.getCanvas().style.cursor = "pointer";
    map.setFilter("atlas-hover", ["==", "iso3", f.properties.iso3]);
    const text = state.mode === "simple" ? simpleSentence(f.properties.iso3) : fmt(valueFor(f.properties.iso3));
    popup
      .setLngLat(e.lngLat)
      .setHTML(`<strong>${f.properties.name}</strong><br>${text}`)
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

// Simple mode always maps SSR on a tonnes basis: "how much of what it uses does it grow?"
function mapIndicator() {
  return state.mode === "simple" ? "ssr" : state.indicator;
}

function mapBasis() {
  return state.mode === "simple" ? "tonnes" : state.basis;
}

function valueFor(iso3, indicator = mapIndicator(), basis = mapBasis()) {
  const c = state.data?.countries?.[iso3];
  const ind = c?.indicators?.[state.group]?.[basis];
  const v = ind?.[indicator];
  return v == null || Number.isNaN(v) ? null : v;
}

function fmt(v) {
  return v == null ? "no data" : `${v.toFixed(0)}%`;
}

function groupInfo() {
  return state.data.groups.find((x) => x.key === state.group) ?? { label: state.group };
}

function food() {
  return groupInfo().label.toLowerCase();
}

// ------------------------------------------------------------------------------------------------
// plain-language text (simple mode)

function simpleSentence(iso3) {
  const name = state.data.countries[iso3]?.name ?? iso3;
  const ssr = valueFor(iso3, "ssr", "tonnes");
  if (ssr == null) return `No reliable figures for ${food()} in ${name}.`;
  if (ssr < 5) return `${name} grows almost none of the ${food()} it uses.`;
  if (ssr < 90) return `${name} grows only ${Math.round(ssr)}% of the ${food()} it uses.`;
  if (ssr <= 110) return `${name} grows about as much ${food()} as it uses.`;
  if (ssr < 195) return `${name} grows ${Math.round(ssr - 100)}% more ${food()} than it uses.`;
  return `${name} grows ${(ssr / 100).toFixed(1)}× as much ${food()} as it uses.`;
}

function kg(v) {
  if (v == null) return "–";
  if (v > 0 && v < 1) return "<1 kg";
  return `${Math.round(v).toLocaleString()} kg`;
}

function bar(value, max, cls) {
  const w = max > 0 && value > 0 ? Math.min(100, (value / max) * 100) : 0;
  return `<span class="bar ${cls}" style="width:${w}%"></span>`;
}

function simpleDetail(iso3) {
  const c = state.data.countries[iso3];
  const pc = c.indicators[state.group]?.tonnes ? c.indicators[state.group].per_capita_kg : null;
  if (!pc || pc.supply == null) {
    return `<p>${simpleSentence(iso3)}</p>`;
  }
  // "Other" = seed, processing (e.g. biofuel, starch), losses and other non-food uses.
  const other = Math.max(0, (pc.supply ?? 0) - (pc.food ?? 0) - (pc.feed ?? 0));
  const max = Math.max(pc.production ?? 0, pc.supply ?? 0);
  const usedParts = [
    pc.food > 0 ? `${kg(pc.food)} eaten` : null,
    pc.feed > 0 ? `${kg(pc.feed)} fed to animals` : null,
    other >= 1 ? `${kg(other)} other uses (seed, processing, waste)` : null,
  ].filter(Boolean);

  return `
    <p class="lead">${simpleSentence(iso3)}</p>
    <p class="unit">Per person, per year:</p>
    <div class="row"><span>Grown here</span><strong>${kg(pc.production)}</strong></div>
    <div class="track">${bar(pc.production, max, "grown")}</div>
    <div class="row"><span>Used here</span><strong>${kg(pc.supply)}</strong></div>
    <div class="track stacked">
      ${bar(pc.food, max, "food")}${bar(pc.feed, max, "feed")}${bar(other, max, "other")}
    </div>
    ${usedParts.length ? `<p class="small">of which ${usedParts.join(", ")}</p>` : ""}
    <p class="small">Bought from abroad: <strong>${kg(pc.imports)}</strong> · Sold abroad: <strong>${kg(pc.exports)}</strong></p>`;
}

// ------------------------------------------------------------------------------------------------
// rendering

function render() {
  const { stops, colors } = SCALES[mapIndicator()];
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
  document.getElementById("expert-controls").hidden = state.mode !== "expert";
  for (const b of document.querySelectorAll(".mode button")) {
    b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode));
  }
  showDetail(state.pinned);
}

function renderLegend() {
  const { colors, ticks } = SCALES[mapIndicator()];
  let label, tickText;
  if (state.mode === "simple") {
    label = `How much of the ${food()} it uses does each country grow?`;
    tickText = ["none", "all of it", "twice that"];
  } else {
    label = `${mapIndicator() === "ssr" ? "Self-sufficiency" : "Import dependency"} (${mapBasis()})`;
    tickText = ticks;
  }
  document.getElementById("legend").innerHTML = `
    <div>${label}</div>
    <div class="bar" style="background: linear-gradient(90deg, ${colors.join(",")})"></div>
    <div class="ticks">${tickText.map((t) => `<span>${t}</span>`).join("")}</div>`;
}

function sourceLine() {
  const s = state.data.meta.sources[state.data.meta.source];
  const released = s.released ? `, released ${longDate(s.released)}` : "";
  return `Source: <a href="${s.url}" target="_blank" rel="noopener">FAO ${s.title}</a>,
    ${state.data.meta.years.replace("-", "–")} average${released}.`;
}

function showDetail(iso3) {
  const el = document.getElementById("detail");
  if (!iso3) {
    el.innerHTML = `<p class="hint">Hover a country for details. Click to pin.</p>`;
    return;
  }
  const c = state.data.countries[iso3];
  const g = groupInfo();
  const body = state.mode === "simple" ? simpleDetail(iso3) : expertDetail(iso3);
  el.innerHTML = `
    <h2>${c.name} <small>· ${g.label}</small></h2>
    ${body}
    ${g.notes && state.mode === "expert" ? `<p class="note">${g.notes}</p>` : ""}
    ${c.notes && state.mode === "expert" ? `<p class="note">⚠ ${c.notes}</p>` : ""}
    <p class="cite">${sourceLine()}</p>`;
}

function expertDetail(iso3) {
  const c = state.data.countries[iso3];
  const g = c.indicators[state.group] ?? {};
  const t = g.tonnes ?? {};
  const k = g.kcal ?? {};
  const comp = g.components_kt ?? {};
  const items = (c.items?.[state.group] ?? [])
    .filter((i) => i.ssr != null)
    .sort((a, b) => (b.supply_kt ?? 0) - (a.supply_kt ?? 0))
    .slice(0, 8);

  return `
    <div class="big">${fmt(valueFor(iso3))}<small>${mapIndicator().toUpperCase()}, ${mapBasis()}</small></div>
    <table>
      <tr><td>SSR (tonnes / kcal)</td><td>${fmt(t.ssr)} / ${fmt(k.ssr)}</td></tr>
      <tr><td>IDR (tonnes / kcal)</td><td>${fmt(t.idr)} / ${fmt(k.idr)}</td></tr>
      <tr><td>Production</td><td>${kt(comp.production)}</td></tr>
      <tr><td>Imports</td><td>${kt(comp.imports)}</td></tr>
      <tr><td>Exports</td><td>${kt(comp.exports)}</td></tr>
      <tr><td>Domestic supply</td><td>${kt(comp.supply)}</td></tr>
      <tr><td>of which food / feed</td><td>${kt(comp.food)} / ${kt(comp.feed)}</td></tr>
      <tr><td>Population</td><td>${c.population_k == null ? "–" : `${(c.population_k / 1000).toFixed(1)} m`}</td></tr>
    </table>
    ${items.length ? `<table style="margin-top:8px">${items
      .map((i) => `<tr><td>${i.item}</td><td>${fmt(i.ssr)}</td></tr>`)
      .join("")}</table>` : ""}
    <p class="note">SSR = production / domestic supply. IDR = imports / domestic supply.
      National view: imports from other EU countries count as imports.</p>
    ${t.flag || k.flag ? `<p class="note">Flag: ${t.flag ?? k.flag}</p>` : ""}`;
}

function renderSources() {
  const link = (url, text) => `<a href="${url}" target="_blank" rel="noopener">${text}</a>`;
  document.getElementById("sources").innerHTML = Object.values(state.data.meta.sources)
    .map((s) => {
      const parts = [
        `${link(s.url, s.title)} — ${s.publisher}.`,
        s.released ? `Released ${longDate(s.released)}.` : "",
        s.file_url ? link(s.file_url, "Data file") + "." : "",
        `Licence: ${link(s.licence_url, s.licence)}.`,
      ];
      return `<li>${parts.filter(Boolean).join(" ")}</li>`;
    })
    .join("");
  const m = state.data.meta;
  document.getElementById("meta").textContent =
    `Figures are ${m.years.replace("-", "–")} averages. Built ${longDate(m.generated.slice(0, 10))}.`;
}

function longDate(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric", month: "short", year: "numeric", timeZone: "UTC",
  });
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

  for (const b of document.querySelectorAll(".mode button")) {
    b.onclick = () => { state.mode = b.dataset.mode; render(); };
  }

  const ind = document.getElementById("indicator");
  ind.value = state.indicator;
  ind.onchange = () => { state.indicator = ind.value; render(); };

  const basis = document.getElementById("basis");
  basis.value = state.basis;
  basis.onchange = () => { state.basis = basis.value; render(); };
}
