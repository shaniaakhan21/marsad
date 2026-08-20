> **Scope note.** Figures marked *verified* come from named UAE government
> publications and are cited. Everything else — pricing, conversion, revenue — is
> a stated assumption, not a forecast. No customer has been signed, no revenue has
> been earned, and no pricing has been tested with a buyer.

# MARSAD — Business Model and Commercialisation

**UAE Hackathon 2026 · Track 1 HackArena · Challenge #9**
Securities and Commodities Authority (now the **UAE Capital Market Authority**) · Vertech Creations FZCO

---

## 1. The commercial problem, not the technical one

MARSAD's technical problem is correlation without disclosure. Its **commercial**
problem is different and harder: a network product is worthless at one customer,
and the first customer must therefore buy something that works alone.

Most information-sharing platforms fail here. They sell collective benefit, which
requires collective adoption, which nobody will go first on. So the business model
is built around one rule:

> **Every tier must be worth buying at n=1.**
> Sharing value is upside, never the basis of the purchase.

That is why the obligation resolver — not correlation — is the commercial wedge.
It saves a compliance officer real hours during an incident, needs zero sharing,
and is already built.

## 2. Who pays, and for what

Three buyers with genuinely different reasons to pay.

| Buyer | Their pain today | What they buy | Why they pay |
|---|---|---|---|
| **Licensed institution** (bank, broker, investment firm) | A compliance officer reconciling ADGM 24h, DIFC 72h, TDRA and CBUAE duties by hand, during an incident, at 3am | Connector licence — obligation resolver, receipts, correlation when they opt in | Avoided breach exposure and analyst hours. Works alone. |
| **Third-party provider** (MSSP, cloud, KYC, market data) | One incident means notifying every client separately, repeatedly, under pressure | Provider portal — declare once, every dependent institution warned | Cost avoidance plus a competitive claim: *"we notify dependents in seconds"* |
| **Regulator** (CMA / CBUAE) | No market-wide cyber picture and no third-party concentration metric exists — the CBUAE Financial Stability Report names cyber risk as systemic without quantifying it *(verified)* | Supervisory console — market risk picture, ranked concentration in AED | A capability they cannot build themselves, because it depends on firms trusting a party that is not their supervisor |

**The structural point about the regulator:** the CMA cannot build this in-house.
Institutions will not pool incident data with the authority that penalises them.
An independent operator holding cryptographic guarantees can occupy that position;
a supervisor cannot. That is not a feature — it is why the company exists.

## 3. Market size, from the licensed registers

Bottom-up from the real population, not a top-down cyber-market number.

| Segment | Count | Source |
|---|---|---|
| CMA-licensed companies | 244 | CMA 2025 annual statement *(verified via syndication)* |
| CBUAE-licensed banks | 61 | CBUAE Annual Report 2025, Table 4 *(verified)* |
| Finance companies · exchange businesses · FinTechs | 20 · 64 · 48 | CBUAE Annual Report 2025, Table 4 *(verified)* |
| Insurance companies + brokers | 58 + 161 | CBUAE Annual Report 2025, Table 4 *(verified)* |
| **Total CBUAE licensees (all types)** | **856** | CBUAE Annual Report 2025, Table 4 *(verified)* |

**Serviceable population, phase 1:** the ~305 firms where cyber incident reporting
is already a live supervisory expectation — 244 CMA-licensed plus 61 banks. This is
an addressable count, not a deduplicated entity count: the two registers are
maintained separately.

**Assumed pricing** (untested — no buyer has seen a price):

| Tier | Assumed annual | Basis |
|---|---|---|
| Connector — small firm | AED 60,000 | Below the cost of 0.25 FTE compliance analyst |
| Connector — mid | AED 140,000 | |
| Connector — large / systemically significant | AED 280,000 | |
| Provider portal | AED 180,000 | Priced on dependents warned, not seats |
| Regulator console | AED 900,000 | One contract, market-wide scope |

Modelled at **10% penetration of 305 firms** (≈30 institutions, mid-weighted), plus
5 providers and one regulator contract:

- Institutions: 30 × ~AED 140,000 ≈ **AED 4.2 m**
- Providers: 5 × AED 180,000 = **AED 0.9 m**
- Regulator: **AED 0.9 m**
- **Modelled ARR at 10% penetration ≈ AED 6.0 m**

Every input above except the population counts is an assumption. The number is a
sizing exercise, not a projection.

**Why the ceiling is higher than the licensed count suggests.** The regulatory
divergence MARSAD resolves — ADGM 24h, DIFC 72h, TDRA triggers, no bright-line
materiality — is not UAE-unique. The same multi-authority problem exists across the
GCC, and the DORA regime creates a structurally identical need in the EU. The
obligation resolver is the portable component; the correlation network is not.

## 4. Why a firm buys before the network exists

The adoption sequence is the business model. Each phase is independently priced and
independently useful.

| Phase | What the customer gets | Sharing required | Status |
|---|---|---|---|
| **1 · Comply** | One filing satisfies every authority; receipts prove timeliness against several clocks | **None** | **Built** — A4 live, 5 authorities |
| **2 · Protect** | Prompt-injection defence over attacker-authored content in incident reports | **None** | **Built** — A14 live |
| **3 · See** | Third-party concentration ranked in AED of daily traded value | Dependency declarations only — no incident data | **Built** — scoring live |
| **4 · Correlate** | Learn within minutes that an attacker is hitting peers, at zero disclosure | Keyed tokens only | Built on prototype cryptography; needs the OPRF |
| **5 · Coordinate** | Act together at disclosure rung 2.5 without revealing the incident | Action status only | Designed, not built |

A customer can stop at phase 1 and the purchase still made sense. That is the whole
commercial argument.

## 5. Unit economics

Deliberately unglamorous, because the cost structure is the good news.

- **Marginal cost per institution is near zero.** The connector is a container the
  institution hosts on its own infrastructure. We ship software; they provide
  compute. No per-customer hosting, no data egress, no storage of their data —
  because we are architecturally forbidden from holding it.
- **The privacy architecture is a cost advantage.** Never holding plaintext means no
  data-residency infrastructure per customer, and a materially smaller breach
  surface to insure and audit.
- **The real costs are trust costs, not compute costs:** HSM and threshold custody
  for the OPRF, independent cryptographic review, and the security review each
  institution will run on the connector. These are largely one-time and shared
  across all customers — the second bank's security review is far cheaper than the
  first, because the first produced the artefacts.
- **Gross margin should behave like enterprise software**; the binding constraint on
  growth is sales cycle length and legal review, not infrastructure.

## 6. Moat

Ranked by how hard each is to copy.

1. **The network, once it exists.** Correlation value is superlinear in
   participants, and a competitor starting later starts at zero. This is the real
   moat, and we do not have it yet.
2. **Neutrality.** A supervisor cannot occupy this position, and neither can any
   participating institution — a bank-owned platform will not be trusted by its
   competitors. The position requires an independent operator.
3. **The boundary contract as an audited artefact.** Each institution's security
   team audits two short files. Once several have signed off, that review history
   is itself an asset a new entrant cannot produce.
4. **Regulatory-corpus depth.** Encoding the divergence across ADGM, DIFC, TDRA,
   CBUAE and CMA correctly, and keeping it current, is unglamorous work that
   compounds.

Explicitly **not** a moat: the cryptography. OPRF is a published standard
(RFC 9497). Anyone can implement it. We do not claim otherwise.

## 7. Existing capability, honestly assessed

Two UAE platforms already exist and are narrower rather than absent:

- **UAE Banks Federation threat-intelligence platform (2017)** — banks only.
- **DFSA threat-intelligence platform (2020)** — DIFC only.

Neither covers the capital-markets ecosystem end to end, neither correlates without
disclosure, and neither measures third-party concentration. MARSAD is
complementary to both rather than a replacement, and an institution can participate
in all three.

**The honest competitive risk:** an incumbent could add correlation to an existing
platform faster than we can build a network. Our defence is the privacy
architecture and the neutral position — not speed.

## 8. Costs and what the prize money buys

Team as stated in the 90-day plan: 2 engineers, 1 founder on partnerships and
legal, fractional cryptography review.

The **AED 10,000** prototype-implementation allocation available in the
post-hackathon phase is earmarked for the single largest infrastructure item in the
90 days: **threshold key custody setup for the OPRF**. It is deliberately not spent
on the demo, which already works.

## 9. What would make this fail

Stated plainly, because a business model that cannot fail is not a model.

1. **Legal counsel refuses the token boundary.** The kill criterion is day 45. If
   it triggers, the company continues as a compliance-automation vendor selling
   phases 1–3, which is a smaller but real business — and, notably, the part that
   is already built.
2. **A zero-disclosure alert turns out not to change SOC behaviour.** Then the
   centre of gravity moves to the concentration register, which needs no alerting.
3. **Enterprise sales cycles outrun the runway.** Mitigated by pricing phase 1
   below a procurement threshold that requires board approval.
4. **An incumbent platform adds correlation first.** The honest answer is that we
   would then be competing on architecture and neutrality, and might lose.

---

*Population figures: CBUAE Annual Report 2025 Table 4; CMA 2025 annual statement.
Full provenance, including which figures we read at source and which we could not
verify, is on the **Evidence** tab of the dashboard and in
`docs/open_data_citations.md`.*
