import { test, expect } from "@playwright/test";

/**
 * Report & guardrails tab — files the demo incident (which carries a hidden
 * prompt injection in its raw_email) and checks every claim the pitch makes
 * about the A14 trick detector and the A4 obligation resolver.
 *
 * Findings are asserted by name rather than by count alone: given the fixed
 * injected email in apps/web/app/report/page.tsx, exactly these four
 * signatures fire — role_impersonation, instruction_override,
 * severity_manipulation, suppression_request — which is itself the ">= 4
 * findings" claim, made precise.
 */

const EXPECTED_FINDINGS = [
  "role_impersonation",
  "instruction_override",
  "severity_manipulation",
  "suppression_request",
];

test.beforeEach(async ({ page }) => {
  await page.goto("/report");
  await page.getByRole("button", { name: "▶ File the incident" }).click();
});

test("filing the demo incident shows TRICK DETECTED with at least 4 findings", async ({ page }) => {
  await expect(page.getByText("◆ TRICK DETECTED")).toBeVisible({ timeout: 15_000 });
  for (const signature of EXPECTED_FINDINGS) {
    await expect(page.getByText(signature, { exact: true })).toBeVisible();
  }
});

test("the incident is not downgraded — severity still shows HIGH", async ({ page }) => {
  await expect(page.getByText("◆ TRICK DETECTED")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/severity: HIGH/)).toBeVisible();
  await expect(page.getByText(/was not downgraded/)).toBeVisible();
});

test("all 5 regulators render with the right deadlines, TDRA needing a human decision", async ({ page }) => {
  const main = page.locator("main");
  await expect(main.getByText("Your deadlines")).toBeVisible({ timeout: 15_000 });

  // Each obligation card's authority code (e.g. "ADGM_FSRA") sits in its own
  // <span>; walk up to the nearest ancestor card div rather than matching any
  // <div> containing the text, which would also catch the shared list
  // wrapper around all five cards.
  const obligationCard = (authorityCode: string) =>
    main
      .getByText(authorityCode, { exact: true })
      .locator('xpath=ancestor::div[contains(@class,"rounded-[10px]")][1]');

  await expect(main.getByText("ADGM Financial Services Regulatory Authority")).toBeVisible();
  await expect(obligationCard("ADGM_FSRA")).toContainText("24 hours from detection of the incident");

  await expect(main.getByText("Central Bank of the UAE")).toBeVisible();
  await expect(obligationCard("CBUAE")).toContainText("24 hours from detection of the incident");

  await expect(main.getByText("UAE Capital Market Authority (formerly SCA)")).toBeVisible();
  await expect(obligationCard("CMA")).toContainText("48 hours from detection of the incident");

  await expect(main.getByText("Dubai Financial Services Authority (DIFC)")).toBeVisible();
  await expect(obligationCard("DFSA")).toContainText("72 hours from detection of the incident");

  await expect(
    main.getByText("Telecommunications and Digital Government Regulatory Authority"),
  ).toBeVisible();
  await expect(obligationCard("TDRA")).toContainText("NEEDS A HUMAN DECISION");
});

test("the receipt/proof hash is displayed", async ({ page }) => {
  await expect(page.getByText("Your deadlines")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Proof this happened (only this leaves your firm)")).toBeVisible();
  // sha256 hex digest, 64 characters
  await expect(page.getByText(/^[0-9a-f]{64}$/)).toBeVisible();
});
