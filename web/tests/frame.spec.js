// The panel's frame (place, food, four-row card) must stand still while the reader clicks through
// a country: the same four rows in the same place for every food and every question, and back
// going up one step at a time.
import { expect, test } from "@playwright/test";

const card = (page) => page.locator("#card");
async function cardTop(page) {
  return Math.round((await card(page).boundingBox()).y);
}

test("the card keeps its place and its four rows", async ({ page }) => {
  await page.goto("./#DEU");
  await expect(card(page).locator(".sum-row")).toHaveCount(4);
  const top = await cardTop(page);
  const steps = [
    () => page.locator("#foods [data-food='fruit']").click(),
    () => card(page).locator("[data-row='imports']").click(),
    () => card(page).locator("[data-row='exports']").click(),
    () => card(page).locator("[data-row='used']").click(),
    () => page.locator("#foods [data-food='cereals']").click(),
    () => page.locator("#foods [data-food='fish']").click(),
    () => page.locator("#foods [data-food='all']").click(),
    () => page.goto("./#POL/meat"),
    () => page.goto("./#JPN"),
    () => page.goto("./#EU27/dairy/used"),
  ];
  for (const step of steps) {
    await step();
    await page.waitForTimeout(150);
    await expect(card(page).locator(".sum-row")).toHaveCount(4);
    expect(await cardTop(page), `card moved after ${step}`).toBe(top);
  }
});

test("back goes up one step at a time", async ({ page }) => {
  await page.goto("./#DEU/fruit/sells");
  for (const want of ["#DEU/fruit", "#DEU", ""]) {
    await page.locator("#up").click();
    await expect.poll(() => page.evaluate(() => location.hash)).toBe(want);
  }
});
