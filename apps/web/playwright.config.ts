import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end smoke suite for the MARSAD pitch demo.
 *
 * Boots the real stack — core, three connectors, the Next.js app — as local
 * processes with synthetic demo data, and asserts exactly what the pitch
 * claims is on screen. No live network: the core's open-data fetchers are
 * routed through an unreachable proxy (HTTPS_PROXY/HTTP_PROXY), so every
 * outbound call to a government portal fails instantly and falls back to a
 * pre-seeded cache (see e2e/support/seed-cache.mjs) — deterministic and fast,
 * never a real network hit.
 *
 * Ports are offset from the docker-compose defaults (core 8000, connectors
 * 8101-8103, web 3000) so this suite never fights `make run` for a port —
 * both can be up at the same time.
 */

const UNREACHABLE_PROXY = "http://127.0.0.1:9"; // nothing listens here; connection refused, no timeout wait
const TOKEN_KEY = "e2e-test-shared-key-16plus";
const CORE_PORT = 18_000;
const WEB_PORT = 13_000;
const CORE_URL = `http://localhost:${CORE_PORT}`;
const CONNECTOR_PORTS = { almaha: 18_101, gulfsec: 18_102, emcap: 18_103 };

function connectorCommand(env: Record<string, string>, port: number) {
  const vars = Object.entries({
    MARSAD_CORE_URL: CORE_URL,
    MARSAD_TOKEN_KEY: TOKEN_KEY,
    MARSAD_TOKENISER: "hmac",
    ...env,
  })
    .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
    .join(" ");
  return `cd ../../services/connector && ${vars} uvicorn marsad_connector.main:app --port ${port}`;
}

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // shared backend state (incident counts, correlations) — run serially
  workers: 1,
  retries: 0, // no flaky tests: a retry masking a real intermittency is worse than a red run
  reporter: [["list"]],
  use: {
    baseURL: `http://localhost:${WEB_PORT}`,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command:
        `node e2e/support/seed-cache.mjs && cd ../../services/core && ` +
        `HTTPS_PROXY=${UNREACHABLE_PROXY} HTTP_PROXY=${UNREACHABLE_PROXY} ` +
        `uvicorn marsad_core.main:app --port ${CORE_PORT}`,
      url: `${CORE_URL}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command: connectorCommand(
        {
          MARSAD_INSTITUTION_NAME: "Al Maha Bank",
          MARSAD_INSTITUTION_REF: "psd_almaha01",
          MARSAD_SECTOR: "BANK",
          MARSAD_SIZE_BAND: "LARGE",
        },
        CONNECTOR_PORTS.almaha,
      ),
      url: `http://localhost:${CONNECTOR_PORTS.almaha}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command: connectorCommand(
        {
          MARSAD_INSTITUTION_NAME: "Gulf Securities",
          MARSAD_INSTITUTION_REF: "psd_gulfsec02",
          MARSAD_SECTOR: "BROKER",
          MARSAD_SIZE_BAND: "MID",
        },
        CONNECTOR_PORTS.gulfsec,
      ),
      url: `http://localhost:${CONNECTOR_PORTS.gulfsec}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command: connectorCommand(
        {
          MARSAD_INSTITUTION_NAME: "Emirates Capital",
          MARSAD_INSTITUTION_REF: "psd_emcap03",
          MARSAD_SECTOR: "INVEST",
          MARSAD_SIZE_BAND: "MID",
        },
        CONNECTOR_PORTS.emcap,
      ),
      url: `http://localhost:${CONNECTOR_PORTS.emcap}/health`,
      reuseExistingServer: false,
      timeout: 20_000,
    },
    {
      command:
        `NEXT_PUBLIC_CORE_URL=${CORE_URL} ` +
        `NEXT_PUBLIC_CONNECTORS=http://localhost:${CONNECTOR_PORTS.almaha},http://localhost:${CONNECTOR_PORTS.gulfsec},http://localhost:${CONNECTOR_PORTS.emcap} ` +
        `npm run build && ` +
        `NEXT_PUBLIC_CORE_URL=${CORE_URL} ` +
        `NEXT_PUBLIC_CONNECTORS=http://localhost:${CONNECTOR_PORTS.almaha},http://localhost:${CONNECTOR_PORTS.gulfsec},http://localhost:${CONNECTOR_PORTS.emcap} ` +
        `npm run start -- -p ${WEB_PORT}`,
      url: `http://localhost:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
