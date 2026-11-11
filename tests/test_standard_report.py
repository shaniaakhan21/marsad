"""
The standard incident report with impact.

The claims: impact reaches the firm's own report and nowhere else; figures are banded;
a missing field is shown as missing rather than filled in; and the layout does not pose
as a CMA form that CMA has not yet given us.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "packages" / "contracts"),
    str(ROOT / "services" / "connector"),
]

SYSTEM_NAME = "CanarySystemSettlementGateway7f3a"

INCIDENT = {
    "narrative": "Credential phishing against the operations team, contained by noon.",
    "indicators": [{"type": "IP", "value": "203.0.113.5"}],
    "techniques": ["T1566"],
    "severity": "HIGH",
    "jurisdictions": ["CMA"],
    "detected_at": "2026-08-19T08:30:00+00:00",
}
IMPACT = {
    "financial_loss": "AED_100K_TO_1M",
    "customers_affected": "FROM_100_TO_1K",
    "service_downtime": "FROM_1H_TO_4H",
    "systems_affected": [SYSTEM_NAME],
    "assessed_by": "a.analyst",
}


@pytest.fixture
def connector(monkeypatch):
    from marsad_connector import main as connector_main
    from marsad_connector.config import settings
    from marsad_connector.store import InMemoryStore

    monkeypatch.setenv("MARSAD_TOKEN_KEY", "standard-report-key-16+")
    settings.cache_clear()
    monkeypatch.setattr(connector_main, "LOCAL", InMemoryStore())
    yield TestClient(connector_main.app)
    settings.cache_clear()


def _incident(client) -> str:
    return client.post("/v1/incidents", json=INCIDENT).json()["incident_id"]


def test_the_report_carries_the_impact_a_named_analyst_assessed(connector):
    iid = _incident(connector)
    assert connector.post(f"/v1/incidents/{iid}/impact", json=IMPACT).status_code == 200
    report = connector.get(f"/v1/incidents/{iid}/standard-report").json()

    assert report["impact"]["financial_loss"] == "AED_100K_TO_1M"
    assert report["impact"]["assessed_by"] == "a.analyst"
    assert report["completeness"] == {"complete": True, "missing": []}
    assert report["taxonomy"]["attack_techniques"] == ["T1566"]


def test_impact_never_appears_in_what_crosses_the_boundary(connector):
    """Losses and system names stay in the firm. The preview is exactly what would leave."""
    iid = _incident(connector)
    connector.post(f"/v1/incidents/{iid}/impact", json=IMPACT)
    payload = connector.post(f"/v1/incidents/{iid}/preview").text
    for private in (SYSTEM_NAME, "AED_100K", "FROM_100_TO_1K", "FROM_1H_TO_4H", "a.analyst"):
        assert private not in payload


def test_the_redaction_agent_does_not_read_impact():
    """The guarantee is an allow-list. Grep the builder for these and find nothing."""
    source = (ROOT / "services/connector/marsad_connector/agents/a3_redact.py").read_text()
    assert "impact" not in source and "systems_affected" not in source


@pytest.mark.parametrize("field,value", [
    ("financial_loss", "AED 742,118.50"),
    ("customers_affected", 412),
    ("service_downtime", "37 minutes"),
])
def test_an_exact_figure_is_refused_only_bands_are_accepted(connector, field, value):
    """Reported in bands, never exact figures: the type has nowhere to put one."""
    iid = _incident(connector)
    response = connector.post(f"/v1/incidents/{iid}/impact", json={**IMPACT, field: value})
    assert response.status_code == 422


def test_an_assessment_needs_a_named_person(connector):
    iid = _incident(connector)
    body = {k: v for k, v in IMPACT.items() if k != "assessed_by"}
    assert connector.post(f"/v1/incidents/{iid}/impact", json=body).status_code == 422


def test_missing_impact_is_listed_as_missing_and_never_guessed(connector):
    """A blank prompts a question; an invented loss figure goes to a regulator."""
    report = connector.get(f"/v1/incidents/{_incident(connector)}/standard-report").json()
    assert report["impact"]["financial_loss"] is None
    assert report["completeness"]["complete"] is False
    assert "impact.financial_loss" in report["completeness"]["missing"]


def test_unknown_is_an_answer_and_counts_as_complete(connector):
    """Someone looked and could not say. That differs from nobody having looked."""
    iid = _incident(connector)
    connector.post(f"/v1/incidents/{iid}/impact", json={**IMPACT, "financial_loss": "UNKNOWN"})
    assert connector.get(f"/v1/incidents/{iid}/standard-report").json()["completeness"]["complete"]


def test_the_layout_says_it_is_provisional_until_cma_supplies_its_template(connector):
    """It must not be mistaken for the regulator's own form."""
    report = connector.get(f"/v1/incidents/{_incident(connector)}/standard-report").json()
    assert report["template"]["status"] == "PROVISIONAL"
    assert "CMA" in report["template"]["note"]


def test_marsad_does_not_file_the_report(connector):
    report = connector.get(f"/v1/incidents/{_incident(connector)}/standard-report").json()
    assert report["filing"]["filed_by_marsad"] is False


def test_the_report_and_the_obligations_endpoint_agree_on_every_deadline(connector):
    """A report showing a different deadline from the deadline tool would mislead a firm."""
    iid = _incident(connector)
    duties = connector.get(f"/v1/incidents/{iid}/obligations").json()["obligations"]
    report = connector.get(f"/v1/incidents/{iid}/standard-report").json()["notifications"]
    assert [(d["authority"], d["deadline"]) for d in duties] == \
           [(r["authority"], r["deadline"]) for r in report]


def test_system_names_expire_with_the_narrative_and_bands_are_kept(tmp_path):
    """Names are free text; bands are what a firm needs to answer a regulator later."""
    from marsad_connector.db.session import build_engine, build_sessionmaker, create_all
    from marsad_connector.main import IncidentIn
    from marsad_connector.store import SqlStore

    engine = build_engine(f"sqlite:///{tmp_path / 'edge.db'}")
    create_all(engine)
    store = SqlStore(build_sessionmaker(engine), retention_days=1,
                     model=lambda **kw: IncidentIn(**kw))
    store.save("inc-1", IncidentIn(**INCIDENT))
    store.set_impact("inc-1", {k: v for k, v in IMPACT.items() if k != "systems_affected"},
                     [SYSTEM_NAME])
    assert store.get("inc-1").systems_affected == [SYSTEM_NAME]

    store.purge_expired(now=datetime.now(timezone.utc) + timedelta(days=2))
    after = store.get("inc-1")
    assert not after.systems_affected
    assert after.impact["financial_loss"] == "AED_100K_TO_1M"
