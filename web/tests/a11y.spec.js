// Accessibility of the panel's views (WCAG 2.2 A/AA rules axe-core can test; the map canvas is left
// out, its content is in the panel as text). Plus: switches keep the keyboard focus.
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

const VIEWS = [
  ["world", "", null],
  ["country", "DEU", null],
  ["food with seasons", "DEU/cereals", null],
  ["food with months from abroad", "DEU/vegetables", null],
  ["food with feed", "DEU/meat", null],
  ["trade by money", "DEU/cereals/trade", '[data-mode="value"]'],
  ["where by region", "DEU/cereals/where", null],
  ["where fields", "DEU/cereals/where", '[data-fields="1"]'],
  ["what if", "EGY/cereals", "#legend .whatif"],
  ["how do we know", "about", null],
];

for (const [name, hash, act] of VIEWS) {
  test(`no accessibility violations: ${name}`, async ({ page }) => {
    await page.goto(`./#${hash}`);
    await page.waitForTimeout(1500);
    if (act) { await page.locator(act).click(); await page.waitForTimeout(800); }
    const r = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .exclude(".maplibregl-canvas")
      .analyze();
    expect(r.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.length})`)).toEqual([]);
  });
}

test("switches keep the keyboard focus on the redrawn button", async ({ page }) => {
  for (const [hash, sel] of [["DEU/cereals/where", '[data-fields="1"]'], ["DEU/cereals/trade", '[data-mode="value"]']]) {
    await page.goto(`./#${hash}`);
    await page.waitForTimeout(1200);
    await page.locator(sel).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator(sel)).toBeFocused();
    await expect(page.locator(sel)).toHaveAttribute("aria-pressed", "true");
  }
});
