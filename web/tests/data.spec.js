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
  await page.waitForFunction(() => document.querySelector("#view")?.textContent.trim().length > 0);
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
        await expect(view(page)).toContainText("do not add up");
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
