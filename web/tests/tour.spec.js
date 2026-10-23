// The tour walks the real pages of one country (tour.js), showing only what each step is about:
// every step must find what it lights and say it with figures from the data; the clicks the
// example needs move it on, others do nothing; at the end every part of the app is back.
import { expect, test } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } }); // a first visit

const tourCard = (page) => page.locator(".tour-card");
const title = (page) => tourCard(page).locator("h1, h2");
async function next(page) {
  const before = await title(page).innerText();
  await tourCard(page).locator("[data-tour-next]").first().click();
  await expect(title(page)).not.toHaveText(before, { timeout: 8000 });
  await expect(tourCard(page)).not.toHaveClass(/waiting/, { timeout: 8000 });
}
const visible = (page, sel) => page.locator(sel).first().evaluate((el) => {
  for (let e = el; e; e = e.parentElement) {
    const s = getComputedStyle(e);
    if (s.visibility === "hidden" || s.opacity === "0") return false;
  }
  return true;
});

test("a first visit opens with the tour or the map; the map shows the whole app", async ({ page }) => {
  await page.goto("./");
  await expect(title(page)).toHaveText("Could your country feed itself?");
  await expect(tourCard(page).locator("[data-tour-next]")).toHaveText(/Start the tour/);
  await expect.poll(() => visible(page, "#foodrail")).toBe(false);
  await tourCard(page).locator("[data-tour-end]").click();
  await expect(page.locator("#tour")).toBeHidden();
  await expect.poll(() => visible(page, "#foodrail")).toBe(true);
  await expect.poll(() => visible(page, ".head .search")).toBe(true);
  // a second visit goes straight to the map
  await page.goto("./");
  await expect(page.locator("#view .hero")).toBeVisible();
  await expect(page.locator("#tour")).toHaveCount(0);
});

test("every step shows its part and says something whole, and the end brings the app back", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("./#tour");
  await expect(title(page)).toHaveText("The map");
  const seen = [];
  for (let i = 0; i < 30; i++) {
    const text = await tourCard(page).innerText();
    seen.push(await title(page).innerText());
    expect(text, `step ${seen.at(-1)}`).not.toMatch(/undefined|NaN|null|\[object/);
    if (await tourCard(page).locator("[data-tour-again]").count()) break;
    expect(await page.locator(".tour-ring.on").count(), `${seen.at(-1)} lights nothing`).toBeGreaterThan(0);
    await next(page);
  }
  expect(seen.at(-1)).toBe("Your turn");
  expect(seen.length).toBeGreaterThan(9);
  await tourCard(page).getByRole("button", { name: "Explore the map" }).click();
  await expect(page.locator("#tour")).toBeHidden();
  await expect(page.locator(".tour-hide")).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("the example's clicks move the tour on, others do nothing; Esc ends it", async ({ page }) => {
  await page.goto("./#tour");
  await next(page); // to "Pick a country"
  await expect(title(page)).toHaveText("Pick a country");
  // only Italy can be found
  await page.locator("#country").fill("Fr");
  await expect(page.locator("#country-list [data-id]")).toHaveCount(0);
  await page.locator("#country").fill("Ita");
  await page.locator("#country-list [data-id='ITA']").click();
  await expect(title(page)).toHaveText("Italy", { timeout: 8000 });
  await next(page); await next(page); // to the food menu
  await expect(title(page)).toHaveText("Choose a food");
  await page.locator("#foods .current").click();
  await expect(page.locator("#foods [data-food='fruit']")).toHaveCSS("pointer-events", "none");
  await page.locator("#foods [data-food='cereals']").click();
  await expect(title(page)).toHaveText("Cereals", { timeout: 8000 });
  await expect(tourCard(page)).not.toHaveClass(/waiting/, { timeout: 8000 });
  // a row the example does not need does nothing; "Buys abroad" goes on
  await page.locator('#card .sum-row[data-row="exports"]').click({ force: true });
  await expect(page).toHaveURL(/#ITA\/cereals$/);
  await page.locator('#card .sum-row[data-row="imports"]').click();
  await expect(title(page)).toHaveText("Who sells it", { timeout: 8000 });
  await page.keyboard.press("Escape");
  await expect(page.locator("#tour")).toBeHidden();
  await expect(page.locator(".tour-hide")).toHaveCount(0);
});
