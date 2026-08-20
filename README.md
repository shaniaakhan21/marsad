# MARSAD · مرصد

**Privacy-preserving cyber-incident correlation for UAE capital markets.**
UAE Hackathon 2026 · Track 1 HackArena · Challenge #9, Securities and Commodities Authority
(now the **UAE Capital Market Authority**) · Vertech Creations FZCO

Institutions gain collective situational awareness — coordinated attacks spanning
several firms, concentration risk on shared providers — **without disclosing
incident detail to a competitor**.

**109 tests passing end to end** — 96 backend + 2 network + 11 Playwright e2e
against the real UI. See [Test coverage](#test-coverage).

---

## Contents

- [The one idea everything serves](#the-one-idea-everything-serves)
- [Quick start](#quick-start)
- [Layout](#layout)
- [The three swap points](#the-three-swap-points)
- [Test coverage](#test-coverage)
- [Design decisions worth knowing before you change things](#design-decisions-worth-knowing-before-you-change-things)
- [Roadmap](#roadmap)
- [Government data this runs on](#government-data-this-runs-on)
- [Honest scope](#honest-scope)

---

## The one idea everything serves

> Narrative, plaintext indicators and PII never leave the institution.
> Only keyed tokens, technique sets and coarse metadata cross the boundary.

Two consequences shape the whole repository:

1. **The edge/core split is physical, not conceptual.** `services/connector` runs
   inside an institution's perimeter and is the only code that touches plaintext.
   `services/core` receives boundary payloads and could not reconstruct an
   incident if it wanted to. They are separate deployables that talk over HTTP.
2. **The boundary contract is a type, not a convention.** If a field is not
   declared in `packages/contracts/marsad_contracts/boundary.py`, it cannot cross.
   Adding one is a security review, not a routine change.

An institution's security team should be able to audit **two files** and be
satisfied: the contract above, and `services/connector/marsad_connector/agents/a3_redact.py`.
Both are deliberately short.

---

## Quick start

```bash
make install          # contracts (editable) + service deps + Playwright browser
make test             # backend unit tests — the privacy and correlation guarantees
make test-network     # the handful of tests that hit a real UAE government portal
make test-e2e         # Playwright smoke suite against the real UI, see below
make run              # docker compose: 3 connectors + core + web
make demo             # drive the full scenario through the real services
```

Then open <http://localhost:3000> and press **▶ Run the demo**.

Without Docker:

```bash
# core
cd services/core && uvicorn marsad_core.main:app --port 8000

# one connector per institution (each needs its own port + ref)
cd services/connector
MARSAD_INSTITUTION_REF=psd_almaha01 MARSAD_SECTOR=BANK MARSAD_SIZE_BAND=LARGE \
MARSAD_CORE_URL=http://localhost:8000 MARSAD_TOKEN_KEY=dev-only-key-16plus \
  uvicorn marsad_connector.main:app --port 8101
```

---

## Layout

```
packages/contracts/         the boundary contract — source of truth, both languages
services/connector/         EDGE · the only service that sees plaintext
  marsad_connector/
    crypto/tokeniser.py     Tokeniser protocol · HMAC (proto) → OPRF (prod)
    agents/a3_redact.py     THE trust anchor — builds the outbound payload
    agents/base.py          Agent protocol with explicit autonomy levels
    llm/provider.py         LLMProvider protocol · offline stub by default
services/core/              CORE · never sees plaintext
  marsad_core/
    engines/correlation.py  exact-token + technique matching, k-anonymity gate
    engines/similarity.py   SimilarityEngine · Jaccard → enclave → SMPC
    services/concentration.py  third-party concentration risk (deterministic)
apps/web/                   Next.js 14 · App Router · Tailwind · TypeScript
tests/                      the tests that encode the product's claims
scripts/seed_demo.py        runs the scenario against live services
```

---

## The three swap points

Upgrading from prototype to production is changing a binding, never a rewrite.
Each is a protocol with a working prototype implementation and a documented target.

| Concern | Today | Target | Where |
|---|---|---|---|
| Tokenisation | `HmacTokeniser` | `OprfTokeniser` (RFC 9497 VOPRF, HSM threshold custody) | `crypto/tokeniser.py` |
| Similarity | `JaccardEngine` | `EnclaveEngine` (attested TEE) → `SmpcEngine` | `engines/similarity.py` |
| LLM | `StubProvider` (offline) | sovereign-hosted open-weight model | `llm/provider.py` |

### Why HMAC is not good enough

Indicators are low-entropy: the whole IPv4 space is 2³² values. Anyone holding an
HMAC token and the key can brute-force the input in seconds, and one shared key
across institutions puts the key holder in exactly the position we promise nobody
occupies. An OPRF removes it — the institution learns `PRF(k, x)` without learning
`k`, the evaluator never sees `x`, and threshold custody means no single party can
evaluate alone. **Do not process real institutional data until this is done.**

---

## Test coverage

Three separate suites, kept separate on purpose — a backend guarantee and
"does the pitch demo actually render this" are different claims, and
inflating one number by mixing them would hide which layer actually broke.

| Suite | Command | Result | Proves |
|---|---|---|---|
| Backend | `make test` | **96 passed**, 2 deselected | The privacy and correlation guarantees, offline |
| Network | `make test-network` | **2 passed** | The same fetchers, against a real UAE government portal |
| End-to-end | `make test-e2e` | **11 passed** | Every claim the pitch makes is actually on screen |

<sub>Total: **109 passed**. Last run: 2026-08-20, `main`.</sub>

### What the backend tests prove

`make test` is not coverage theatre — each test encodes a claim we make to a
regulator or a bank's counsel.

- narrative, analyst notes and plaintext indicators never appear in the payload
- the contract **rejects** an unknown field, so a typo cannot smuggle data across
- the leak guard trips loudly if a future refactor reintroduces narrative
- the same indicator tokenises identically across institutions — without this,
  correlation silently never fires
- canonicalisation survives analyst formatting (`Evil-Domain[.]com`, spaced IBANs)
- indicator types are domain-separated, so an account and an IBAN cannot collide
- exact token match is detected with no plaintext anywhere
- **technique similarity catches an attacker who rotated infrastructure** — the
  capability indicator-sharing platforms lack
- one campaign is never double-reported as two correlations
- a duplicate submission cannot inflate a campaign's apparent size
- a rung-0 notice reveals peer *count*, never peer *identity*
- k-anonymity gates aggregate publication while still notifying the parties
- concentration scoring ranks a non-substitutable shared provider highest, and
  discounts inferred dependency edges
- ADGM (24h), DFSA (72h), CMA (48h) and CBUAE (24h) deadlines are exact
  arithmetic from detection, not just in-scope — a missed deadline is legal
  exposure, so every clock is asserted by value

<details>
<summary><b>Terminal output</b> — <code>make test</code></summary>

```text
$ make test
======================= test session starts =======================
platform darwin -- Python 3.12.6, pytest-8.3.4
collecting ... collected 98 items / 2 deselected / 96 selected

tests/test_agents.py ..........................                 [ 27%]
tests/test_boundary.py .............                             [ 40%]
tests/test_fetchers.py ................                          [ 56%]
tests/test_open_data.py .......................................  [100%]

======================= 96 passed, 2 deselected in 0.74s =======================
```

</details>

<details>
<summary><b>Terminal output</b> — <code>make test-network</code></summary>

```text
$ make test-network
collecting ... collected 98 items / 96 deselected / 2 selected

tests/test_fetchers.py::test_ajman_catalogue_is_genuinely_reachable_live PASSED
tests/test_fetchers.py::test_tdra_workbook_is_genuinely_parsed_live PASSED

======================= 2 passed, 96 deselected in 2.09s =======================
```

</details>

### What the end-to-end suite proves

`apps/web` had zero tests before this suite. Playwright drives the **real
UI** — clicking "▶ Run the demo", "▶ File the incident" — against the real
backend (core + all 3 connectors, started as local processes) and checks the
exact claims the pitch makes out loud:

- all three firms render and pick up their incident count after the demo runs
- the outbound payload panel shows only tokens — no narrative, no raw indicator
  values, checked against every synthetic plaintext string in the demo data
- a ◆ SAME ATTACKER and a ◆ SIMILAR ATTACK METHOD card both render
- the k-anonymity gate says "not yet" at 3 participating institutions
- filing the demo incident (which carries a hidden prompt injection) shows
  ◆ TRICK DETECTED with its 4 named findings, and severity stays HIGH — not
  downgraded
- all 5 regulators render with the right deadlines (ADGM 24h, CBUAE 24h,
  CMA 48h, DFSA 72h) and TDRA is flagged as needing a human decision
- the receipt/proof hash is displayed
- the three "Live UAE government data" tiles never render blank or an error
- the riskiest-vendor card and the banks=YES / finance companies=MUST COMBINE
  publishing-rule table are correct

No live network in this suite: the core's open-data fetchers are routed
through an unreachable proxy so a portal outage can never make it flaky, and
a fixed cache is seeded first (`e2e/support/seed-cache.mjs`) so the three
gov-data tiles resolve to CACHED deterministically. Runs on a port range
offset from `make run`, so both can be up at once.

<details>
<summary><b>Terminal output</b> — <code>make test-e2e</code></summary>

```text
$ make test-e2e
Running 11 tests using 1 worker

  ✓  exposure.spec.ts   › the three gov-data tiles render with a CACHED label, never blank or error
  ✓  exposure.spec.ts   › the riskiest vendor card shows an AED figure and 'no replacement exists'
  ✓  exposure.spec.ts   › the publishing-rule table shows banks=YES and finance companies=MUST COMBINE
  ✓  operations.spec.ts › all three firms render and pick up their incident count after the demo runs
  ✓  operations.spec.ts › the outbound payload panel shows tokens and no readable narrative
  ✓  operations.spec.ts › the matches panel shows a SAME ATTACKER and a SIMILAR ATTACK METHOD card
  ✓  operations.spec.ts › a "safe to publish: not yet" k-anonymity label is visible
  ✓  report.spec.ts     › filing the demo incident shows TRICK DETECTED with at least 4 findings
  ✓  report.spec.ts     › the incident is not downgraded — severity still shows HIGH
  ✓  report.spec.ts     › all 5 regulators render with the right deadlines, TDRA needing a human decision
  ✓  report.spec.ts     › the receipt/proof hash is displayed

  11 passed (34.3s)
```

</details>

<details open>
<summary><b>Playwright HTML report</b> — all 11 green (<code>npx playwright show-report</code>)</summary>
<br/>

<img src="docs/screenshots/04-e2e-report.png" alt="Playwright HTML report showing 11 of 11 tests passed" width="850"/>

</details>

### The screens those tests are exercising

<table>
<tr><td>

**01 · Operations** — three firms, one attacker campaign, correlated with
zero plaintext shared

<img src="docs/screenshots/01-operations.png" alt="Operations tab: three firms, payload panel showing only tokens, SAME ATTACKER and SIMILAR ATTACK METHOD cards" width="850"/>

</td></tr>
<tr><td>

**02 · Report & guardrails** — the injected demo email caught, deadlines
resolved across all 5 regulators, receipt hash produced

<img src="docs/screenshots/02-report.png" alt="Report tab: TRICK DETECTED with 4 findings, 5 regulator deadlines, receipt hash" width="850"/>

</td></tr>
<tr><td>

**03 · Systemic exposure** — riskiest shared vendor priced in AED, live
government data, the k-anonymity publishing rule

<img src="docs/screenshots/03-exposure.png" alt="Exposure tab: three LIVE gov-data tiles, UAESWITCH/Jaywan scored CRITICAL with no replacement exists, publishing-rule table" width="850"/>

</td></tr>
</table>

---

## Design decisions worth knowing before you change things

**`institution_ref` is a rotating pseudonym.** Not a name, not a stable ID. The
validator rejects anything containing spaces or uppercase, which is a cheap guard
against someone "helpfully" putting a firm name there.

**Timestamps are bucketed to the hour and severity is banded.** Precise values
would let a peer or the operator single out a firm by timing. Deliberate loss.

**A3 holds no network capability.** It builds payloads; it cannot send them. The
only egress is `submit()` in the connector's `main.py`, and it accepts nothing but
an already-validated `IncidentSubmission`.

**The core is additive.** If it disappears, an institution's own incident response
is unaffected — the connector queues locally and returns 503 rather than blocking.
MARSAD must never sit on the critical path of a firm in a crisis.

**Nothing degrades silently.** `SimilarityResult.reduced_fidelity` propagates to
every alert produced by a weaker engine, so an operator always knows the
confidence context. A confident-looking alert from a degraded path is worse than
no alert.

**Concentration risk is deterministic, never model output.** A regulator may act
on those numbers, so they must be reproducible and explainable line by line. The
weights are named constants with a calibration note — the first version
under-rated a provider the whole sample depended on, and the test suite caught it.

---

## Roadmap

**Now** — obligation resolver (A4) across the divergent UAE clocks: ADGM 24h,
DIFC 72h, TDRA on essential-service disruption, no bright-line materiality. This
is the adoption wedge, because it delivers value with **zero** sharing.

**Next** — Postgres + Alembic in place of in-memory state; telemetry ingest (A5)
for precursor detection; Response Room (A11) at disclosure rung 2.5.

**Then** — OPRF; enclave similarity with published attestation measurements;
Merkle-batched reporting receipts with public anchoring; Neo4j once graph
traversals justify it.

---

## Government data this runs on

Incident data is synthetic — no UAE open dataset publishes cyber incidents broken
down by financial-sector entity, and that absence is the gap MARSAD fills. But the
**privacy parameters and the exposure figures are not invented**, and neither is
decorative:

| Source | Publisher | What it determines |
|---|---|---|
| Annual Report 2025, Table 4 — Licensees by Type | CBUAE | Cohort sizes → the k-anonymity floor per sector |
| CB Register (**monthly**) | CBUAE | Participant registry; monthly recomputation of cohort sizes |
| Monetary, Banking & Financial Markets Developments Report, Q4 2025 | CBUAE | ADX/DFM market cap and traded value → AED exposure |
| CMA 2025 annual statement | UAE Capital Market Authority | Average daily traded value, AED 2.21 bn |
| Licensed Companies — Open Data | UAE Capital Market Authority | Enrolment universe, 244 licensed companies |
| TDRA Open Data (XLSX, 61 datasets) | TDRA | Attack-surface scaling; pilot volume sizing |
| Monthly UAE Security Report (aeCERT) | TDRA | Incident taxonomy and monthly incident rate |

Two consequences worth knowing:

- **k is derived, not chosen.** 3 of 61 licensed banks is 4.9% of the cohort and
  publishable; 3 of 20 third-party administrators is 15% and is re-identifying, so
  that cohort is pooled instead. See `data/uae_open_data.py::cohort_rule`.
- **Concentration is reported in AED.** A regulator cannot act on "score 88.4", so
  every score is multiplied through published market figures — and the two
  independent government sources for daily traded value are reconciled in
  `market_basis()["cross_check"]` (they agree within 2%).

Provenance is served live at `/v1/data/sources` and rendered on the dashboard's
**Evidence** tab, including the sources we could *not* verify and the portals that
blocked our client. Overstating a citation is the fastest way to lose a reviewer
who checks one.

---

## Honest scope

Incident data is synthetic. HMAC not OPRF. Jaccard not enclave. In-memory not Postgres.
No verified access to SCA systems, taxonomies or data, and **no government
integration is in place** — every entity named in the design is a notional
counterparty requiring formal agreement. These limits are stated in the UI too;
overstating them is the fastest way to lose a technically literate audience.
