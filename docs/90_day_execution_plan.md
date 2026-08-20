# MARSAD — 90-Day Execution Plan

**UAE Hackathon 2026 · Track 1 HackArena · Challenge #9**
Securities and Commodities Authority (now the **UAE Capital Market Authority**) · Vertech Creations FZCO

> Judged under *Solution Feasibility and Planning* (20%): "ease of implementation in the actual
> work environment of the government entity, including a clear 90-day execution plan to test the
> product, with defined milestones and a realistic timeline."

---

## The judgement this plan rests on

MARSAD's binding constraint is **not engineering**. It is whether an institution's legal counsel
accepts that a keyed token is not a disclosure of incident data. Cryptographic rigour cannot
settle that question — it is a legal judgement, and a conservative counsel may decline on
principle.

So the plan is sequenced around that risk rather than around the technology:

1. **Days 1–30 deliver value that requires zero sharing.** A firm gets a working benefit while the
   legal question is still open.
2. **Days 31–60 build production cryptography, then switch sharing on.** Correlation between two
   firms is the first moment the privacy guarantee is load-bearing, so the OPRF lands *before* the
   second institution, not after.
3. **Days 61–90 prove the market-wide and predictive claims, and reach a funded go/no-go.**

A plan that built correlation first and asked permission later would stall at day 60 with nothing
deployable. Every phase ends at an **exit gate**, and the programme has **kill criteria** — it is
designed to be stopped, not to run on optimism.

---

## Phase 1 · Days 1–30 — Obligation resolver in production at one institution

**Objective.** Deliver a capability that is useful to a single firm on its own, before asking any
firm to share anything with anyone.

**Why this order.** Multi-authority incident reporting is pure benefit and needs no sharing, so it
can be deployed while the legal question is unresolved. It also puts a connector inside a real
perimeter — the hard part of every later phase.

| Day | Milestone | Owner | Evidence it is done |
|---|---|---|---|
| 7 | **Legal boundary contract before a DPO.** Put the boundary contract and the redaction agent in front of one institution's Data Protection Officer and general counsel for a written opinion on whether keyed tokens constitute disclosure. | Founder / legal counsel | Written legal opinion, or a written list of conditions to satisfy |
| 14 | **Obligation resolver across the divergent UAE clocks.** One submission satisfies ADGM's 24-hour duty, DIFC's 72-hour duty and TDRA's essential-service notification, with a receipt hash per authority. No materiality bright line exists, so the resolver presents the decision rather than making it. | Engineering | Passing test suite per authority; a filed receipt in staging |
| 21 | **Connector deployed inside one institution's perimeter.** Docker deployment behind the firm's firewall, egress restricted to the core endpoint, reviewed by the firm's own security team. | Engineering / partner SOC | Signed-off deployment review; connector health green for 7 days |
| 30 | **Postgres and audit persistence replace in-memory state.** Alembic migrations, retention policy, per-submission audit trail. | Engineering | Restart-survival test; an auditor can reconstruct any submission |

**Exit gate.** A written legal opinion exists **and** one connector has run inside a real perimeter
for 7 consecutive days. If counsel refuses, the product continues as a single-firm obligation
resolver and correlation is dropped — we do not proceed on hope.

**Success metric.** 1 institution live; ≥3 real filings resolved across ≥2 authorities.

**Principal risk.** Counsel declines on principle, regardless of cryptographic rigour.
**Mitigation.** The 30-day deliverable has standalone commercial value without sharing, so a
refusal costs the correlation roadmap, not the company.

---

## Phase 2 · Days 31–60 — Production cryptography and the second institution

**Objective.** Make correlation safe enough to switch on, then switch it on between two firms.

**Why this order.** The hackathon prototype tokenises with a shared-key HMAC. That is adequate to
demonstrate the mechanics and **not** adequate for real data: indicators are low-entropy — the
whole IPv4 space is 2³² values — so anyone holding the key could enumerate them, which puts the
key holder in exactly the position we promise nobody occupies. The OPRF must land before the
second institution joins.

| Day | Milestone | Owner | Evidence it is done |
|---|---|---|---|
| 40 | **OPRF tokenisation replacing HMAC.** RFC 9497 VOPRF over Ristretto255: the institution learns `PRF(k, x)` without learning `k`; the evaluator never sees `x`. Key epochs recorded in the token scheme so tokens are never compared across epochs. | Engineering (cryptography) | Interop test across two connectors; independent code review |
| 48 | **Threshold key custody across independent parties.** Key shares split so no single party — including us — can evaluate alone. HSM-backed, with evaluation metered and audited so bulk enumeration is visible. | Engineering / infrastructure | Custody agreement signed; single-share evaluation demonstrably fails |
| 55 | **Second institution live; first real cross-firm correlation.** Two firms in different sectors submit under the production tokeniser. Correlation notices at disclosure rung 0 only. | Founder / engineering | A correlation notice delivered to two SOCs from real submissions |
| 60 | **Concentration register seeded from declared dependencies.** Both firms declare third-party dependencies; scoring runs against the real licensed population as denominator, with exposure expressed in AED of daily traded value. | Engineering / risk | Ranked register reviewed by both firms' third-party risk leads |

**Exit gate.** OPRF in production with threshold custody, and at least one correlation notice
generated from two institutions' real submissions.

**Success metric.** 2 institutions live; ≥1 genuine cross-firm correlation; 0 privacy incidents.

**Principal risk.** OPRF round trips add latency, or HSM procurement slips.
**Mitigation.** Batch blinding gives one round trip per incident rather than per indicator;
software threshold custody ships first with HSM migration as a follow-on; the `reduced_fidelity`
flag makes any weaker path visible to operators rather than silently degrading.

---

## Phase 3 · Days 61–90 — Regulator view, telemetry, and the commercial decision

**Objective.** Give the challenge owner a market-wide picture, prove the predictive claim, and
reach a fundable go/no-go.

**Why this order.** Regulator-facing value only becomes real above two participants, and the
predictive claim — detecting a campaign forming before anyone files — needs a telemetry baseline
that takes weeks to accumulate. Both depend on phases 1 and 2 having held.

| Day | Milestone | Owner | Evidence it is done |
|---|---|---|---|
| 70 | **Five institutions enrolled; k-anonymity gate active.** Cohort publication rules derived from the CBUAE licensee register: small cohorts are pooled rather than published, because a labelled statistic over a 20-firm cohort is itself an identifier. | Founder | 5 signed participation agreements; the gate blocking a real aggregate |
| 78 | **Continuous coarse telemetry ingest.** Sub-threshold signals — authentication failure rates, mail rejects, scan volume — pooled as deviations from each firm's local baseline. Rates and counts only; never events, never logs. | Engineering | 14 days of baseline per firm; one precursor alert reviewed by a SOC |
| 84 | **Regulator console for the challenge owner.** Market-wide risk picture, ranked concentration with AED exposure, campaign view. Read-only; no new powers over any firm, no visibility of an individual firm's incident detail. | Engineering / design | Walkthrough completed with the CMA challenge mentor |
| 90 | **Pilot report and go/no-go.** Measured outcomes against the pilot hypotheses, a costed operating model, and a written recommendation to continue, pivot or stop. | Founder | Pilot report delivered to participants and the challenge owner |

**Exit gate.** Five institutions live, one precursor alert acknowledged by a SOC, and a written
pilot report with a costed operating model.

**Success metric.** 5 institutions; ≥1 correlation that changed a SOC's action; a concentration
register naming at least one shared provider no single firm could see.

**Principal risk.** A zero-disclosure alert may not actually change SOC behaviour — the assumption
that a bare "you are not alone" signal is actionable is unvalidated.
**Mitigation.** Day-78 telemetry and the rung-2.5 Response Room let firms coordinate action
without disclosing. If rung 0 proves inert, the product's centre of gravity moves to the
concentration register, which needs no alerting at all.

---

## Resourcing

| | |
|---|---|
| **Team** | 2 engineers, 1 founder on partnerships and legal, fractional cryptography review |
| **Critical dependency** | One institution willing to host a connector in month 1 |
| **Post-hackathon support** | The AED 10,000 prototype-implementation allocation covers HSM/threshold-custody setup in Phase 2 — the single largest infrastructure item in the 90 days |
| **Integration status** | **No verified access to the challenge owner's systems, taxonomies or data is in place.** Every entity named is a notional counterparty requiring a formal agreement. |

## Kill criteria

Legal counsel refuses the token boundary and no alternative institution accepts it by **day 45**;
or five institutions cannot be enrolled by **day 90**.

---

## Government data this plan runs on

The plan is not data-free: the privacy parameters and the exposure figures are both derived from
named UAE government publications, refreshed on their own publication cadence.

| Source | Publisher | Used for | Cadence |
|---|---|---|---|
| Annual Report 2025, Table 4 — Licensees by Type | CBUAE | Cohort sizes that set the k-anonymity floor per sector | Annual |
| CB Register | CBUAE | Participant registry; monthly recomputation of cohort sizes | **Monthly** |
| UAE Monetary, Banking & Financial Markets Developments Report, Q4 2025 | CBUAE | ADX/DFM market cap and traded value → AED exposure | Quarterly |
| CMA 2025 annual statement | UAE Capital Market Authority | Average daily traded value (AED 2.21 bn) | Annual |
| Licensed Companies — Open Data | UAE Capital Market Authority | Enrolment universe (244 licensed companies) | Continuous |
| TDRA Open Data — Phone & Internet Subscriptions, ICT Access & Use | TDRA | Attack-surface scaling; pilot volume sizing | Periodic, XLSX |
| Monthly UAE Security Report (aeCERT) | TDRA | Incident taxonomy and monthly incident rate | Monthly (latest published issues are 2020) |

The monthly CB Register is what makes the data use *sustainable* rather than a one-off citation:
cohort sizes and the concentration denominator are recomputed on each publication, so the privacy
floor moves as the market moves.

**Stated gap.** No UAE open dataset publishes cyber incidents broken down by financial-sector
entity. The CBUAE Financial Stability Report names cybersecurity threats as a systemic risk
without quantifying them, and contains no third-party concentration metric. That absence is
precisely the gap MARSAD fills — and naming it is more defensible than inventing a source.

---

*Live version of this plan, with the same data behind it: the **90-day plan** tab of the MARSAD
dashboard, served from `/v1/roadmap`. The document and the dashboard read from one module, so they
cannot drift apart.*
