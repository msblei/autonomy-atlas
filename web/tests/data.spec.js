// The numbers on screen against the numbers in web/public/data: every figure shown must be the
// precomputed one, rounded the documented way; withheld figures must appear nowhere but in their
// own explanation. A fixed sample of countries plus a seeded random one.
import { readFileSync } from "node:fs";
import { expect, test } from "@playwright/test";
import { forHowLong } from "../src/calendar.js";

const data = JSON.parse(readFileSync(new URL("../public/data/ssr.json", import.meta.url), "utf8"));
const C = data.countries;
const GROUPS = data.groups.map((g) => g.key).filter((k) => k !== "all");
const FIXED = ["DEU", "FRA", "NLD", "UKR", "EU27", "NGA", "JOR", "URY", "ISL", "IRL", "LUX", "USA", "TUR", "NOR"];
let seed = 20261016;
const rand = () => ((seed = (seed * 1103515245 + 12345) % 2 ** 31) / 2 ** 31);
const others = Object.keys(C).filter((k) => !FIXED.includes(k) && C[k].indicators?.all);
const SAMPLE = [...FIXED, ...Array.from({ length: 20 }, () => others[Math.floor(rand() * others.length)])];

const view = (page) => page.locator("#view");
async function open(page, hash) {
  await page.goto(`./#${hash}`);
  // The detail is handed over with a short fade: wait for the one that belongs to this address.
  await page.waitForFunction((h) => {
    const d = document.querySelector("#view .detail");
    return d?.dataset.hash === h && !d.classList.contains("leave") && d.textContent.trim().length > 0;
  }, `#${hash}`);
}

test("headline per country is the protein figure, worded by calendar.js", async ({ page }) => {
  for (const id of SAMPLE) {
    await open(page, id);
    const p = C[id].indicators?.all?.protein ?? {};
    const answer = view(page).locator(".answer");
    if (p.ssr == null) {
      await expect(answer).toHaveCount(0);
      if (p.withheld) await expect(view(page)).toContainText("contradict themselves");
    } else {
      await expect(answer).toHaveText(`${forHowLong(p.ssr)}.`);
    }
  }
});

test("food pages: figure, withheld explanation, and the receipt's sum", async ({ page }) => {
  for (const id of SAMPLE.slice(0, 16)) {
    for (const g of GROUPS) {
      const ind = C[id].indicators?.[g];
      if (!ind) continue;
      await open(page, `${id}/${g}`);
      const v = ind.tonnes?.ssr;
      if (ind.withheld) {
        // contradictory balances say so; one withheld by review gives the reviewed reason
        await expect(view(page)).toContainText(ind.withheld.reason === "reviewed" ? ind.withheld.note : "do not add up");
        await expect(view(page).locator(".answer")).toHaveCount(0);
        await expect(view(page)).not.toContainText("Was it always like this?");
      } else if (v != null) {
        await expect(view(page).locator(".answer")).toHaveText(`${forHowLong(v)}.`);
        // a second source's disagreement is shown exactly where the data has one
        const note = view(page).locator(".aside", { hasText: "Another source disagrees" });
        await expect(note).toHaveCount(ind.usda ? 1 : 0);
        for (const d of ind.usda ?? []) await expect(note).toContainText(`${Math.round(d.usda)}%`);
        await open(page, `${id}/${g}/sources`);
        await expect(view(page).locator(".sum strong")).toHaveText(`${Math.round(v)}%`);
      }
    }
  }
});

test("rankings never list a withheld figure and agree with the data", async ({ page }) => {
  const members = data.meta.eu_members;
  for (const g of GROUPS) {
    await open(page, `DEU/${g}`);
    const hrefs = await view(page).locator("ol.rank a").evaluateAll((as) => as.map((a) => a.getAttribute("href")));
    const ids = hrefs.map((h) => h.slice(1).split("/")[0]);
    for (const id of ids) {
      expect(C[id].indicators?.[g]?.withheld, `${id}/${g} is withheld but ranked`).toBeUndefined();
      expect(C[id].indicators?.[g]?.components_kt, `${id}/${g} ranked without figures`).toBeTruthy();
    }
    // "Most to spare": the five largest (production - supply) per person among countries shown.
    const pc = (id) => {
      const c = C[id].indicators?.[g]?.components_kt;
      const pop = C[id].population_k;
      return c && pop && c.production != null && c.supply != null ? ((c.production - c.supply) * 1000) / pop : null;
    };
    const pool = Object.keys(C).filter((id) => id !== "EU27" || !members.length).map((id) => [id, pc(id)])
      .filter(([, v]) => v != null).sort((a, b) => b[1] - a[1]);
    if (ids.length >= 5 && pool.length >= 10) {
      const zoomedOut = ids.includes("EU27");
      const want = pool.filter(([id]) => (zoomedOut ? !members.includes(id) : id !== "EU27")).slice(0, 5).map(([id]) => id);
      expect(ids.slice(0, 5), `top 5 for ${g}`).toEqual(want);
    }
  }
});

test("withheld trade flows are never shown, and say so", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  const withheld = trade.meta.withheld;
  expect(withheld.length).toBeGreaterThan(0);
  for (const [iso3, group, flow] of withheld) {
    if (!C[iso3]) continue; // trade-only places have no page of their own
    await open(page, `${iso3}/${group}/${flow === "imports" ? "trade" : "sells"}`);
    await expect(view(page)).toContainText("No reliable trading partners");
    await expect(view(page).locator("ol.partners")).toHaveCount(0);
    if (group === "all") {
      const row = page.locator(`#card [data-row="${flow}"] .value`);
      await expect(row).toHaveText("no reliable data");
    }
  }
});

test("unusual years are drawn apart in the year-by-year chart", async ({ page }) => {
  const marked = Object.entries(C).flatMap(([iso3, c]) =>
    Object.entries(c.trend_unusual ?? {}).map(([g, ys]) => [iso3, g, ys]));
  expect(marked.length).toBeGreaterThan(0);
  for (const [iso3, g, ys] of marked) {
    if (g === "all" || C[iso3].indicators?.[g]?.withheld) continue;
    await open(page, `${iso3}/${g}`);
    const odd = view(page).locator(".spark .odd");
    if (await view(page).locator(".spark").count()) await expect(odd).toHaveCount(ys.length);
    for (const y of ys) await expect(view(page)).toContainText(String(y));
  }
});

test("trade pages say when the records hold under half of the balance", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  // The United Kingdom's sugar exports: the balance also counts sugar inside processed goods.
  const t = trade.countries.GBR.sugar.exports, b = C.GBR.indicators.sugar.components_kt.exports;
  expect(t[0] / 1000).toBeLessThan(0.5 * b);
  await open(page, "GBR/sugar/sells");
  await expect(view(page)).toContainText("The split by country is of the records");
  await open(page, "DEU/fruit/trade"); // records cover the balance: no such line
  await expect(view(page)).not.toContainText("The split by country is of the records");
});

test("purchases from Russia and Ukraine are summed from the listed partners", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  const [total, parts] = trade.countries.TUR.cereals.imports;
  const share = Math.round(parts.filter(([p]) => p === "RUS" || p === "UKR").reduce((a, [, t]) => a + t, 0) / total * 100);
  expect(share).toBeGreaterThan(1);
  await open(page, "TUR/cereals/trade");
  await expect(view(page)).toContainText(`From Russia and Ukraine: ${share}%`);
});

test("all the numbers shows the published import and export concentration", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  const h = trade.concentration.TUR.cereals;
  await open(page, "TUR/cereals/table");
  const fmt = (v) => (v == null ? "–" : v.toLocaleString("en-GB"));
  await expect(view(page)).toContainText(`${fmt(h.imports)} / ${fmt(h.exports)}`);
});

test("fish partners: Eurostat for EU countries, BACI elsewhere, never traced", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  expect(trade.meta.group_source.fish).toEqual({ eu: "eurostat_comext", other: "cepii_baci" });
  const [total, parts] = trade.countries.DEU.fish.imports;
  await open(page, "DEU/fish/trade");
  await expect(view(page).locator("ol.partners li").first()).toContainText(
    `${Math.round((parts[0][1] / total) * 100)}%`);
  await expect(view(page).locator('[data-mode="grown"]')).toHaveCount(0);
  await expect(page.locator("#foot")).toContainText("Eurostat Comext");
  // all food leaves fish out, so it compares across countries
  for (const id of Object.keys(trade.countries)) expect(trade.countries[id].fish?.grown).toBeUndefined();
  // outside the EU: CEPII BACI, also not traced
  const [usTotal, usParts] = trade.countries.USA.fish.imports;
  await open(page, "USA/fish/trade");
  await expect(view(page).locator("ol.partners li").first()).toContainText(
    `${Math.round((usParts[0][1] / usTotal) * 100)}%`);
  await expect(view(page).locator('[data-mode="grown"]')).toHaveCount(0);
  await expect(page.locator("#foot")).toContainText("CEPII BACI");
});

test("money paid and earned: euros from Eurostat for EU countries, tonnes stay in the card", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  const v = trade.value.countries.DEU.cereals;
  await open(page, "DEU/cereals/trade");
  const card = await page.locator("#card").innerText();
  await view(page).locator('[data-mode="value"]').click();
  await expect(view(page).locator('[data-mode="value"]')).toHaveAttribute("aria-pressed", "true");
  const [total, parts] = v.imports;
  await expect(view(page).locator("ol.partners li").first()).toContainText(nameShare(parts[0], total));
  await expect(view(page)).toContainText(`Paid abroad: €${(total / 1e6).toFixed(1)} billion`);
  await expect(page.locator("#foot")).toContainText("Eurostat Comext");
  expect(await page.locator("#card").innerText()).toBe(card);
  // a country outside the EU has no money view and falls back to tonnes
  await open(page, "USA/cereals/trade");
  await expect(view(page).locator('[data-mode="value"]')).toHaveCount(0);
  await expect(page.locator("#foot")).toContainText("FAO");
});

function nameShare([, amount], total) {
  const p = (amount / total) * 100;
  return `${p < 1 ? "<1" : Math.round(p)}%`;
}

test("crop calendars: the strip shows the exported months in a typical year", async ({ page }) => {
  const sea = JSON.parse(readFileSync(new URL("../public/data/seasons.json", import.meta.url), "utf8"));
  const rows = sea.countries.DEU.cereals;
  const t = sea.meta.thresholds;
  await open(page, "DEU/cereals");
  const strip = view(page).locator(".season:not(.imports)");
  await expect(strip.locator(".srow:not(.months)")).toHaveCount(rows.length);
  for (const [i, r] of rows.entries()) {
    const row = strip.locator(".srow:not(.months)").nth(i);
    await expect(row.locator(".crop")).toHaveText(r.label);
    for (let k = 0; k < 12; k++) {
      const want = r.harvest[k] >= t.harvest ? "harvest" : r.sown[k] >= t.sowing ? "sowing" : r.growing[k] >= t.growing ? "growing" : null;
      const cls = await row.locator(".m").nth(k).getAttribute("class");
      expect(cls.trim(), `${r.label} month ${k + 1}`).toBe(want ? `m ${want}` : "m");
    }
  }
  await expect(view(page)).toContainText("a typical year");
  await open(page, "DEU/fruit"); // no crop calendar for fruit (its months are purchases, below)
  await expect(view(page).locator(".season:not(.imports)")).toHaveCount(0);
});

test("where it is grown: regions and shares as exported, reached from the food page", async ({ page }) => {
  const reg = JSON.parse(readFileSync(new URL("../public/data/regions.json", import.meta.url), "utf8"));
  const r = reg.countries.DEU.cereals.regions;
  await open(page, "DEU/cereals");
  await view(page).locator("a.more", { hasText: "Where in Germany" }).click();
  await expect.poll(() => page.evaluate(() => location.hash)).toBe("#DEU/cereals/where");
  const first = view(page).locator("ol.partners li").first();
  await expect(first).toContainText(reg.names[r[0][0]]);
  await expect(first).toContainText(`${Math.round(r[0][2])}%`);
  await expect(page.locator("#foot")).toContainText("Eurostat crop statistics by region");
  await page.locator("#up").click(); // back goes to the food page
  await expect.poll(() => page.evaluate(() => location.hash)).toBe("#DEU/cereals");
});

test("when it comes from abroad: products, shaded months and leading suppliers as exported", async ({ page }) => {
  const imo = JSON.parse(readFileSync(new URL("../public/data/import_months.json", import.meta.url), "utf8"));
  const rows = imo.countries.DEU.vegetables;
  await open(page, "DEU/vegetables");
  const box = view(page).locator(".season.imports");
  await expect(box.locator(".srow:not(.months)")).toHaveCount(rows.length);
  const first = box.locator(".srow:not(.months)").first();
  await expect(first.locator(".crop")).toHaveText(imo.names[rows[0].hs4]);
  const k = rows[0].share.indexOf(Math.max(...rows[0].share));
  await expect(first.locator(".m").nth(k)).toHaveClass(/s4/); // the busiest month is darkest
  const lead = rows[0].top[0][0];
  await expect(box.locator(".who").first()).toContainText(lead === "ESP" ? "Spain" : lead);
  await open(page, "USA/vegetables"); // outside the EU: no monthly trade figures
  await expect(view(page).locator(".season.imports")).toHaveCount(0);
});

test("fields: the crop map image replaces the regions' shading, with its own legend and source", async ({ page }) => {
  const cm = JSON.parse(readFileSync(new URL("../public/data/cropmap.json", import.meta.url), "utf8"));
  await open(page, "DEU/cereals/where");
  await view(page).locator('[data-fields="1"]').click();
  await expect(page.locator("#legend")).toContainText(`Share of the land under cereals, ${cm.meta.year}`);
  await expect(page.locator("#foot")).toContainText(`JRC EUCROPMAP ${cm.meta.year}`);
  const img = await page.request.get(`data/${cm.groups.cereals.file}`);
  expect(img.ok()).toBe(true);
  await view(page).locator('[data-fields="0"]').click();
  await expect(page.locator("#legend")).toContainText("tonnes per km²");
});

test("feed from abroad: the imported share and the feed-adjusted meat as exported", async ({ page }) => {
  const f = C.DEU.feed;
  await open(page, "DEU/meat");
  const box = view(page);
  await expect(box).toContainText(`${Math.round(f.imported_pct)}% of the protein in Germany's animal feed`);
  await expect(box).toContainText(`its own meat would last ${forHowLong(f.meat_ssr)}`);
  await open(page, "DEU/dairy"); // milk is not adjusted, only explained
  await expect(box).toContainText("cows live mostly on grass");
  await expect(box).not.toContainText("would last for about");
});

test("what if Russia and Ukraine stopped selling: the map key switches and the page says the share", async ({ page }) => {
  const sc = JSON.parse(readFileSync(new URL("../public/data/scenario.json", import.meta.url), "utf8"));
  const v = sc.countries.EGY.cereals;
  await open(page, "EGY/cereals");
  await expect(view(page)).toContainText(`Egypt would lack ${Math.round(v)}% of the cereals it uses`);
  await page.locator("#legend .whatif").click();
  await expect(page.locator("#legend")).toContainText("grown in Russia or Ukraine");
  await page.locator("#legend .whatif").click(); // and back
  await expect(page.locator("#legend")).toContainText("would last");
});

test("a trade flow withheld by review says why in words", async ({ page }) => {
  const trade = JSON.parse(readFileSync(new URL("../public/data/trade.json", import.meta.url), "utf8"));
  const w = trade.meta.withheld.find((r) => r.length > 5);
  expect(w).toBeTruthy();
  await open(page, `${w[0]}/${w[1]}/${w[2] === "imports" ? "trade" : "sells"}`);
  await view(page).locator("details.notes summary").click();
  await expect(view(page)).toContainText(w[5].slice(0, 40));
});

test("how do we know: every source is credited with its licence", async ({ page }) => {
  await page.goto("./#about");
  const list = page.locator("ul.sources li");
  const n = Object.keys(data.meta.sources).length - 1; // the borders are credited under "The map"
  await expect(list).toHaveCount(n);
  for (const key of ["eumofa_cf", "ggcmi_calendar", "isimip_landuse", "feedipedia", "cepii_baci"]) {
    await expect(page.locator("#view")).toContainText(data.meta.sources[key].title);
  }
});
