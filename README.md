# MARSAD · مرصد

**Privacy-preserving cross-institution incident correlation, with a self-hosted LLM
running inside the data-residency boundary.**

Financial institutions learn they are being hit by the same attacker — coordinated
campaigns, concentration risk on shared providers — **without disclosing incident
detail to a competitor**. Narrative, plaintext indicators and PII never leave the
firm. Only keyed tokens, ATT&CK technique IDs and hour-bucketed metadata cross. The
language model that reads the analyst's prose runs on the institution's own hardware;
a provider pointed at a hosted vendor is refused at construction, not at request time.

Built for **UAE Hackathon 2026 · Track 1 HackArena · Challenge #9**, Securities and
Commodities Authority — now the **UAE Capital Market Authority** — under **Theme 4,
Digital Trust & Cyber-Secure Nation**. The privacy parameters are derived from
published CBUAE and CMA figures rather than chosen: the k-anonymity floor per sector
comes from real licensee cohort sizes, and exposure is priced in AED against two
independent government sources that reconcile within 2%.

---

## Results

Every figure below carries its caveat in the same row. None of them should be quoted
without it.

| What | Result | The caveat, attached |
|---|---|---|
| **Tests** | **623** backend, **14** Playwright e2e, **18** network-boundary (in real containers), **8** live-model | 27 known lint findings, tracked as a ratchet |
| **Canary** | Zero planted strings reach the core — swept across every table, column and row of the live database, every API response, the OpenAPI document and every log line | The sweep is proven able to catch a leak planted in a real row; it is **not** proof against a leak nobody thought to plant |
| **Network boundary** | A connector cannot reach the core by name or by raw IP; the core cannot reach an institution's plaintext store; two institutions cannot reach each other | Enforced by Docker networking. **Single-host caveat**: these containers share a laptop, so a container can still reach `host.docker.internal`. Recorded, not hidden |
| **Rules vs model** — English | Deterministic **98.6%** (138/140) · model **56.4%** (79/140) | **Self-authored fixtures.** The rules were tuned against them; the model never saw them. So the comparison favours the model on paper and it still loses by 42 points |
| **Rules vs model** — Arabic | Deterministic **100%** (70/70) · model **58.6%** (41/70) | Same caveat, harder: 10 fixtures written *after* the Arabic cue tables, by their author. A regression baseline, never a generalisation estimate |
| **Prompt injection** | **26/33** reach `INJECTION` (neutralised, logged as attacker tradecraft) · **7/33** reach `SUSPECTED` only (neutralised, **not** logged) · **0** missed | The `SUSPECTED` row is the honest failure column. Cases are self-authored, so this measures coverage of patterns we thought of — not robustness |
| **Connector image** | **8.73 GB → 327 MB** | camel-tools pulled torch, transformers and CUDA for four character maps. Vendored, with upstream kept as a test oracle checking **every codepoint** in U+0600–U+06FF |
| **Noise floor** | **~0 pts** for warm runs — runs 2–5 of five identical passes were byte-identical. **~1.5 pts** if the first run after a model load is included | **The protocol that follows: discard the first run after every model load.** Without it you carry 12.4% field churn that has nothing to do with model quality |

A four-model benchmark therefore needs **two passes per model**, one discarded — not
dozens. Our own earlier before/after comparison was contaminated by exactly this, and
is corrected in [docs/model-path-results.md](docs/model-path-results.md).

---

## What we measured, and what it cost

The most original work here is not the pipeline — it is what running a real model
through it actually costs. "Constrained decoding is free" is a widespread assumption.
On a 3B model on CPU it is not.

### Constrained decoding is not free, and the cost is a cliff

| Enum size | Mean latency | vs baseline |
|---|---|---|
| Free text (baseline) | 29.3s | — |
| **20 values** (service vocabulary) | **29.2s** | **free** |
| **697 values** (canonical ATT&CK) | **1663s** | **57×** |

Plus a **one-off ~46-minute grammar compile** for the 697-value enum. The threshold
between 20 and 697 is not gradual. Constraining the small vocabulary moved its field
from 12/30 to **20/30 at no latency cost**; constraining the large one made the
experiment unviable — 15 extractions took 7 hours, projecting 42.

### Worst-case latency lands on the least informative reports

| Fixture | Content | Constrained latency |
|---|---|---|
| `10_almost_nothing` | "Something odd happened with our email service." | **4183s** (70 min) |
| `11_typos_chat` | chat fragment, typos | **4103s** |
| `02_ransomware_critical` | a complete, well-formed report | **169s** |

The mechanism is legible: constrained decoding prunes the token distribution to what
the grammar allows. A strong narrative kills most of the 697 branches immediately. A
sparse one prunes nothing, so the decoder grinds through all of them.

The operational consequence is worse than the number. **A hurried, half-written
incident note is exactly when an analyst is most uncertain and least willing to
wait — and it is the input that makes the system slowest.** A tool that degrades most
sharply where it helps least is a design problem, not a benchmark footnote.

### Grammar fixes spelling, not judgement

Classifying every ATT&CK ID the model emitted against the canonical 697:

| | |
|---|---|
| Fixtures already correct | 6/30 |
| Wrong, but **every emitted ID is already valid** — grammar inert | **17/30** |
| Wrong, invented IDs present, but deleting them still leaves the wrong set | 6/30 |
| Wrong, and deleting invented IDs **would** give the right set | **1/30** |

At the ID level, 69% of wrong identifiers are inventions a grammar would remove — true
and flattering. **At the level scoring actually works on, a perfect ATT&CK grammar
takes techniques from 6/30 to at most 7/30. One fixture, for a 57× cost.** The
majority of the failure is the model choosing real, well-formed identifiers that
describe a different attack, and nothing in the schema layer reaches that.

### A certificate that was silently never presented

httpx 0.28 accepts `cert=(crt, key)` and then does not present the certificate. The
server refuses the handshake, the connector reports *core unreachable* and queues
locally — so **a TLS misconfiguration on the remote host looks exactly like a network
outage**, which is the hardest kind of failure to diagnose. Found by testing the
mechanism rather than assuming it; the connector now builds an explicit
`ssl.SSLContext`, and `tests/test_mtls.py` fails if that regresses.

---

## Architecture

```
   INSTITUTION (edge)                    │              OPERATOR (core)
   plaintext lives here, and stays       │              never sees plaintext
                                         │
  ┌───────────────────────────────┐      │      ┌──────────────────────────┐
  │ analyst types prose           │      │      │  correlation engine      │
  │        ↓                      │      │      │  · exact token match     │
  │  A2 extraction ── Ollama      │      │      │  · technique similarity  │
  │   (self-hosted, sovereignty   │      │      │  · k-anonymity gate      │
  │    guard refuses any public   │      │      └──────────┬───────────────┘
  │    endpoint at construction)  │      │                 │
  │        ↓                      │      │      ┌──────────┴───────────────┐
  │  HUMAN CONFIRMS every field   │      │      │ Postgres · schema "core" │
  │        ↓                      │      │      │ no column can hold       │
  │  A14 injection check          │      │      │ narrative                │
  │  (regex, never model-based)   │      │      └──────────────────────────┘
  │        ↓                      │      │                 ▲
  │  A3 REDACTION ─ the only      │      │                 │
  │  component that may build     │      │         mutual TLS, one route
  │  a boundary payload           │      │                 │
  └───────────────┬───────────────┘      │                 │
                  │                      │                 │
  ┌───────────────┴───────────────┐      │      ══════════════════════════
  │ Postgres · schema "edge"      │      │       ONLY THIS CROSSES:
  │ narrative, analyst notes,     │      │       · keyed tokens (HMAC→OPRF)
  │ raw email, extraction spans   │      │       · ATT&CK technique IDs
  │ — expire together, 90 days    │      │       · sector, size, severity band
  └───────────────────────────────┘      │       · timestamp, bucketed to the hour
                                         │       · an obligation receipt HASH
   separate database, separate           │      ══════════════════════════
   schema, separate host, no route       │       NEVER: narrative · notes
   from core to here                     │       plaintext indicators · PII
                                         │       service names · vendor names
                                         │       extraction spans · firm names
```

The model sits **inside** the edge, upstream of redaction. That is why the sovereignty
guard runs at construction: this layer sees plaintext before any boundary control acts,
so a misconfigured base URL would leak before A3 exists.

---

## How the boundary is enforced

Two tests check the central claim itself rather than a mechanism supporting it.

**The canary.** Plants unique random strings inside an incident, runs the real
pipeline — extraction, confirmation, redaction, submission, correlation — then looks
everywhere the core can hold or emit anything: every table, column and row (found by
**reflection**, not by asking the ORM what it declared), every API response, the
OpenAPI document, every log line. Five surfaces are canaried separately, including a
vendor name that extraction quotes verbatim as span evidence, and an Arabic canary
planted so normalisation rewrites it — it then exists in two forms and both must be
absent.

```bash
python -m pytest tests/test_canary.py -v
```

**The network boundary.** Runs *inside* the containers and asserts a connector cannot
reach the core by service name or raw IP, the core cannot reach a connector's
plaintext store, and two institutions cannot reach each other. A positive control
drives a real incident through the one permitted route, because isolation tests pass
trivially when everything is broken.

```bash
make test-boundary          # brings the stack up, runs the suite, tears it down
```

Both keep themselves honest: `test_the_sweep_can_find_a_leak_planted_in_a_database_row`
plants narrative in a real column and requires the sweep to report it at the right
path, and `test_the_sweep_reflects_tables_rather_than_trusting_the_orm` creates a table
outside the ORM and requires the sweep to find that too.

```bash
make test                   # 623 backend
make test-e2e               # 14 Playwright, against the real UI
make test-llm               # 8, needs a live Ollama
make test-network           # 2, hits a real UAE government portal
```

---

## Honest scope

Read this before believing anything above.

- **Incident data is synthetic.** No UAE open dataset publishes cyber incidents broken
  down by financial-sector entity — that absence is the gap MARSAD fills. The privacy
  parameters and AED exposure figures are *not* invented; the incidents are.
- **Every accuracy figure is a regression baseline, not a generalisation estimate.**
  The extraction fixtures and the injection corpus are **self-authored**, and the
  deterministic extractor was tuned against them. They tell you when a change makes
  things worse. They say nothing about an unseen institution's prose.
- **HMAC, not OPRF.** Indicators are low-entropy; anyone holding the key can brute-force
  the input. One shared key across institutions puts the holder in exactly the position
  we promise nobody occupies. **Do not process real institutional data until this is
  replaced.**
- **Jaccard, not enclave.** Technique similarity needs the technique sets in the clear
  at the core — a weaker privacy position than the deployment target. Every result from
  a weaker engine self-labels `reduced_fidelity`.
- **Not deployed.** There is no public URL. The deployment artefacts exist and are
  verified locally; nothing has run on public infrastructure. See
  [docs/deployment.md](docs/deployment.md), which separates what was verified from what
  was not.
- **The network boundary is proven on one host.** Containers share a laptop, so one can
  still reach `host.docker.internal`. In deployment the two sides are different
  organisations on different machines — but that has not been tested, and the test says
  so rather than pretending otherwise.
- **The model path is measured on one model.** qwen2.5:3b-instruct on CPU. A larger
  model may well close the gap with the rules; that is unmeasured.
- **No government integration.** No verified access to SCA/CMA systems, taxonomies or
  data. Every entity named in the design is a notional counterparty requiring a formal
  agreement.

---

## Install

```bash
make install          # contracts, service deps, Playwright browser
make migrate          # both databases, empty to current
make run              # docker compose: core + 3 connectors + web
make demo             # drive the full scenario through the real services
```

Then open <http://localhost:3000>.

Optional — the self-hosted model:

```bash
ollama serve & ollama pull qwen2.5:3b-instruct
export MARSAD_LLM_PROVIDER=openai_compatible
export MARSAD_LLM_BASE_URL=http://localhost:11434/v1
export MARSAD_LLM_MODEL=qwen2.5:3b-instruct
```

The sovereignty guard refuses any endpoint reachable on the public internet, and any
hosted-vendor API key, **at construction** — a connector that only fails when an
analyst files their first incident has already failed.

**Further reading:** [CLAUDE.md](CLAUDE.md) (what a contributor must not get wrong) ·
[docs/model-path-results.md](docs/model-path-results.md) (the measurements) ·
[docs/injection-results.md](docs/injection-results.md) ·
[docs/deployment.md](docs/deployment.md)
