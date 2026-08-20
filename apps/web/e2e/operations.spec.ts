import { test, expect } from "@playwright/test";

/**
 * Operations tab — "Three firms get attacked."
 *
 * Drives the real UI action (the "Run the demo" button), the same as a judge
 * would, rather than pre-seeding data through the API. Firm order and
 * incidents mirror scripts/seed_demo.py exactly: Al Maha Bank and Gulf
 * Securities share attacker IP 185.220.101.44 (exact-token match), Emirates
 * Capital shares Al Maha's technique set on rotated infrastructure
 * (technique-similarity match).
 */

const FIRMS = ["Al Maha Bank", "Gulf Securities", "Emirates Capital"];

// Plaintext that must never leave a firm — narrative, analyst notes and raw
// indicator values from the three synthetic incidents (apps/web/app/page.tsx).
const FORBIDDEN_PLAINTEXT = [
  "credential-harvesting",
  "Two users submitted credentials",
  "Client-services mailbox compromised",
  "Portfolio team targeted",
  "sso-almaha-verify",
  "gulfsec-clientlogin.net",
  "emcap-portal-secure.io",
  "185.220.101.44",
  "91.219.238.12",
  "AE07 0331 2345 6789 0123 456",
];

test.beforeEach(async ({ page }) => {
  await page.goto("/");
});

test("all three firms render and pick up their incident count after the demo runs", async ({ page }) => {
  const main = page.locator("main");
  for (const firm of FIRMS) {
    await expect(main.getByText(firm, { exact: true })).toBeVisible();
  }

  await page.getByRole("button", { name: "▶ Run the demo" }).click();

  // The run posts one incident per firm, sequentially, with a UI health
  // refresh after each — give it real room rather than racing the network.
  for (const firm of FIRMS) {
    const card = main.locator("section", { has: page.getByText(firm, { exact: true }) });
    // [1-9]\d* rather than \d+ — the panel shows "0 local incident(s)" even
    // before the run, so this specifically waits for the count to move.
    await expect(card.getByText(/[1-9]\d* local incident\(s\)/)).toBeVisible({ timeout: 25_000 });
  }
});

test("the outbound payload panel shows tokens and no readable narrative", async ({ page }) => {
  await page.getByRole("button", { name: "▶ Run the demo" }).click();

  const payloadPanel = page.locator("pre").first();
  await expect(payloadPanel).toContainText('"tokens"', { timeout: 25_000 });

  const payloadText = await payloadPanel.innerText();
  expect(payloadText).toContain('"token"'); // keyed tokens present
  for (const secret of FORBIDDEN_PLAINTEXT) {
    expect(payloadText.toLowerCase()).not.toContain(secret.toLowerCase());
  }
});

test("the matches panel shows a SAME ATTACKER and a SIMILAR ATTACK METHOD card", async ({ page }) => {
  await page.getByRole("button", { name: "▶ Run the demo" }).click();

  await expect(page.getByText("◆ SAME ATTACKER").first()).toBeVisible({ timeout: 25_000 });
  await expect(page.getByText("◆ SIMILAR ATTACK METHOD").first()).toBeVisible({ timeout: 25_000 });
});

test('a "safe to publish: not yet" k-anonymity label is visible', async ({ page }) => {
  await page.getByRole("button", { name: "▶ Run the demo" }).click();

  await expect(
    page.getByText("Safe to publish as a group total: not yet").first(),
  ).toBeVisible({ timeout: 25_000 });
});
