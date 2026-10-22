// The tour walks the real pages of one country (tour.js): every step must find what it lights and
// say it with figures from the data, never an empty or broken sentence; it must end cleanly.
import { expect, test } from "@playwright/test";

const tourCard = (page) => page.locator(".tour-card");

test("every step of the tour lights its part and says something whole", async ({ page }) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("./#tour");
  await expect(tourCard(page).locator("h2")).toHaveText(/A tour with/);
  const seen = [];
  for (let i = 0; i < 30; i++) {
    const text = await tourCard(page).innerText();
    seen.push(text.split("\n").find((l) => l.trim() && !/^\d+ of \d+$|^Tour$/.test(l.trim())));
    expect(text, `step ${i}`).not.toMatch(/undefined|NaN|null|\[object/);
    if (i > 0) {
      const rings = await page.locator(".tour-ring.on").count();
      expect(rings, `step ${i} (${seen.at(-1)}) lights nothing`).toBeGreaterThan(0);
    }
    const next = tourCard(page).locator("[data-tour-next]");
    if (!(await next.count()) || /Start with/.test(await next.innerText())) break;
    const title = await tourCard(page).locator("h2").innerText();
    await next.click();
    await expect(tourCard(page).locator("h2")).not.toHaveText(title, { timeout: 8000 });
    await expect(tourCard(page)).not.toHaveClass(/waiting/, { timeout: 8000 });
  }
  expect(seen.at(-1)).toBe("Your turn");
  expect(seen.length).toBeGreaterThan(10);
  expect(errors).toEqual([]);
});

test("a click on the lit part moves the tour on, and Esc ends it without leaving a scenario on", async ({ page }) => {
  await page.goto("./#tour");
  const next = () => tourCard(page).locator("[data-tour-next]").click();
  // to the cereals step, whose card lights the balance rows
  for (let i = 0; i < 7; i++) {
    const title = await tourCard(page).locator("h2").innerText();
    await next();
    await expect(tourCard(page).locator("h2")).not.toHaveText(title, { timeout: 8000 });
  }
  await expect(tourCard(page)).not.toHaveClass(/waiting/, { timeout: 8000 });
  await page.locator('#card .sum-row[data-row="imports"]').click();
  await expect(tourCard(page).locator("h2")).toHaveText("Who sells it", { timeout: 8000 });
  // on to the scenario, then Esc
  while ((await tourCard(page).locator("h2").innerText()) !== "What if…?") {
    const title = await tourCard(page).locator("h2").innerText();
    await next();
    await expect(tourCard(page).locator("h2")).not.toHaveText(title, { timeout: 8000 });
  }
  await expect(page.locator("#whatif .badge")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator("#tour")).toBeHidden();
  await expect(page.locator("#whatif .badge")).toHaveCount(0);
});
