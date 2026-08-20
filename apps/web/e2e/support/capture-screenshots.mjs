// One-off capture script for README evidence — NOT part of the test suite.
// Drives the already-running docker-compose stack (localhost:3000) and the
// already-running Playwright HTML report (localhost:9323) through the same
// actions the e2e tests perform, and saves full-page screenshots to
// docs/screenshots/. Re-run any time the UI changes and the README images
// need refreshing.
import { chromium } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.resolve(__dirname, "../../../../docs/screenshots");

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

// ---- Operations tab ----
await page.goto("http://localhost:3000/");
await page.getByRole("button", { name: "▶ Run the demo" }).click();
await page.getByText("◆ SAME ATTACKER").first().waitFor({ timeout: 25_000 });
await page.getByText("◆ SIMILAR ATTACK METHOD").first().waitFor({ timeout: 25_000 });
// Let the run() loop's trailing pacing delay finish so the button is back to
// idle ("▶ Run the demo") rather than caught mid-"RUNNING…" in the shot.
await page.getByRole("button", { name: "▶ Run the demo" }).waitFor({ timeout: 5_000 });
await page.screenshot({ path: path.join(OUT, "01-operations.png"), fullPage: true });

// ---- Report & guardrails tab ----
await page.goto("http://localhost:3000/report");
await page.getByRole("button", { name: "▶ File the incident" }).click();
await page.getByText("◆ TRICK DETECTED").waitFor({ timeout: 15_000 });
await page.getByText("Your deadlines").waitFor({ timeout: 15_000 });
await page.waitForTimeout(500);
await page.screenshot({ path: path.join(OUT, "02-report.png"), fullPage: true });

// ---- Systemic exposure tab ----
await page.goto("http://localhost:3000/exposure");
await page.getByText("Which shared vendor is riskiest").waitFor({ timeout: 15_000 });
// The three gov-data tiles fetch live from real government portals here (this
// is the actual docker stack, not the proxy-blocked e2e instance) — give that
// real network round trip room before the shot.
await page.getByText(/^(LIVE|CACHED|PINNED)/).first().waitFor({ timeout: 20_000 });
await page.waitForTimeout(500);
await page.screenshot({ path: path.join(OUT, "03-exposure.png"), fullPage: true });

// ---- Playwright HTML report (all 11 e2e tests, green) ----
await page.goto("http://localhost:9323/");
await page.getByText("Passed11").first().waitFor({ timeout: 10_000 });
await page.waitForTimeout(300);
await page.screenshot({ path: path.join(OUT, "04-e2e-report.png"), fullPage: true });

await browser.close();
console.log("Saved screenshots to", OUT);
