// The tour: the real atlas, built up step by step, with Italy as the worked example. Each step
// opens a page of the app (by its hash) and shows only the parts it is about, in the places they
// have in the app; everything else is invisible (not moved). The map stays plain land except where
// a step is about it. Where a step shows something to click, that click (and only the one the
// example needs) moves the tour on, as Next does. At the end the whole map and every control
// come in: the finale. Every figure in the cards is read from the data the page shows.

const ID = "ITA";
const FOOD = "cereals";
const PAD = 6; // around each lit part
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
  "September", "October", "November", "December"];
const CLOSE = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18" /></svg>`;
const ARROW = `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6" /></svg>`;
// Never hidden: the map (the veil does that) and the tour itself.
const SKIP = new Set(["map", "land", "tour"]);

let api = null;
let list = [];
let at = -1;
let root, rings, card, rule;
let busy = 0; // a counter, so a step still waiting for its page gives way to a newer one
let follow = 0; // requestAnimationFrame id while the lit parts are followed after a change

const pct = (v) => `${v < 1 ? "under 1" : Math.round(v)}%`;
const kcal = (v) => `${Math.round(v).toLocaleString("en-GB")} kcal`;
const calm = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const phone = () => matchMedia("(max-width: 760px)").matches;
const q = (sel) => document.querySelector(sel);
const linkText = (sel) => (q(sel)?.textContent ?? "").replace("›", "").trim();
// The answer at the top of a food or country page: the question, the answer and the year strip.
const ANSWER = ["#view .q", "#view .answer", "#view svg.strip"];
const ROW = (r) => `#card .sum-row[data-row="${r}"]`;

// ------------------------------------------------------------------------------------------------
// the steps
//   hash      the page it opens          holes   what it lights (each a list of parts, one ring)
//   keep      shown for orientation, not clickable   map   "blank" | "focus" (Italy) | "full"
//   only      the one choice let through (country, food)   camera   where the map looks

function steps() {
  const { state, country, pctFor, lasts, forHowLong, lastDay, nameOf, inText, listOf, shortTonnes } = api;
  const it = nameOf(ID);
  const foodName = api.food(FOOD);
  const foodLabel = api.groupInfo(FOOD).label;
  const place = ["#where"];
  return [
    {
      landing: true, hash: "#", group: "all", map: "blank",
      title: "Could your country feed itself?",
      text: () => "How long the food a country produces would last its own people, if it bought nothing abroad.",
    },
    {
      title: "The map", hash: "#", group: "all", map: "full",
      holes: [["#legend"]],
      camera: () => api.showWorld(),
      text: () => `Every country has one colour: how many months its own harvests, herds and catches
        would feed its people. Red runs out within half a year, dark green has more than it needs.`,
    },
    {
      title: "Pick a country", hash: "#", group: "all", map: "focus",
      holes: [[".head .search"]],
      only: { country: ID },
      camera: () => api.showEurope(),
      text: () => `Type <strong>${it}</strong> into the search box, or click it on the map.`,
    },
    {
      title: it, hash: `#${ID}`, map: "focus",
      holes: [ANSWER], keep: place,
      ready: () => pctFor(ID, "all") != null,
      text: () => {
        const v = pctFor(ID, "all");
        const day = lastDay(v);
        return `Food produced in ${it} alone would give enough calories ${forHowLong(v)}${day
          ? `: eaten from 1 January, it would run out on ${day}` : ""}.`;
      },
    },
    {
      title: "Behind the answer", hash: `#${ID}`, map: "focus",
      holes: [["#card"]], keep: place,
      ready: () => !!country(ID)?.indicators?.all?.kcal?.balance,
      text: () => {
        const b = country(ID).indicators.all.kcal.balance;
        return `Per person and day, ${it} produces <strong>${kcal(b.produced)}</strong>, buys
          <strong>${kcal(b.imports)}</strong> abroad and sells <strong>${kcal(b.exports)}</strong>. It uses
          <strong>${kcal(b.used)}</strong>. Produced against used gives the months.`;
      },
    },
    {
      title: "Choose a food", hash: `#${ID}`, map: "focus",
      holes: [["#foodrail"]], keep: place,
      only: { food: FOOD },
      text: () => {
        const rows = state.data.groups.filter((g) => g.key !== "all")
          .map((g) => ({ name: g.label.toLowerCase(), v: pctFor(ID, g.key) })).filter((r) => r.v != null);
        const spare = rows.filter((r) => r.v >= 100).sort((a, b) => b.v - a.v).slice(0, 2).map((r) => r.name);
        const short = rows.filter((r) => r.v < 75).sort((a, b) => a.v - b.v).slice(0, 2).map((r) => r.name);
        return `Each food has its own answer.${spare.length ? ` ${it} produces more ${listOf(spare)} than it uses` : ""}${
          short.length ? `${spare.length ? ", but" : ""} its own ${listOf(short)} would run out first` : ""}. This menu
          switches the map and the page to one food: open it and choose <strong>${foodLabel}</strong>.`;
      },
    },
    {
      title: foodLabel, hash: `#${ID}/${FOOD}`, map: "full",
      holes: [ANSWER, ["#card"]], keep: place,
      ready: () => pctFor(ID, FOOD) != null,
      text: () => {
        const c = country(ID).indicators[FOOD].components_kt;
        return `${it}'s own ${foodName} would last ${lasts(pctFor(ID, FOOD))}. It produces
          <strong>${shortTonnes(c.production)}</strong> a year and buys <strong>${shortTonnes(c.imports)}</strong>
          abroad. Click <strong>Buys abroad</strong> to see who sells them.`;
      },
    },
    {
      title: "Who sells it", hash: `#${ID}/${FOOD}/trade`, map: "full",
      holes: [["#view .partners"], [ROW("used")]], keep: [...place, ROW("imports")],
      ready: () => api.shares(ID, FOOD, "imports").length > 0,
      text: () => {
        const top = api.shares(ID, FOOD, "imports").slice(0, 3);
        return `The most comes from ${listOf(top.map((r) => `${inText(r.id)} (${pct(r.share)})`))}; the map
          draws each seller as a line to ${it}. Then click <strong>Uses</strong>.`;
      },
    },
    {
      title: "What it is used for", hash: `#${ID}/${FOOD}/used`, map: "focus",
      holes: [["#view .detail > h3", "#view .detail > .row", "#view .detail > .track", "#view .uses"], [ROW("food")]], keep: [...place, ROW("used")],
      ready: () => api.perCapita(ID, FOOD)?.supply > 0,
      text: () => {
        const pc = api.perCapita(ID, FOOD);
        const tenths = Math.round((pc.food / pc.supply) * 10);
        const rest = api.USES.filter((u) => u.key !== "food").sort((a, b) => (pc[b.key] ?? 0) - (pc[a.key] ?? 0))[0];
        return `Of every 10 kg of ${foodName} used in ${it}, ${tenths} go to food directly; most of the rest is
          ${rest.label}. Click <strong>Produces</strong> to go back.`;
      },
    },
    {
      title: "When it grows", hash: `#${ID}/${FOOD}`, map: "focus",
      holes: [["#view .season", "#view .season-key"], ["#view a.more"]], keep: place,
      ready: () => !!state.seasons?.countries?.[ID]?.[FOOD]?.length && !!q("#view a.more"),
      text: () => {
        const r = state.seasons.countries[ID][FOOD][0];
        const t = state.seasons.meta.thresholds;
        const harvest = MONTHS.filter((_, k) => r.harvest[k] >= t.harvest);
        const sown = MONTHS.filter((_, k) => r.harvest[k] < t.harvest && r.sown[k] >= t.sowing);
        return `A typical year for each crop. ${r.label} is sown in ${listOf(sown)} and harvested in
          ${listOf(harvest)}: one harvest has to last until the next. Then click
          <strong>${linkText("#view a.more")}</strong>`;
      },
    },
    {
      title: "Where it grows", hash: `#${ID}/${FOOD}/where`, map: "full",
      holes: [["#view .q", "#view .partners"], ["#legend"]], keep: place,
      ready: () => !!api.regionsFor(ID, FOOD)?.regions?.length,
      text: () => {
        const [code, , share] = api.regionsFor(ID, FOOD).regions[0];
        return `${api.regionName(code)} alone grows ${pct(share)} of ${it}'s ${foodName}. The map shades
          each region by tonnes per square kilometre${q("#view [data-fields]")
          ? `; <strong>Fields</strong> shows the fields themselves, from satellite images` : ""}.`;
      },
    },
    {
      title: "How do we know?", hash: `#${ID}/${FOOD}`, map: "focus",
      holes: [["#foot .tools"]], keep: place,
      text: () => `Every figure has its sources. <strong>How do we know?</strong> walks through the sum for
        ${it} and how to check it in FAO's own tables; <strong>All the numbers</strong> lists FAO's figures,
        food item by food item.`,
    },
    {
      title: "Your turn", hash: "#", group: "all", map: "full", reveal: true, last: true,
      camera: () => api.showWorld(1600),
      text: () => "",
    },
  ];
}

function endScenario() {
  if (api.state.scenario) api.setScenario(null);
}

// ------------------------------------------------------------------------------------------------
// moving through it

export function startTour(from, a) {
  api = a;
  list = steps();
  if (!root) build();
  root.hidden = false;
  document.body.classList.add("touring");
  go(from);
}

// The end of the tour, early or not: every part of the app comes in, the map gets its colours.
function end() {
  if (at < 0) return;
  list[at]?.leave?.();
  endScenario();
  at = -1;
  busy++;
  cancelAnimationFrame(follow);
  api.setGate(null);
  api.setRoom({ left: 0, top: 0 });
  rule.textContent = "";
  root.classList.add("leaving");
  reveal();
  api.setVeil({ mode: "full", ids: [] });
  setTimeout(() => {
    root.hidden = true;
    root.classList.remove("leaving");
    document.body.classList.remove("touring", "tour-all");
  }, calm() ? 0 : 200);
}

async function go(i) {
  if (i < 0 || i >= list.length) return;
  const from = at;
  if (from >= 0 && from !== i) list[from].leave?.();
  at = i;
  const ticket = ++busy;
  const s = list[i];
  card.classList.add("waiting");
  api.setGate((kind, v) => (kind === "country" ? s.only?.country === v : true));
  rule.textContent = gateRules(s);
  // the card's room beside the panel, kept free of the map's countries (none on the landing and the finale)
  api.setRoom(s.landing || s.reveal ? { left: 0, top: 0 } : phone() ? { left: 0, top: 190 } : { left: 360, top: 0 });
  // What the step is not about goes at once; its own parts come in as the page draws them.
  if (!s.reveal) { document.body.classList.remove("tour-all"); hideAround(s); }
  if (s.group && !api.state.iso3 && api.state.group !== s.group) api.setGroup(s.group);
  if (s.hash && location.hash !== s.hash && !(s.hash === "#" && location.hash === "")) {
    if (s.group) api.state.group = s.group; // the world map keeps the food it shows
    location.hash = s.hash;
  }
  await s.enter?.();
  await ready(s, ticket);
  if (ticket !== busy) return;
  document.documentElement.classList.remove("tour-boot");
  api.setVeil({ mode: s.map ?? "full", ids: [ID] });
  if (s.reveal) { reveal(); document.body.classList.add("tour-all"); } else { document.body.classList.remove("tour-all"); hideAround(s); }
  if (s.camera) s.camera();
  else if (s.map === "focus" && api.state.iso3 === ID) api.flyTo(ID);
  show(s, i);
}

// Wait until the page of a step is drawn and has what the step talks about (data loads on first
// use), at most a few seconds: then the card shows whatever is there.
function ready(s, ticket) {
  const t0 = performance.now();
  return new Promise((done) => {
    const check = () => {
      if (ticket !== busy) { done(); return; }
      const detail = q("#view .detail[data-hash]");
      const page = !s.hash || s.hash === "#" || detail?.dataset.hash === location.hash;
      const parts = (s.holes ?? []).every((h) => q(h[0]));
      let data = true;
      try { data = s.ready ? !!s.ready() : true; } catch { data = false; }
      if ((page && parts && data) || performance.now() - t0 > 5000) done();
      else setTimeout(check, 60);
    };
    check();
  });
}

// Menu entries other than the example's are shown but cannot be chosen.
function gateRules(s) {
  const off = "opacity: .35 !important; pointer-events: none !important;";
  return [
    s.only?.food ? `#foods .list [data-food]:not([data-food="${s.only.food}"]) { ${off} }` : "",
  ].join("\n");
}

function show(s, i) {
  let text;
  try { text = s.text(); } catch (e) { console.error(e); text = ""; }
  // Lit parts below the fold of a scrolling list come into view first.
  for (const h of s.holes ?? []) {
    const el = q(h[0]);
    const box = el && scroller(el)?.getBoundingClientRect();
    const r = el?.getBoundingClientRect();
    if (box && (r.top < box.top || r.bottom > box.bottom)) {
      el.scrollIntoView({ block: r.height > box.height * 0.6 ? "start" : "center", behavior: calm() ? "auto" : "smooth" });
    }
  }
  const n = list.length - 1; // the landing is not counted
  const title = typeof s.title === "function" ? s.title() : s.title;
  card.innerHTML = s.landing ? `
    <h1 id="tour-title">${title}</h1>
    <p>${text}</p>
    <div class="tour-btns">
      <button type="button" class="tour-next" data-tour-next><span>Start the tour</span>${ARROW}</button>
      <button type="button" class="tour-skip" data-tour-end>Go to the map</button>
    </div>` : `
    <div class="tour-top">
      <span class="tour-count">${i} of ${n}</span>
      <button type="button" class="tour-x" data-tour-end aria-label="End the tour">${CLOSE}</button>
    </div>
    <div class="tour-progress" aria-hidden="true"><span style="width:${(i / n) * 100}%"></span></div>
    <h2 id="tour-title">${title}</h2>
    ${text ? `<p>${text}</p>` : ""}
    <div class="tour-btns">${buttons(s, i)}</div>`;
  card.classList.toggle("landing", !!s.landing);
  card.classList.toggle("wide", !!s.last);
  wireCard();
  card.classList.remove("waiting", "in");
  void card.offsetWidth;
  card.classList.add("in");
  place();
  // The page settles after a change (the detail slides in, a list scrolls, the map flies):
  // follow the lit parts for a moment.
  cancelAnimationFrame(follow);
  const t0 = performance.now();
  const loop = () => { place(); if (performance.now() - t0 < 1000) follow = requestAnimationFrame(loop); };
  follow = requestAnimationFrame(loop);
  card.querySelector("[data-tour-next]")?.focus({ preventScroll: true });
}

function buttons(s, i) {
  if (s.last) {
    return `<button type="button" class="tour-next" data-tour-end>Explore the map</button>
      <button type="button" class="tour-back" data-tour-again>Start again</button>`;
  }
  return `<button type="button" class="tour-back" data-tour-back${i <= 1 ? " disabled" : ""}>Back</button>
    <button type="button" class="tour-next" data-tour-next>Next</button>`;
}

function wireCard() {
  card.querySelector("[data-tour-next]")?.addEventListener("click", () => go(at + 1));
  card.querySelector("[data-tour-back]")?.addEventListener("click", () => go(at - 1));
  card.querySelector("[data-tour-again]")?.addEventListener("click", () => go(1));
  for (const b of card.querySelectorAll("[data-tour-end]")) b.addEventListener("click", () => end());
}

// ------------------------------------------------------------------------------------------------
// what is shown: the lit parts and the kept ones, in their places; everything else is invisible

const hidden = () => document.querySelectorAll(".tour-hide, .tour-inert, .tour-mute");
const bareText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());

function hideAround(s) {
  for (const el of hidden()) el.classList.remove("tour-hide", "tour-inert", "tour-mute");
  const all = (sels) => sels.flatMap((x) => [...document.querySelectorAll(x)]);
  const lit = all((s.holes ?? []).flat());
  const keep = all(s.keep ?? []);
  const shown = [...lit, ...keep];
  for (const el of keep) el.classList.add("tour-inert");
  // The panel's lower card is one box: when anything in it shows, its frame stays and only its
  // contents go.
  const lower = ["frame", "view", "foot"].map((x) => document.getElementById(x));
  const lowerUsed = shown.some((x) => lower.some((b) => b.contains(x)));
  const walk = (parent) => {
    for (const el of parent.children) {
      if (SKIP.has(el.id) || ["SCRIPT", "STYLE", "LINK"].includes(el.tagName)) continue;
      el.classList.add("tour-fx");
      if (shown.includes(el)) continue;
      if (shown.some((x) => el.contains(x)) || (lowerUsed && lower.includes(el))) {
        // Loose words in a box that stays ("Figures: …") go with a transparent colour; its
        // elements keep theirs.
        if (bareText(el)) {
          el.classList.remove("tour-mute");
          el.style.setProperty("--tour-c", getComputedStyle(el).color);
          el.classList.add("tour-mute");
        }
        walk(el);
        continue;
      }
      el.classList.add("tour-hide");
    }
  };
  walk(document.body);
}

// The finale: every part comes in, one group after the other.
function reveal() {
  const order = [".head", "#frame", "#view", "#foot", "#foodrail", "#whatif", "#legend"];
  const els = hidden();
  for (const el of els) {
    const k = order.findIndex((sel) => el.closest(sel));
    el.style.transitionDelay = `${calm() ? 0 : 120 + 110 * (k < 0 ? 2 : k)}ms`;
    el.classList.remove("tour-hide", "tour-inert", "tour-mute");
  }
  setTimeout(() => {
    for (const el of document.querySelectorAll(".tour-fx")) { el.style.transitionDelay = ""; if (at < 0) el.classList.remove("tour-fx"); }
  }, 1400);
}

// ------------------------------------------------------------------------------------------------
// the layer: rings around the lit parts and the card

function build() {
  root = document.createElement("div");
  root.id = "tour";
  root.hidden = true;
  root.innerHTML = `<span class="tour-ring"></span><span class="tour-ring"></span>
    <section class="tour-card" role="dialog" aria-modal="false" aria-labelledby="tour-title"></section>`;
  document.body.append(root);
  rings = [...root.querySelectorAll(".tour-ring")];
  card = root.querySelector(".tour-card");
  rule = document.createElement("style");
  document.head.append(rule);

  addEventListener("resize", () => at >= 0 && place());
  document.addEventListener("scroll", () => at >= 0 && place(), true);
  // The app redraws parts of the page as it goes (data arriving, a menu opening): keep what is
  // hidden hidden, and move on when the page now shows what the next step is about.
  new MutationObserver((records) => {
    if (at < 0 || records.every((r) => root.contains(r.target))) return;
    const s = list[at];
    if (!s.reveal) hideAround(s);
    if (list[at + 1]?.reached?.() && !s.reached) go(at + 1);
  }).observe(document.body, { childList: true, subtree: true });
  addEventListener("hashchange", () => {
    if (at < 0) return;
    const next = list[at + 1];
    if (next?.hash && next.hash === location.hash && list[at].hash !== location.hash) go(at + 1);
    else setTimeout(place, 50);
  });
  // Clicks: in the tour, a link goes only where the next step is; a choice in a menu only to the
  // example's; the app's own buttons that would leave the tour do nothing.
  document.addEventListener("click", (e) => {
    if (at < 0 || root.contains(e.target)) return;
    const s = list[at];
    const t = e.target.closest?.("a[href], [data-food], [data-pick], [data-end], [data-go], [data-seller], [data-back], [data-tour]");
    if (!t) return;
    const next = list[at + 1];
    const ok = t.matches("a[href]") ? t.getAttribute("href") === next?.hash
      : t.matches("[data-food]") ? t.dataset.food === s.only?.food
      : false;
    if (ok) return;
    e.preventDefault();
    e.stopPropagation();
    nudge();
  }, true);
  document.addEventListener("keydown", (e) => {
    if (at < 0) return;
    if (e.target.closest?.("input, select, textarea")) { if (e.key === "Escape" && !e.target.value) end(); return; }
    const k = e.key;
    if (k === "Escape") { end(); e.preventDefault(); return; }
    if (["ArrowRight", "ArrowDown", "PageDown"].includes(k)) { go(at + 1); e.preventDefault(); }
    else if (["ArrowLeft", "ArrowUp", "PageUp"].includes(k) && at > 1) { go(at - 1); e.preventDefault(); }
  }, true);
  // Scrolling over the card, or swiping it, moves through the tour.
  let wheel = 0, lastStep = 0;
  card.addEventListener("wheel", (e) => {
    e.preventDefault();
    if (at < 1 || performance.now() - lastStep < 700) return;
    wheel += e.deltaY;
    if (Math.abs(wheel) < 60) return;
    const d = Math.sign(wheel);
    wheel = 0;
    lastStep = performance.now();
    if (d > 0 && at < list.length - 1) go(at + 1);
    else if (d < 0 && at > 1) go(at - 1);
  }, { passive: false });
  let x0 = null;
  card.addEventListener("touchstart", (e) => { x0 = e.touches[0].clientX; }, { passive: true });
  card.addEventListener("touchend", (e) => {
    if (x0 == null || at < 1) return;
    const dx = x0 - e.changedTouches[0].clientX;
    x0 = null;
    if (dx > 60 && at < list.length - 1) go(at + 1);
    else if (dx < -60 && at > 1) go(at - 1);
  });
}

function nudge() {
  card.classList.remove("nudge");
  void card.offsetWidth;
  card.classList.add("nudge");
}

// The nearest ancestor that scrolls (the detail on wide screens, the sheet on phones).
function scroller(el) {
  for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
    const o = getComputedStyle(p).overflowY;
    if ((o === "auto" || o === "scroll") && p.scrollHeight > p.clientHeight) return p;
  }
  return null;
}

// A ring: the parts it lights, as one rectangle, cut to what its scrolling box shows.
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

function place() {
  if (at < 0) return;
  const s = list[at];
  const rects = (s.holes ?? []).map(rectOf).filter(Boolean).slice(0, 2);
  rings.forEach((ring, k) => {
    const r = s.reveal ? null : rects[k];
    ring.classList.toggle("on", !!r);
    if (r) Object.assign(ring.style, { transform: `translate(${r.x}px, ${r.y}px)`, width: `${r.w}px`, height: `${r.h}px` });
  });
  placeCard(s.reveal ? [] : rects, s);
}

// Next to the first lit part where there is room (right, left, below, above); without one, in the
// middle of the map (of the screen on the landing); on phones above or below the sheet.
function placeCard(rects, s) {
  const W = innerWidth, H = innerHeight, gap = 14, m = 10;
  const cw = card.offsetWidth, ch = card.offsetHeight;
  const clampX = (x) => Math.max(m, Math.min(x, W - cw - m));
  const clampY = (y) => Math.max(m, Math.min(y, H - ch - m));
  let x, y;
  const r = rects[0];
  if (phone()) {
    x = (W - cw) / 2;
    const lowest = Math.max(...rects.map((v) => v.y + v.h), 0);
    const highest = Math.min(...rects.map((v) => v.y), H);
    const sheet = document.getElementById("panel").getBoundingClientRect().top;
    y = !rects.length ? (s.landing ? (H - ch) / 2 : Math.max(m, sheet - ch - gap))
      : highest > ch + 2 * m ? Math.min(m + 46, highest - ch - gap) : clampY(lowest + gap);
  } else if (s.landing || s.reveal) {
    const left = s.landing ? 0 : document.getElementById("panel").getBoundingClientRect().right;
    x = left + (W - left - cw) / 2;
    y = (H - ch) / 2;
  } else {
    // In the room kept free beside the panel (the map frames its countries to the right of it),
    // level with the first lit part.
    x = document.getElementById("panel").getBoundingClientRect().right + gap;
    y = r ? clampY(r.y) : (H - ch) / 2;
    // A lit part out on the map (the key at the bottom) is not covered: the card goes above it.
    const hit = rects.find((v) => x < v.x + v.w && x + cw > v.x && y < v.y + v.h && y + ch > v.y);
    if (hit) y = hit.y > H / 2 ? Math.max(m, hit.y - ch - gap) : clampY(hit.y + hit.h + gap);
  }
  // The first placement is not animated: the card appears where it belongs, not from the corner.
  const first = !card.style.transform;
  if (first) card.style.transition = "none";
  card.style.transform = `translate(${Math.round(clampX(x))}px, ${Math.round(clampY(y))}px)`;
  if (first) { void card.offsetWidth; card.style.transition = ""; }
}
