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
- [Proving the boundary](#proving-the-boundary)
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
make test-boundary    # the network boundary, proven inside the real containers
make test-llm         # the model path against a live Ollama endpoint
make migrate          # both databases, empty to current, in one command
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

## Proving the boundary

Everything else in this repository tests a mechanism that *supports* the privacy
claim. These two test the claim itself, and they are the reason to believe the rest.

### The canary test — nothing from inside the institution reaches the core

Runs in the default suite, so it cannot be forgotten:

```bash
make test                                   # included
python -m pytest tests/test_canary.py -v    # on its own
```

It plants unique random strings inside an incident, runs the **real** pipeline —
A2 extraction, human confirmation, A3 redaction, submission, core correlation — and
then looks for them everywhere the core can hold or emit anything: **the core
database — every table, every column, every row**, with tables found by reflection
rather than by asking the ORM what it declared; an exhaustive recursive walk of the
core's process state, since the correlation engine keeps an in-memory index rebuilt
from the database; every API response including the OpenAPI document; and every line
the core logs. Both store backends are covered — Postgres/SQLite and the in-memory
one kept for speed. Four surfaces are canaried
separately: ordinary prose, an analyst note, a plaintext indicator, and a vendor name
planted specifically because extraction quotes it **verbatim as span evidence** — the
provenance surface free-text intake introduced. A fifth is Arabic, planted so that
normalisation rewrites it, because the canary then exists in two forms and both are
inside the institution.

Two things keep it honest. Every canary is asserted **present** on the edge before it
is asserted absent at the core, and the core is asserted to have actually ingested the
submission — a canary test that passes because nothing ran is a green light with
nothing behind it. And the sweep itself is tested twice over:
`test_the_sweep_can_actually_find_a_leak` plants a canary in core process state, and
`test_the_sweep_can_find_a_leak_planted_in_a_database_row` writes one into a real
column of a real table and requires the sweep to report it at the right path.
`test_the_sweep_reflects_tables_rather_than_trusting_the_orm` creates a table outside
the ORM and requires the sweep to find that too.

### The network boundary test — isolation the code cannot undo

```bash
make test-boundary        # brings the stack up, runs the suite, tears it down

# or by hand:
docker compose up -d --build
python -m pytest tests/test_network_boundary.py -v -m docker
docker compose down
```

Each connector sits alone on its own Docker network; core sits alone on `core_net`.
One container — `boundary-gateway` — is attached to both sides and forwards exactly
one endpoint, `POST /v1/submissions`. The tests run *inside* the containers and
assert that a connector cannot reach core by service name or by raw IP, that core
cannot reach a connector's plaintext store, and that two institutions cannot reach
each other. A positive control drives a real incident all the way through the
permitted route, because isolation tests pass trivially when everything is broken.

#### What the boundary test does and does not prove

| Claim | Enforced by | Proven |
|---|---|---|
| A connector cannot reach core, by name or address | Docker networking | Yes |
| Core cannot reach a connector's plaintext store | Docker networking | Yes |
| Two institutions cannot reach each other | Docker networking | Yes |
| Only `POST /v1/submissions` crosses | nginx config in `infra/` | Yes, but this is a proxy rule, not network isolation |
| A connector cannot reach the host's own namespace | — | **No.** See below |

The last row is a real limitation, recorded rather than glossed. These containers run
on one laptop, and an edge network that is not `internal` leaves a container able to
reach `host.docker.internal`. Marking the edge networks `internal: true` closes it and
also breaks published ports, so the dashboard and `make demo` stop working — the
tradeoff was made in favour of a working demo, because the exposure is an artifact of
the simulation rather than the design: in deployment the connector runs inside an
institution and the core in another organisation, with no shared host to route
through. `test_the_single_host_limitation_is_recorded_rather_than_claimed_away`
asserts the claims we *do* make still hold, and skips with an explanation rather than
pretending the hole is closed.

Both suites run in CI on every push (`.github/workflows/ci.yml`), the canary in the
backend job and the boundary in its own Docker job, so a refactor cannot quietly
breach either.

---

## Two databases, never one

The edge stores plaintext — narrative, analyst notes, the attacker's email body, and
extraction provenance that quotes the narrative verbatim. The core stores boundary
payloads. **They are separate databases and they must stay separate**, because this is
the one control that would be destroyed silently: sharing an instance is a
configuration, invisible in code review, and it makes narrative reachable from the core
without a line of code changing.

Three independent separations, each enforced by something different:

| Separation | Enforced by | Checked by |
|---|---|---|
| Separate MetaData — the core ORM cannot name an edge table | `CoreBase` / `EdgeBase` | `test_the_two_sides_share_no_table` |
| Separate schemas — `core.*` and `edge.*` | Schema-qualified models; the name is a constant, not a setting | `test_the_schemas_are_different_and_not_configurable_to_match` |
| Separate instances — different databases, on different networks | `docker-compose.yml`: `core-db` on `core_net`, `edge-db-<institution>` on that institution's edge network | `test_a_core_session_cannot_reach_an_edge_table`, plus the boundary suite |

The core schema also has no column a narrative could land in, which
`test_the_core_schema_has_no_column_that_could_hold_narrative` asserts by name. The
store cannot express what must not cross.

SQLite is used for local runs and the fast test path. Schemas are real there too — the
engine attaches a database under the schema's name — so the test path exercises the
same schema-qualified SQL as Postgres rather than a schema-less variant that would
hide a class of bug.

### Migrations

```bash
make migrate     # both databases, empty to current
```

Two separate Alembic trees (`services/core/alembic`, `services/connector/alembic`),
never merged. Each keeps its `alembic_version` table **inside its own schema**, so if
the two were ever pointed at one database their histories could not collide in a
shared namespace — each would refuse rather than run the other's migrations. Each
tree's `include_object` refuses to touch tables outside its schema, so a migration run
against the wrong URL cannot alter the other side. Containers run `alembic upgrade
head` before serving, so a container that cannot migrate never starts.

### Retention on the edge plaintext store

`MARSAD_RETENTION_DAYS` (default **90**). After the window, these expire:

- `narrative`, `narrative_normalised`, `analyst_notes`, `raw_email`
- **every `extraction_provenance` row**

That second line is the point. `ExtractionProvenance.evidence` holds a verbatim slice
of the narrative and the span offsets index into it — it is the narrative, in a table
whose name does not say so. Clearing the narrative and leaving provenance behind
produces a database that looks purged and still holds the analyst's words, which is
worse than not purging, because someone would believe it was done. So provenance
expires **with** the narrative, never after it, by two independent mechanisms: the
purge deletes both in one transaction, and the foreign key cascades if anything
deletes an incident another way.

Deliberately kept: severity, techniques, indicator types, detection time, and the
obligation receipt. That is what a regulator may ask about months later and what A3
derives a submission from — structured, bounded, and none of it free text an analyst
wrote. A row whose `expires_at` was never set is treated as expiring on the default
window from creation, not as "keep forever": text nobody made a decision about is
exactly the text most likely to be forgotten. A purged incident records `redacted_at`,
so a reader can tell "no narrative was written" from "the narrative expired".

---

## Arabic normalisation is vendored, and tested against the real thing

`camel-tools` declares torch, transformers and the NVIDIA CUDA runtime as hard
dependencies. Installing it to obtain four character maps produced an **8.73GB**
connector image — a deep-learning stack, and its attack surface, shipped inside an
institution's perimeter for four `str.translate` tables. Three connectors at that size
also do not fit on a modest VPS.

The four maps — `dediac_ar`, `normalize_alef_ar`, `normalize_alef_maksura_ar`,
`normalize_teh_marbuta_ar` — are now implemented in
[lang/arabic.py](services/connector/marsad_connector/lang/arabic.py), derived from and
cited to CAMeL Tools 1.6.0. They are deliberately dull: a table and a translate, so a
reviewer can check them against the upstream source by eye.

**Image: 8.73GB → 327MB**, a 96% reduction, with no torch and no CUDA in the runtime.

Vendoring normally trades one risk for another — a second implementation that drifts
silently. Here it is a test instead of a hope.
[test_vendored_normalisation.py](tests/test_vendored_normalisation.py) keeps the real
CAMeL Tools as a **test-only** dependency and asserts identical output for **every
codepoint in the Arabic block U+0600–U+06FF, individually** (303 assertions, one per
character, so a drift failure names the exact codepoint), for the whole block as a
single string, for each of the four operations separately, for every Arabic and
code-switched narrative fixture, and for the offset map that spans depend on. A
missing oracle is an error rather than a skip, because a silently skipped oracle leaves
the vendored tables unverified while the suite still looks green.

`test_camel_tools_is_not_a_runtime_dependency` keeps the saving: it fails if any
runtime module imports it, if the Dockerfile installs it, or if it reappears outside
the test extra.

The single-function guarantee is unchanged. `normalise()` is still one function object
shared by the write and query paths — `test_write_and_query_paths_share_one_normalisation_function`
asserts identity, not equivalence.

---

## The model path, measured

Every accuracy figure in this repository used to describe the deterministic offline
extractor. The LLM path had never been executed. It has now:
**[docs/model-path-results.md](docs/model-path-results.md)**.

Ollama 0.33.0, `qwen2.5:3b-instruct` (Q4_K_M, 1.93GB), the connector's own prompt and
schema, the existing fixtures, nothing tuned.

| Set | Deterministic | Model |
|---|---|---|
| English | 138/140 = **98.6%** | 74/140 = **52.9%** |
| Arabic | 70/70 = **100.0%** | 35/70 = **50.0%** |

Across 210 field comparisons the model was right where the deterministic extractor was
wrong **zero times**. It hallucinates well-formed ATT&CK IDs that are unrelated to the
incident, paraphrases service names out of the canonical vocabulary, inflates severity,
reads through Arabic negation, drops indicators, once extracted our own fence marker as
an indicator, and once answered an Arabic narrative in Chinese.

Six breakages are recorded there rather than worked around — including that Ollama
rejects the production schema outright (its grammar compiler cannot parse `\d`), that
`strict: true` does not validate (95 of 203 confidence values fell outside the declared
`[0,1]`), and that **103 of 203 fields cited evidence that is not in the narrative**,
which is the guard in `_locate` firing on half of real model output.

```bash
ollama serve & ollama pull qwen2.5:3b-instruct
make test-llm
```

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
