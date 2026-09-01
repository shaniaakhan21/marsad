# CLAUDE.md — working on MARSAD

## What this is

MARSAD is privacy-preserving cyber-incident correlation for UAE capital markets: institutions learn
they are being hit by the same attacker without any of them disclosing incident detail to a
competitor. A connector runs inside each institution's perimeter and is the only code that touches
plaintext; a core service receives keyed tokens and coarse metadata and could not reverse them into
an incident if it wanted to. Everything here serves that one property — a change that weakens it is
wrong regardless of what else it improves.

## The edge/core split is physical, not conceptual

`services/connector` is EDGE, `services/core` is CORE — separate deployables talking over HTTP,
and the split is the product rather than an architectural preference.

**May cross:** keyed tokens (`KeyedToken`), ATT&CK technique IDs, hour-bucketed timestamps,
banded severity, sector, size band, a rotating `institution_ref` pseudonym, an obligation
receipt *hash*.
**May never cross:** narrative, analyst notes, plaintext indicator values, hostnames, user
identifiers, affected system names, evidence files, precise timestamps, firm names, rule text,
draft notifications — anything from A4 other than the receipt hash.

[boundary.py](packages/contracts/marsad_contracts/boundary.py) is the only source of truth.
`StrictModel` sets `extra="forbid"`, so an undeclared field cannot cross and a typo cannot smuggle
data across. **Adding a field to those models is a security review, not a routine change** — do not
add one to make a feature easier.

## A3 is the only component that may build a boundary payload

[a3_redact.py](services/connector/marsad_connector/agents/a3_redact.py) constructs
`IncidentSubmission`; nothing else may. It holds no network capability by design — the sole egress
is `submit()` in [main.py](services/connector/marsad_connector/main.py), which accepts nothing but
an already-validated submission.

A3 **builds from an allow-list; it does not strip a rich object down to a safe one.** That
distinction is the whole guarantee. It reads only the fields it names — grep `build_submission`
for `narrative`, `analyst_notes` or `evidence_paths` and you will find nothing. A stripper leaks
the moment someone adds a field upstream; a constructor cannot. If you find yourself writing
`.pop(...)`, `del payload[...]`, or "copy it all, then remove the sensitive bits", stop — you
have inverted the design. `_assert_no_leakage` sits on top as belt-and-braces: do not delete it
because "the types already prevent this", it turns a future refactoring mistake into a loud
failure rather than a silent disclosure. A3 fails closed — `RedactionError`, never partial.

## Extraction proposes; a human confirms

Free-text intake ([a2_extract.py](services/connector/marsad_connector/agents/a2_extract.py)) reads
an analyst's prose and produces an `ExtractionDraft`. A draft is a proposal, not an incident, and
it **structurally cannot reach A3**: the attributes A3 reads are not present on it, and touching
one raises `UnconfirmedExtractionError` rather than returning a value. `confirm(analyst=...)` is
the only path to a `ConfirmedIncident`, and a `ConfirmedIncident` is the only thing A3 will build
from.

A2 is `Autonomy.PROPOSE_CONFIRM`, never `AUTOMATIC` — the analyst sees every field with its
confidence and the span of text it came from, and may edit any of them. Fields the narrative does
not state are omitted, never guessed: a confident wrong severity is worse than a blank one,
because a blank prompts a question and a guess does not. **Any change that lets a draft reach the
boundary is a regression**, whether by adding the missing attributes to the draft, by relaxing the
gate to a boolean flag a caller can forget, or by constructing a `ConfirmedIncident` anywhere
other than `confirm()`.

## A14 injection detection is deterministic on purpose

[a14_supervisor.py](services/connector/marsad_connector/agents/a14_supervisor.py) is regex plus
weighted heuristics — **never model-based**, and this is not a prototype shortcut. Asking a
language model whether text contains an injection means asking the compromised component to
police itself: the same text that subverts extraction can subvert the classifier. Detection has
to sit outside the thing being attacked. Weights are small integers so a compliance reviewer can add
a score up by hand, and every finding carries a named signature, a stated reason and an excerpt so an
analyst can disagree with the verdict. Do not route this through `LLMProvider`; to improve coverage,
add a `Signature` with its `why` written out.

## A detected injection returns a finding, never a veto

`extraction_blocked` is `False` and stays `False`. Blocking would hand the attacker a
denial-of-service: embed an injection in the phishing email, the report stops, the correlation
never fires, and every other institution hit by the same campaign is never warned. Suppressing
one report suppresses the collective signal — the highest-value attack on this system. So the
attempt is neutralised (delimiters defanged, invisible characters stripped, evidence preserved
for attribution), logged as attacker tradecraft, surfaced to the analyst, and the incident
proceeds at its original severity. Any change that lets a verdict gate a code path is a
regression. Same reasoning elsewhere: the core is *additive* — if it is unreachable the connector
queues locally and returns 503, because MARSAD must never sit on the critical path of a firm in
crisis.

## Test discipline: tests are documentation

Each test in [tests/](tests/) encodes a claim the project makes out loud to a regulator, a
bank's counsel, or a reviewer. `test_injection_never_blocks_the_incident` is not coverage — it
is the denial-of-service argument, executable. `test_leak_guard_trips_on_regression` sabotages
the agent on purpose to prove the guard fires. The fetcher suite asserts a dead portal falls back
honestly instead of raising; the open-data suite asserts citations are complete and provenance is
never overstated. So when you add behaviour the project claims, add the test that proves the claim
and name it as the claim (`test_cma_deadline_is_48_hours_from_detection`, not `test_cma`), with a
docstring giving the reason it matters. Changing behaviour a test asserts changes a public promise
— say so, don't quietly retune the assertion. Deleting a test deletes a claim. Anything touching a
real portal is marked `@pytest.mark.network` and stays out of the default run.

## Code style, as observed

- `from __future__ import annotations` at the top of every module; full type hints throughout.
- Module docstrings explain **why the module exists and what it defends against**, not what the
  functions do. Read the top of `tokeniser.py` or `a14_supervisor.py` for the register.
- Comments state design stances, especially where the obvious implementation is wrong
  (`# never. See the module docstring, rule 3.`).
- Module-level `#:` constants for anything a reviewer might tune — thresholds, weights, caps.
- Protocols/ABCs at swap points (`Tokeniser`, `SimilarityEngine`, `LLMProvider`, `IncidentLike`),
  so upgrading a trust assumption is a change of binding, not a rewrite.
- Weaker-than-target implementations self-label (`reduced_fidelity = True`) and that label
  propagates to every downstream alert. Nothing degrades silently.
- `make lint` (`ruff check packages services tests`) is **not** clean: 39 pre-existing
  errors, mostly `# noqa: E402` on the test path shims and logically-grouped `__all__`.
  The rule is a ratchet — your change must not raise that number. Fix what you touch if
  you like, but do not leave it higher than you found it.

## The rule

**Every change must leave `python -m pytest` fully green.** Currently 284 passed, 17 deselected
(the `network` marker — `make test-network`; and the `docker` marker — `make test-boundary`). No
skips, no xfails, no "unrelated failure". If a test blocks you, it is a claim someone made
deliberately — understand the claim before you touch it.

Two of those tests check the central claim rather than a mechanism supporting it:
`tests/test_canary.py` proves nothing planted inside an institution reaches the core, and
`tests/test_network_boundary.py` proves a connector cannot reach the core at all. Both run in CI.
Neither may be weakened to make a change pass.
