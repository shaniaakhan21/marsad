# The model path, measured

Until now every accuracy figure in this repository described `HeuristicExtractor` —
the deterministic offline path. `ModelExtractor` had never been executed. This is that
measurement.

## Setup

| | |
|---|---|
| Serving stack | Ollama **0.33.0** (Homebrew), OpenAI-compatible endpoint at `http://localhost:11434/v1` |
| Model | **`qwen2.5:3b-instruct`** |
| Digest | `357c53fb659c5076` |
| Parameters / quantisation | 3.1B, **Q4_K_M**, 1.93 GB, context 32768 |
| Host | Intel x86_64 macOS, **no Metal/GPU acceleration** — CPU only, ~7 tok/s |
| Prompt | the connector's own `SYSTEM_PROMPT`, unchanged |
| Schema | the connector's own `EXTRACTION_SCHEMA`, with one recorded transform (below) |
| Fixtures | the existing 20 English + 10 Arabic, unchanged |

Qwen2.5 was chosen for Arabic coverage at a size that runs on modest hardware, which
is the deployment this project actually targets — a sovereign model inside an
institution, not a datacentre.

**Nothing was tuned.** No prompt edits, no schema edits to improve the score, no
fixture edits. The two deviations below exist to make the path executable at all and
are both recorded in `docs/model-bench-raw.json`.

## Headline: the model is roughly half as accurate as the regex tables

Reported per language, never blended, with the same caveat as every other figure here.

| Set | Deterministic | Model | Field slots |
|---|---|---|---|
| English | **138/140 = 98.6%** | **74/140 = 52.9%** | 20 narratives × 7 fields |
| Arabic | **70/70 = 100.0%** | **35/70 = 50.0%** | 10 narratives × 7 fields |

Excluding the fixture that timed out, the model scores 74/133 = 55.6% (EN) and
50.0% (AR). Reporting it both ways because a 900-second timeout is a real production
failure, not a measurement artefact to be excused.

> **The same caveat applies to every number above.** These are self-authored fixtures
> and the deterministic extractor was tuned against them, so its figure is a
> regression baseline measured close to its own training set, not a generalisation
> estimate. The model figure is *not* subject to that particular bias — the model has
> never seen these fixtures — which makes the comparison **unfair in the model's
> disfavour on paper, and yet the model still loses by 45 points**. Neither number
> says anything about accuracy on an unseen institution's prose. See
> `tests/fixtures/narratives/README.md`.

### Per field

| Field | EN det | EN model | AR det | AR model |
|---|---|---|---|---|
| severity | 20/20 | 12/20 | 10/10 | 6/10 |
| category | 20/20 | 12/20 | 10/10 | 5/10 |
| affected_services | 20/20 | **8/20** | 10/10 | **2/10** |
| third_party_dependencies | 20/20 | 13/20 | 10/10 | 5/10 |
| indicators | 20/20 | 9/20 | 10/10 | 7/10 |
| techniques | 18/20 | **4/20** | 10/10 | **1/10** |
| detected_at | 20/20 | 16/20 | 10/10 | 9/10 |

### The model never won

Across all 210 field comparisons:

| | Count |
|---|---|
| Both right | 109 |
| Deterministic right, model wrong | **99** |
| **Model right, deterministic wrong** | **0** |
| Both wrong | 2 |

Not one field where the model beat the tables. That is the result.

## Where they disagree, and which is right

**Techniques — the worst field, and the model is wrong nearly every time.** It emits
well-formed ATT&CK IDs that are unrelated to the incident: `T1010` (Application Window
Discovery) for a phishing report, `T1158.001` for invoice fraud, `T1027.002` for a
DDoS, `T1040.006` for a phishing email. The grammar guarantees the *shape* `T\d{4}`
and guarantees nothing about the meaning, so the model produces syntactically perfect
nonsense. The cue tables map an English or Arabic phrase to an ID and decline when
there is no phrase — 18/20 and 10/10. **Deterministic is right.**

**Affected services — the model paraphrases; the tables use a canonical vocabulary.**
The model returns `core_banking` for `core banking`, `payment_gateway` for `payment
gateway`, `kyc` for `kyc service`, `customer portal` for `client portal`. Some of these
are arguably the same thing to a human and none of them are the same string to a
concentration analysis that groups by provider. A free-text field extracted freely is
not a vocabulary. **Deterministic is right**, and this is the strongest argument in the
set for a closed vocabulary over model judgement.

**Severity — the model inflates.** `MEDIUM → HIGH` (03), `CRITICAL → HIGH` (02, 05),
`HIGH → CRITICAL` (07, ar_01, ar_09), and on `04_vendor_breach` it invented `CRITICAL`
where the narrative states no severity at all and the expected answer is *absent*.
Severity drives every regulatory deadline in A4. **Deterministic is right**, and this
field is why A2 forces severity in front of a human regardless of confidence.

**Negation — the model reads through it.** `ar_10_negation` says
"لم يتم تسريب البيانات ولم يتم اختراق المزود" (no data was leaked and the provider was
not compromised). The model returned a third-party dependency and techniques anyway.
The tables have an explicit Arabic negation guard, added after the `لم` bug.
**Deterministic is right.**

**Indicators — the model drops them or mistypes them.** It returned `None` where a URL
or domain is plainly present (01, 05, 11, ar_01, ar_03, ar_07), typed a Bitcoin wallet
as `URL` (02), typed a domain as `IP` (08), and on `07` emitted
`("URL", "UNTRUSTED_...")` — **it extracted our own fence marker as an indicator**.
That last one would have been tokenised and submitted. **Deterministic is right**, and
this is the field where being wrong is most expensive: a mistyped indicator tokenises
into a different domain-separated namespace and silently never correlates.

**The model emitted Chinese.** On `ar_07_credentials_mixed`, `affected_services` came
back as `网上银行服务` — "online banking services" in Chinese, for an Arabic input.
Qwen is a Chinese-developed model and a third language leaked into structured output
under grammar constraints. No downstream component would recognise it.

**Two cases where neither is right.** On `01_clean_phishing` techniques, the tables add
`T1656` (impersonation) to the expected `T1566.002` — defensible, since the narrative
says "impersonating"; the model returned `T1021.002`, unrelated. On `18_mixed_script`
both miss. These are the honest remainder.

## Breakages

Each is captured as a test in `tests/test_llm_live.py` (marker `llm`), so a future
Ollama that fixes one will fail the test rather than pass silently.

**1. Ollama rejects the production schema outright.** `HTTP 400 — failed to initialize
samplers: failed to parse grammar`. Ollama *does* honour `response_format:
json_schema`, by compiling it to a GBNF grammar; its compiler does not support the
`\d` shorthand. Bisected: every other construct passes alone — nullable unions, enums
containing `null`, nested objects, arrays, `additionalProperties: false`, `pattern`,
`format: date-time`. The cause is the ATT&CK pattern `^T\d{4}(\.\d{3})?$` inherited
from the boundary contract. `^T[0-9]{4}(\.[0-9]{3})?$` compiles and means the same for
ASCII IDs. **The contract was not changed**; the benchmark applies the transform and
records it.

**2. `strict: true` does not validate.** `confidence` is declared `minimum: 0,
maximum: 1`. **95 of 203 returned values were outside that range** — the maximum
observed was `100.0`. A toy schema with `maximum: 1` returned `1234567890`. Anything
treating this schema as a validator is wrong, and A2 stores what arrives, so an
out-of-range confidence reaches the analyst's review screen and the
`CONFIDENCE_THRESHOLD` comparison is meaningless against it.

**3. Confidence is not calibrated in any usable sense.** 41% of fields came back at
exactly `1.0`, including fields the model got wrong. The whole review mechanism — flag
below `0.70`, always review severity and `detected_at` — assumes a confidence that
means something. It does not.

**4. Half the evidence is fabricated.** **103 of 203 fields cited evidence that does
not appear verbatim in the narrative.** This is the single best result of the exercise:
`_locate` already treats an unlocatable citation as unsupported and flags the field, so
the guard written on suspicion turns out to fire on *half* of real model output. It was
not paranoia.

**5. Runaway generation.** `17_many_indicators` (six indicators) generated for
**900 seconds** without completing and was recorded as a timeout. All four array fields
in `EXTRACTION_SCHEMA` are unbounded, while the boundary contract caps `tokens` at 512
and `technique_set` at 64. Grammar-constrained decoding has nowhere to stop. Adding
`maxItems` mirroring the contract is the obvious fix and was **not** applied, because
doing so during measurement would have changed the number.

**6. The connector's timeout is too short for this hardware.** `REQUEST_TIMEOUT_SECONDS`
is 45s; median extraction was **38.1s** and the mean was above 45s (min 24.1s, median
38.1s, max 900.1s, ~34 minutes for 30 narratives). The shipped default would fail a
large fraction of requests on a CPU-only host. Not raised — that is a deployment-sizing
decision, and raising it trades a failed request for an analyst watching a spinner.

## The sovereignty guard, exercised live for the first time

Every previous test injected a fake DNS resolver. Against the real endpoint and real
DNS, through the same `build_llm` construction path:

- `http://localhost:11434/v1` — **accepted**, and the model answers.
- `https://api.openai.com/v1` with `sk-proj-…` — refused (vendor key prefix).
- `https://api.anthropic.com/v1` — refused, **by genuine DNS resolution** to a public
  address (160.79.104.10).
- `http://8.8.8.8:11434/v1` — refused (public IP literal).

A guard that refused everything would have looked identical in the mocked tests. It
does not.

## What this does and does not license

It does **not** say language models are useless here. It says this model, at this size,
on this schema, with no tuning, is worse than the cue tables on every field, and that
several of the mechanisms built around the model — confidence thresholds, evidence
spans, schema validation — are load-bearing precisely because the model behaves badly.

It also does **not** establish the deterministic extractor is good. Its figure is
measured on fixtures written alongside it.

What it does establish: the default `StubProvider` is not hiding a better path, A2's
PROPOSE_CONFIRM gate is not ceremony, and any future multi-model benchmark now has a
measured floor to beat. Larger models, a schema with `maxItems`, and a held-out fixture
set authored by someone else are the three things that would make the next run mean
more than this one.
