import { test, expect } from "@playwright/test";

/**
 * The guided demo — the path a reviewer watches, and the one a screen capture follows.
 *
 * Every assertion here is about something a viewer must actually SEE, in order, so a
 * broken step fails the build rather than producing a recording with a dead panel in
 * it. The two things the product turns on get the most attention: the boundary
 * indicator, and the raw payload panel that lets a reviewer check the boundary claim
 * for themselves rather than believing the labels.
 *
 * The demo runs against the real stack with the deterministic extractor (the default
 * `make run` config, MARSAD_LLM_PROVIDER=stub), so it completes in seconds rather than
 * the ~30s per extraction a live model costs.
 */

const RUN = "▶ Run the guided demo";

test.beforeEach(async ({ page }) => {
  await page.goto("/demo");
});

test("the six steps are laid out before anything runs", async ({ page }) => {
  await expect(page.getByTestId("step-rail")).toBeVisible();
  for (let n = 1; n <= 6; n++) {
    await expect(page.getByTestId(`step-${n}`)).toBeVisible();
  }
  await expect(page.getByRole("button", { name: RUN })).toBeEnabled();
});

test("the English filing shows what stayed local and what crossed", async ({ page }) => {
  await page.getByRole("button", { name: RUN }).click();

  const stayed = page.getByTestId("stayed-local").first();
  await expect(stayed).toBeVisible({ timeout: 60_000 });
  // The narrative and the plaintext indicator are on the LOCAL side.
  await expect(stayed).toContainText("credential-harvesting");
  await expect(stayed).toContainText("sso-almaha-verify.com");

  const crossed = page.getByTestId("crossed-boundary").first();
  await expect(crossed).toBeVisible();
  await expect(crossed).toContainText("Keyed tokens");
  // and the plaintext is NOT on the crossed side
  await expect(crossed).not.toContainText("credential-harvesting");
  await expect(crossed).not.toContainText("sso-almaha-verify.com");
});

test("the Arabic filing renders right-to-left", async ({ page }) => {
  await page.getByRole("button", { name: RUN }).click();

  const arabic = page.getByTestId("arabic-narrative");
  await expect(arabic).toBeVisible({ timeout: 60_000 });
  await expect(arabic).toHaveAttribute("dir", "rtl");
  await expect(arabic).toContainText("رسالة تصيد");
});

test("the raw payload a reviewer can search contains no narrative or plaintext indicator", async ({ page }) => {
  await page.getByRole("button", { name: RUN }).click();

  const json = page.getByTestId("core-sees-json");
  await expect(json).toBeVisible({ timeout: 60_000 });

  const payload = (await json.textContent()) ?? "";
  expect(payload.length).toBeGreaterThan(50);
  expect(payload).toContain("tokens");

  // The claim the whole product rests on, checked against the bytes on screen.
  for (const secret of [
    "credential-harvesting", "رسالة تصيد", "sso-almaha-verify",
    "gulfsec-rotated", "Nexa KYC", "a.karim", "n.saleh",
  ]) {
    expect(payload).not.toContain(secret);
  }
});

test("the correlation, the gate, the exposure and the injection all render", async ({ page }) => {
  await page.getByRole("button", { name: RUN }).click();

  await expect(page.getByTestId("correlations")).toBeVisible({ timeout: 60_000 });

  const gate = page.getByTestId("k-gate");
  await expect(gate).toBeVisible({ timeout: 60_000 });
  await expect(gate).toContainText("NOT YET");

  const exposure = page.getByTestId("exposure");
  await expect(exposure).toBeVisible({ timeout: 60_000 });
  await expect(exposure).toContainText("AED");

  const injection = page.getByTestId("injection");
  await expect(injection).toBeVisible({ timeout: 60_000 });
  await expect(injection).toContainText("TRICK DETECTED");
  // the incident is not downgraded — the whole point of returning a finding, not a veto
  await expect(injection).toContainText("HIGH");
});

test("the demo reaches its completion state", async ({ page }) => {
  await page.getByRole("button", { name: RUN }).click();
  await expect(page.getByTestId("demo-complete")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByRole("button", { name: RUN })).toBeEnabled();
});

test("the extractor caveat is visible from frame one, before anything runs", async ({ page }) => {
  /**
   * On screen at load, not added in post. A recording that shows the demo running
   * fast and mentions the extractor afterwards has already misled anyone who stops
   * watching early — and the model path being slower is a measured result of this
   * project, not something to hide behind editing.
   */
  const caveat = page.getByTestId("extractor-caveat");
  await expect(caveat).toBeVisible();
  await expect(caveat).toContainText("deterministic extractor");
  await expect(caveat).toContainText("docs/model-path-results.md");

  // Above the fold: it must be visible without scrolling, at the recording viewport.
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(caveat).toBeInViewport();
});
