"""
Field-level accuracy of the offline extractor, reported SEPARATELY per language.

English and Arabic are never blended into one figure. They are different cue tables
of different maturity measured on fixture sets of different sizes, and a single
average would hide whichever is weaker behind whichever is larger — which is exactly
the number someone would quote.

What these numbers measure, and what they do not
------------------------------------------------
Both are **regression baselines for the deterministic offline extractor
(`HeuristicExtractor`), measured on self-authored fixtures**. Specifically:

* **Not a generalisation estimate.** The fixtures and their labels were authored
  alongside the extractor, and extractor bugs were found and fixed against them —
  each number is measured on something close to its own training set.
* **Not a measure of model quality.** No language model is involved. The default
  provider is the offline stub and CI has no sovereign endpoint. `ModelExtractor` —
  the path that calls a real sovereign model — is UNMEASURED, in both languages.
* **Not evidence extraction can be trusted unreviewed.** It cannot, which is why A2
  is PROPOSE_CONFIRM and every field goes in front of an analyst whatever its score.

The Arabic figure carries the caveat *more* heavily than the English one, not less:
it is measured over 10 fixtures written **after** the Arabic cue tables, by their
author. A perfect score there is evidence that the cues cover those ten narratives
and nothing more. Treat any Arabic number as provisional until a held-out set exists.

Still unmeasured, and not to be presented otherwise: a held-out set in either
language, labelled by someone else before the extractor sees it; and the model path.
See the fixtures README.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
]

from marsad_connector.agents.a2_extract import EXTRACTED_FIELDS, ExtractionAgent

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "narratives"
FIXTURES = sorted(FIXTURE_DIR.glob("*.json"))

#: Measured baselines for the OFFLINE HEURISTIC extractor on SELF-AUTHORED fixtures.
#: Regression floors, not generalisation estimates and not statements about any
#: model. Raise one when the extractor genuinely improves; never lower one to make a
#: change pass. Kept apart on purpose — a blended figure would hide a regression in
#: the smaller set.
#: (correct field slots, total field slots). Integers, not a rounded percentage —
#: a float baseline either rounds above the real figure and fails immediately, or
#: rounds below it and silently tolerates a lost field.
BASELINES: dict[str, tuple[int, int]] = {
    "en": (138, 140),        # 20 narratives x 7 fields
    "ar": (70, 70),          # 10 narratives x 7 fields
}


def _load(language: str) -> list[dict]:
    return [
        f for f in (json.loads(p.read_text(encoding="utf-8")) for p in FIXTURES)
        if f["language"] == language
    ]


def _normalise(name: str, value):
    """Compare meaning, not formatting. Absent and empty are the same claim."""
    if value is None or value == []:
        return None
    if name == "indicators":
        return frozenset(
            (i["type"], i["value"]) if isinstance(i, dict) else tuple(i) for i in value
        )
    if isinstance(value, list):
        return frozenset(v.lower() if isinstance(v, str) else v for v in value)
    return value


def _score(language: str) -> tuple[dict[str, list[int]], list[tuple[str, str]]]:
    agent = ExtractionAgent()
    per_field = {f: [0, 0] for f in EXTRACTED_FIELDS}
    misses: list[tuple[str, str]] = []

    for fixture in _load(language):
        draft = asyncio.run(agent.propose(fixture["narrative"]))
        for name in EXTRACTED_FIELDS:
            expected = _normalise(name, fixture["expected"][name])
            actual = _normalise(name, draft.fields[name].value)
            per_field[name][1] += 1
            if expected == actual:
                per_field[name][0] += 1
            else:
                misses.append((fixture["id"], name))
    return per_field, misses


# ---------------------------------------------------------------- the fixture set


def test_the_fixture_set_covers_both_languages_and_varied_messiness():
    """A measurement over a handful of tidy samples in one language says nothing."""
    assert len(_load("en")) == 20
    assert len(_load("ar")) == 10
    styles = {f["messiness"] for f in _load("en") + _load("ar")}
    assert len(styles) >= 15, "fixtures must vary in register, not just in content"


def test_every_fixture_declares_its_language_and_labels_every_field():
    """
    An unlabelled language would land in the wrong bucket and a partially labelled
    fixture silently inflates accuracy.
    """
    for path in FIXTURES:
        fixture = json.loads(path.read_text(encoding="utf-8"))
        assert fixture["language"] in ("en", "ar"), fixture["id"]
        assert set(fixture["expected"]) == set(EXTRACTED_FIELDS), fixture["id"]


def test_the_arabic_set_includes_code_switched_narratives():
    """
    The case this work was done for. A pure-Arabic set would not exercise the path
    that actually fails in the field: Arabic prose carrying English technical terms.
    """
    code_switched = [f for f in _load("ar") if "code-switched" in f["messiness"]]
    assert len(code_switched) >= 3


# ---------------------------------------------------------------- accuracy, per language


@pytest.mark.parametrize("language", ["en", "ar"])
def test_field_level_accuracy_holds_at_the_recorded_baseline(language, capsys):
    """
    Recorded: English 138/140 = 98.6%, Arabic 70/70 = 100.0%.

    Offline heuristic extractor, self-authored fixtures. Regression baselines only —
    not generalisation estimates, not model quality, and the Arabic figure especially
    is measured on fixtures written after the cues by the same author.

    Asserted as a ratchet per language. A change that drops one has made extraction
    worse in that language and must say so rather than quietly re-baselining.
    """
    baseline_correct, expected_slots = BASELINES[language]
    per_field, misses = _score(language)
    correct = sum(c for c, _ in per_field.values())
    total = sum(n for _, n in per_field.values())
    accuracy = correct / total

    with capsys.disabled():
        print(f"\n  {language.upper()} extraction accuracy: {correct}/{total} = {accuracy:.1%}")
        for name, (c, n) in per_field.items():
            print(f"    {name:26} {c}/{n}")
        if misses:
            print(f"    misses: {', '.join(f'{i}:{f}' for i, f in misses)}")
        print("   (offline heuristic extractor, self-authored fixtures — regression")
        print("    baseline only; not a generalisation estimate, not model quality)")

    assert total == expected_slots
    assert correct >= baseline_correct, (
        f"{language} extraction fell to {correct}/{total} ({accuracy:.1%}) from a "
        f"baseline of {baseline_correct}/{expected_slots}; misses: {misses}"
    )


@pytest.mark.parametrize("language", ["en", "ar"])
def test_no_single_field_collapses(language):
    """
    Overall accuracy can stay high while one field stops working entirely. Each field
    carries its own floor, per language, so a total failure cannot hide in an average.
    """
    per_field, _ = _score(language)
    for name, (correct, total) in per_field.items():
        assert correct / total >= 0.85, f"{language}/{name} extracted {correct}/{total}"


def test_accuracy_cannot_be_computed_without_naming_a_language():
    """
    Guards the reporting rule structurally rather than by inspecting prose. There is
    no way to ask this module for one combined figure: scoring requires a language,
    and each language carries its own baseline. Merging a strong 140-slot set with a
    weaker 70-slot one yields a number that hides the weaker of the two — and that is
    the number that ends up quoted.
    """
    import inspect

    signature = inspect.signature(_score)
    language_param = signature.parameters["language"]
    assert language_param.default is inspect.Parameter.empty, (
        "_score must require a language; a default would make a blended figure the "
        "easy thing to compute"
    )
    assert set(BASELINES) == {"en", "ar"}


# ---------------------------------------------------------------- verbatim indicators


@pytest.mark.parametrize("language", ["en", "ar"])
def test_indicators_are_extracted_verbatim_so_they_tokenise_consistently(language):
    """
    An indicator clipped or reformatted by extraction tokenises to a different value
    than the same indicator at another firm, and the correlation silently never
    fires. This is the failure the truncated-IBAN and trailing-full-stop bugs caused.
    """
    agent = ExtractionAgent()
    for fixture in _load(language):
        draft = asyncio.run(agent.propose(fixture["narrative"]))
        for indicator in draft.fields["indicators"].value or []:
            assert indicator["value"] in fixture["narrative"], (
                f"{fixture['id']}: {indicator['value']!r} is not verbatim in the narrative"
            )
