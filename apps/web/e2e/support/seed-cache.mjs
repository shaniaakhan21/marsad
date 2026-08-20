// Seeds services/core/var/opendata_cache/*.json with fixed values before the
// core service starts for e2e tests, so the three "Live UAE government data"
// tiles resolve to CACHED (never LIVE, never a real network call) on any
// machine — a fresh checkout has no cache on disk, and we deliberately never
// let the e2e run touch data.ajman.ae or tdra.gov.ae.
//
// Values match the pinned constants in services/core/marsad_core/data/fetchers.py
// so the numbers on screen match what the pitch script says, whether the demo
// happens to hit CACHED or PINNED on a given machine.
import { fileURLToPath } from "node:url";
import path from "node:path";
import fs from "node:fs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CACHE_DIR = path.resolve(__dirname, "../../../../services/core/var/opendata_cache");

const FIXED_FETCHED_AT = "2026-08-19T12:00:00.000000+00:00";

const ENTRIES = {
  ajman_catalogue: {
    value: 211,
    url: "https://data.ajman.ae/api/explore/v2.1/catalog/datasets?limit=1",
    detail: "datasets currently published on data.ajman.ae",
  },
  ajman_business_licenses: {
    value: 4046,
    url: "https://data.ajman.ae/api/explore/v2.1/catalog/datasets/companies-by-license-type/records?limit=1&where=company_status%3D%22Active%22",
    detail: "active licences, Ajman 'Companies by License Type' dataset",
  },
  tdra_mobile_subscriptions: {
    value: 24_278_380,
    url: "https://tdra.gov.ae/-/media/Open-Data/Phone-and-internet-subscriptions/Phone-and-Internet-Subscriptions-2025/Active-Mobile-Subscriptions-Dec-2025.ashx",
    detail: "cell B181 on sheet 'Monthly statistics'",
  },
};

fs.mkdirSync(CACHE_DIR, { recursive: true });
for (const [key, entry] of Object.entries(ENTRIES)) {
  const file = path.join(CACHE_DIR, `${key}.json`);
  fs.writeFileSync(
    file,
    JSON.stringify({ ...entry, fetched_at: FIXED_FETCHED_AT }),
  );
}

console.log(`[e2e] seeded ${Object.keys(ENTRIES).length} open-data cache fixtures in ${CACHE_DIR}`);
