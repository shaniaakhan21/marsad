import { test, expect } from "@playwright/test";

/**
 * Systemic exposure tab — loads automatically on navigation, no button.
 *
 * The three "Live UAE government data" tiles are pinned to CACHED by the
 * cache fixtures seeded in e2e/support/seed-cache.mjs (core is started with
 * an unreachable proxy, so nothing here ever calls a live government portal).
 * The riskiest-vendor and publishing-rule numbers below follow deterministically
 * from services/core/marsad_core/services/concentration.py and
 * services/core/marsad_core/data/uae_open_data.py given the seeded dependency
 * data: UAESWITCH/Jaywan scores highest (all 3 firms, no substitute), and
 * banks (3 of 61) clear the 10% publishing ceiling while finance companies
 * (3 of 20) do not.
 */

const GOV_DATA_TILES = [
  "Open datasets published by Ajman government",
  "Active business licences in Ajman",
  "Active mobile phone subscriptions, UAE (Dec 2025)",
];

test.beforeEach(async ({ page }) => {
  await page.goto("/exposure");
});

test("the three gov-data tiles render with a CACHED label, never blank or error", async ({ page }) => {
  const main = page.locator("main");
  await expect(main.getByText("Live UAE government data")).toBeVisible({ timeout: 15_000 });

  for (const label of GOV_DATA_TILES) {
    // Walk up to the tile's own card div rather than matching "any div
    // containing this text" — the grid wrapper around all three tiles
    // contains every label too, and is nested *outside* each tile.
    const tile = main
      .getByText(label, { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"rounded-[10px]")][1]');
    await expect(tile.getByText(/^[\d,]+$/)).toBeVisible(); // a real number, not "…"
    await expect(tile.getByText(/^CACHED/)).toBeVisible();
  }
});

test("the riskiest vendor card shows an AED figure and 'no replacement exists'", async ({ page }) => {
  const main = page.locator("main");
  await expect(main.getByText("Which shared vendor is riskiest")).toBeVisible({ timeout: 15_000 });

  // Scored highest by services/core/marsad_core/services/concentration.py
  // given the seeded SEED_DEPENDENCIES: all 3 firms depend on it, no substitute.
  const worst = main
    .getByText("UAESWITCH / Jaywan (domestic card routing)", { exact: true })
    .locator('xpath=ancestor::div[contains(@class,"rounded-[10px]")][1]');
  await expect(worst.getByText(/AED \d+\.\d{2} bn/)).toBeVisible();
  await expect(worst.getByText("No — no replacement exists")).toBeVisible();
});

test("the publishing-rule table shows banks=YES and finance companies=MUST COMBINE", async ({ page }) => {
  const main = page.locator("main");
  await expect(main.getByRole("table")).toBeVisible({ timeout: 15_000 });

  const banksRow = main.getByRole("row", { name: /Banks/ });
  await expect(banksRow).toContainText("YES");

  const financeRow = main.getByRole("row", { name: /Finance companies/ });
  await expect(financeRow).toContainText("MUST COMBINE WITH ANOTHER GROUP");
});
