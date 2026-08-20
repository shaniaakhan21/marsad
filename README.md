# MARSAD · مرصد

**Privacy-preserving cyber-incident correlation for UAE capital markets.**
UAE Hackathon 2026 · Track 1 HackArena · Challenge #9, Securities and Commodities Authority
(now the **UAE Capital Market Authority**) · Vertech Creations FZCO

Institutions gain collective situational awareness — coordinated attacks spanning
several firms, concentration risk on shared providers — **without disclosing
incident detail to a competitor**.

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
make install          # contracts (editable) + service deps
make test             # 21 tests — the privacy and correlation guarantees
make run              # docker compose: 3 connectors + core + web
make demo             # drive the full scenario through the real services
```

Then open <http://localhost:3000> and press **Run scenario**.

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

## What the tests prove

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
