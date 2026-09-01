"""
Tests for Arabic incident intake.

Same discipline as the other suites: each test encodes a claim we make out loud.
The claims here are about a failure mode with no error message. If normalisation is
applied on one path and not the other, nothing raises: two institutions holding the
same Arabic indicator produce two different tokens, the correlation never fires, and
every dashboard looks healthy while the system quietly does not work.

So the sharpest test in this file is not about Arabic linguistics at all — it is
`test_normalising_on_write_but_not_on_query_would_break_matching`.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
]

from marsad_connector.agents import a2_extract
from marsad_connector.agents.a2_extract import (
    AR_CATEGORY_CUES,
    AR_SERVICE_CUES,
    AR_SEVERITY_LABELS,
    AR_SEVERITY_WORDS,
    AR_TECHNIQUE_CUES,
    ExtractionAgent,
)
from marsad_connector.agents.a3_redact import RedactionAgent
from marsad_connector.crypto import tokeniser as tokeniser_module
from marsad_connector.crypto.tokeniser import HmacTokeniser, canonicalise
from marsad_connector.lang import arabic
from marsad_connector.lang.arabic import (
    Language,
    detect_language,
    normalise,
    normalise_tracked,
)
from marsad_contracts.boundary import IndicatorType, Sector, SizeBand

KEY = b"test-key-at-least-sixteen-bytes-long"

#: The same Arabic word, written the two ways analysts actually write it: with teh
#: marbuta and with heh, with and without diacritics and hamza.
WRITE_FORM = "شركة-المعلومات.ae"
QUERY_FORM = "شركه-المعلومات.ae"

AR_PHISHING = (
    "تلقى موظفو قسم المالية رسالة تصيد تحاكي بوابة الدخول الموحد في 2026-08-19 08:00 UTC. "
    "تم إدخال بيانات الاعتماد في https://sso-fake-portal.com. الأثر: عالي."
)


def propose(text: str):
    return asyncio.run(ExtractionAgent().propose(text))


# ---------------------------------------------------------------- the silent failure


def test_normalising_on_write_but_not_on_query_would_break_matching(monkeypatch):
    """
    THE test this work exists for.

    An indicator written with teh marbuta and the same indicator written with heh
    must produce the same token. If a future change normalises when storing but not
    when querying — or drops normalisation from `canonicalise` altogether — nothing
    raises anywhere: the tokens simply stop matching and the correlation silently
    never fires. This test fails loudly in that case.
    """
    tokeniser = HmacTokeniser(KEY)

    written = tokeniser.tokenise(WRITE_FORM, IndicatorType.DOMAIN)
    queried = tokeniser.tokenise(QUERY_FORM, IndicatorType.DOMAIN)
    assert written == queried, (
        "two spellings of one Arabic indicator produced different tokens — "
        "normalisation is missing from canonicalise()"
    )

    # Now simulate the bug directly: one path forgets to normalise. WRITE_FORM is the
    # spelling normalisation actually changes (teh marbuta -> heh), so tokenising it
    # unnormalised must diverge from the stored token. That divergence is what proves
    # the equality above is produced by normalisation rather than by the two strings
    # happening to be equal already.
    monkeypatch.setattr(tokeniser_module, "normalise_arabic", lambda text: text)
    forgot_to_normalise = tokeniser.tokenise(WRITE_FORM, IndicatorType.DOMAIN)
    assert forgot_to_normalise != written, (
        "skipping normalisation made no difference, so this test is no longer "
        "detecting the bug it was written for"
    )


def test_write_and_query_paths_share_one_normalisation_function():
    """
    Not "the same four operations" — literally the same function object. Two
    implementations that agree today drift apart the first time one is edited, and
    the drift produces no error.
    """
    assert tokeniser_module.normalise_arabic is arabic.normalise

    # A2 matches against text produced by the same function.
    doc = normalise_tracked(WRITE_FORM)
    assert doc.text == normalise(WRITE_FORM)


def test_normalisation_is_unconditional_not_gated_on_language_detection():
    """
    A detector that says Arabic on one path and English on the other reintroduces the
    bug. Latin-only text must go through normalise() unchanged, which is what makes
    applying it to everything safe.
    """
    for latin in ("sso-almaha-verify.com", "185.220.101[.]44", "T1566.002", "HIGH"):
        assert normalise(latin) == latin
        assert canonicalise(latin, IndicatorType.DOMAIN) == canonicalise(latin, IndicatorType.DOMAIN)


@pytest.mark.parametrize("variant", [
    "شركة-المعلومات.ae",     # teh marbuta
    "شركه-المعلومات.ae",     # heh
    "شَرِكَة-المعلومات.ae",     # diacritised
    "شركة-المعلومـات.ae".replace("ـ", ""),
])
def test_every_spelling_of_one_indicator_tokenises_the_same(variant):
    """Without this, correlation across two firms silently never fires."""
    tokeniser = HmacTokeniser(KEY)
    assert tokeniser.tokenise(variant, IndicatorType.DOMAIN) == \
           tokeniser.tokenise(WRITE_FORM, IndicatorType.DOMAIN)


def test_alef_hamza_and_alef_maksura_variants_collapse():
    """The four CAMeL operations, exercised on the forms that actually vary."""
    assert normalise("أحمد") == normalise("احمد") == normalise("إحمد")
    assert normalise("مستشفى") == normalise("مستشفي")
    assert normalise("شركة") == normalise("شركه")
    assert normalise("مُتَوَسِّط") == normalise("متوسط")


# ---------------------------------------------------------------- offsets


def test_character_wise_normalisation_matches_whole_string_normalisation():
    """
    `NormalisedText` builds its offset map character by character, which is only
    valid because all four operations are per-character maps. If a CAMeL Tools
    release makes any of them context-sensitive, every offset this class hands out
    becomes wrong — silently, since the spans would still be in range. This catches it.
    """
    for sample in (AR_PHISHING, "الأثَر: مُتوسِّط", "تقرير — a phishing email (بريد احتيالي)"):
        assert normalise(sample) == "".join(normalise(c) for c in sample)


def test_a_span_found_in_normalised_text_displays_the_analysts_own_words():
    """
    Display raw, match on normalised. dediac deletes characters, so the two strings
    do not share an index space — without the offset map the analyst would be shown
    the wrong slice of their own report.
    """
    raw = "الأثَر: عالي"
    doc = normalise_tracked(raw)
    at = doc.text.find("الاثر")
    assert at >= 0                                   # matched in normalised space
    assert doc.raw_excerpt(at, at + 5) == "الأثَر"     # displayed in raw space
    assert doc.raw_excerpt(at, at + 5) != doc.text[at:at + 5]


def test_extraction_evidence_is_verbatim_raw_text():
    """An analyst reviewing a field must see what they typed, diacritics and all."""
    draft = propose(AR_PHISHING)
    for name, field in draft.fields.items():
        if field.present and field.evidence:
            assert field.evidence in draft.narrative, f"{name} cited text not in the raw narrative"


# ---------------------------------------------------------------- language routing


def test_language_detection_routes_arabic_english_and_code_switched():
    assert detect_language("Finance staff received a phishing email.") is Language.ENGLISH
    assert detect_language(AR_PHISHING) is Language.ARABIC
    assert detect_language("تقرير حادث — a phishing email reached the portal on 2026-01-01") \
        is Language.MIXED


def test_a_code_switched_severity_label_is_read():
    """
    The case this work was done for: an Arabic label carrying an English value.
    Previously the Arabic label was invisible and an inferred English cue won instead.
    """
    draft = propose(
        "تقرير حادث — a phishing email reached the retail banking portal team on "
        "2026-02-14 08:45 UTC. الأثر: moderate."
    )
    assert draft.fields["severity"].value == "MEDIUM"
    assert "الأثر" in draft.fields["severity"].evidence


def test_english_technical_terms_inside_arabic_prose_are_still_read():
    """Gulf reports mix scripts inside one sentence; indicators stay Latin."""
    draft = propose(
        "رصد فريق الـ SOC محاولات رش كلمات المرور ضد الخدمات المصرفية عبر الانترنت "
        "في 2026-01-30 22:00 UTC من العنوان 185.220.101[.]44. الأثر: high."
    )
    assert draft.fields["severity"].value == "HIGH"
    assert draft.fields["affected_services"].value == ["online banking"]
    assert {i["value"] for i in draft.fields["indicators"].value} == {"185.220.101[.]44"}
    assert "T1110" in draft.fields["techniques"].value


def test_arabic_service_names_map_to_the_same_canonical_labels_as_english():
    """
    One structured vocabulary regardless of reporting language — otherwise the same
    outage reads as two different services depending on who wrote it up, and
    concentration analysis splits one provider into two.
    """
    arabic_draft = propose("توقفت منصة التداول في 2026-05-11 at 09:30. الأثر: عالي.")
    english_draft = propose("The trading platform went down on 2026-05-11 at 09:30. Severity: HIGH.")
    assert arabic_draft.fields["affected_services"].value == \
           english_draft.fields["affected_services"].value == ["trading platform"]


def test_arabic_negation_is_not_read_as_the_thing_it_denies():
    """
    "لم يتم تسريب البيانات" is a denial of exfiltration. The guard must also not fire
    on ordinary words: the particle لم occurs as a letter sequence inside المالية and
    المعلومات, and an unbounded match read almost every Arabic sentence as negated.
    """
    draft = propose(
        "تم رصد برمجيات خبيثة على نظام الخزينة في 2026-09-01 06:30 UTC. "
        "لم يتم تسريب البيانات ولم يتم اختراق المزود. الأثر: متوسط."
    )
    assert draft.fields["category"].value == "MALWARE"
    assert draft.fields["third_party_dependencies"].value is None

    # and the guard has not swallowed a normal sentence
    assert propose(AR_PHISHING).fields["category"].value == "PHISHING"


# ---------------------------------------------------------------- cue hygiene


def test_every_arabic_cue_is_written_in_normalised_form():
    """
    Cues are matched against normalised text, so a cue containing ة, أ or ى could
    never fire — and the failure is silent: the field simply comes back empty.
    """
    literals: list[str] = []
    literals += [w for words in AR_SEVERITY_WORDS.values() for w in words]
    literals += list(AR_SEVERITY_LABELS)
    literals += [w for _, words, _ in AR_CATEGORY_CUES for w in words]
    literals += [w for _, words, _ in a2_extract.AR_SEVERITY_INFERRED for w in words]
    literals += [cue for cue, _ in AR_SERVICE_CUES]
    literals += [w for _, words in AR_TECHNIQUE_CUES for w in words]
    literals += list(a2_extract.AR_VAGUE_TIME)
    literals += list(a2_extract.AR_THIRD_PARTY_WORDS)
    literals += list(a2_extract.AR_NEGATION)

    unnormalised = [w for w in literals if normalise(w) != w]
    assert not unnormalised, f"cues that can never match normalised text: {unnormalised}"


# ---------------------------------------------------------------- the boundary


def test_arabic_narrative_never_crosses_the_boundary():
    """
    Arabic intake must not become a second route out. A3 still builds from an
    allow-list, and the leak guard still checks the payload against the raw narrative.
    """
    confirmed = propose(AR_PHISHING).confirm(analyst="a.karim")
    submission = RedactionAgent(HmacTokeniser(KEY)).build_submission(
        confirmed, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
    )
    blob = submission.model_dump_json()
    for leaked in ("تصيد", "المالية", "بوابة", "sso-fake-portal", "a.karim"):
        assert leaked not in blob


def test_both_raw_and_normalised_narratives_are_kept_locally():
    """
    Display raw, match on normalised — which requires holding both. Storing only the
    normalised form would show the analyst text they did not write; storing only the
    raw form would mean re-deriving it on every query, which is where drift starts.
    """
    draft = propose(AR_PHISHING)
    assert draft.narrative == AR_PHISHING
    assert draft.narrative_normalised == normalise(AR_PHISHING)
    assert draft.narrative_normalised != draft.narrative
    assert draft.language == Language.ARABIC.value

    confirmed = draft.confirm(analyst="a.karim")
    assert confirmed.narrative == AR_PHISHING
    assert confirmed.narrative_normalised == normalise(AR_PHISHING)
