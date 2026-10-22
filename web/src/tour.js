// The tour: the real atlas, step by step, with Italy as the worked example. Each step opens a
// page of the app (by its hash), dims everything but the part it explains, and puts a short card
// next to it. Every figure in the cards is read from the data the page itself shows, never typed.
// Next, Back, the arrow keys, the mouse wheel and a swipe move through it; a click on the lit part
// works as in the app (and moves the tour on when it is what the next step shows); Esc ends it.

const ID = "ITA";
const FOOD = "cereals";
const SCENARIO = "black_sea";
const PAD = 6; // around each lit part
const RADIUS = 10;
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const CLOSE = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>`;

let api = null;
let at = -1;
let root = null;
let busy = 0; // a counter, so a step that is still waiting for its page gives way to a newer one
let follow = 0; // requestAnimationFrame id while the lit parts are followed after a change
let lit = []; // the selectors of the lit parts, per hole, for re-measuring
let scenarioOurs = false;

const pct = (v) => `${v < 1 ? "under 1" : Math.round(v)}%`;
const kcal = (v) => `${Math.round(v).toLocaleString("en-GB")} kcal`;
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const phone = () => matchMedia("(max-width: 760px)").matches;

// ------------------------------------------------------------------------------------------------
// the steps

function steps() {
  const { state, country, pctFor, lasts, forHowLong, lastDay, nameOf, inText, listOf, shortTonnes } = api;
  const it = nameOf(ID);
  const foodName = () => api.food(FOOD);
  const foodRows = () => state.data.groups.filter((g) => g.key !== "all")
    .map((g) => ({ name: g.label.toLowerCase(), v: pctFor(ID, g.key) })).filter((r) => r.v != null);
  return [
    {
      title: `A tour with ${it}`,
      hash: "#", group: "all",
      text: () => `How long would the food a country produces feed its own people, if it bought nothing
        abroad? This tour takes one country, ${it}, through every part of the atlas, step by step.`,
      hint: phone() ? "Next, or a swipe over the map, moves on." : "Next, the arrow keys or the mouse wheel move on. Esc ends the tour.",
      first: true,
    },
    {
      title: "The map",
      hash: "#", group: "all",
      holes: [["#legend"]],
      text: () => `Every country has one colour: how many months its own harvests, herds and catches
        would feed its people. Red runs out within half a year, dark green has more than it needs.`,
      hint: "Counted in calories, so bread, oil and sugar weigh most.",
    },
    {
      title: "Pick a country",
      hash: "#", group: "all",
      holes: [[".head .search"]],
      text: () => `Type a name here, or click a country on the map. We take ${it}.`,
    },
    {
      title: it,
      hash: `#${ID}`,
      holes: [["#view .q", "#view .answer", "#view svg.strip"]],
      ready: () => pctFor(ID, "all") != null,
      text: () => {
        const v = pctFor(ID, "all");
        const day = lastDay(v);
        return `Food produced in ${it} alone would give enough calories ${forHowLong(v)}${day
          ? `: eaten from 1 January, it would run out on ${day}` : ""}.`;
      },
      hint: "The coloured boxes are the months of the year.",
    },
    {
      title: "Behind the answer",
      hash: `#${ID}`,
      holes: [["#card"]],
      ready: () => !!country(ID)?.indicators?.all?.kcal?.balance,
      text: () => {
        const b = country(ID).indicators.all.kcal.balance;
        return `Per person and day, ${it} produces <strong>${kcal(b.produced)}</strong>, buys
          <strong>${kcal(b.imports)}</strong> abroad and sells <strong>${kcal(b.exports)}</strong>. It uses <strong>${kcal(b.used)}</strong>. Produced against
          used gives the months.`;
      },
      hint: "The four rows open the details. We will come back to them.",
    },
    {
      title: "Food by food",
      hash: `#${ID}`,
      holes: [["#view .foodlist"]],
      text: () => {
        const rows = foodRows();
        const spare = rows.filter((r) => r.v >= 100).sort((a, b) => b.v - a.v).slice(0, 2).map((r) => r.name);
        const short = rows.filter((r) => r.v < 75).sort((a, b) => a.v - b.v).slice(0, 2).map((r) => r.name);
        return `The same question for each food on its own.${spare.length ? ` ${it} produces more ${listOf(spare)}
          than it uses` : ""}${short.length ? `${spare.length ? ", but" : ""} its own ${listOf(short)} would run out first` : ""}.`;
      },
      hint: "Each line opens that food.",
    },
    {
      title: "Choose a food",
      hash: `#${ID}`,
      holes: [["#foodrail"]],
      text: () => `This menu switches the map and the page to one food. Next we take ${foodName()}.`,
    },
    {
      title: api.groupInfo(FOOD).label,
      hash: `#${ID}/${FOOD}`,
      holes: [["#view .q", "#view .answer", "#view svg.strip"], ["#card"]],
      ready: () => pctFor(ID, FOOD) != null,
      text: () => {
        const c = country(ID).indicators[FOOD].components_kt;
        return `${it}'s own ${foodName()} would last ${lasts(pctFor(ID, FOOD))}. It produces
          <strong>${shortTonnes(c.production)}</strong> a year and buys <strong>${shortTonnes(c.imports)}</strong>
          abroad. The card now counts tonnes.`;
      },
    },
    {
      title: "Who sells it",
      hash: `#${ID}/${FOOD}/trade`,
      holes: [['#card .sum-row[data-row="imports"]'], ["#view .partners"]],
      ready: () => api.shares(ID, FOOD, "imports").length > 0,
      text: () => {
        const top = api.shares(ID, FOOD, "imports").slice(0, 3);
        return `“Buys abroad” opens the countries it buys from. The most comes from
          ${listOf(top.map((r) => `${inText(r.id)} (${pct(r.share)})`))}. The map draws each as a line to ${it}.`;
      },
      hint: "Click a seller to see what it trades itself.",
    },
    {
      title: "What it is used for",
      hash: `#${ID}/${FOOD}/used`,
      holes: [['#card .sum-row[data-row="used"]'], ["#view .detail > h3", "#view .uses"]],
      ready: () => api.perCapita(ID, FOOD)?.supply > 0,
      text: () => {
        const pc = api.perCapita(ID, FOOD);
        const tenths = Math.round((pc.food / pc.supply) * 10);
        const rest = api.USES.filter((u) => u.key !== "food").sort((a, b) => (pc[b.key] ?? 0) - (pc[a.key] ?? 0))[0];
        return `“Uses” splits what is used. Of every 10 kg of ${foodName()} used in ${it}, ${tenths} go to food
          directly; most of the rest is ${rest.label}.`;
      },
    },
    {
      title: "When it grows",
      hash: `#${ID}/${FOOD}`,
      holes: [["#view .season", "#view .season-key"]],
      ready: () => !!state.seasons?.countries?.[ID]?.[FOOD]?.length,
      text: () => {
        const r = state.seasons.countries[ID][FOOD][0];
        const t = state.seasons.meta.thresholds;
        const harvest = MONTHS.filter((_, k) => r.harvest[k] >= t.harvest);
        const sown = MONTHS.filter((_, k) => r.harvest[k] < t.harvest && r.sown[k] >= t.sowing);
        return `A typical year for each crop. ${r.label} is sown in ${listOf(sown)} and harvested in
          ${listOf(harvest)}: one harvest has to last until the next.`;
      },
    },
    {
      title: "Where it grows",
      hash: `#${ID}/${FOOD}/where`,
      holes: [["#view .q", "#view .partners"], ["#legend"]],
      ready: () => !!api.regionsFor(ID, FOOD)?.regions?.length,
      text: () => {
        const [code, , share] = api.regionsFor(ID, FOOD).regions[0];
        return `${api.regionName(code)} alone grows ${pct(share)} of ${it}'s ${foodName()}. The map shades
          each region by tonnes per square kilometre${document.querySelector("#view [data-fields]")
          ? `; “Fields” shows the fields themselves, from satellite images` : ""}.`;
      },
    },
    {
      title: "What if…?",
      hash: `#${ID}/${FOOD}`,
      holes: [["#whatif .badge", "#whatif .open"], ["#view .lack"]],
      enter: async () => {
        await api.loadScenario();
        if (state.scenario !== SCENARIO) { scenarioOurs = true; api.setScenario(SCENARIO); }
      },
      leave: () => endScenario(),
      ready: () => state.scenario === SCENARIO && api.scenValue(ID, FOOD) != null,
      text: () => `Scenarios stop some countries from selling. Here: “${api.scenInfo(SCENARIO).label}”.
        ${it} would miss <strong>${pct(api.scenValue(ID, FOOD))}</strong> of the ${foodName()} it uses; the map
        shows the share for every country.`,
      hint: "The cross on the badge ends a scenario.",
    },
    {
      title: "How do we know?",
      hash: `#${ID}/${FOOD}`,
      holes: [["#foot .tools"]],
      text: () => `Every figure has its sources. “How do we know?” walks through the sum for ${it} and how to
        check it in FAO's own tables; “All the numbers” lists FAO's figures, food item by food item.`,
    },
    {
      title: "Your turn",
      hash: "#", group: "all",
      holes: [[".head .search"]],
      last: true,
      text: () => `That was ${it}. Find your own country in the search box, or click one on the map.`,
    },
  ];
}

function endScenario() {
  if (scenarioOurs && api.state.scenario === SCENARIO) api.setScenario(null);
  scenarioOurs = false;
}

// ------------------------------------------------------------------------------------------------
// moving through it

let list = [];

export function startTour(a) {
  api = a;
  list = steps();
  if (!root) build();
  root.hidden = false;
  document.body.classList.add("touring");
  go(0);
}

function end() {
  if (at < 0) return;
  list[at]?.leave?.();
  at = -1;
  busy++;
  cancelAnimationFrame(follow);
  root.classList.add("leaving");
  setTimeout(() => {
    root.hidden = true;
    root.classList.remove("leaving");
    document.body.classList.remove("touring");
  }, calm() ? 0 : 160);
  document.getElementById("country")?.focus({ preventScroll: true });
}

async function go(i) {
  if (i < 0 || i >= list.length) return;
  const from = at;
  if (from >= 0 && from !== i) list[from].leave?.();
  at = i;
  const ticket = ++busy;
  const s = list[i];
  card.classList.add("waiting");
  if (s.group && !api.state.iso3 && api.state.group !== s.group) api.setGroup(s.group);
  if (s.hash && location.hash !== s.hash && !(s.hash === "#" && location.hash === "")) {
    if (s.group) api.state.group = s.group; // the world map keeps the food it shows
    location.hash = s.hash;
  }
  await s.enter?.();
  await ready(s, ticket);
  if (ticket !== busy) return;
  show(s, i);
}

// Wait until the page of a step is drawn and has what the step talks about (data loads on first
// use), at most a few seconds: then the card shows whatever is there.
function ready(s, ticket) {
  const t0 = performance.now();
  return new Promise((done) => {
    const check = () => {
      if (ticket !== busy) { done(); return; }
      const detail = document.querySelector("#view .detail[data-hash]");
      const page = !s.hash || s.hash === "#" || detail?.dataset.hash === location.hash;
      const parts = (s.holes ?? []).every((h) => document.querySelector(h[0]));
      let data = true;
      try { data = s.ready ? !!s.ready() : true; } catch { data = false; }
      if ((page && parts && data) || performance.now() - t0 > 5000) done();
      else setTimeout(check, 60);
    };
    check();
  });
}

function show(s, i) {
  let text;
  try { text = s.text(); } catch (e) { console.error(e); text = ""; }
  lit = s.holes ?? [];
  // A lit part below the fold of a scrolling list comes into view first.
  for (const h of lit) {
    const el = document.querySelector(h[0]);
    const box = el && scroller(el)?.getBoundingClientRect();
    const r = el?.getBoundingClientRect();
    if (box && (r.top < box.top || r.bottom > box.bottom)) el.scrollIntoView({ block: "center", behavior: calm() ? "auto" : "smooth" });
  }
  const n = list.length - 1; // the opening card is not counted
  card.innerHTML = `
    <div class="tour-top">
      <span class="tour-count">${s.first ? "Tour" : `${i} of ${n}`}</span>
      <button type="button" class="tour-x" data-tour-end aria-label="End the tour">${CLOSE}</button>
    </div>
    ${s.first ? "" : `<div class="tour-progress" aria-hidden="true"><span style="width:${(i / n) * 100}%"></span></div>`}
    <h2 id="tour-title">${s.title}</h2>
    ${text ? `<p>${text}</p>` : ""}
    ${s.hint ? `<p class="tour-hint">${s.hint}</p>` : ""}
    <div class="tour-btns">${buttons(s, i)}</div>`;
  card.classList.toggle("wide", !!(s.first || s.last));
  wireCard();
  card.classList.remove("waiting");
  card.classList.remove("in");
  void card.offsetWidth;
  card.classList.add("in");
  place();
  // The page settles after a change (the detail slides in, a list scrolls, the map flies): follow
  // the lit parts for a moment.
  cancelAnimationFrame(follow);
  const t0 = performance.now();
  const loop = () => { place(); if (performance.now() - t0 < 900) follow = requestAnimationFrame(loop); };
  follow = requestAnimationFrame(loop);
  card.querySelector("[data-tour-next]")?.focus({ preventScroll: true });
}

function buttons(s, i) {
  if (s.first) {
    return `<button type="button" class="tour-next" data-tour-next>Start the tour</button>
      <button type="button" class="tour-back" data-tour-end>Not now</button>`;
  }
  if (s.last) {
    const own = api.readersCountry();
    return `${own && own !== ID ? `<button type="button" class="tour-next" data-tour-country="${own}">Start with ${api.nameOf(own)}</button>` : ""}
      <button type="button" class="${own && own !== ID ? "tour-back" : "tour-next"}" data-tour-end>Explore the map</button>
      <button type="button" class="tour-back" data-tour-again>Start again</button>`;
  }
  return `<button type="button" class="tour-back" data-tour-back${i <= 1 ? " disabled" : ""}>Back</button>
    <button type="button" class="tour-next" data-tour-next>Next</button>`;
}

function wireCard() {
  card.querySelector("[data-tour-next]")?.addEventListener("click", () => go(at + 1));
  card.querySelector("[data-tour-back]")?.addEventListener("click", () => go(at - 1));
  card.querySelector("[data-tour-again]")?.addEventListener("click", () => go(1));
  for (const b of card.querySelectorAll("[data-tour-end]")) b.addEventListener("click", end);
  card.querySelector("[data-tour-country]")?.addEventListener("click", (e) => {
    const id = e.currentTarget.dataset.tourCountry;
    end();
    location.hash = `#${id}`;
  });
}

// ------------------------------------------------------------------------------------------------
// the layer: a dimmed screen with holes where the lit parts are, rings around them, and the card

let dim, rings, card;

function build() {
  root = document.createElement("div");
  root.id = "tour";
  root.hidden = true;
  root.innerHTML = `<div class="tour-dim"></div><span class="tour-ring"></span><span class="tour-ring"></span>
    <section class="tour-card" role="dialog" aria-modal="false" aria-labelledby="tour-title"></section>`;
  document.body.append(root);
  dim = root.querySelector(".tour-dim");
  rings = [...root.querySelectorAll(".tour-ring")];
  card = root.querySelector(".tour-card");

  addEventListener("resize", () => at >= 0 && place());
  document.addEventListener("scroll", () => at >= 0 && place(), true);
  addEventListener("hashchange", () => {
    if (at < 0) return;
    // A click on the lit part that leads to the next step's page moves the tour on.
    const next = list[at + 1];
    if (next?.hash && next.hash === location.hash && list[at].hash !== location.hash) go(at + 1);
    else setTimeout(place, 50);
  });
  document.addEventListener("keydown", (e) => {
    if (at < 0) return;
    if (e.target.closest?.("input, select, textarea")) { if (e.key === "Escape") end(); return; }
    const k = e.key;
    if (k === "Escape") { end(); e.preventDefault(); return; }
    if (["ArrowRight", "ArrowDown", "PageDown"].includes(k)) { go(at + 1); e.preventDefault(); }
    else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(k) && at > 1) { go(at - 1); e.preventDefault(); }
  }, true);
  // Scrolling over the dimmed part, or swiping it, moves through the tour; the lit parts scroll as usual.
  let wheel = 0, lastStep = 0;
  dim.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (performance.now() - lastStep < 700) return;
    wheel += e.deltaY;
    if (Math.abs(wheel) < 60) return;
    const d = Math.sign(wheel);
    wheel = 0;
    lastStep = performance.now();
    if (d > 0 && at < list.length - 1) go(at + 1);
    else if (d < 0 && at > 1) go(at - 1);
  }, { passive: false });
  let y0 = null;
  dim.addEventListener("touchstart", (e) => { y0 = e.touches[0].clientY; }, { passive: true });
  dim.addEventListener("touchend", (e) => {
    if (y0 == null) return;
    const dy = y0 - e.changedTouches[0].clientY;
    y0 = null;
    if (dy > 50 && at < list.length - 1) go(at + 1);
    else if (dy < -50 && at > 1) go(at - 1);
  });
  // A click on the dimmed part only draws the eye back to the card.
  dim.addEventListener("click", () => {
    card.classList.remove("nudge");
    void card.offsetWidth;
    card.classList.add("nudge");
  });
}

// The nearest ancestor that scrolls (the detail on wide screens, the sheet on phones).
function scroller(el) {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if ((o === "auto" || o === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

// A hole: the parts it lights, as one rectangle, cut to what its scrolling box shows.
function rectOf(sels) {
  let r = null;
  for (const sel of sels) {
    for (const el of document.querySelectorAll(sel)) {
      const b = el.getBoundingClientRect();
      if (!b.width || !b.height) continue;
      r = r ? { l: Math.min(r.l, b.left), t: Math.min(r.t, b.top), r: Math.max(r.r, b.right), b: Math.max(r.b, b.bottom) }
        : { l: b.left, t: b.top, r: b.right, b: b.bottom };
      const box = scroller(el)?.getBoundingClientRect();
      if (box) r = { l: Math.max(r.l, box.left), t: Math.max(r.t, box.top), r: Math.min(r.r, box.right), b: Math.min(r.b, box.bottom) };
    }
  }
  if (!r || r.r - r.l < 2 || r.b - r.t < 2) return null;
  return { x: r.l - PAD, y: r.t - PAD, w: r.r - r.l + 2 * PAD, h: r.b - r.t + 2 * PAD };
}

// Rounded rectangle as a path; a hole of size 0 where there is none, so the path always has the
// same shape and the browser can animate from one step's holes to the next.
function hole({ x, y, w, h }) {
  const r = Math.min(RADIUS, w / 2, h / 2);
  const f = (v) => v.toFixed(1);
  return `M${f(x + r)} ${f(y)}H${f(x + w - r)}A${f(r)} ${f(r)} 0 0 1 ${f(x + w)} ${f(y + r)}V${f(y + h - r)}`
    + `A${f(r)} ${f(r)} 0 0 1 ${f(x + w - r)} ${f(y + h)}H${f(x + r)}A${f(r)} ${f(r)} 0 0 1 ${f(x)} ${f(y + h - r)}`
    + `V${f(y + r)}A${f(r)} ${f(r)} 0 0 1 ${f(x + r)} ${f(y)}Z`;
}

function place() {
  if (at < 0) return;
  const W = innerWidth, H = innerHeight;
  const rects = lit.map(rectOf).filter(Boolean).slice(0, 2);
  const none = (c) => ({ x: c.x + c.w / 2, y: c.y + c.h / 2, w: 0, h: 0 });
  const centre = { x: W / 2, y: H / 2, w: 0, h: 0 };
  const holes = [rects[0] ?? centre, rects[1] ?? none(rects[0] ?? centre)];
  dim.style.clipPath = `path(evenodd, "M0 0H${W}V${H}H0Z${holes.map(hole).join("")}")`;
  rings.forEach((ring, k) => {
    const r = rects[k];
    ring.classList.toggle("on", !!r);
    if (r) Object.assign(ring.style, { transform: `translate(${r.x}px, ${r.y}px)`, width: `${r.w}px`, height: `${r.h}px` });
  });
  placeCard(rects);
}

// Next to the first lit part where there is room (right, left, below, above), else over the map;
// on phones above or below the sheet, whichever half is free.
function placeCard(rects) {
  const W = innerWidth, H = innerHeight, gap = 14, m = 10;
  const cw = card.offsetWidth, ch = card.offsetHeight;
  const clampX = (x) => Math.max(m, Math.min(x, W - cw - m));
  const clampY = (y) => Math.max(m, Math.min(y, H - ch - m));
  let x, y;
  const r = rects[0];
  if (phone()) {
    x = m;
    const lowest = Math.max(...rects.map((q) => q.y + q.h), 0);
    const highest = Math.min(...rects.map((q) => q.y), H);
    y = !rects.length ? (H - ch) / 2 : highest > ch + 2 * m ? m : clampY(lowest + gap);
  } else if (!r) {
    const left = document.getElementById("panel").getBoundingClientRect().right;
    x = left + (W - left - cw) / 2;
    y = (H - ch) / 2;
  } else if (r.x + r.w + gap + cw + m <= W) {
    x = r.x + r.w + gap; y = clampY(r.y);
  } else if (r.x - gap - cw >= m) {
    x = r.x - gap - cw; y = clampY(r.y);
  } else if (r.y + r.h + gap + ch + m <= H) {
    x = clampX(r.x); y = r.y + r.h + gap;
  } else {
    x = clampX(r.x); y = Math.max(m, r.y - gap - ch);
  }
  card.style.transform = `translate(${Math.round(clampX(x))}px, ${Math.round(clampY(y))}px)`;
}
