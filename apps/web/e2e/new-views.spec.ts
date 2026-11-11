import { test, expect } from "@playwright/test";

/** The views added for the pilot: early warnings, the regulator page and receipt checks. */

test("the first firm to report is warned once a later firm matches", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /run/i }).first().click();
  await expect(page.getByTestId("warnings-0")).toContainText("Warned", { timeout: 40_000 });
  await expect(page.getByTestId("warnings-0")).toContainText("does not say which");
});

test("the regulator page names no firm", async ({ page }) => {
  await page.goto("/regulator");
  await expect(page.getByRole("heading", { name: /The market, with no firm in it/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Financial impact" })).toBeVisible();
  const text = await page.locator("main").innerText();
  for (const firm of ["psd_almaha01", "psd_gulfsec02", "psd_emcap03", "Al Maha Bank"]) {
    expect(text).not.toContain(firm);
  }
});

test("an unknown receipt is reported as unknown rather than as a failed proof", async ({ page }) => {
  await page.goto("/verify");
  await page.getByLabel("Receipt hash").fill("a".repeat(64));
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByText("No report with this receipt is known.")).toBeVisible();
});

test("the verify button stays off until the input is a receipt", async ({ page }) => {
  await page.goto("/verify");
  await page.getByLabel("Receipt hash").fill("not-a-receipt");
  await expect(page.getByRole("button", { name: "Verify" })).toBeDisabled();
});
