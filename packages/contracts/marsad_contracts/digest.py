"""
One digest of a boundary payload, computed identically on both sides.

Why this exists. An institution's auditor, its counsel and the regulator will each
eventually ask the same question: *what exactly did this firm disclose, and does the
operator hold the same thing?* The connector records every payload before it sends
it; the core records every payload it accepts. Two records of one event are only
evidence if they can be compared without trusting either party, so each side stores
a digest of the payload, the core returns its digest to the sender, and a mismatch is
visible to both.

That only works if the two sides compute the digest the same way, which is why this
lives in the contracts package rather than being written twice. It is a function
*over* the boundary contract, not part of it: it adds no field and nothing crosses
because of it.

Canonical form, and the one normalisation it makes
--------------------------------------------------
Keys sorted, no insignificant whitespace, UTF-8. Every datetime is rendered in UTC,
and a datetime without a zone is read as UTC — the same reading A3 applies when it
buckets a detection time. This is not cosmetic. The same instant arrives as
`08:00+04:00` from a connector, comes back as `04:00+00:00` from Postgres, and until
the stores normalised it came back as a zoneless `08:00` from SQLite. A digest over
the rendered text would call those three different payloads; a digest over the
instant calls them one, which is the truth.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from marsad_contracts.boundary import IncidentSubmission

#: Named in every stored digest's provenance so a future change to the canonical form
#: is a new version rather than a silent disagreement between old and new records.
DIGEST_SCHEME = "sha256-canonical-json-utc-v1"


def _canonical(value: Any) -> Any:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical(v) for v in value]
    return value


def payload_digest(submission: IncidentSubmission) -> str:
    """Hex SHA-256 of the submission's canonical form. Same instant, same digest."""
    canonical = _canonical(submission.model_dump(mode="python"))
    blob = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


__all__ = ["DIGEST_SCHEME", "payload_digest"]
