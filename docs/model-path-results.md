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

---

# Re-measurement, after the controls

The first run justified four changes. They were applied and the same fixtures re-run
against the same model, with no prompt or fixture edits and no tuning.

## What moved, and what did not

| | Before | After |
|---|---|---|
| English accuracy | 74/140 = 52.9% | **79/140 = 56.4%** (+3.6 pts) |
| Arabic accuracy | 35/70 = 50.0% | **41/70 = 58.6%** (+8.6 pts) |
| Errors / timeouts | 1 (`17_many_indicators`, 900s) | **0** |
| Slowest extraction | 900.1s (killed) | **131.1s** |
| Wall clock, 30 narratives | 34 min | **18 min** |

**The accuracy delta is not attributable to the controls, and should not be read as
one.** Decomposed:

* English gained 5 fields. **3 of those are fixture 17 alone**, which previously
  scored 0/7 because it timed out and now scores 3/7 because it completes. Outside
  that fixture: 3 fields newly right, 1 newly wrong — net +2.
* Arabic gained 6 fields, none of them from fixture 17 (it is English). All 6 are
  changed answers.
* **32 of 203 fields — 16% — produced a different value on the second run**, at
  `temperature: 0`, on an identical prompt. Adding `maxItems` changes the grammar and
  therefore the constrained-decoding path, so the two runs are not the same
  experiment; and a 16% churn rate means a ±6 field swing is inside the noise floor
  of a single 30-narrative run.

So the honest statement is: **the controls did not measurably improve extraction
accuracy, and were not intended to.** They are safety and availability controls. What
they demonstrably fixed is what they targeted.

## What the controls actually fixed

**The hang is gone.** `17_many_indicators` went from 900 seconds and killed to 131.1
seconds and correct-enough to score. `maxItems`, read off the contract rather than
repeated, gives constrained decoding somewhere to stop. Total wall clock nearly
halved as a side effect.

**69 malformed confidences were caught in the second run** — out-of-range values that
`strict: true` still lets through, that would previously have been compared against
`CONFIDENCE_THRESHOLD` as though they meant something. They are now refused rather
than clamped: a 100.0 clamped to 1.0 would become a maximally *trusted* answer.

**Fabricated indicators are dropped rather than tokenised.** The gate fired in the
re-run. This is the control with real downstream consequence: an indicator that was
never written becomes a token in a matching space every other institution is compared
against, reviewable by nobody because they see only the hash.

**The timeout no longer fails a quarter of requests.** It is now
`2 × 90.5s = 181s`, derived from the slowest extraction actually observed, rather than
a round 45s that sat between the measured mean (40.1s) and p95 (53.5s) and failed 8 of
30.

## What still has not moved

The model remains roughly half as accurate as the regex tables, and every reason from
the first run stands: hallucinated ATT&CK IDs (techniques 4/20 EN, unchanged),
paraphrased service names outside the canonical vocabulary (8/20 EN, unchanged),
inflated severity (12/20 EN, unchanged). None of the controls address model judgement,
which is where the losses are.

The 16% run-to-run churn is itself a new finding, and a caution for any future
multi-model benchmark: at this fixture count, a single run cannot resolve differences
smaller than about ten points. Comparing models on 30 self-authored narratives, once
each, would produce a ranking that is mostly noise.

---

# Experiment 1 — the noise floor of this fixture set

Five identical passes: same model, same prompt, same schema, same fixtures, nothing
changed between runs.

| | run 1 | run 2 | run 3 | run 4 | run 5 |
|---|---|---|---|---|---|
| English | 56.4% | 57.9% | 57.9% | 57.9% | 57.9% |
| Arabic | 58.6% | 57.1% | 57.1% | 57.1% | 57.1% |

## This corrects an earlier claim in this document

The "16% of fields change at temperature 0" reported after the second run was real but
misattributed. Measured cleanly, the pairwise field-level churn matrix is:

```
        run1  run2  run3  run4  run5
run1     0.0  12.4  12.4  12.4  12.4
run2    12.4   0.0   0.0   0.0   0.0
run3    12.4   0.0   0.0   0.0   0.0
run4    12.4   0.0   0.0   0.0   0.0
run5    12.4   0.0   0.0   0.0   0.0
```

**Runs 2–5 are field-for-field identical.** Only the first run differs. This is not
ongoing nondeterminism; it is a **cold-start effect**, confirmed directly rather than
inferred: after `ollama stop` forced a reload, the first extraction differed from the
second, and the second and third were byte-identical.

So Ollama at `temperature: 0` **is** deterministic — once the model is warm.

## The number, published

**Minimum resolvable difference on this fixture set at 95% confidence:**

| Protocol | MRD |
|---|---|
| Warm runs, first run after model load discarded | **~0 pts** — a single warm run resolves any real difference |
| First run after model load included | **~1.5 pts** |

The naive statistic — SD 0.21 across five runs, giving 0.6pt at n=1 — is misleading,
because the variance is not random scatter but one outlier run. The two-regime
statement above is the operational one.

## What a four-model benchmark costs

**Two passes per model: one discarded warm-up, one measured.** Eight passes for four
models, ~4 hours at ~30s per extraction on this CPU-only host. That is affordable,
which would not have been the conclusion from the contaminated 16% figure — that
number implied dozens of runs per model.

The protocol point matters more than the arithmetic: **discard the first run after
every model load.** Without it a comparison carries 12.4% field churn that has nothing
to do with model quality, and differences below ~1.5 points are unresolvable. The
before/after comparison earlier in this document was contaminated in exactly that way,
and its "+3.6 / +8.6 points" should be read as a cold-start artefact plus one fixture
that stopped timing out.

## Per-field instability

Across the five runs, cells with more than one distinct value:

| Field | Unstable |
|---|---|
| techniques | **14/30 = 47%** |
| affected_services | 3/30 = 10% |
| third_party_dependencies | 3/30 = 10% |
| category | 2/30 = 7% |
| detected_at | 2/30 = 7% |
| severity | 1/30 = 3% |
| indicators | 1/30 = 3% |

All of it is contributed by run 1. The field that scores worst — `techniques` at 4/20
— is also by far the least stable across a cold start.

---

# Experiment 2 — vocabulary versus judgement

`severity` is enum-constrained and scores 19/30. `affected_services` (12/30) and
`techniques` (6/30) were generated freely. Is that difference causal?

It is, for one of them, and the cost of finding out is the more interesting result.

## Lead finding: constrained decoding is not free, and it fails worst where you need it most

The headline number is that constraining `techniques` to the 697-value canonical
ATT&CK list made extraction **57× slower** — a mean of 1663s against a 29.3s baseline,
on the same fixtures and the same model. But the shape of the cost matters more than
the multiplier.

**The slowest fixtures were the least informative ones.**

| Fixture | What it contains | Constrained latency |
|---|---|---|
| `10_almost_nothing` | "Something odd happened with our email service. Still looking into it." | **4183s** (70 min) |
| `11_typos_chat` | chat-register fragment, typos, one domain | **4103s** (68 min) |
| `14_run_on` | run-on sentence, no punctuation | 3806s |
| `01_clean_phishing` | complete, well-formed report | 2764s (includes one-off grammar compile) |
| `02_ransomware_critical` | complete, well-formed report | 169s |

This is mechanistically legible. Constrained decoding prunes the token distribution to
what the grammar permits; when the narrative gives the model a strong signal, most of
the 697 branches die immediately and generation is quick. When the narrative says
almost nothing, nothing prunes them, and the decoder grinds through a 697-branch
grammar with no evidence to collapse it.

The operational consequence is worse than the latency: **worst-case latency lands on
the least informative reports.** A sparse, hurried, half-written incident note is
precisely when an analyst is most uncertain, most time-pressed and least willing to
wait — and it is exactly the input that makes the system slowest. A tool that degrades
most sharply where it helps least is a design problem, not a performance footnote.

There is also a **one-off grammar-compilation cost of ~46 minutes** for the 697-value
enum, paid on the first request after the schema changes.

"Constrained decoding is free" is a widely held assumption. On a 3B model on CPU, with
a realistically sized vocabulary, it is not.

## Claim 1 — constraining a small vocabulary is cheap, and it works

`affected_services` constrained to the repo's existing 20-label vocabulary, everything
else untouched:

| | Baseline (warm) | Services enum (warm) | |
|---|---|---|---|
| `affected_services` | 12/30 | **20/30** | **+8 fixtures** |
| English overall | 57.9% | **64.3%** | +6.4 pts |
| Arabic overall | 57.1% | 57.1% | +0.0 pts |
| Mean latency | 29.3s | **29.2s** | free |

Against the noise floor from experiment 1 (~1.5 pts including a cold run, ~0 for warm
runs), +8 fixtures on the constrained field is decisively real.

**Latency was unchanged.** 29.2s against 29.3s. So the 57× penalty is not a property of
constrained decoding as such — it is a property of *vocabulary size*, and the threshold
between 20 values and 697 is not gradual.

Two honest qualifications. The service vocabulary is the repo's own and the fixtures'
expected labels are drawn from it, so this measures "does constraining generation to
the vocabulary the system actually consumes eliminate format errors" — which it does —
and not "does the model know which service was affected". And the English gain (9/20 →
16/20) dwarfs the Arabic one (3/10 → 4/10): constraint fixed English *spelling*
(`CORE_BANKING`, `PAYMENT_GATEWAY`, `KYC` — case and underscore variants of real
members) while Arabic failures were more often the model choosing the wrong service
entirely, which no grammar reaches.

`techniques` moved 6/30 → 7/30 in this run despite not being constrained. That is
incidental drift from a changed grammar, not an effect; it should not be read as one.

## Claim 2 — constraining a large vocabulary costs 57×, and is unviable here

Measured, then abandoned: 15 extractions took ~7 hours, projecting **42 hours** for the
3-pass experiment. Mean 1663s, worst case 4183s, against a 29.3s baseline.

The run was stopped rather than completed. Reporting an unviable configuration as
unviable, with the numbers, is the result — finishing it would have cost two days to
learn the same thing more precisely.

## Claim 3 — grammar's ceiling on techniques is one fixture, and it is not worth 57×

This was answered analytically from data already in hand, which is why the 42 hours
were not spent. Classifying every technique ID the model emitted in the warm
deterministic run against the canonical 697:

| | |
|---|---|
| Fixtures already correct | 6/30 |
| Wrong, **every emitted ID already valid ATT&CK** — grammar is inert | **17/30** |
| Wrong, contains invented IDs, but deleting them still leaves the wrong set | 6/30 |
| Wrong, and deleting invented IDs **would** yield the right set | **1/30** |

At the ID level, 61 of 89 wrong identifiers (69%) are inventions a grammar would
eliminate — `T1044`, `T1089`, `T1158.001`, `T1059.014`, none of which exist. That
number is true and flattering.

At the level scoring actually operates on — set equality per fixture — **a perfect
ATT&CK grammar takes techniques from 6/30 to at most 7/30.** One fixture. And that one
is `ar_10_negation`, whose expected answer is *no techniques at all*: the model
invented IDs for a narrative that explicitly states no data was leaked and the provider
was not compromised, so deleting the fabrications leaves an empty set that happens to
be right.

**Grammar fixes spelling. It cannot fix judgement.** 17 of 30 fixtures are the model
selecting real, well-formed ATT&CK identifiers that describe a different attack.
Nothing in the schema layer can reach that, and it is the majority of the failure.

## Future work — hierarchical constraint

The obvious engineering answer, recorded as future work and not as a rescue: constrain
in two stages. Pick a parent technique from the 222-value parent list, then pick a
sub-technique from within the chosen parent — at most 30 or so options. Two small
grammars instead of one 697-branch grammar, each in the size regime that Claim 1 shows
is free.

That would make the technique enum affordable. It would not make it worthwhile here:
Claim 3 says the ceiling is one fixture. It is worth doing when the field to be
constrained has failures that are actually spelling, as `affected_services` did.
