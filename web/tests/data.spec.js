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

test("headline per country is the feed-adjusted calorie figure, worded by calendar.js", async ({ page }) => {
  for (const id of SAMPLE) {
    await open(page, id);
    const k = C[id].indicators?.all?.kcal ?? {};
    const p = { ssr: k.feed_ssr, withheld: k.withheld };
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
        // contradictory balances say so; one withheld by review gives the reviewed reason; one
        // withheld as implausible names every second reading with its share (plausible.py)
        const w = ind.withheld;
        if (w.reason === "implausible") {
          await expect(view(page)).toContainText("add up, but");
          for (const t of w.plausibility) {
            await expect(view(page)).toContainText(t.ssr_alt == null ? "nothing left for use at home"
              : `produce ${Math.round(t.ssr_alt)}% of what it uses`);
          }
        } else {
          await expect(view(page)).toContainText(w.reason === "reviewed" ? w.note : "do not add up");
        }
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
    // all food with a calorie balance: the card shows that (FAO's balance), not the trade records
    if (group === "all" && !C[iso3].indicators?.all?.kcal?.balance) {
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
  // Spain's sugar exports: the balance also counts sugar inside processed goods. (The United
  // Kingdom's, the earlier example, is withheld as implausible since 2026-10-18.)
  const t = trade.countries.ESP.sugar.exports, b = C.ESP.indicators.sugar.components_kt.exports;
  expect(t[0] / 1000).toBeLessThan(0.5 * b);
  await open(page, "ESP/sugar/sells");
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
  await expect(box).toContainText(`${Math.round(f.imported_pct)}% of the protein in Germany's animal feed other than grass and hay`);
  await expect(box).toContainText(`its own meat would last ${forHowLong(f.meat_ssr)}`);
  await open(page, "DEU/dairy"); // milk: only for the bought share of the cows' diet (GLEAM)
  await expect(box).toContainText(`Cattle get about ${Math.round(f.c_cattle)}% of their protein`);
  await expect(box).toContainText(`its own dairy would last ${forHowLong(f.dairy_ssr)}`);
});

test("what if: scenarios from the button on the map, a badge while one is on", async ({ page }) => {
  const sc = JSON.parse(readFileSync(new URL("../public/data/scenario.json", import.meta.url), "utf8"));
  const v = sc.scenarios.black_sea.EGY.cereals;
  await open(page, "EGY/cereals");
  await expect(view(page)).not.toContainText("would be missing"); // no scenario text until one is on
  await page.locator("#whatif [data-open]").click();
  await page.locator('#whatif [data-pick="black_sea"]').click();
  await expect(page.locator("#whatif .badge")).toContainText("The Black Sea countries stop selling grain");
  await expect(page.locator("#legend")).toContainText("would be missing");
  await expect(view(page)).toContainText(`${Math.round(v)}% of the cereals it uses would be missing`);
  await page.locator("#whatif [data-end]").click(); // and off again
  await expect(page.locator("#whatif .badge")).toHaveCount(0);
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

test("all food: countries are compared on the headline, the figure the map shows", async ({ page }) => {
  await open(page, "DEU");
  const cmp = view(page).locator("h3", { hasText: "compare?" }).locator("xpath=following-sibling::div[1]");
  const top = await cmp.locator("ol.rank").nth(1).locator("a").evaluateAll((as) => as.map((a) => a.getAttribute("href").slice(1)));
  const menu = (id) => C[id].indicators?.all?.kcal?.feed_ssr;
  const pool = Object.keys(C).filter((id) => id !== "EU27" && menu(id) != null).sort((a, b) => menu(b) - menu(a));
  expect(top).toEqual(pool.slice(0, 5));
});

test("crops whose calendar fails the wheat-harvest check are named, not drawn", async ({ page }) => {
  const sea = JSON.parse(readFileSync(new URL("../public/data/seasons.json", import.meta.url), "utf8"));
  const out = sea.left_out.DEU.pulses; // GGCMI's peas: "ripe 31 October" (methodology, "Seasons")
  expect(out).toContain("Peas");
  await open(page, "DEU/pulses");
  await expect(view(page)).toContainText("Not shown: peas");
  await expect(view(page).locator(".season .crop", { hasText: "Peas" })).toHaveCount(0);
});

test("the crop map says which countries it leaves blank, with both areas", async ({ page }) => {
  const cm = JSON.parse(readFileSync(new URL("../public/data/cropmap.json", import.meta.url), "utf8"));
  const r = cm.groups.potatoes_roots.left_out.POL; // EUCROPMAP finds about a quarter of Poland's potatoes
  await open(page, "POL/potatoes_roots/where");
  await expect(view(page).locator('[data-fields="1"]')).toHaveCount(0); // no blank map to switch to
  await view(page).locator("details.notes summary").last().click();
  await expect(view(page)).toContainText(`finds ${Math.round(r.map_kha)} thousand hectares`);
  await expect(view(page)).toContainText(`${Math.round(r.eurostat_kha)} thousand`);
  await open(page, "DEU/potatoes_roots/where"); // Germany is drawn; the notes name the blank ones
  await view(page).locator('[data-fields="1"]').click();
  await view(page).locator("details.notes summary").last().click();
  await expect(view(page)).toContainText("Poland");
});

test("a withheld food shows its band when every reading agrees, never a figure", async ({ page }) => {
  // Ireland's dairy: both readings of FAO's figures are far above what it uses.
  const r = C.IRL.indicators.dairy.withheld.range;
  expect(r[0]).toBeGreaterThan(104.17);
  await open(page, "IRL");
  const row = view(page).locator(".foodlist li", { hasText: "Dairy" });
  await expect(row).toContainText("more than a year");
});

test("no FAO balance: Japan shows its own statistic, with its source", async ({ page }) => {
  const nat = (await (await page.request.get("/data/ssr.json")).json()).meta.national.JPN;
  await open(page, "JPN");
  await expect(view(page).locator(".answer")).toHaveText(`${forHowLong(nat.value)}.`);
  await expect(view(page)).toContainText("Ministry of Agriculture, Forestry and Fisheries of Japan");
});

test("no balance (Japan): shipments are labelled as weight shipped, not a balance", async ({ page }) => {
  await open(page, "JPN");
  await expect(page.locator("#card")).toContainText("Shipped in");
  await expect(page.locator("#card .sum-row[data-row=imports]")).toHaveAttribute("title", /by weight as shipped/);
});

test("all food: the card is a calorie balance, produced as in the headline", async ({ page }) => {
  const k = C.CHE.indicators.all.kcal;
  await open(page, "CHE");
  const fmtK = (v) => `${Math.round(v).toLocaleString("en-GB")} kcal /person/day`;
  await expect(page.locator("#card .sum-row[data-row=food]")).toContainText(fmtK(k.balance.produced));
  await expect(page.locator("#card .sum-row[data-row=used]")).toContainText(fmtK(k.balance.used));
  expect(Math.abs(k.balance.produced - k.feed_ssr * k.balance.used / 100)).toBeLessThan(1);
});

test("every page links the legal notice, the privacy policy and an error report", async ({ page }) => {
  for (const hash of ["about", "DEU", "DEU/meat/trade"]) {
    await open(page, hash);
    await expect(page.locator("#foot .legal a[href='#legal']")).toHaveCount(1);
    await expect(page.locator("#foot .legal a[href='#privacy']")).toHaveCount(1);
    await expect(page.locator("#foot .legal a[href^='mailto:']")).toHaveCount(1);
  }
  await open(page, "legal");
  await expect(view(page).locator("h2")).toHaveText("Legal notice");
  await expect(view(page)).toContainText("Altendorf");
  await open(page, "privacy");
  await expect(view(page).locator("h2")).toHaveText("Privacy policy");
  await expect(view(page)).toContainText("built with the help of an AI system");
  await expect(page.locator("#frame")).toBeHidden();
  await expect(view(page)).not.toContainText("As of");
  await open(page, "DEU/meat");
  await open(page, "legal");
  await view(page).locator("[data-back]").click();
  await expect(page).toHaveURL(/#DEU\/meat$/);
});

test("what if one country stopped selling: from its sales page, figures as exported", async ({ page }) => {
  const bra = JSON.parse(readFileSync(new URL("../public/data/whatif/BRA.json", import.meta.url), "utf8"));
  await open(page, "BRA/stimulants/sells");
  await page.locator(".whatif-go").click();
  await expect(page.locator("#whatif .badge")).toContainText("Brazil stops selling");
  await open(page, "DEU/stimulants");
  await expect(view(page)).toContainText(`${Math.round(bra.DEU.stimulants)}% of the coffee, cocoa, tea it uses would be missing`);
});

test("what if: a scenario shows its own food", async ({ page }) => {
  await open(page, "DEU");
  await page.locator("#whatif [data-open]").click();
  await page.locator('#whatif [data-pick="cocoa"]').click();
  await expect(page).toHaveURL(/#DEU\/stimulants$/);
  await expect(page.locator("#legend")).toContainText("coffee, cocoa, tea");
});

test("all food withheld but more than a year on any reading (Ukraine): the band, not a blank", async ({ page }) => {
  const u = C.UKR.indicators.all.kcal.withheld.range;
  expect(u[0] * (1 - C.UKR.feed.imported_pct / 100)).toBeGreaterThan(104.17);
  await open(page, "UKR");
  await expect(view(page)).toContainText("produces more calories than it uses");
});
