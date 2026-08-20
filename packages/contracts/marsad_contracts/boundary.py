"""
MARSAD boundary contract — the single source of truth for what may cross
the privacy boundary between an institution's connector and the MARSAD core.

This module is deliberately the smallest, most heavily reviewed part of the
codebase. An institution's own security team should be able to read this file
alone and satisfy itself that narrative, plaintext indicators and PII cannot
leave the perimeter — because the emitted shape simply cannot express them.

RULE: if a field is not defined here, it cannot cross. Adding a field to these
models is a security decision requiring review, not a routine change.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------
# Enumerations — closed vocabularies keep coarse data genuinely coarse
# --------------------------------------------------------------------------


class IndicatorType(str, Enum):
    IP = "IP"
    DOMAIN = "DOMAIN"
    URL = "URL"
    FILE_HASH = "FILE_HASH"
    ACCOUNT = "ACCOUNT"
    IBAN = "IBAN"
    WALLET = "WALLET"


class Sector(str, Enum):
    BANK = "BANK"
    BROKER = "BROKER"
    INVEST = "INVEST"
    EXCHANGE = "EXCHANGE"
    INSURER = "INSURER"
    PROVIDER = "PROVIDER"


class SizeBand(str, Enum):
    SMALL = "SMALL"
    MID = "MID"
    LARGE = "LARGE"


class SeverityBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DisclosureRung(int, Enum):
    """Graduated disclosure. The institution alone advances this."""

    ANONYMOUS_MATCH = 0        # a correlation exists; nothing else revealed
    TECHNIQUE_CATEGORY = 1     # technique class only
    FULL_INDICATORS = 2        # indicator set, still no narrative
    RESPONSE_ACTIONS = 25      # act together without disclosing (rung 2.5)
    BILATERAL = 3              # identities known, SCA-facilitated


class TelemetrySignal(str, Enum):
    AUTH_FAIL = "AUTH_FAIL"
    MAIL_REJECT = "MAIL_REJECT"
    SCAN_VOL = "SCAN_VOL"
    ALERT_VOL = "ALERT_VOL"
    OUTBOUND_ANOM = "OUTBOUND_ANOM"


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    BLOCKED = "BLOCKED"


# --------------------------------------------------------------------------
# Crossing types
# --------------------------------------------------------------------------

Token = Annotated[str, Field(min_length=32, max_length=64, pattern=r"^[0-9a-f]+$")]
AttackTechnique = Annotated[str, Field(pattern=r"^T\d{4}(\.\d{3})?$")]


class StrictModel(BaseModel):
    """Forbids unknown fields. A typo cannot smuggle data across."""

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=True)


class KeyedToken(StrictModel):
    """
    A keyed, non-invertible reference to an indicator.

    Produced only by a Tokeniser implementation inside the connector. The core
    can compare tokens for equality and nothing else — it cannot recover the
    indicator, and with an OPRF it cannot enumerate candidates either.
    """

    type: IndicatorType
    token: Token


class CoarseMetadata(StrictModel):
    """
    Deliberately low-resolution context. Timestamps are bucketed to the hour
    and severity is banded so that neither can be used to single out a firm.
    """

    sector: Sector
    size_band: SizeBand
    severity_band: SeverityBand
    ts_bucket: datetime

    @field_validator("ts_bucket")
    @classmethod
    def _hour_bucket(cls, v: datetime) -> datetime:
        return v.replace(minute=0, second=0, microsecond=0)


class ObligationReceiptRef(StrictModel):
    """Hash of a filed regulatory notification. No rule text, no narrative."""

    receipt_hash: Annotated[str, Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")]
    authority: str
    filed_at: datetime


class IncidentSubmission(StrictModel):
    """
    THE payload. This is the only shape the connector may emit for an incident.

    Note what is absent and can never be added without an explicit security
    review: narrative, analyst notes, plaintext indicators, hostnames, user
    identifiers, affected system names, evidence files.
    """

    schema_version: Literal["1.0"] = "1.0"
    submission_id: str
    institution_ref: str = Field(
        description="Rotating pseudonym, unlinkable across key epochs.",
        min_length=6,
        max_length=64,
    )
    tokens: list[KeyedToken] = Field(min_length=1, max_length=512)
    technique_set: list[AttackTechnique] = Field(default_factory=list, max_length=64)
    coarse: CoarseMetadata
    obligation_ref: ObligationReceiptRef | None = None
    disclosure_rung: DisclosureRung = DisclosureRung.ANONYMOUS_MATCH

    @field_validator("institution_ref")
    @classmethod
    def _no_names(cls, v: str) -> str:
        # Cheap belt-and-braces: a pseudonym must not look like a firm name.
        if " " in v or v.lower() != v:
            raise ValueError("institution_ref must be an opaque lowercase pseudonym")
        return v


class TelemetrySample(StrictModel):
    """
    Continuous coarse signal. Rates and counts only — never events, never logs.
    The local baseline stays inside the institution; only the deviation leaves.
    """

    schema_version: Literal["1.0"] = "1.0"
    institution_ref: str
    signal: TelemetrySignal
    band: int | None = Field(default=None, ge=0, le=9)
    zscore: float | None = Field(default=None, ge=-10, le=10)
    ts_bucket: datetime

    @field_validator("zscore")
    @classmethod
    def _one_of(cls, v, info):
        if v is None and info.data.get("band") is None:
            raise ValueError("provide either band or zscore")
        return v


class ResponseActionStatus(StrictModel):
    """
    Disclosure rung 2.5 — coordinate action without disclosing the incident.
    Status only. A declined action is recorded with a reason and never penalised.
    """

    schema_version: Literal["1.0"] = "1.0"
    room_id: str
    action_id: str
    institution_ref: str
    status: ActionStatus
    decline_reason: str | None = Field(default=None, max_length=280)
    note: str | None = Field(
        default=None, max_length=500,
        description="Voluntary, firm-authored. Never auto-populated from the incident.",
    )
    updated_at: datetime


# --------------------------------------------------------------------------
# Core-derived types (never emitted by a connector; returned to institutions)
# --------------------------------------------------------------------------


class CorrelationKind(str, Enum):
    EXACT_TOKEN = "EXACT_TOKEN"
    TECHNIQUE_SIMILARITY = "TECHNIQUE_SIMILARITY"


class CorrelationNotice(BaseModel):
    """What an institution receives at rung 0 — deliberately uninformative."""

    model_config = ConfigDict(use_enum_values=True)

    correlation_id: str
    kind: CorrelationKind
    peer_count: int = Field(description="How many other institutions, not which.")
    indicator_type: IndicatorType | None = None
    shared_techniques: list[AttackTechnique] = Field(default_factory=list)
    similarity: float | None = Field(default=None, ge=0, le=1)
    detected_at: datetime
    campaign_id: str | None = None


__all__ = [
    "IndicatorType", "Sector", "SizeBand", "SeverityBand", "DisclosureRung",
    "TelemetrySignal", "ActionStatus", "KeyedToken", "CoarseMetadata",
    "ObligationReceiptRef", "IncidentSubmission", "TelemetrySample",
    "ResponseActionStatus", "CorrelationKind", "CorrelationNotice",
]
