// The built site (vite build, served by vite preview), not the dev server the other tests use: the
// build inlines the stylesheet and splits off the map library, which the dev server never does,
// and a slip there (a file a chunk's loader needs but the build did not write) shows only here.
import { expect, test } from "@playwright/test";

test("the built site paints the map and the start page, and every request succeeds", async ({ page }) => {
  const failed = [];
  page.on("response", (r) => { if (r.status() >= 400) failed.push(`${r.status()} ${r.url()}`); });
  page.on("requestfailed", (r) => failed.push(`${r.failure()?.errorText} ${r.url()}`));
  await page.goto("./");
  await expect(page.locator("#view")).not.toBeEmpty();
  await expect(page.locator("#legend")).toContainText("would last");
  // The grey land from index.html goes once the map has drawn its colours.
  await expect(page.locator("#land")).toHaveCount(0, { timeout: 30_000 });
  expect(failed).toEqual([]);
  // What the build is for: no stylesheet to fetch before the first paint, the map library on its own.
  const html = await page.content();
  expect(html).not.toMatch(/<link[^>]+rel="stylesheet"/);
  expect(html).toMatch(/modulepreload[^>]+maplibre/);
});
