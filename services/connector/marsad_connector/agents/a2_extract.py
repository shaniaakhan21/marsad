"""
A2 — Extraction Agent. Free-text incident intake, at the edge.

Why this agent exists
---------------------
An analyst in the middle of an incident types prose, not a form. Asking them to
hand-fill a structured schema at 3am is how fields get left blank and how a firm
ends up with an incident record too thin to correlate against anything. A2 reads
the prose and proposes the structured incident; the analyst corrects and confirms.

Where it sits, and why that matters
-----------------------------------
A2 runs entirely inside the institution, upstream of A3, and reads the narrative in
full. That makes it the single most dangerous component in the connector to get
wrong, so three rules constrain it:

1. **It is PROPOSE_CONFIRM, never AUTOMATIC.** Extraction output is a *proposal*.
   Nothing reaches A3 until a human has seen every field and confirmed it. The gate
   is structural, not procedural: an `ExtractionDraft` does not expose the attributes
   A3 reads, and the only way to obtain an object that does is `confirm()`. A
   component that tries to shortcut it gets a loud `UnconfirmedExtractionError`
   naming the rule, not a quiet `AttributeError` someone might paper over.

2. **It opens no second path to the core.** A2 produces plenty that must never
   cross — affected service names, third-party vendor names, and evidence spans that
   are verbatim slices of the narrative. None of it is added to the boundary
   contract, and A3 still reads only the seven fields it names. The extra fields on
   `ConfirmedIncident` are invisible to A3 by construction, and the leak guard is
   what proves it stayed that way.

3. **Absent is not the same as zero.** A field the narrative does not state is
   omitted, never guessed. A confident-looking severity invented from nothing is
   worse than a blank one, because a blank prompts a question and a guess does not.

Every extracted field carries a confidence score and the span of source text it came
from, so an analyst reviews a claim with its evidence attached rather than a bare
value they have to take on trust. Spans are resolved by locating the model's quoted
evidence in the narrative — a citation we cannot find in the source is treated as
unevidenced and flagged, which catches a fabricated quote for free.
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import annotated_types
from marsad_contracts.boundary import IncidentSubmission, IndicatorType, SeverityBand

from marsad_connector.agents.base import Agent, Autonomy
from marsad_connector.lang.arabic import (
    Language,
    NormalisedText,
    detect_language,
    has_arabic,
    normalise_tracked,
)

log = logging.getLogger("marsad.a2")


class IncidentCategory(str, Enum):
    """
    Edge-only vocabulary.

    Deliberately NOT in `marsad_contracts.boundary`: category never crosses the
    privacy boundary, and putting it in the contract would invite someone to start
    emitting it. Anything defined there is a thing that can cross; this cannot.
    """

    PHISHING = "PHISHING"
    CREDENTIAL_COMPROMISE = "CREDENTIAL_COMPROMISE"
    BUSINESS_EMAIL_COMPROMISE = "BUSINESS_EMAIL_COMPROMISE"
    RANSOMWARE = "RANSOMWARE"
    MALWARE = "MALWARE"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    DENIAL_OF_SERVICE = "DENIAL_OF_SERVICE"
    VULNERABILITY_EXPLOITATION = "VULNERABILITY_EXPLOITATION"
    THIRD_PARTY_COMPROMISE = "THIRD_PARTY_COMPROMISE"
    INSIDER = "INSIDER"
    FRAUD = "FRAUD"
    UNKNOWN = "UNKNOWN"


#: Below this, a field is surfaced for human attention rather than accepted. Set
#: high on purpose: the cost of an analyst glancing at a correct field is seconds,
#: and the cost of a wrong severity reaching a regulator's clock is not.
CONFIDENCE_THRESHOLD = 0.70

#: The range a confidence may occupy. Enforced HERE rather than trusted to the schema:
#: `response_format: json_schema` with `strict: true` declares `minimum: 0, maximum: 1`
#: and does not enforce it — 95 of 203 values in the first live run fell outside the
#: range and the largest was 100.0 (docs/model-path-results.md). A value outside this
#: range is a malformed response, not a low-confidence answer, and must not be clamped
#: into something that looks like one.
CONFIDENCE_RANGE = (0.0, 1.0)

#: Fields the analyst must positively see before anything is filed, even when the
#: model is confident. Severity drives A4's deadlines and the correlation's coarse
#: band; detected_at starts every regulatory clock in the country.
ALWAYS_REVIEW = frozenset({"severity", "detected_at"})

EXTRACTED_FIELDS = (
    "severity", "category", "affected_services", "third_party_dependencies",
    "indicators", "techniques", "detected_at",
)


# --------------------------------------------------------------------------
# The schema, built from the contract's own enums
# --------------------------------------------------------------------------


def _contract_max_items(field_name: str) -> int:
    """
    Read a list cap straight off the boundary contract.

    Read rather than repeated. A literal here would be a second copy of a number the
    contract already enforces, and the two would drift the moment either moved —
    with the schema silently permitting more than the payload can carry.
    """
    field = IncidentSubmission.model_fields[field_name]
    caps = [m.max_length for m in field.metadata if isinstance(m, annotated_types.MaxLen)]
    if not caps:
        raise RuntimeError(
            f"IncidentSubmission.{field_name} no longer declares a max_length. The "
            f"extraction schema derives its array bound from it, so the bound has "
            f"silently disappeared — restore the contract cap or bound this explicitly."
        )
    return caps[0]


#: Array bounds for the extraction schema. These are a denial-of-service control, not
#: tidying. Under grammar-constrained decoding an unbounded array has nowhere to stop:
#: `17_many_indicators` generated for 900 seconds without completing and had to be
#: killed (docs/model-path-results.md). An analyst filing an indicator-dense incident
#: could hang the connector for as long as the timeout allows.
#:
#: The two that cross take the contract's own caps. The two that never cross have no
#: contract counterpart, so they carry a local bound chosen to be far above any real
#: incident and far below anything that generates for minutes.
MAX_INDICATORS = _contract_max_items("tokens")
MAX_TECHNIQUES = _contract_max_items("technique_set")
MAX_LOCAL_LIST_ITEMS = 64


def _tracked(value_schema: dict[str, Any], description: str) -> dict[str, Any]:
    """
    Wrap a value so it arrives with its confidence and its citation.

    A bare value is unreviewable: the analyst cannot tell a field read straight out
    of the text from one the model inferred. `evidence` is the verbatim slice the
    model claims it read; we resolve it to offsets ourselves rather than trusting a
    model to count characters.
    """
    return {
        "type": "object",
        "description": description,
        "additionalProperties": False,
        "required": ["value", "confidence", "evidence"],
        "properties": {
            "value": value_schema,
            "confidence": {
                "type": "number", "minimum": 0, "maximum": 1,
                "description": "0 when the narrative does not state this field.",
            },
            "evidence": {
                "type": ["string", "null"],
                "description": "Verbatim substring of the narrative supporting the value.",
            },
        },
    }


#: Formal JSON Schema for extraction, used as the `response_format` schema so the
#: serving stack constrains generation rather than the prompt asking politely.
#:
#: `severity` and `indicators[].type` take their vocabularies from
#: `marsad_contracts.boundary` rather than repeating them. A parallel list here
#: would drift from the contract, and a severity the contract cannot express is a
#: submission that fails validation at the boundary — after the analyst has already
#: confirmed it and believes the incident is filed.
#:
#: Every value is nullable and every key is required: that is how a strict schema
#: expresses "the narrative did not say", which is a different fact from "low
#: confidence" and must not collapse into a guess.
EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": list(EXTRACTED_FIELDS),
    "properties": {
        "severity": _tracked(
            {"type": ["string", "null"], "enum": [*(s.value for s in SeverityBand), None]},
            "Impact band. Null unless the narrative supports one.",
        ),
        "category": _tracked(
            {"type": ["string", "null"], "enum": [*(c.value for c in IncidentCategory), None]},
            "Incident class. UNKNOWN only when the narrative describes an incident of no clear class.",
        ),
        "affected_services": _tracked(
            {"type": ["array", "null"], "items": {"type": "string"},
             "maxItems": MAX_LOCAL_LIST_ITEMS},
            "Business services disrupted, as named in the narrative. Never leaves the institution.",
        ),
        "third_party_dependencies": _tracked(
            {"type": ["array", "null"], "items": {"type": "string"},
             "maxItems": MAX_LOCAL_LIST_ITEMS},
            "Named external providers involved. Never leaves the institution.",
        ),
        "indicators": _tracked(
            {
                "type": ["array", "null"],
                "maxItems": MAX_INDICATORS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "value"],
                    "properties": {
                        "type": {"type": "string", "enum": [t.value for t in IndicatorType]},
                        "value": {"type": "string"},
                    },
                },
            },
            "Technical indicators exactly as written, including defanged forms.",
        ),
        "techniques": _tracked(
            {"type": ["array", "null"], "maxItems": MAX_TECHNIQUES,
             "items": {"type": "string", "pattern": r"^T\d{4}(\.\d{3})?$"}},
            "MITRE ATT&CK technique IDs the narrative supports. Do not speculate.",
        ),
        "detected_at": _tracked(
            {"type": ["string", "null"], "format": "date-time"},
            "ISO-8601 UTC detection time. Null unless the narrative states one.",
        ),
    },
}


# --------------------------------------------------------------------------
# Draft, gate, and confirmed incident
# --------------------------------------------------------------------------


class UnconfirmedExtractionError(RuntimeError):
    """
    Raised when something tries to read incident fields off an unconfirmed draft.

    Loud on purpose. The alternative — an `AttributeError` from deep inside A3 —
    reads like a plumbing bug and invites a fix that restores the attribute and
    removes the gate along with it.
    """


@dataclass(frozen=True)
class TrackedField:
    """One extracted field, with everything an analyst needs to disagree with it."""

    name: str
    value: Any
    confidence: float
    evidence: str | None = None
    span: tuple[int, int] | None = None
    needs_attention: bool = False
    reason: str = ""
    edited: bool = False
    #: Proposed values refused outright rather than flagged. Kept so the analyst can
    #: see what was thrown away and disagree — a silent drop is as unreviewable as a
    #: silent acceptance.
    rejected: tuple = ()

    @property
    def present(self) -> bool:
        """False when the narrative did not state this field. Not the same as low confidence."""
        return self.value is not None and self.value != []

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["span"] = list(self.span) if self.span else None
        d["present"] = self.present
        d["rejected"] = list(self.rejected)
        return d


@dataclass(frozen=True)
class ConfirmedIncident:
    """
    An incident a human has signed off. The ONLY thing A2 produces that A3 will read.

    The first seven attributes are exactly A3's `IncidentLike` protocol. Everything
    after them is local provenance — who confirmed, what they changed, which draft it
    came from — and A3 never reads any of it, because A3 builds from an allow-list.
    `test_extraction_provenance_never_reaches_the_payload` is what keeps that true.
    """

    narrative: str | None
    analyst_notes: str | None
    indicators: list[dict[str, Any]]
    techniques: list[str]
    severity: str
    obligation_receipt: dict[str, Any] | None
    detected_at: datetime | None

    # -- local only, never read by A3 --------------------------------------
    confirmed_by: str = ""
    confirmed_at: datetime | None = None
    draft_id: str = ""
    edited_fields: tuple[str, ...] = ()
    narrative_normalised: str = ""
    language: str = ""
    category: str | None = None
    affected_services: tuple[str, ...] = ()
    third_party_dependencies: tuple[str, ...] = ()
    raw_email: str | None = None


@dataclass(frozen=True)
class ExtractionDraft:
    """
    A proposal. Not an incident.

    The attributes A3 needs are deliberately absent — reading one raises rather than
    returning a value. That is the confirmation gate: it is enforced by the shape of
    this object, so no caller can forget to check a flag.
    """

    draft_id: str
    narrative: str
    fields: dict[str, TrackedField]
    #: The normalised form every pattern was matched against. Kept beside the raw
    #: text, never instead of it: the analyst is shown what they typed, and a
    #: reviewer can reproduce exactly what the matcher saw. Storing only one of the
    #: two is how the write and query forms drift apart.
    narrative_normalised: str = ""
    analyst_notes: str | None = None
    raw_email: str | None = None
    method: str = ""
    #: True when a language model proposed these fields. Model-proposed indicators
    #: need positive sign-off before they can be tokenised; heuristic ones are cut
    #: verbatim out of the narrative by a regex, so they are locatable by construction.
    model_proposed: bool = False
    language: str = Language.ENGLISH.value
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # -- the gate -----------------------------------------------------------

    def _refuse(self, attribute: str):
        raise UnconfirmedExtractionError(
            f"{attribute!r} was read from an unconfirmed ExtractionDraft. A2 is "
            f"PROPOSE_CONFIRM: extracted fields are a proposal, and an analyst must see "
            f"and confirm every one of them before an incident exists. Call "
            f"ExtractionDraft.confirm(analyst=..., edits=...) and pass the resulting "
            f"ConfirmedIncident. Do not add this attribute to the draft to make an error "
            f"go away — it would delete the only thing standing between a model's guess "
            f"and a regulatory filing."
        )

    @property
    def indicators(self):
        self._refuse("indicators")

    @property
    def severity(self):
        self._refuse("severity")

    @property
    def techniques(self):
        self._refuse("techniques")

    @property
    def obligation_receipt(self):
        self._refuse("obligation_receipt")

    @property
    def detected_at(self):
        self._refuse("detected_at")

    # -- review surface -----------------------------------------------------

    @property
    def needs_attention(self) -> list[str]:
        """Fields the analyst must look at before this can be confirmed."""
        return [n for n, f in self.fields.items() if f.needs_attention]

    @property
    def requires_indicator_confirmation(self) -> bool:
        """
        True when an analyst must positively sign off the indicator list.

        Only for model-proposed drafts, and only when indicators were proposed. The
        deterministic extractor takes indicators verbatim out of the narrative with a
        regex, so there is nothing to confirm that the text does not already say.
        """
        return bool(self.model_proposed and (self.fields["indicators"].value or []))

    @property
    def missing(self) -> list[str]:
        """Fields the narrative did not state. Omitted, never guessed."""
        return [n for n, f in self.fields.items() if not f.present]

    def as_dict(self) -> dict[str, Any]:
        return {
            "draft_id": self.draft_id,
            "method": self.method,
            "created_at": self.created_at.isoformat(),
            "narrative": self.narrative,
            "narrative_normalised": self.narrative_normalised,
            "language": self.language,
            "fields": {n: f.as_dict() for n, f in self.fields.items()},
            "needs_attention": self.needs_attention,
            "missing": self.missing,
            "confidence_threshold": CONFIDENCE_THRESHOLD,
            "model_proposed": self.model_proposed,
            "requires_indicator_confirmation": self.requires_indicator_confirmation,
            "autonomy": Autonomy.PROPOSE_CONFIRM.value,
            "confirmed": False,
        }

    # -- the only way out ---------------------------------------------------

    def confirm(
        self,
        *,
        analyst: str,
        edits: dict[str, Any] | None = None,
        obligation_receipt: dict[str, Any] | None = None,
    ) -> ConfirmedIncident:
        """
        Turn a reviewed proposal into an incident.

        `edits` overrides any extracted field with what the analyst actually typed;
        an edited field is recorded as edited so a later reviewer can tell the
        model's answer from the human's. Severity has no default — if extraction
        found none and the analyst supplied none, this raises rather than picking
        one, because every downstream regulatory clock hangs off it.
        """
        if not analyst.strip():
            raise ValueError("confirmation requires the identity of the confirming analyst")

        edits = edits or {}
        unknown = set(edits) - set(EXTRACTED_FIELDS)
        if unknown:
            raise ValueError(f"cannot confirm unknown field(s): {sorted(unknown)}")

        if self.requires_indicator_confirmation and "indicators" not in edits:
            raise ValueError(
                "model-proposed indicators require explicit confirmation. Pass "
                "edits={'indicators': [...]} with the list the analyst actually "
                "accepts — an empty list is a valid answer. Every other field a model "
                "gets wrong is wrong inside one institution; an indicator becomes a "
                "token in a matching space every other institution is compared "
                "against, and nobody downstream can review it because they see only "
                "the hash."
            )

        def value_of(name: str):
            return edits[name] if name in edits else self.fields[name].value

        severity = value_of("severity")
        if not severity:
            raise ValueError(
                "severity is not set. Extraction did not find one in the narrative and the "
                "analyst did not supply one; it drives every regulatory deadline, so this "
                "system will not choose it."
            )
        severity = str(severity).upper()
        if severity not in {s.value for s in SeverityBand}:
            raise ValueError(f"severity {severity!r} is not a band the boundary contract can carry")

        detected = value_of("detected_at")
        if isinstance(detected, str):
            detected = datetime.fromisoformat(detected.replace("Z", "+00:00"))

        return ConfirmedIncident(
            narrative=self.narrative,
            analyst_notes=self.analyst_notes,
            indicators=list(value_of("indicators") or []),
            techniques=list(value_of("techniques") or []),
            severity=severity,
            obligation_receipt=obligation_receipt,
            detected_at=detected,
            confirmed_by=analyst,
            confirmed_at=datetime.now(timezone.utc),
            draft_id=self.draft_id,
            edited_fields=tuple(sorted(edits)),
            narrative_normalised=self.narrative_normalised,
            language=self.language,
            category=value_of("category"),
            affected_services=tuple(value_of("affected_services") or []),
            third_party_dependencies=tuple(value_of("third_party_dependencies") or []),
            raw_email=self.raw_email,
        )


# --------------------------------------------------------------------------
# Extractors
# --------------------------------------------------------------------------


_NEGATION = re.compile(r"\b(?:no|not|nothing|never|without|denied|ruled out)\b", re.IGNORECASE)


def _negated(text: str, match: re.Match, window: int = 40) -> bool:
    """
    True when a negation sits just before the match.

    Without this, "nothing was exfiltrated" reads as exfiltration and "confirmed no
    breach" reads as a breach — the extractor would report the opposite of what the
    analyst wrote, which is worse than reporting nothing.
    """
    return bool(_NEGATION.search(text[max(0, match.start() - window):match.start()]))


def _locate(narrative: str, evidence: str | None) -> tuple[int, int] | None:
    """
    Resolve a quoted span to offsets in the narrative.

    Returns None when the quoted text is not in the source. That is a meaningful
    result, not a lookup failure: a model that cites text the analyst never wrote
    has fabricated its evidence, and the field is flagged rather than trusted.
    """
    if not evidence:
        return None
    at = narrative.find(evidence)
    if at < 0:
        at = narrative.lower().find(evidence.lower().strip())
        if at < 0:
            return None
        return (at, at + len(evidence.strip()))
    return (at, at + len(evidence))


def _locatable_indicators(value: Any, narrative: str) -> tuple[list, list]:
    """
    Split proposed indicators into those present verbatim in the narrative and those
    that are not. The second list is dropped, not flagged.

    Locatability is ADVISORY for every other field and a HARD GATE here, and the
    asymmetry is deliberate. A fabricated severity is wrong inside one institution
    and a human is going to look at it anyway. A fabricated indicator becomes a
    TOKEN — a value in a matching space that every other institution's submissions
    are compared against. It cannot be reviewed by anyone downstream, because
    downstream sees only the hash. It either matches nothing, wasting the slot, or it
    matches something by accident and manufactures a campaign that does not exist.

    The first live run produced exactly this: on `07_webshell_exploit` the model
    returned our own `UNTRUSTED_` fence marker as an indicator of type URL. Under the
    old code that would have been canonicalised, tokenised and submitted.
    """
    kept: list = []
    rejected: list = []
    for item in value or []:
        raw = str((item or {}).get("value", "")).strip() if isinstance(item, dict) else ""
        if raw and _locate(narrative, raw) is not None:
            kept.append(item)
        else:
            rejected.append(item)
            log.warning("a2.indicator_rejected not_in_narrative value=%r", raw[:60])
    return kept, rejected


def _field(
    name: str, value: Any, confidence: float, narrative: str, evidence: str | None,
) -> TrackedField:
    """Assemble one field, deciding on its own whether a human must look at it."""
    span = _locate(narrative, evidence)
    present = value is not None and value != []

    rejected: tuple = ()
    if name == "indicators" and value:
        kept, dropped = _locatable_indicators(value, narrative)
        rejected = tuple(dropped)
        value = kept or None
        present = value is not None

    low, high = CONFIDENCE_RANGE
    malformed_confidence = not (low <= confidence <= high)
    if malformed_confidence:
        # Not clamped. A confidence of 100.0 is a broken response, and clamping it to
        # 1.0 would turn a malformed answer into a maximally trusted one.
        log.warning("a2.malformed_confidence field=%s value=%r", name, confidence)

    needs, reason = False, ""
    if malformed_confidence:
        needs = True
        reason = (
            f"Confidence {confidence!r} is outside {CONFIDENCE_RANGE} — the response is "
            f"malformed, not merely uncertain. Treat this field as unverified."
        )
        confidence = 0.0
    elif not present:
        needs, reason = True, "Not stated in the narrative — supply it or leave it out deliberately."
    elif confidence < CONFIDENCE_THRESHOLD:
        needs, reason = True, f"Confidence {confidence:.2f} is below {CONFIDENCE_THRESHOLD:.2f}."
    elif evidence and span is None:
        needs, reason = True, "Cited evidence does not appear in the narrative — treat as unsupported."
    elif name in ALWAYS_REVIEW:
        needs, reason = True, "Drives regulatory deadlines and the correlation band; always reviewed."

    if rejected:
        needs = True
        dropped_values = ", ".join(
            repr(str(item.get("value", ""))[:40]) for item in rejected if isinstance(item, dict)
        )
        reason = (
            f"Dropped {len(rejected)} proposed indicator(s) not present in the narrative "
            f"({dropped_values}). An indicator that was never written cannot become a "
            f"token. " + reason
        ).strip()

    return TrackedField(
        name=name, value=value, confidence=round(float(confidence), 2),
        evidence=evidence, span=span, needs_attention=needs, reason=reason,
        rejected=rejected,
    )


# -- deterministic offline extractor ---------------------------------------

#: Trailing sentence punctuation is not part of an indicator. A URL written at the
#: end of a sentence would otherwise carry the full stop into the token, and the same
#: URL written mid-sentence would tokenise differently — correlation then silently
#: never fires, which is the failure this whole pipeline exists to avoid. Arabic
#: full stop and semicolon are included: the prose around an indicator may be Arabic.
_TRAILING_PUNCTUATION = ".,;:!?)]}'\"،؛"

_INDICATOR_RULES: tuple[tuple[IndicatorType, str, float], ...] = (
    (IndicatorType.URL, r"https?://[^\s,;)\]]+", 0.95),
    (IndicatorType.FILE_HASH, r"\b[a-fA-F0-9]{64}\b|\b[a-fA-F0-9]{40}\b|\b[a-fA-F0-9]{32}\b", 0.95),
    (IndicatorType.IBAN, r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}(?:[ ]?[A-Z0-9]{1,4})?\b", 0.9),
    (IndicatorType.WALLET, r"\b(?:bc1[a-z0-9]{25,50}|0x[a-fA-F0-9]{40})\b", 0.9),
    (IndicatorType.IP, r"\b(?:\d{1,3}(?:\[\.\]|\.)){3}\d{1,3}\b", 0.95),
    (IndicatorType.DOMAIN,
     r"\b(?:[a-zA-Z0-9-]+(?:\[\.\]|\.)){1,3}(?:com|net|org|io|ae|info|xyz|top|ru|cn|co|biz|online)\b",
     0.9),
    (IndicatorType.ACCOUNT, r"\baccount(?:\s+number)?\s+(\d{6,12})\b", 0.75),
)

_TECHNIQUE_CUES: tuple[tuple[str, str], ...] = (
    ("T1566.002", r"\b(phish\w*|spear[- ]?phish\w*)\b.{0,60}\b(link|url|page|portal|site)\b|credential[- ]harvest\w*"),
    ("T1566", r"\bphish\w*|fraudulent email|lookalike email\b"),
    ("T1078", r"\bvalid (?:account|credential)s?\b|logged in (?:with|using) (?:stolen|harvested)|legitimate credentials\b"),
    ("T1114", r"\b(?:mail|mailbox|email) (?:collection|forwarding|rule)s?\b|auto[- ]?forward\w*"),
    ("T1567", r"\bexfiltrat\w*\b.{0,40}\b(web|cloud|https?|drive|storage)\b|uploaded .{0,30}to an external"),
    ("T1041", r"\bexfiltrat\w*\b(?!.{0,40}\b(web|cloud|https?|drive|storage)\b)"),
    ("T1190", r"\bexploit\w*\b.{0,40}\b(public[- ]facing|internet[- ]facing|vpn|gateway|appliance|cve)\b|\bCVE-\d{4}-\d+"),
    ("T1505.003", r"\bweb ?shell\b"),
    ("T1486", r"\bransomware\b|\bencrypted (?:our|the) (?:files|servers|shares|systems)\b"),
    ("T1498", r"\b(?:ddos|denial[- ]of[- ]service|traffic flood|volumetric)\b"),
    ("T1110", r"\b(?:brute[- ]?force|password spray\w*|credential stuffing)\b"),
    ("T1656", r"\b(?:impersonat\w*|business email compromise|\bbec\b|pretend\w* to be)\b"),
    ("T1195.002", r"\b(?:supply[- ]chain|compromised (?:update|vendor software))\b"),
)

_SEVERITY_CUES: tuple[tuple[str, str, float], ...] = (
    ("CRITICAL", (r"\bcritical\b|\bsevere\b|\bfunds? (?:were )?(?:transferred|stolen|lost)\b|"
                  r"\bcustomer data (?:was )?(?:exfiltrated|stolen)\b|\btrading (?:was )?halted\b"), 0.85),
    ("HIGH", (r"\bhigh(?:ly)? (?:severity|serious|impact)\b|\bmajor\b|"
              r"\bcredentials? (?:were )?(?:harvested|submitted|stolen)\b|"
              r"\bunavailable for\b|\boutage\b"), 0.8),
    ("MEDIUM", r"\bmedium\b|\bmoderate\b|\bcontained (?:quickly|immediately)\b|\bno (?:data|funds) (?:were )?lost\b", 0.75),
    ("LOW", r"\blow (?:severity|impact)\b|\bminor\b|\bno impact\b|\bblocked before\b", 0.75),
)

#: An explicit statement of severity is the analyst's own assessment and outranks
#: anything inferred from impact wording. "Severity: HIGH" in a pasted ticket, or
#: "low impact confirmed", must not lose to a keyword elsewhere in the prose.
_SEVERITY_EXPLICIT = re.compile(
    r"\b(?:severity|impact|priority)\s*[:=-]?\s*(critical|high|medium|moderate|low|minor)\b"
    r"|\b(critical|high|medium|moderate|low|minor)\s+(?:severity|impact)\b"
    r"|\b(?:calling it|assessed as|rated|classified as)\s+(critical|high|medium|moderate|low|minor)\b",
    re.IGNORECASE,
)

_EXPLICIT_TO_BAND = {
    "critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM",
    "moderate": "MEDIUM", "low": "LOW", "minor": "LOW",
}

_CATEGORY_CUES: tuple[tuple[str, str, float], ...] = (
    ("RANSOMWARE", r"\bransomware\b|\bransom note\b|\bencrypted (?:our|the) \w+\b", 0.9),
    ("DENIAL_OF_SERVICE", r"\b(?:ddos|denial[- ]of[- ]service|traffic flood|volumetric)\b", 0.9),
    ("INSIDER", r"\b(?:insider|departing employee|former employee|staff member (?:copied|downloaded))\b", 0.85),
    ("BUSINESS_EMAIL_COMPROMISE", r"\bbusiness email compromise\b|\bbec\b|\binvoice (?:fraud|redirect\w*)\b|\bpayment redirect\w*\b", 0.85),
    ("PHISHING", r"\bphish\w*|\bcredential[- ]harvest\w*|\blookalike (?:page|portal|domain|site)\b", 0.85),
    # Requires an affirmative statement of compromise: "confirmed no breach" is not one.
    ("THIRD_PARTY_COMPROMISE",
     (r"\b(?:our |a )?(?:provider|vendor|supplier|third[- ]party)\b[^.\n]{0,50}?"
      r"\b(?:was breached|were breached|suffered a breach|was compromised|were compromised|"
      r"disclosed a breach|reported a breach)\b"), 0.85),
    ("VULNERABILITY_EXPLOITATION", r"\bCVE-\d{4}-\d+|\bexploit\w*\b|\bunpatched\b|\bweb ?shell\b", 0.8),
    # Malware outranks exfiltration: the implant is the incident, exfiltration is
    # something it did. Classing it the other way loses the intrusion.
    ("MALWARE", r"\bmalware\b|\btrojan\b|\bimplant\b|\bbackdoor\b", 0.8),
    ("CREDENTIAL_COMPROMISE",
     (r"\bcredentials? (?:were |was )?(?:stolen|harvested|compromis\w+|submitted)\b|"
      r"\baccount takeover\b|\b(?:accounts?|logins?) (?:were|was) compromis\w+\b|"
      r"\bcredential stuffing\b|\bpassword spray\w*\b"), 0.8),
    ("DATA_EXFILTRATION", r"\bexfiltrat\w*|\bdata (?:was )?(?:stolen|copied|removed)\b", 0.8),
    ("FRAUD", r"\bfraudulent (?:transaction|transfer|payment)s?\b|\bunauthorised (?:payment|transfer)s?\b", 0.8),
)

_SERVICE_CUES = (
    "retail banking portal", "online banking", "mobile app", "mobile banking", "core banking",
    "trading platform", "trading terminal", "payment gateway", "swift gateway", "atm network",
    "custody platform", "settlement system", "client portal", "email service", "vpn", "kyc service",
    "card processing", "internet banking", "treasury system", "market data feed",
)

_THIRD_PARTY_CUE = re.compile(
    r"\b(?:provider|vendor|supplier|third[- ]party|hosted by|managed by|outsourced to|"
    r"platform from|service from)\b[^.\n]{0,40}?\b([A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,2})",
)

_TIMESTAMPS: tuple[tuple[str, float], ...] = (
    (r"\b(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?)\s*(?:UTC|Z)?\b", 0.95),
    (r"\b(\d{1,2}:\d{2})\s*(?:UTC|GST|local)?\s+on\s+(\d{4}-\d{2}-\d{2})\b", 0.9),
    (r"\b(\d{4}-\d{2}-\d{2})\s+at\s+(\d{1,2}:\d{2})\b", 0.9),
    (r"\b(\d{1,2}\s+\w+\s+\d{4})\s+at\s+(\d{1,2}:\d{2})\b", 0.85),
    (r"\bon\s+(\d{4}-\d{2}-\d{2})\b", 0.8),
)

_VAGUE_TIME = re.compile(r"\b(?:this morning|yesterday|last night|earlier today|over the weekend|a few days ago)\b", re.IGNORECASE)


# -- Arabic cue tables -----------------------------------------------------
#
# EVERY literal below is written in NORMALISED form — no diacritics, alef as ا, no
# alef maksura, teh marbuta folded to ه. Patterns are matched against normalised
# text, so a cue containing ة or أ could never fire, and the mistake would be silent.
# `test_every_arabic_cue_is_written_in_normalised_form` fails the build instead.

#: Severity words. Gulf reports code-switch mid-phrase, so an Arabic label routinely
#: carries an English value ("الأثر: moderate") — the label patterns accept both.
AR_SEVERITY_WORDS: dict[str, tuple[str, ...]] = {
    "CRITICAL": ("حرج", "حرجه", "كارثي", "كارثيه", "بالغ الخطوره", "جسيم"),
    "HIGH": ("عالي", "عاليه", "مرتفع", "مرتفعه", "خطير", "خطيره", "كبير", "كبيره"),
    "MEDIUM": ("متوسط", "متوسطه", "معتدل", "معتدله"),
    "LOW": ("منخفض", "منخفضه", "بسيط", "بسيطه", "طفيف", "طفيفه", "محدود", "محدوده"),
}

#: Words that introduce a stated severity: "الأثر:", "درجة الخطورة:", "التصنيف:".
AR_SEVERITY_LABELS: tuple[str, ...] = (
    "الاثر", "الخطوره", "درجه الخطوره", "مستوي الخطوره", "التصنيف", "التقييم", "الشده",
)

_EN_SEVERITY_WORD = "critical|high|medium|moderate|low|minor"

#: Inferred severity from Arabic impact wording, used only when nobody stated one.
AR_SEVERITY_INFERRED: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("CRITICAL", ("تحويل اموال", "سرقه اموال", "توقف التداول", "تسريب بيانات العملاء"), 0.8),
    ("HIGH", ("انقطاع الخدمه", "توقف الخدمه", "سرقه بيانات الدخول", "اختراق واسع"), 0.75),
    ("MEDIUM", ("تم احتواء", "احتواء الحادث", "لم تفقد بيانات"), 0.7),
    ("LOW", ("لا يوجد اثر", "بدون اثر", "تم الحظر قبل", "اثر محدود"), 0.7),
)

#: Relative Arabic time references. Surfaced, never resolved — same reason as English.
AR_VAGUE_TIME: tuple[str, ...] = ("هذا الصباح", "امس", "الليله الماضيه", "اليوم", "نهايه الاسبوع")

AR_CATEGORY_CUES: tuple[tuple[str, tuple[str, ...], float], ...] = (
    ("RANSOMWARE", ("فديه", "برنامج فديه", "برمجيه الفديه", "طلب فديه"), 0.9),
    ("DENIAL_OF_SERVICE", ("حجب الخدمه", "حرمان من الخدمه", "اغراق"), 0.9),
    ("INSIDER", ("موظف سابق", "تسريب داخلي", "من الداخل"), 0.85),
    ("BUSINESS_EMAIL_COMPROMISE", ("اختراق البريد التجاري", "تحويل فاتوره", "فاتوره مزوره"), 0.85),
    ("PHISHING", ("تصيد", "التصيد", "بريد احتيالي", "رساله احتياليه", "صفحه مزيفه", "موقع مزيف"), 0.85),
    ("THIRD_PARTY_COMPROMISE", ("اختراق المزود", "اختراق المورد", "اختراق الطرف الثالث"), 0.85),
    ("VULNERABILITY_EXPLOITATION", ("استغلال ثغره", "ثغره امنيه", "غير محدث"), 0.8),
    ("MALWARE", ("برمجيات خبيثه", "برنامج خبيث", "برمجيه خبيثه", "باب خلفي"), 0.8),
    ("CREDENTIAL_COMPROMISE", ("سرقه بيانات الدخول", "اختراق الحساب", "كلمات المرور", "بيانات الاعتماد"), 0.8),
    ("DATA_EXFILTRATION", ("تسريب البيانات", "سرقه البيانات", "نقل البيانات خارج"), 0.8),
    ("FRAUD", ("احتيال مالي", "تحويلات غير مصرح", "معاملات احتياليه"), 0.8),
)

#: Arabic service names map to the SAME canonical English labels the English cues
#: produce. The structured incident is one vocabulary regardless of the language it
#: was reported in; only the display stays in the analyst's words.
AR_SERVICE_CUES: tuple[tuple[str, str], ...] = (
    ("الخدمات المصرفيه عبر الانترنت", "online banking"),
    ("الخدمات المصرفيه الالكترونيه", "online banking"),
    ("تطبيق الهاتف", "mobile app"),
    ("الخدمات المصرفيه عبر الهاتف", "mobile banking"),
    ("منصه التداول", "trading platform"),
    ("النظام المصرفي الاساسي", "core banking"),
    ("بوابه الدفع", "payment gateway"),
    ("بوابه العملاء", "client portal"),
    ("نظام التسويه", "settlement system"),
    ("الصراف الالي", "atm network"),
    ("خدمه اعرف عميلك", "kyc service"),
    ("نظام الخزينه", "treasury system"),
)

AR_TECHNIQUE_CUES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("T1566", ("تصيد", "التصيد", "بريد احتيالي", "رساله احتياليه")),
    ("T1078", ("بيانات اعتماد صحيحه", "حساب شرعي", "بيانات دخول مسروقه")),
    ("T1114", ("اعاده توجيه البريد", "قاعده توجيه", "تجميع البريد")),
    ("T1486", ("تشفير الملفات", "تشفير الانظمه", "فديه")),
    ("T1498", ("حجب الخدمه", "اغراق الشبكه")),
    ("T1110", ("تخمين كلمات المرور", "رش كلمات المرور", "محاولات دخول متكرره")),
    ("T1190", ("استغلال ثغره", "استغلال خدمه عامه")),
    ("T1567", ("تسريب البيانات الي الخارج", "رفع البيانات الي")),
)

#: Provider words. The vendor's own name is usually Latin even in Arabic prose, so
#: the name group deliberately accepts both scripts.
AR_THIRD_PARTY_WORDS: tuple[str, ...] = ("مزود", "المزود", "المورد", "مورد", "الطرف الثالث", "شركه")

#: Arabic negation — "لم يتم تسريب" (no exfiltration occurred) must not be read as
#: exfiltration, exactly as the English guard prevents "nothing was exfiltrated".
AR_NEGATION: tuple[str, ...] = ("لم", "لن", "لا", "دون", "بدون", "غير", "نفي", "لم يتم")


def _ar_alt(words: tuple[str, ...]) -> str:
    """Regex alternation over cue literals, longest first so the specific one wins."""
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


_AR_SEVERITY_RE = re.compile(
    r"(?:" + _ar_alt(AR_SEVERITY_LABELS) + r")\s*[:=-]?\s*"
    r"(" + _ar_alt(tuple(w for ws in AR_SEVERITY_WORDS.values() for w in ws))
    + r"|" + _EN_SEVERITY_WORD + r")",
    re.IGNORECASE,
)

_AR_TO_BAND = {w: band for band, words in AR_SEVERITY_WORDS.items() for w in words}

#: Bounded on both sides by non-letters. Arabic negation particles are short and
#: occur inside ordinary words as letter sequences — "لم" sits inside "المالية" and
#: "المعلومات" — so an unbounded match reads almost every Arabic sentence as negated
#: and silently drops its cues. This is the Arabic equivalent of a word boundary.
_AR_NEGATION_RE = re.compile(
    r"(?<![ؠ-ي])(?:" + _ar_alt(AR_NEGATION) + r")(?![ؠ-ي])"
)

#: Latin-script names only. Vendor names in Gulf incident reports are written in
#: Latin even inside Arabic prose ("مزود Nexa KYC"), and an Arabic-script capture
#: cannot tell a company name from the next ordinary word — it read "بتاريخ" ("dated")
#: as a vendor. An Arabic-named vendor is therefore missed rather than invented,
#: which is the safe direction: the analyst adds it, and A2 never fabricates one.
_AR_THIRD_PARTY_RE = re.compile(
    r"(?:" + _ar_alt(AR_THIRD_PARTY_WORDS) + r")\s+"
    r"([A-Z][A-Za-z0-9&.-]*(?:\s+[A-Z][A-Za-z0-9&.-]*){0,2})",
)


def _ar_negated(text: str, match: re.Match, window: int = 30) -> bool:
    """Arabic reads right to left, but the string is stored left to right, so the
    qualifier still precedes the verb in index order."""
    return bool(_AR_NEGATION_RE.search(text[max(0, match.start() - window):match.start()]))


class HeuristicExtractor:
    """
    The offline path, and the one CI measures.

    Rules and regexes, no model. It exists because the connector's default LLM
    provider is the offline stub: a firm evaluating MARSAD without standing up a
    sovereign model still gets working intake, and the test suite gets an extractor
    whose accuracy is a fixed number rather than whatever a model did that morning.

    It is weaker than a model on prose and says so — inferred fields carry lower
    confidence and land in front of the analyst, which is the correct failure mode
    for a component whose output a human confirms anyway.
    """

    name = "heuristic-v1"

    def propose(self, narrative: str) -> dict[str, TrackedField]:
        """
        Read the narrative in whichever language(s) it is written in.

        The text is normalised once, here, and every pattern below matches against
        the normalised form while every span shown back to the analyst is resolved to
        the raw form. Language selects which cue tables run — never whether to
        normalise, which is unconditional.
        """
        doc = normalise_tracked(narrative or "")
        lang = detect_language(narrative or "")
        return {
            "severity": self._severity(doc, lang),
            "category": self._category(doc, lang),
            "affected_services": self._services(doc, lang),
            "third_party_dependencies": self._third_parties(doc, lang),
            "indicators": self._indicators(doc),
            "techniques": self._techniques(doc, lang),
            "detected_at": self._detected_at(doc),
        }

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _ar_evidence(doc: NormalisedText, match: re.Match) -> str:
        """The analyst's own words for a match found in normalised text."""
        return doc.raw_excerpt(match.start(), match.end()) or match.group(0)

    # -- fields -------------------------------------------------------------

    def _severity(self, doc: NormalisedText, lang: Language) -> TrackedField:
        """
        An explicitly stated severity always beats an inferred one, in either
        language. That is what fixes the code-switched case this was written for:
        "الأثر: moderate" is the analyst stating MEDIUM, and it must not lose to an
        English impact word elsewhere in the sentence.
        """
        candidates: list[tuple[int, str, str, float]] = []   # (raw pos, band, evidence, conf)

        stated_en = _SEVERITY_EXPLICIT.search(doc.raw)
        if stated_en:
            word = next(g for g in stated_en.groups() if g)
            candidates.append(
                (stated_en.start(), _EXPLICIT_TO_BAND[word.lower()], stated_en.group(0), 0.9)
            )

        if has_arabic(doc.raw):
            stated_ar = _AR_SEVERITY_RE.search(doc.text)
            if stated_ar:
                word = stated_ar.group(1).lower()
                band = _AR_TO_BAND.get(word) or _EXPLICIT_TO_BAND.get(word)
                if band:
                    span = doc.to_raw_span(stated_ar.start(), stated_ar.end())
                    candidates.append(
                        (span[0] if span else 0, band, self._ar_evidence(doc, stated_ar), 0.9)
                    )

        if candidates:
            _, band, evidence, conf = min(candidates, key=lambda c: c[0])
            return _field("severity", band, conf, doc.raw, evidence)

        for band, pattern, conf in _SEVERITY_CUES:
            m = re.search(pattern, doc.raw, re.IGNORECASE)
            if m:
                return _field("severity", band, conf, doc.raw, m.group(0))

        if has_arabic(doc.raw):
            for band, words, conf in AR_SEVERITY_INFERRED:
                m = re.search(_ar_alt(words), doc.text)
                if m and not _ar_negated(doc.text, m):
                    return _field("severity", band, conf, doc.raw, self._ar_evidence(doc, m))

        return _field("severity", None, 0.0, doc.raw, None)

    def _category(self, doc: NormalisedText, lang: Language) -> TrackedField:
        """
        Both tables are ordered most-distinctive first and mirror each other, so the
        lower table index is the more specific claim and wins. Position breaks a tie.
        A vendor named in passing must not outrank the incident's own class in either
        language.
        """
        best: tuple[int, int, str, str, float] | None = None   # (rank, pos, cat, ev, conf)

        for rank, (cat, pattern, conf) in enumerate(_CATEGORY_CUES):
            for m in re.finditer(pattern, doc.raw, re.IGNORECASE):
                if _negated(doc.raw, m):
                    continue
                best = (rank, m.start(), cat, m.group(0), conf)
                break
            if best:
                break

        if has_arabic(doc.raw):
            for rank, (cat, words, conf) in enumerate(AR_CATEGORY_CUES):
                if best and rank >= best[0]:
                    break
                m = re.search(_ar_alt(words), doc.text)
                if m and not _ar_negated(doc.text, m):
                    span = doc.to_raw_span(m.start(), m.end())
                    best = (rank, span[0] if span else 0, cat,
                            self._ar_evidence(doc, m), conf)
                    break

        if best is None:
            return _field("category", None, 0.0, doc.raw, None)
        return _field("category", best[2], best[4], doc.raw, best[3])

    def _services(self, doc: NormalisedText, lang: Language) -> TrackedField:
        """
        Arabic service names resolve to the same canonical English labels as the
        English cues. One structured vocabulary regardless of reporting language —
        otherwise the same outage reads as two different services depending on who
        typed it up.
        """
        found: list[str] = []
        first: tuple[int, str] | None = None
        low = doc.raw.lower()

        for cue in _SERVICE_CUES:
            at = low.find(cue)
            if at >= 0:
                found.append(cue)
                if first is None or at < first[0]:
                    first = (at, doc.raw[at:at + len(cue)])

        if has_arabic(doc.raw):
            for cue, canonical in AR_SERVICE_CUES:
                m = re.search(re.escape(cue), doc.text)
                if not m:
                    continue
                if canonical not in found:
                    found.append(canonical)
                span = doc.to_raw_span(m.start(), m.end())
                if span and (first is None or span[0] < first[0]):
                    first = (span[0], self._ar_evidence(doc, m))

        found = [s for s in found if not any(s != o and s in o for o in found)]
        return _field("affected_services", sorted(set(found)) or None,
                      0.7 if found else 0.0, doc.raw, first[1] if first else None)

    def _third_parties(self, doc: NormalisedText, lang: Language) -> TrackedField:
        names: list[str] = []
        evidence = None

        for m in _THIRD_PARTY_CUE.finditer(doc.raw):
            name = m.group(1).strip().rstrip(".")
            if name and name not in names:
                names.append(name)
                evidence = evidence or m.group(0)

        if has_arabic(doc.raw):
            # The vendor's own name is usually Latin even in Arabic prose, so match on
            # normalised text but take the name verbatim from the raw span.
            for m in _AR_THIRD_PARTY_RE.finditer(doc.text):
                span = doc.to_raw_span(m.start(1), m.end(1))
                name = (doc.raw[span[0]:span[1]] if span else m.group(1)).strip().rstrip(".")
                if name and name not in names:
                    names.append(name)
                    evidence = evidence or self._ar_evidence(doc, m)

        return _field("third_party_dependencies", names or None,
                      0.6 if names else 0.0, doc.raw, evidence)

    def _indicators(self, doc: NormalisedText) -> TrackedField:
        """
        Matched on RAW text, deliberately. Indicators are ASCII — addresses, domains,
        hashes, IBANs — and must be captured exactly as written so they canonicalise
        and tokenise to the same value at every institution. Normalisation would not
        change them, but reading them from the raw string removes any doubt that what
        we tokenise is what the analyst typed.
        """
        text = doc.raw
        found: list[dict[str, str]] = []
        claimed: list[tuple[int, int]] = []
        evidence = None
        for itype, pattern, _conf in _INDICATOR_RULES:
            for m in re.finditer(pattern, text):
                start, end = m.span()
                if any(start < ce and cs < end for cs, ce in claimed):
                    continue
                value = (m.group(1) if m.lastindex else m.group(0)).strip()
                value = value.rstrip(_TRAILING_PUNCTUATION)
                if not value:
                    continue
                claimed.append((start, end))
                found.append({"type": itype.value, "value": value})
                evidence = evidence or m.group(0)
        return _field("indicators", found or None, 0.9 if found else 0.0, text, evidence)

    def _techniques(self, doc: NormalisedText, lang: Language) -> TrackedField:
        """Techniques are a set, so both languages contribute and the union is taken."""
        found: list[str] = []
        evidence = None

        for tid, pattern in _TECHNIQUE_CUES:
            for m in re.finditer(pattern, doc.raw, re.IGNORECASE):
                if _negated(doc.raw, m) or tid in found:
                    continue
                found.append(tid)
                evidence = evidence or m.group(0)
                break

        if has_arabic(doc.raw):
            for tid, words in AR_TECHNIQUE_CUES:
                if tid in found:
                    continue
                m = re.search(_ar_alt(words), doc.text)
                if m and not _ar_negated(doc.text, m):
                    found.append(tid)
                    evidence = evidence or self._ar_evidence(doc, m)

        found = [t for t in found if not any(o.startswith(t + ".") for o in found)]
        return _field("techniques", sorted(found) or None, 0.7 if found else 0.0,
                      doc.raw, evidence)

    def _detected_at(self, doc: NormalisedText) -> TrackedField:
        """
        Read from raw text. Timestamps in these reports are written in Latin digits
        even in Arabic prose; Arabic-Indic numerals (٢٠٢٦) are NOT handled and would
        be reported as absent rather than misread, which is the safe direction for a
        field every regulatory clock starts from.
        """
        text = doc.raw
        for pattern, conf in _TIMESTAMPS:
            m = re.search(pattern, text)
            if not m:
                continue
            parsed = self._parse(m)
            if parsed:
                return _field("detected_at", parsed.isoformat(), conf, text, m.group(0))

        vague = _VAGUE_TIME.search(text)
        if vague:
            return _field("detected_at", None, 0.3, text, vague.group(0))

        if has_arabic(text):
            m = re.search(_ar_alt(AR_VAGUE_TIME), doc.text)
            if m:
                return _field("detected_at", None, 0.3, text, self._ar_evidence(doc, m))

        return _field("detected_at", None, 0.0, text, None)

    @staticmethod
    def _parse(m: re.Match) -> datetime | None:
        groups = [g for g in m.groups() if g]
        for candidate in (" ".join(groups), " ".join(reversed(groups))):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%dT%H:%M", "%Y-%m-%d", "%H:%M %Y-%m-%d",
                        "%d %B %Y %H:%M", "%d %b %Y %H:%M"):
                try:
                    return datetime.strptime(candidate.strip(), fmt).replace(tzinfo=timezone.utc)
                except ValueError:
                    continue
        return None


class ModelExtractor:
    """
    The sovereign-model path. Decoding is constrained to EXTRACTION_SCHEMA by the
    provider, so this is mapping and verification, not parsing.
    """

    name = "model-v1"

    def __init__(self, provider) -> None:
        self._provider = provider

    async def propose(self, narrative: str) -> dict[str, TrackedField]:
        raw = await self._provider.extract(narrative, EXTRACTION_SCHEMA)
        out: dict[str, TrackedField] = {}
        for name in EXTRACTED_FIELDS:
            cell = raw.get(name) or {}
            if not isinstance(cell, dict):
                cell = {}
            out[name] = _field(
                name,
                cell.get("value"),
                float(cell.get("confidence") or 0.0),
                narrative,
                cell.get("evidence"),
            )
        return out


class ExtractionAgent(Agent):
    """
    A2 as an addressable agent.

    PROPOSE_CONFIRM and `may_cross_boundary = False`. It produces a draft and
    nothing else: it cannot file, cannot submit, and cannot construct a boundary
    payload. Only A3 does that, and only from a ConfirmedIncident.
    """

    agent_id = "A2"
    autonomy = Autonomy.PROPOSE_CONFIRM
    may_cross_boundary = False

    def __init__(self, provider=None, budget=None) -> None:
        # The offline stub cannot produce this schema, so a connector without a
        # sovereign model configured uses the deterministic extractor rather than
        # pretending a model ran.
        from marsad_connector.llm.provider import StubProvider

        use_model = provider is not None and not isinstance(provider, StubProvider)
        self._model_extractor = ModelExtractor(provider) if use_model else None
        self._heuristic = HeuristicExtractor()
        self._extractor = self._model_extractor or self._heuristic
        self._is_model = use_model
        #: Optional ceiling on model calls. When it is spent, extraction degrades to
        #: the deterministic path rather than failing — a public demo must not become
        #: free compute, and an institution must never be unable to file an incident
        #: because someone else exhausted a quota. See llm/budget.py.
        self._budget = budget

    async def propose(
        self, narrative: str, *, analyst_notes: str | None = None, raw_email: str | None = None,
    ) -> ExtractionDraft:
        if not (narrative or "").strip():
            raise ValueError("nothing to extract: the narrative is empty")

        # Claim budget before the call, and fall back rather than fail if it is gone.
        use_model = self._is_model
        if use_model and self._budget is not None and not self._budget.try_spend():
            use_model = False

        fields = (
            await self._model_extractor.propose(narrative)
            if use_model
            else self._heuristic.propose(narrative)
        )
        extractor_name = self._model_extractor.name if use_model else self._heuristic.name
        draft = ExtractionDraft(
            draft_id=str(uuid.uuid4()),
            narrative=narrative,
            fields=fields,
            narrative_normalised=normalise_tracked(narrative).text,
            analyst_notes=analyst_notes,
            raw_email=raw_email,
            method=extractor_name,
            model_proposed=use_model,
            language=detect_language(narrative).value,
        )
        log.info(
            "a2.proposed draft=%s method=%s lang=%s needs_attention=%d missing=%d",
            draft.draft_id, draft.method, draft.language,
            len(draft.needs_attention), len(draft.missing),
        )
        return draft

    async def run(self, payload: dict) -> dict:
        draft = await self.propose(
            payload.get("narrative") or "",
            analyst_notes=payload.get("analyst_notes"),
            raw_email=payload.get("raw_email"),
        )
        return draft.as_dict()


__all__ = [
    "ALWAYS_REVIEW",
    "CONFIDENCE_RANGE",
    "CONFIDENCE_THRESHOLD",
    "EXTRACTED_FIELDS",
    "EXTRACTION_SCHEMA",
    "MAX_INDICATORS",
    "MAX_LOCAL_LIST_ITEMS",
    "MAX_TECHNIQUES",
    "ConfirmedIncident",
    "ExtractionAgent",
    "ExtractionDraft",
    "HeuristicExtractor",
    "IncidentCategory",
    "ModelExtractor",
    "TrackedField",
    "UnconfirmedExtractionError",
]
