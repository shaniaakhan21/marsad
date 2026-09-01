"""
Tests for A2 — free-text incident intake.

Same discipline as the other suites: each test encodes a claim we make out loud.
A2's claims are about a component that reads the narrative in full and sits upstream
of every privacy control in the system, so they are about three things — that it
proposes rather than decides, that a human gate stands between it and A3, and that
reading the narrative did not open a second route to the core.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
    str(ROOT / "services" / "core"),
]

from marsad_connector.agents.a2_extract import (
    CONFIDENCE_THRESHOLD,
    EXTRACTED_FIELDS,
    EXTRACTION_SCHEMA,
    ExtractionAgent,
    ExtractionDraft,
    IncidentCategory,
    UnconfirmedExtractionError,
)
from marsad_connector.agents.a3_redact import RedactionAgent
from marsad_connector.agents.base import Autonomy
from marsad_connector.crypto.tokeniser import HmacTokeniser
from marsad_contracts.boundary import (
    IndicatorType,
    Sector,
    SeverityBand,
    SizeBand,
)

KEY = b"test-key-at-least-sixteen-bytes-long"

CLEAN = (
    "Finance staff received a credential-harvesting email impersonating the internal SSO "
    "portal at 2026-08-19 08:00 UTC. Two users submitted credentials at "
    "https://sso-almaha-verify.com/portal hosted on 185.220.101[.]44. The online banking "
    "service was unavailable for 40 minutes. Severity: HIGH."
)

SPARSE = "Something odd happened with our email service. Still looking into it."


def propose(text: str) -> ExtractionDraft:
    return asyncio.run(ExtractionAgent().propose(text))


# ---------------------------------------------------------------- the schema


def test_the_schema_reuses_the_contracts_vocabularies():
    """
    A parallel severity list here would drift from the contract, and a band the
    contract cannot carry is a submission that fails at the boundary — after the
    analyst has confirmed it and believes the incident is filed.
    """
    severity = EXTRACTION_SCHEMA["properties"]["severity"]["properties"]["value"]["enum"]
    assert set(severity) == {s.value for s in SeverityBand} | {None}

    indicator = (EXTRACTION_SCHEMA["properties"]["indicators"]["properties"]["value"]
                 ["items"]["properties"]["type"]["enum"])
    assert set(indicator) == {t.value for t in IndicatorType}


def test_every_field_is_nullable_so_absent_is_expressible():
    """"Not stated" and "low confidence" are different facts and must not collapse."""
    for name in EXTRACTED_FIELDS:
        value = EXTRACTION_SCHEMA["properties"][name]["properties"]["value"]
        assert None in value["enum"] if "enum" in value else "null" in value["type"]


def test_category_is_not_in_the_boundary_contract():
    """
    Category never crosses. Defining it in the contract would invite someone to
    start emitting it — everything in that file is a thing that can cross.
    """
    from marsad_contracts import boundary
    assert not hasattr(boundary, "IncidentCategory")
    assert IncidentCategory.PHISHING.value == "PHISHING"


# ---------------------------------------------------------------- clean extraction


def test_clean_narrative_extracts_every_field_with_evidence():
    """The base claim: prose in, structured incident out, each field citable."""
    draft = propose(CLEAN)

    assert draft.fields["severity"].value == "HIGH"
    assert draft.fields["category"].value == "PHISHING"
    assert draft.fields["affected_services"].value == ["online banking"]
    assert draft.fields["detected_at"].value == "2026-08-19T08:00:00+00:00"
    assert {i["type"] for i in draft.fields["indicators"].value} == {"URL", "IP"}
    assert "T1566.002" in draft.fields["techniques"].value

    for name, f in draft.fields.items():
        assert 0.0 <= f.confidence <= 1.0, name
        if f.present:
            assert f.span is not None, f"{name} must cite the text it came from"
            start, end = f.span
            assert CLEAN[start:end] == f.evidence


def test_a_cited_span_is_verbatim_narrative_text():
    """An analyst reviews a claim with its evidence attached, not a bare value."""
    draft = propose(CLEAN)
    f = draft.fields["detected_at"]
    assert CLEAN[f.span[0]:f.span[1]] == f.evidence == "2026-08-19 08:00 UTC"


# ---------------------------------------------------------------- missing information


def test_fields_the_narrative_does_not_state_are_omitted_not_guessed():
    """
    A confident-looking severity invented from nothing is worse than a blank one:
    a blank prompts a question and a guess does not.
    """
    draft = propose(SPARSE)
    assert draft.fields["severity"].value is None
    assert draft.fields["category"].value is None
    assert draft.fields["indicators"].value is None
    assert draft.fields["techniques"].value is None
    assert draft.fields["detected_at"].value is None
    assert set(draft.missing) >= {"severity", "category", "indicators", "detected_at"}


def test_an_absent_field_is_flagged_for_a_human_not_silently_dropped():
    draft = propose(SPARSE)
    assert "severity" in draft.needs_attention
    assert "Not stated" in draft.fields["severity"].reason


def test_a_relative_time_is_surfaced_rather_than_resolved():
    """
    "Earlier today" depends on a timezone and a filing date we do not have.
    Inventing a timestamp here would start every regulatory clock at the wrong hour.
    """
    draft = propose("Earlier today a phishing email reached the trading desk.")
    assert draft.fields["detected_at"].value is None
    assert draft.fields["detected_at"].evidence == "Earlier today"
    assert "detected_at" in draft.needs_attention


def test_a_negated_statement_is_not_extracted_as_the_thing_it_denies():
    """"Nothing was exfiltrated" must not be read as exfiltration."""
    draft = propose(
        "Credential stuffing against the mobile banking service on 2026-07-07 21:10 UTC. "
        "Nothing was exfiltrated. Our vendor Meridian Cloud was not compromised. Severity: HIGH."
    )
    assert draft.fields["category"].value == "CREDENTIAL_COMPROMISE"
    assert "T1041" not in (draft.fields["techniques"].value or [])


# ---------------------------------------------------------------- confidence


def test_low_confidence_fields_are_marked_for_human_attention():
    """Never silently accepted — the threshold is the whole point of the review step."""
    draft = propose(CLEAN)
    for f in draft.fields.values():
        if f.present and f.confidence < CONFIDENCE_THRESHOLD:
            assert f.needs_attention
            assert str(CONFIDENCE_THRESHOLD) in f.reason or "below" in f.reason


def test_severity_and_detected_at_are_always_reviewed_however_confident():
    """
    These two drive every regulatory deadline and the correlation's coarse band.
    A high-confidence wrong answer on either is exactly the expensive kind.
    """
    draft = propose(CLEAN)
    assert draft.fields["severity"].confidence >= CONFIDENCE_THRESHOLD
    assert "severity" in draft.needs_attention
    assert "detected_at" in draft.needs_attention


def test_evidence_that_is_not_in_the_narrative_is_treated_as_unsupported():
    """A model citing text the analyst never wrote has fabricated its evidence."""
    from marsad_connector.agents.a2_extract import _field
    f = _field("severity", "CRITICAL", 0.99, "a short narrative", "text that is not there")
    assert f.span is None
    assert f.needs_attention
    assert "does not appear" in f.reason


# ---------------------------------------------------------------- the confirmation gate


def test_a2_is_propose_confirm_never_automatic():
    """The autonomy level is the claim, and it is declared on the agent itself."""
    assert ExtractionAgent.autonomy is Autonomy.PROPOSE_CONFIRM
    assert ExtractionAgent.may_cross_boundary is False


def test_extraction_output_cannot_reach_a3_without_confirmation():
    """
    The sharpest test here. A draft is a proposal, and A3 must not be able to read
    an incident out of one. The gate is the shape of the object, not a flag a caller
    can forget to check.
    """
    draft = propose(CLEAN)
    agent = RedactionAgent(HmacTokeniser(KEY))

    with pytest.raises(UnconfirmedExtractionError, match="PROPOSE_CONFIRM"):
        agent.build_submission(
            draft, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
        )

    for attribute in ("indicators", "severity", "techniques", "detected_at"):
        with pytest.raises(UnconfirmedExtractionError):
            getattr(draft, attribute)


def test_a_confirmed_incident_builds_a_submission_normally():
    """The gate must not be a wall: once a human signs off, the pipeline runs."""
    confirmed = propose(CLEAN).confirm(analyst="a.karim")
    sub = RedactionAgent(HmacTokeniser(KEY)).build_submission(
        confirmed, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
    )
    assert sub.coarse.severity_band == "HIGH"
    assert len(sub.tokens) == 2
    assert "T1566.002" in sub.technique_set


def test_confirmation_requires_a_named_analyst():
    """A confirmation with nobody's name on it is not a confirmation."""
    with pytest.raises(ValueError, match="identity"):
        propose(CLEAN).confirm(analyst="   ")


def test_the_analyst_can_edit_any_field_and_the_edit_is_recorded():
    """Correcting the model is the normal case, not the exception."""
    confirmed = propose(CLEAN).confirm(
        analyst="a.karim",
        edits={"severity": "CRITICAL", "techniques": ["T1566.002", "T1078"]},
    )
    assert confirmed.severity == "CRITICAL"
    assert confirmed.techniques == ["T1566.002", "T1078"]
    assert confirmed.edited_fields == ("severity", "techniques")


def test_confirmation_refuses_a_severity_the_contract_cannot_carry():
    with pytest.raises(ValueError, match="boundary contract"):
        propose(CLEAN).confirm(analyst="a.karim", edits={"severity": "APOCALYPTIC"})


def test_confirmation_refuses_an_unknown_field():
    """A typo in an edit must not silently do nothing."""
    with pytest.raises(ValueError, match="unknown field"):
        propose(CLEAN).confirm(analyst="a.karim", edits={"severty": "HIGH"})


def test_an_incident_with_no_severity_cannot_be_confirmed_into_existence():
    """
    Extraction found none and the analyst supplied none. Every regulatory clock
    hangs off this field, so the system refuses rather than choosing one.
    """
    with pytest.raises(ValueError, match="will not choose it"):
        propose(SPARSE).confirm(analyst="a.karim")


# ---------------------------------------------------------------- no second path out


def test_extraction_provenance_never_reaches_the_payload():
    """
    A2 reads the narrative and produces spans that are verbatim slices of it, plus
    service and vendor names that are explicitly on the never-cross list. A3 builds
    from an allow-list, so none of it is read — and the leak guard proves it.
    """
    confirmed = propose(CLEAN).confirm(analyst="a.karim")
    assert confirmed.affected_services == ("online banking",)

    sub = RedactionAgent(HmacTokeniser(KEY)).build_submission(
        confirmed, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
    )
    blob = sub.model_dump_json().lower()

    for leaked in ("online banking", "credential-harvesting", "sso", "a.karim",
                   "sso-almaha-verify.com", "185.220.101", "phishing"):
        assert leaked not in blob


def test_the_leak_guard_still_sees_the_narrative_it_needs():
    """
    ConfirmedIncident keeps the narrative precisely so `_assert_no_leakage` can check
    the payload against it. Dropping it here would quietly disarm the guard.
    """
    confirmed = propose(CLEAN).confirm(analyst="a.karim")
    assert confirmed.narrative == CLEAN
    assert set(EXTRACTED_FIELDS) - {"severity", "indicators", "techniques", "detected_at"}


def test_confirmed_incident_carries_who_signed_it_off():
    """Provenance stays local, but it must exist — someone stood behind these values."""
    before = datetime.now(timezone.utc)
    confirmed = propose(CLEAN).confirm(analyst="a.karim")
    assert confirmed.confirmed_by == "a.karim"
    assert confirmed.confirmed_at >= before


def test_empty_narrative_is_refused_rather_than_extracted_from():
    with pytest.raises(ValueError, match="empty"):
        propose("   ")


def test_the_timestamp_exemption_did_not_disarm_the_leak_guard():
    """
    Free-text intake made analysts write the detection time in the prose, which
    collided with the hour bucket the contract deliberately carries. The guard now
    exempts exactly that text — so this proves it still fires on everything else,
    including a date-shaped word that is NOT the timestamp we emitted.
    """
    from marsad_connector.agents.a3_redact import RedactionError

    confirmed = propose(CLEAN).confirm(analyst="a.karim")

    class Sabotaged(RedactionAgent):
        def build_submission(self, incident, **kw):
            sub = super().build_submission(incident, **kw)
            object.__setattr__(sub, "institution_ref", "credential-harvesting")
            self._assert_no_leakage(sub, incident)
            return sub

    with pytest.raises(RedactionError, match="LEAK GUARD"):
        Sabotaged(HmacTokeniser(KEY)).build_submission(
            confirmed, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
        )

    # A different date, one the payload does not carry, is still treated as narrative.
    other = propose(
        "Phishing detected at 2026-08-19 08:00 UTC. Severity: HIGH. Earlier report 1999-01-02 "
        "covered https://x-evil-domain.com/a and 10.9.8.7."
    ).confirm(analyst="a.karim")

    class LeaksAnotherDate(RedactionAgent):
        def build_submission(self, incident, **kw):
            sub = super().build_submission(incident, **kw)
            object.__setattr__(sub, "institution_ref", "1999-01-02")
            self._assert_no_leakage(sub, incident)
            return sub

    with pytest.raises(RedactionError, match="LEAK GUARD"):
        LeaksAnotherDate(HmacTokeniser(KEY)).build_submission(
            other, institution_ref="psd_a0001", sector=Sector.BANK, size_band=SizeBand.LARGE
        )


# ---------------------------------------------------------------- controls the live run justified


def test_a_fabricated_indicator_cannot_reach_a3_however_confident():
    """
    THE control the first live model run justified.

    Locatability is advisory for every other field and a HARD GATE here. A fabricated
    severity is wrong inside one institution and a human looks at it anyway. A
    fabricated indicator becomes a TOKEN — a value in a matching space every other
    institution is compared against, which nobody downstream can review because they
    see only the hash. It either matches nothing or manufactures a campaign.

    Confidence is irrelevant to this gate. The model reported 1.0 on values it
    invented, so trusting confidence here would trust exactly the wrong number.
    """
    from marsad_connector.agents.a2_extract import _field

    narrative = "Phishing reported at 2026-08-19 08:00 UTC from real-domain.com. Severity: HIGH."
    field = _field(
        "indicators",
        [
            {"type": "DOMAIN", "value": "real-domain.com"},        # present
            {"type": "IP", "value": "203.0.113.99"},               # invented
            {"type": "URL", "value": "https://not-in-the-text.example"},  # invented
        ],
        1.0,                                                        # maximum confidence
        narrative,
        None,
    )

    assert field.value == [{"type": "DOMAIN", "value": "real-domain.com"}]
    assert len(field.rejected) == 2
    assert field.needs_attention
    assert "not present in the narrative" in field.reason

    for indicator in field.value:
        assert indicator["value"] in narrative


def test_the_untrusted_fence_marker_is_rejected_as_an_indicator():
    """
    Fixture 07, exactly as it failed live.

    On `07_webshell_exploit` the model returned our own `UNTRUSTED_INCIDENT_TEXT`
    fence — the delimiter the provider wraps hostile text in — as an indicator of type
    URL. Under the previous code that would have been canonicalised, tokenised and
    submitted: the connector would have published a token derived from its own prompt
    scaffolding into a shared matching space.
    """
    import json

    from marsad_connector.agents.a2_extract import _field
    from marsad_connector.llm.provider import UNTRUSTED_CLOSE, UNTRUSTED_OPEN

    fixture = json.loads(
        (ROOT / "tests" / "fixtures" / "narratives" / "07_webshell_exploit.json")
        .read_text(encoding="utf-8")
    )
    narrative = fixture["narrative"]
    assert UNTRUSTED_OPEN not in narrative, "the fence is scaffolding, never the analyst's text"

    field = _field(
        "indicators",
        [
            {"type": "URL", "value": UNTRUSTED_OPEN},
            {"type": "URL", "value": f"{UNTRUSTED_OPEN}\n{narrative}\n{UNTRUSTED_CLOSE}"},
            {"type": "FILE_HASH", "value": fixture["expected"]["indicators"][0][1]},
        ],
        1.0, narrative, None,
    )

    kept = {i["value"] for i in field.value or []}
    assert UNTRUSTED_OPEN not in kept
    assert not any(UNTRUSTED_OPEN in value for value in kept)
    assert fixture["expected"]["indicators"][0][1] in kept


def test_model_proposed_indicators_need_explicit_confirmation(monkeypatch):
    """
    The second half of the gate. Locatable is not the same as correct — the model also
    mistyped a wallet as a URL and a domain as an IP, and both of those ARE in the
    narrative. So a human signs off the indicator list before it can be tokenised.

    An empty list is a valid answer. Silence is not.
    """
    from marsad_connector.agents.a2_extract import ExtractionAgent, ModelExtractor

    narrative = ("Phishing at 2026-08-19 08:00 UTC from evil-model.com. Severity: HIGH.")

    class FakeProvider:
        name = "fake"

        async def extract(self, text, schema):
            return {
                "severity": {"value": "HIGH", "confidence": 0.9, "evidence": "Severity: HIGH"},
                "category": {"value": "PHISHING", "confidence": 0.9, "evidence": "Phishing"},
                "affected_services": {"value": None, "confidence": 0.0, "evidence": None},
                "third_party_dependencies": {"value": None, "confidence": 0.0, "evidence": None},
                "indicators": {"value": [{"type": "DOMAIN", "value": "evil-model.com"}],
                               "confidence": 1.0, "evidence": "evil-model.com"},
                "techniques": {"value": None, "confidence": 0.0, "evidence": None},
                "detected_at": {"value": "2026-08-19T08:00:00+00:00", "confidence": 0.9,
                                "evidence": "2026-08-19 08:00 UTC"},
            }

    agent = ExtractionAgent()
    agent._extractor = ModelExtractor(FakeProvider())
    agent._is_model = True

    draft = asyncio.run(agent.propose(narrative))
    assert draft.model_proposed
    assert draft.requires_indicator_confirmation

    with pytest.raises(ValueError, match="explicit confirmation"):
        draft.confirm(analyst="a.karim")

    accepted = draft.confirm(
        analyst="a.karim", edits={"indicators": [{"type": "DOMAIN", "value": "evil-model.com"}]}
    )
    assert accepted.indicators == [{"type": "DOMAIN", "value": "evil-model.com"}]

    declined = draft.confirm(analyst="a.karim", edits={"indicators": []})
    assert declined.indicators == []


def test_the_heuristic_path_needs_no_indicator_confirmation():
    """
    The gate is friction aimed at model output, not at the analyst. The deterministic
    extractor cuts indicators verbatim out of the narrative with a regex, so they are
    locatable by construction and there is nothing to confirm the text does not say.
    """
    draft = propose(CLEAN)
    assert not draft.model_proposed
    assert not draft.requires_indicator_confirmation
    confirmed = draft.confirm(analyst="a.karim")
    assert len(confirmed.indicators) == 2


def test_array_bounds_are_read_from_the_contract_not_repeated():
    """
    A denial-of-service control, not tidying: `17_many_indicators` generated for 900
    seconds under constrained decoding because the array had nowhere to stop.

    The bound is read off the contract rather than written twice, so the schema cannot
    permit more than the payload can carry.
    """
    import annotated_types
    from marsad_connector.agents.a2_extract import (
        MAX_INDICATORS,
        MAX_LOCAL_LIST_ITEMS,
        MAX_TECHNIQUES,
    )
    from marsad_contracts.boundary import IncidentSubmission

    def contract_cap(field_name: str) -> int:
        field = IncidentSubmission.model_fields[field_name]
        return next(m.max_length for m in field.metadata
                    if isinstance(m, annotated_types.MaxLen))

    assert MAX_INDICATORS == contract_cap("tokens")
    assert MAX_TECHNIQUES == contract_cap("technique_set")

    properties = EXTRACTION_SCHEMA["properties"]
    assert properties["indicators"]["properties"]["value"]["maxItems"] == contract_cap("tokens")
    assert properties["techniques"]["properties"]["value"]["maxItems"] == contract_cap("technique_set")
    for local in ("affected_services", "third_party_dependencies"):
        assert properties[local]["properties"]["value"]["maxItems"] == MAX_LOCAL_LIST_ITEMS

    for name, spec in properties.items():
        value = spec["properties"]["value"]
        if "array" in str(value.get("type")):
            assert value.get("maxItems"), f"{name} is unbounded — that is a hang, not untidiness"


def test_an_out_of_range_confidence_is_malformed_not_low():
    """
    `strict: true` declares `minimum: 0, maximum: 1` and does not enforce it: 95 of 203
    values in the first live run fell outside the range, the largest being 100.0.

    Such a value is refused, not clamped. Clamping 100.0 to 1.0 would turn a broken
    response into a maximally trusted one.
    """
    from marsad_connector.agents.a2_extract import CONFIDENCE_RANGE, _field

    for bad in (100.0, 1.5, -0.5, 42):
        field = _field("severity", "HIGH", bad, "Severity: HIGH", "Severity: HIGH")
        assert field.confidence == 0.0, f"{bad} was not refused"
        assert field.needs_attention
        assert "malformed" in field.reason

    good = _field("severity", "HIGH", 0.9, "Severity: HIGH", "Severity: HIGH")
    assert good.confidence == 0.9
    assert CONFIDENCE_RANGE == (0.0, 1.0)
