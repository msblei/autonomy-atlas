// A phone: the food menu opens as one list with every food in view, the sheet says when it goes
// on below, and the chart's labels stay inside the panel (issue #4, an iPhone).
import { expect, test } from "@playwright/test";

test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

test("the food menu opens over the map with every food in view, and closes on a choice", async ({ page }) => {
  await page.goto("./");
  await expect(page.locator("#legend")).toContainText("would last");
  const current = page.locator("#foods .current");
  await expect(current).toBeVisible();
  await expect(current).toContainText("All food");
  await expect(page.locator("#foods .list")).toBeHidden();
  await current.click();
  const foods = page.locator("#foods .list [data-food]");
  await expect(foods).toHaveCount(15);
  // All of them above the sheet, none to scroll to.
  const rail = await page.locator("#foodrail").boundingBox();
  const sheet = await page.locator("#panel").boundingBox();
  expect(rail.y + rail.height).toBeLessThan(sheet.y);
  for (const b of await foods.all()) {
    const box = await b.boundingBox();
    expect(box.y + box.height).toBeLessThanOrEqual(rail.y + rail.height + 1);
  }
  await page.locator("#foods [data-food='pulses']").click();
  await expect(page.locator("#foods .list")).toBeHidden();
  await expect(current).toContainText("Pulses");
  await expect(page.locator("#legend")).toContainText("pulses");
});

test("the sheet fades at its bottom edge while there is more below", async ({ page }) => {
  await page.goto("./#DEU/cereals");
  await expect(page.locator("#view")).toContainText("Year by year");
  const panel = page.locator("#panel");
  await expect(panel).toHaveClass(/more/);
  await panel.evaluate((el) => { el.scrollTop = el.scrollHeight; });
  await expect(panel).not.toHaveClass(/more/);
  await panel.evaluate((el) => { el.scrollTop = 0; });
  await expect(panel).toHaveClass(/more/);
});

test("a chart label on the first year is not cut off at the panel's edge", async ({ page }) => {
  // Croatia's oilseeds: lowest in the first year, labelled "year + 3 mo" under that point.
  await page.goto("./#HRV/oilseeds");
  const label = page.locator(".spark .tick", { hasText: "year + 3 mo" });
  await expect(label).toBeVisible();
  // The detail is drawn again as more data arrives, so measure until the page has settled.
  await expect(async () => {
    const svg = await page.locator(".spark svg").boundingBox();
    const box = await label.boundingBox();
    expect(svg && box, "chart and label drawn").toBeTruthy();
    const where = `label ${box.x.toFixed(1)}–${(box.x + box.width).toFixed(1)}, drawing ${svg.x.toFixed(1)}–${(svg.x + svg.width).toFixed(1)}`;
    expect(box.x, where).toBeGreaterThanOrEqual(svg.x - 1);
    expect(box.x + box.width, where).toBeLessThanOrEqual(svg.x + svg.width + 1);
  }).toPass({ timeout: 10_000 });
});
