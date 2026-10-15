import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

// ------------------------------------------------------------------------------------------------
// state

const state = {
  mode: "simple", // simple | expert
  group: "all", // "all" = protein-weighted across every food, else a products.yaml group key
  indicator: "ssr", // ssr | idr (expert only; simple mode is always SSR in tonnes)
  basis: "tonnes", // tonnes | kcal
  bloc: false, // true: EU members take the values of the EU27 bloc
  pinned: null, // iso3
  data: null, // ssr.json
};

const EU = "EU27";

const SCALES = {
  // SSR: diverging around 100 (below = net dependent, above = net exporter)
  ssr: { stops: [0, 50, 100, 150, 200], colors: ["#b84a2a", "#e8a46a", "#f2efe6", "#7fb58b", "#1e6b45"], ticks: ["0%", "100%", "200%+"] },
  // IDR: sequential
  idr: { stops: [0, 25, 50, 75, 100], colors: ["#f2efe6", "#f6d1a8", "#e89a62", "#c95f33", "#7a2a12"], ticks: ["0%", "50%", "100%"] },
  // Coverage share for "all food" (capped at 100)
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
    const id = entity(f.properties.iso3);
    const text = state.mode === "simple" ? headline(id) : fmt(valueFor(id));
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
  map.on("click", "atlas-fill", (e) => pin(e.features[0].properties.iso3));
});

function pin(iso3) {
  state.pinned = state.pinned === iso3 ? null : iso3;
  map.setFilter("atlas-hover", ["==", "iso3", state.pinned ?? ""]);
  showDetail(state.pinned);
}

// ------------------------------------------------------------------------------------------------
// data access

// With the EU toggle on, every member state shows the EU27 bloc's figures.
function entity(iso3) {
  if (state.bloc && state.data.meta.eu_members.includes(iso3) && state.data.countries[EU]) return EU;
  return iso3;
}

function country(id) {
  return state.data.countries[id];
}

function isAll() {
  return state.group === "all";
}

// Simple mode always maps SSR on a tonnes basis: "how much of what it uses does it grow?"
function mapIndicator() {
  if (isAll()) return state.mode === "expert" && state.indicator === "idr" ? "idr" : "share";
  return state.mode === "simple" ? "ssr" : state.indicator;
}

function mapBasis() {
  if (isAll()) return state.mode === "expert" && state.basis === "kcal" ? "kcal" : "protein";
  return state.mode === "simple" ? "tonnes" : state.basis;
}

function valueFor(id, indicator = mapIndicator(), basis = mapBasis()) {
  const ind = country(id)?.indicators?.[state.group]?.[basis];
  const v = ind?.[indicator];
  return v == null || Number.isNaN(v) ? null : v;
}

function perCapita(id) {
  return country(id)?.indicators?.[state.group]?.per_capita_kg ?? null;
}

function fmt(v) {
  return v == null ? "no data" : `${v.toFixed(0)}%`;
}

function groupInfo() {
  return state.data.groups.find((x) => x.key === state.group) ?? { label: state.group };
}

function food() {
  return isAll() ? "food" : groupInfo().label.toLowerCase();
}

// "in Germany" / "in the EU"
function inPlace(id) {
  return id === EU ? "in the EU" : `in ${country(id).name}`;
}

function subject(id) {
  return id === EU ? "The EU" : country(id).name;
}

// ------------------------------------------------------------------------------------------------
// plain-language text (simple mode)

function headline(id) {
  const who = subject(id);
  if (isAll()) {
    const s = valueFor(id, "share", "protein");
    if (s == null) return `No reliable figures for ${country(id).name}.`;
    if (s >= 97) return `Food grown ${inPlace(id)} could cover nearly all the protein people eat there.`;
    return `Food grown ${inPlace(id)} could cover ${Math.round(s)}% of the protein people eat there.`;
  }
  const ssr = valueFor(id, "ssr", "tonnes");
  if (ssr == null) return `No reliable figures for ${food()} ${inPlace(id)}.`;
  if (ssr < 5) return `${who} grows almost none of the ${food()} it uses.`;
  if (ssr < 90) return `${who} grows only ${Math.round(ssr)}% of the ${food()} it uses.`;
  if (ssr <= 110) return `${who} grows about as much ${food()} as it uses.`;
  if (ssr < 195) return `${who} grows ${Math.round(ssr - 100)}% more ${food()} than it uses.`;
  return `${who} grows ${(ssr / 100).toFixed(1)}× as much ${food()} as it uses.`;
}

function kg(v) {
  if (v == null) return "–";
  if (v > 0 && v < 1) return "<1 kg";
  return `${Math.round(v).toLocaleString()} kg`;
}

function bar(value, max, color) {
  const w = max > 0 && value > 0 ? Math.min(100, (value / max) * 100) : 0;
  return `<span class="bar" style="width:${w}%;background:${color}"></span>`;
}

function sparkline(values, { ref = 100, label = "" } = {}) {
  const years = state.data.meta.trend_years;
  const pts = values.map((v, i) => [i, v]).filter(([, v]) => v != null);
  if (pts.length < 2) return "";
  // Axis fits the data plus the 100% line, so year-to-year swings stay visible.
  const vals = pts.map(([, v]) => v);
  const lo = Math.max(0, Math.min(ref, ...vals) - 10);
  const hi = Math.max(ref, ...vals) + 10;
  const W = 288, H = 64, P = 6, PX = 34;
  const x = (i) => PX + (i / (years.length - 1)) * (W - 2 * PX);
  const y = (v) => H - P - ((v - lo) / (hi - lo)) * (H - 2 * P);
  const path = pts.map(([i, v], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const [fi, fv] = pts[0];
  const [li, lv] = pts[pts.length - 1];
  return `
    <div class="spark">
      <div class="spark-head"><span>${label}</span><span>${years[fi]}–${years[li]}</span></div>
      <div class="spark-key"><i></i> ${ref}%</div>
      <svg viewBox="0 0 ${W} ${H}" width="100%" height="${H}" role="img" aria-label="${label}">
        <line x1="${PX}" x2="${W - PX}" y1="${y(ref)}" y2="${y(ref)}" class="ref" />
        <path d="${path}" class="line" />
        <circle cx="${x(li)}" cy="${y(lv)}" r="3" class="dot" />
        <text x="${x(fi) - 4}" y="${y(fv) + 3}" class="val" text-anchor="end">${Math.round(fv)}%</text>
        <text x="${x(li) + 5}" y="${y(lv) + 3}" class="val">${Math.round(lv)}%</text>
      </svg>
    </div>`;
}

function trendFor(id) {
  return country(id)?.trend?.[state.group] ?? [];
}

function simpleGroupDetail(id) {
  const pc = perCapita(id);
  if (!pc || pc.supply == null) return `<p class="lead">${headline(id)}</p>`;
  const max = Math.max(pc.production ?? 0, pc.supply ?? 0);
  const uses = USES.map((u) => ({ ...u, v: pc[u.key] ?? 0 })).filter((u) => u.v >= 0.5);
  const eatenTenths = pc.supply > 0 ? Math.round(((pc.food ?? 0) / pc.supply) * 10) : null;
  const eatenText =
    eatenTenths == null ? ""
    : eatenTenths >= 9 ? "Almost all of it is eaten by people."
    : eatenTenths === 0 ? "Hardly any of it is eaten by people directly."
    : `Only ${eatenTenths} in every 10 kg is eaten by people directly.`;
  const avg = state.data.meta.europe_avg?.[state.group]?.food_kg_pc;
  const perDay = pc.food != null ? Math.round((pc.food * 1000) / 365) : null;
  const trade = id === EU
    ? `<p class="small">Trade between EU countries isn't counted here — only what the EU as a whole grows and uses.</p>`
    : `<p class="small">Bought from abroad: <strong>${kg(pc.imports)}</strong> · Sold abroad: <strong>${kg(pc.exports)}</strong> per person</p>`;

  return `
    <p class="lead">${headline(id)}</p>
    ${sparkline(trendFor(id), { label: "Share grown at home, each year" })}
    <p class="unit">Per person, per year:</p>
    <div class="row"><span>Grown here</span><strong>${kg(pc.production)}</strong></div>
    <div class="track">${bar(pc.production, max, "var(--accent)")}</div>
    <div class="row"><span>Used here</span><strong>${kg(pc.supply)}</strong></div>
    <div class="track">${uses.map((u) => bar(u.v, max, u.color)).join("")}</div>
    <ul class="uses">${uses
      .map((u) => `<li><i style="background:${u.color}"></i>${kg(u.v)} ${u.label}</li>`)
      .join("")}</ul>
    ${eatenText ? `<p class="small">${eatenText}</p>` : ""}
    ${perDay != null ? `<p class="small">The average person ${inPlace(id)} eats <strong>${kg(pc.food)}</strong> of ${food()} a year — about ${perDay.toLocaleString()} g a day${avg != null ? `. European average: ${kg(avg)}` : ""}.</p>` : ""}
    ${trade}`;
}

function simpleAllDetail(id) {
  const c = country(id);
  const p = c.indicators.all?.protein;
  const avg = state.data.meta.europe_avg?.all?.protein_g;
  const rows = state.data.groups
    .filter((g) => g.key !== "all")
    .map((g) => ({ g, v: c.indicators[g.key]?.tonnes?.ssr }))
    .filter((r) => r.v != null)
    .sort((a, b) => a.v - b.v);
  return `
    <p class="lead">${headline(id)}</p>
    ${sparkline(trendFor(id), { label: "Protein that home-grown food could cover, each year" })}
    ${p?.g_per_day != null ? `<p class="small">People ${inPlace(id)} eat about <strong>${Math.round(p.g_per_day)} g</strong> of protein a day${avg != null ? ` (European average: ${Math.round(avg)} g)` : ""}.</p>` : ""}
    <p class="unit" style="margin-top:10px">Food by food — how much of what it uses does ${id === EU ? "the EU" : c.name} grow?</p>
    <table class="foods">${rows
      .map(({ g, v }) => `
        <tr data-group="${g.key}">
          <td>${g.label}</td>
          <td class="meter"><span style="width:${Math.min(100, v / 2)}%;background:${v >= 100 ? "var(--accent)" : "#d28a55"}"></span><i></i></td>
          <td>${fmt(v)}</td>
        </tr>`)
      .join("")}</table>
    <p class="small">The line marks 100%: growing exactly what is used. Click a food for details.</p>
    <p class="small">Meat, milk and eggs count as home-grown even when the animals ate imported feed such as soy.</p>`;
}

// Idle panel: who has the biggest surplus / shortfall for the selected food?
function rankingDetail() {
  const rows = Object.entries(state.data.countries)
    .filter(([id]) => id !== EU)
    .map(([id, c]) => {
      if (isAll()) return { id, c, v: c.indicators.all?.protein?.share };
      const pc = c.indicators[state.group]?.per_capita_kg;
      return { id, c, v: pc?.production != null && pc?.supply != null ? pc.production - pc.supply : null };
    })
    .filter((r) => r.v != null)
    .sort((a, b) => b.v - a.v);
  if (!rows.length) return `<p class="hint">Hover a country for details. Click to pin.</p>`;
  const fmtV = (v) => (isAll() ? fmt(v) : `${v > 0 ? "+" : "−"}${kg(Math.abs(v))}`);
  const list = (rs) => `<ol class="rank">${rs
    .map((r) => `<li data-iso3="${r.id}"><span>${r.c.name}</span><strong>${fmtV(r.v)}</strong></li>`)
    .join("")}</ol>`;
  const [topTitle, bottomTitle] = isAll()
    ? ["Most self-sufficient in protein", "Least self-sufficient in protein"]
    : [`Biggest ${food()} surplus per person`, `Biggest ${food()} shortfall per person`];
  return `
    <p class="hint">Hover a country for details. Click to pin.</p>
    <h3>${topTitle}</h3>${list(rows.slice(0, 5))}
    <h3>${bottomTitle}</h3>${list(rows.slice(-5).reverse())}
    ${isAll() ? "" : `<p class="small">Grown minus used, kg per person per year.</p>`}`;
}

// ------------------------------------------------------------------------------------------------
// rendering

function render() {
  const { stops, colors } = SCALES[mapIndicator()] ?? SCALES.ssr;
  const interp = ["interpolate", ["linear"], ["coalesce", ["feature-state", "v"], -1]];
  stops.forEach((s, i) => interp.push(s, colors[i]));
  map.setPaintProperty("atlas-fill", "fill-color", [
    "case",
    ["==", ["coalesce", ["feature-state", "v"], -1], -1],
    NO_DATA,
    interp,
  ]);
  for (const iso3 of Object.keys(state.data.countries)) {
    if (iso3 === EU) continue;
    map.setFeatureState({ source: "countries", id: iso3 }, { v: valueFor(entity(iso3)) });
  }
  renderLegend();
  document.getElementById("group").value = state.group;
  // "All food" has no tonnes basis: the same control picks protein vs calorie weighting.
  document.querySelector('#basis option[value="tonnes"]').textContent = isAll() ? "Protein" : "Tonnes";
  document.getElementById("expert-controls").hidden = state.mode !== "expert";
  for (const b of document.querySelectorAll(".mode button")) {
    b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode));
  }
  showDetail(state.pinned);
}

function renderLegend() {
  const ind = mapIndicator();
  const { colors, ticks } = SCALES[ind] ?? SCALES.ssr;
  let label, tickText;
  if (state.mode === "simple" && isAll()) {
    label = "How much of the protein people eat could home-grown food cover?";
    tickText = ["20% or less", "75%", "all of it"];
  } else if (state.mode === "simple") {
    label = `How much of the ${food()} it uses does each country grow?`;
    tickText = ["none", "all of it", "twice that"];
  } else if (isAll()) {
    label = ind === "idr" ? "Import dependency is not defined for all food" : `Coverage of food supply (${mapBasis()}, capped per food)`;
    tickText = ticks;
  } else {
    label = `${ind === "ssr" ? "Self-sufficiency" : "Import dependency"} (${mapBasis()})`;
    tickText = ticks;
  }
  const bloc = state.bloc ? `<div class="small">EU members show the EU-wide figure.</div>` : "";
  document.getElementById("legend").innerHTML = `
    <div>${label}</div>
    <div class="bar" style="background: linear-gradient(90deg, ${colors.join(",")})"></div>
    <div class="ticks">${tickText.map((t) => `<span>${t}</span>`).join("")}</div>${bloc}`;
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
    el.innerHTML = state.mode === "simple" ? rankingDetail() : `<p class="hint">Hover a country for details. Click to pin.</p>`;
    wireDetail(el);
    return;
  }
  const id = entity(iso3);
  const c = country(id);
  const g = groupInfo();
  const viaBloc = id !== iso3 ? ` <small>(${state.data.countries[iso3].name} is a member)</small>` : "";
  const body = state.mode === "simple"
    ? (isAll() ? simpleAllDetail(id) : simpleGroupDetail(id))
    : expertDetail(id);
  el.innerHTML = `
    <h2>${c.name} <small>· ${g.label}</small>${viaBloc}</h2>
    ${body}
    ${g.notes && state.mode === "expert" ? `<p class="note">${g.notes}</p>` : ""}
    ${c.notes && (state.mode === "expert" || id === EU) ? `<p class="note">⚠ ${c.notes}</p>` : ""}
    <p class="cite">${sourceLine()}</p>`;
  wireDetail(el);
}

// Clickable rows inside the detail panel: foods (switch group) and rankings (pin country).
function wireDetail(el) {
  for (const tr of el.querySelectorAll("[data-group]")) {
    tr.onclick = () => { state.group = tr.dataset.group; render(); };
  }
  for (const li of el.querySelectorAll("[data-iso3]")) {
    li.onclick = () => pin(li.dataset.iso3);
  }
}

function expertDetail(id) {
  const c = country(id);
  if (isAll()) {
    const a = c.indicators.all ?? {};
    return `
      <div class="big">${fmt(valueFor(id))}<small>coverage, ${mapBasis()}</small></div>
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
  const items = (c.items?.[state.group] ?? [])
    .filter((i) => i.ssr != null)
    .sort((a, b) => (b.supply_kt ?? 0) - (a.supply_kt ?? 0))
    .slice(0, 8);

  return `
    <div class="big">${fmt(valueFor(id))}<small>${mapIndicator().toUpperCase()}, ${mapBasis()}</small></div>
    ${sparkline(trendFor(id), { label: "SSR (tonnes), each year" })}
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
    ${items.length ? `<table style="margin-top:8px">${items
      .map((i) => `<tr><td>${i.item}</td><td>${fmt(i.ssr)}</td></tr>`)
      .join("")}</table>` : ""}
    <p class="note">SSR = production / domestic supply. IDR = imports / domestic supply.
      ${id === EU ? "EU bloc: members summed; intra-EU trade cancels out of supply." : "National view: imports from other EU countries count as imports."}</p>
    ${t.flag || k.flag ? `<p class="note">Flag: ${t.flag ?? k.flag}</p>` : ""}`;
}

function pop(c) {
  return c.population_k == null ? "–" : `${(c.population_k / 1000).toFixed(1)} m`;
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
    `Figures are ${m.years.replace("-", "–")} averages; trend lines show single years. Built ${longDate(m.generated.slice(0, 10))}.`;
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

  const bloc = document.getElementById("bloc");
  bloc.checked = state.bloc;
  bloc.onchange = () => { state.bloc = bloc.checked; render(); };

  const ind = document.getElementById("indicator");
  ind.value = state.indicator;
  ind.onchange = () => { state.indicator = ind.value; render(); };

  const basis = document.getElementById("basis");
  basis.value = state.basis;
  basis.onchange = () => { state.basis = basis.value; render(); };
}
