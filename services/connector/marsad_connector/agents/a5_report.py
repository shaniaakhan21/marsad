"""
A5 — the standard incident report: one record, one format, with impact.

Assembled by fixed rules from what the analyst confirmed and what A4 computed. No model
is involved. A field nobody supplied is listed as missing and left blank, because a
regulator's report with a plausible invented figure is worse than one with a gap.

This never leaves the firm through MARSAD. It has no route to the core, and the impact
fields are not on the boundary contract: A3 builds from an allow-list that does not name
them. The firm reviews the report and files it itself.

Losses, customers and downtime are bands from closed vocabularies. An exact loss figure
has nowhere to go, here or anywhere downstream.

The layout is provisional. CMA's reporting template has been requested but not received,
so `template.status` says PROVISIONAL and the report must not be presented as CMA's form.
"""

from __future__ import annotations

from collections import Counter
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

TEMPLATE_VERSION = "marsad-provisional-1"


class LossBand(str, Enum):
    NONE = "NONE"
    UNDER_AED_100K = "UNDER_AED_100K"
    AED_100K_TO_1M = "AED_100K_TO_1M"
    AED_1M_TO_10M = "AED_1M_TO_10M"
    OVER_AED_10M = "OVER_AED_10M"
    UNKNOWN = "UNKNOWN"


class CustomersBand(str, Enum):
    NONE = "NONE"
    UNDER_100 = "UNDER_100"
    FROM_100_TO_1K = "FROM_100_TO_1K"
    FROM_1K_TO_10K = "FROM_1K_TO_10K"
    OVER_10K = "OVER_10K"
    UNKNOWN = "UNKNOWN"


class DowntimeBand(str, Enum):
    NONE = "NONE"
    UNDER_1H = "UNDER_1H"
    FROM_1H_TO_4H = "FROM_1H_TO_4H"
    FROM_4H_TO_24H = "FROM_4H_TO_24H"
    OVER_24H = "OVER_24H"
    UNKNOWN = "UNKNOWN"


class ImpactAssessment(BaseModel):
    """An analyst's assessment. Named, banded, and closed to anything else."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    financial_loss: LossBand
    customers_affected: CustomersBand
    service_downtime: DowntimeBand
    #: Local only. Affected system names are on the never-cross list, and they expire.
    systems_affected: list[str] = Field(default_factory=list, max_length=200)
    assessed_by: str = Field(min_length=1, max_length=128)


#: Impact fields a complete report needs. UNKNOWN counts as answered: a person looked and
#: said so, which is different from nobody having looked.
REQUIRED_IMPACT = ("financial_loss", "customers_affected", "service_downtime")


def build_report(incident_id: str, incident: Any, obligations: dict[str, Any]) -> dict[str, Any]:
    """The report for one incident. Reads only the incident this connector holds."""
    impact = incident.impact or {}
    systems = incident.systems_affected

    missing = [f"impact.{name}" for name in REQUIRED_IMPACT if not impact.get(name)]
    if not incident.narrative:
        missing.append("description")

    return {
        "template": {
            "version": TEMPLATE_VERSION,
            "status": "PROVISIONAL",
            "note": "Common format proposed by MARSAD, pending CMA's reporting template.",
        },
        "incident_ref": incident_id[:8].upper(),
        "detected_at": incident.detected_at.isoformat() if incident.detected_at else None,
        "severity": incident.severity,
        "source": incident.source,
        "confirmed_by": incident.confirmed_by,
        "description": incident.narrative,
        "taxonomy": {
            "attack_techniques": sorted(set(incident.techniques or [])),
            "indicator_counts": dict(Counter(str(i.get("type")) for i in incident.indicators or [])),
        },
        "impact": {
            "financial_loss": impact.get("financial_loss"),
            "customers_affected": impact.get("customers_affected"),
            "service_downtime": impact.get("service_downtime"),
            "systems_affected": list(systems or []),
            "assessed_by": impact.get("assessed_by"),
        },
        "notifications": [
            {key: item.get(key) for key in ("authority", "applicability", "deadline")}
            for item in obligations.get("obligations", [])
        ],
        "completeness": {"complete": not missing, "missing": missing},
        "filing": {"filed_by_marsad": False, "note": "The firm reviews and files this itself."},
    }


__all__ = ["CustomersBand", "DowntimeBand", "ImpactAssessment", "LossBand", "build_report"]
