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
