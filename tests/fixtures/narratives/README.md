# Narrative fixtures — extraction regression set

30 incident narratives with hand-labelled expected fields: **20 English, 10 Arabic**.
Used by `tests/test_extraction_accuracy.py`.

## The two numbers, and why they are never one number

| Set | Fixtures | Field slots | Recorded |
|---|---|---|---|
| English | 20 | 140 | **138/140 = 98.6%** |
| Arabic | 10 | 70 | **70/70 = 100.0%** |

They are reported separately and must stay that way. They are different cue tables of
different maturity measured on sets of different sizes; a blended average would hide
whichever is weaker behind whichever is larger, and the blended figure is the one that
would end up quoted. `test_accuracy_cannot_be_computed_without_naming_a_language`
enforces this structurally — there is no way to ask the module for a combined figure.

## What both numbers mean, and what they do not

Read each as exactly one thing:

> **A regression baseline for the deterministic offline extractor
> (`HeuristicExtractor`), measured on fixtures authored by the same person who wrote
> and tuned that extractor.**

Neither is:

- **A generalisation estimate.** The fixtures and their labels were written alongside
  the extractor, and extractor bugs were found and fixed against them. Each number is
  measured on something close to its own training set. Quoting either as accuracy on
  an unseen institution's prose would be dishonest.
- **A measure of model quality.** No language model is involved. The connector's
  default LLM provider is the offline stub and CI has no sovereign endpoint, so a
  number that moved with whatever a model produced that morning would not be a
  regression test. `ModelExtractor` — the path that calls a real sovereign model — is
  **unmeasured, in both languages**.
- **Evidence that extraction is safe to trust unreviewed.** It is not, which is why
  A2 is `PROPOSE_CONFIRM` and every field goes in front of an analyst regardless of
  score.

### The Arabic 100% deserves more scepticism, not less

It is measured over **10 fixtures written after the Arabic cue tables, by their
author**. A perfect score there is evidence that the cues cover those ten narratives
and nothing more. The English set is larger and still does not clear 100%. Treat any
Arabic figure as provisional until a held-out set exists, and do not put it in front
of a reviewer without this paragraph attached.

## Still unmeasured

None of these should be presented as done:

1. **A held-out set, in either language.** Narratives written by someone other than
   the extractor's author, labelled before the extractor sees them. Until that exists
   there is no generalisation number at all.
2. **The model path.** `ModelExtractor` against a real sovereign-hosted open-weight
   model, scored on the same fixtures and on the held-out set above.
3. **Arabic-Indic numerals.** Timestamps written ٢٠٢٦-٠٨-١٩ are not parsed; the field
   comes back absent rather than misread, which is the safe direction but is not
   support.
4. **Arabic-named vendors.** `third_party_dependencies` captures Latin-script names
   only. An Arabic-script vendor name is missed rather than invented — again the safe
   direction, and again not support.

## Fixture format

```json
{
  "id": "ar_03_codeswitch_severity",
  "language": "ar",
  "messiness": "code-switched: Arabic prose, English severity value",
  "narrative": "…what an analyst typed…",
  "expected": { "severity": "MEDIUM", "category": "PHISHING", "…": null }
}
```

`language` is `en` or `ar` and decides which bucket the fixture scores into.
`expected` must label all seven fields; `null` means the narrative genuinely does not
state it, and a fixture that omits a key silently inflates accuracy
(`test_every_fixture_declares_its_language_and_labels_every_field` enforces both).

Expected values are **canonical**: `affected_services` uses the same English labels
for an Arabic report as for an English one, because the structured incident is one
vocabulary regardless of the language it was reported in. Only the display stays in
the analyst's words.

## Register coverage

The English set varies across clean prose, chat shorthand with typos, shouted
all-caps, a pasted ticket, bullet fragments, run-on text, mixed script, and two
narratives that state almost nothing. The Arabic set covers clean Arabic prose, fully
diacritised text, hamza and teh-marbuta variants, Arabic negation, a sparse report,
and — the case this work was done for — three code-switched narratives where Arabic
prose carries English technical terms and severity values in the same sentence.

## Adding a fixture

Label what the narrative **says**, not what the extractor happens to produce.
Changing a label to match the output is how a regression suite stops measuring
anything. If the extractor disagrees with a fair label, that is a miss — record it.

Arabic cue literals live in `a2_extract.py` and must be written in **normalised**
form (no diacritics, alef as ا, no alef maksura, teh marbuta folded to ه). A cue
containing ة or أ can never fire and fails silently;
`test_every_arabic_cue_is_written_in_normalised_form` fails the build instead.
