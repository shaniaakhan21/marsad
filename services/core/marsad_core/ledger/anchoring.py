"""
Batches receipts, anchors them, and answers "has this record been changed?".

Only digests go in. A digest is SHA-256 over a payload containing a random submission id,
so it cannot be reversed by guessing and reveals nothing once the payload is purged.

Never on the critical path. Submissions are stored first and anchored later from a
background loop; if the ledger is down, batches wait as PENDING and retry, and nothing
about accepting a submission changes. The audit trail may lag. It must not block.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import sqlalchemy as sa
from marsad_contracts.digest import payload_digest
from pydantic import ValidationError
from sqlalchemy.orm import Session, sessionmaker

from marsad_core.db.models import AnchorBatch, AnchorLeaf, Submission
from marsad_core.db.session import session_scope
from marsad_core.ledger.backends import LedgerBackend, LedgerUnavailable
from marsad_core.ledger.merkle import inclusion_path, root_from_path, root_of

log = logging.getLogger("marsad.core.anchoring")

#: Receipts per batch. A reviewer may tune it; proofs grow with its logarithm.
MAX_BATCH_LEAVES = 4096


@dataclass(frozen=True)
class AnchorRun:
    batches_anchored: int
    receipts_anchored: int
    pending: int


class Anchorer:
    def __init__(self, factory: sessionmaker[Session], backend: LedgerBackend, store) -> None:
        self._factory = factory
        self._backend = backend
        self._store = store

    @property
    def backend(self) -> LedgerBackend:
        return self._backend

    def run_once(self) -> AnchorRun:
        """Retry anything PENDING, then batch whatever has arrived since."""
        self._batch_new_receipts()
        anchored = receipts = pending = 0
        with session_scope(self._factory) as session:
            waiting = [(b.batch_id, b.merkle_root, b.leaf_count) for b in session.scalars(
                sa.select(AnchorBatch).where(AnchorBatch.status == "PENDING")
                .order_by(AnchorBatch.batch_id)
            )]
        for batch_id, root, count in waiting:
            try:
                record = self._backend.anchor(root, count)
            except LedgerUnavailable as exc:
                log.warning("anchoring.ledger_unavailable batch=%d err=%s", batch_id, exc)
                pending += 1
                continue
            with session_scope(self._factory) as session:
                batch = session.get(AnchorBatch, batch_id)
                batch.status = "ANCHORED"
                batch.backend = self._backend.name
                batch.transaction = record.transaction
                batch.block = record.block
                batch.anchored_at = record.anchored_at
            anchored += 1
            receipts += count
        return AnchorRun(anchored, receipts, pending)

    def _batch_new_receipts(self) -> None:
        """The batch and its leaves are written together, before any ledger call."""
        with session_scope(self._factory) as session:
            anchored = sa.select(AnchorLeaf.submission_id)
            rows = session.execute(
                sa.select(Submission.submission_id, Submission.payload_digest)
                .where(Submission.payload_digest.is_not(None),
                       Submission.submission_id.not_in(anchored))
                .order_by(Submission.received_at, Submission.submission_id)
                .limit(MAX_BATCH_LEAVES)
            ).all()
            if not rows:
                return
            digests = [digest for _, digest in rows]
            batch = AnchorBatch(merkle_root=root_of(digests), leaf_count=len(digests),
                                status="PENDING")
            batch.leaves = [
                AnchorLeaf(submission_id=sid, payload_digest=digest, position=i)
                for i, (sid, digest) in enumerate(rows)
            ]
            session.add(batch)

    def status(self) -> dict:
        with session_scope(self._factory) as session:
            count = sa.select(sa.func.count()).select_from(AnchorBatch)
            total = session.scalar(count) or 0
            waiting = session.scalar(count.where(AnchorBatch.status == "PENDING")) or 0
        return {"backend": self._backend.name, "reduced_fidelity": self._backend.reduced_fidelity,
                "batches": int(total), "pending_batches": int(waiting)}

    def proof(self, receipt: str) -> dict | None:
        """
        Everything needed to check one receipt, and the result of checking it.

        `receipt` is a payload digest or an obligation receipt hash. Three independent
        checks, so a failure says what was altered: the stored record against its
        anchored digest, the digest against the batch's root, and the root against the
        ledger. Nothing about the submission's content or sender is returned.
        """
        with session_scope(self._factory) as session:
            row = session.scalar(
                sa.select(Submission)
                .where(sa.or_(Submission.payload_digest == receipt,
                              Submission.obligation_receipt_hash == receipt))
                .order_by(Submission.received_at).limit(1)
            )
            # An edited record no longer carries the digest it was anchored under, so
            # the anchored leaf has to be able to find it too.
            leaf = session.scalar(sa.select(AnchorLeaf).where(AnchorLeaf.payload_digest == receipt))
            if row is None and leaf is None:
                return None
            if leaf is None:
                leaf = session.scalar(
                    sa.select(AnchorLeaf).where(AnchorLeaf.submission_id == row.submission_id))
            if leaf is None:
                return {"receipt": receipt, "status": "NOT_YET_BATCHED", "verified": False}

            batch = leaf.batch
            leaves = sorted(batch.leaves, key=lambda x: x.position)
            digests = [x.payload_digest for x in leaves]
            digest, position, submission_id = leaf.payload_digest, leaf.position, leaf.submission_id
            root, status = batch.merkle_root, batch.status
            batch_id, backend = batch.batch_id, batch.backend
            transaction, block, anchored_at = batch.transaction, batch.block, batch.anchored_at

        path = inclusion_path(digests, position)
        record_unchanged = self._record_matches(submission_id, digest)
        in_batch = root_from_path(digest, path) == root
        on_ledger = False
        ledger_error = None
        if status == "ANCHORED" and backend != self._backend.name:
            # A false "not on ledger" would read as tampering. It is a migration.
            ledger_error = f"anchored on {backend}; this core now uses {self._backend.name}"
        elif status == "ANCHORED":
            try:
                on_ledger = self._backend.lookup(root) is not None
            except LedgerUnavailable as exc:
                ledger_error = str(exc)

        return {
            "receipt": receipt,
            "status": status,
            "payload_digest": digest,
            "merkle_root": root,
            "batch_id": batch_id,
            "position": position,
            "path": [step.as_dict() for step in path],
            "ledger": {
                "backend": backend, "transaction": transaction, "block": block,
                "anchored_at": anchored_at.isoformat() if anchored_at else None,
                "reduced_fidelity": self._backend.reduced_fidelity,
                "error": ledger_error,
            },
            "checks": {
                "record_unchanged": record_unchanged,
                "included_in_batch": in_batch,
                "root_on_ledger": on_ledger,
            },
            "verified": record_unchanged and in_batch and on_ledger,
        }

    def _record_matches(self, submission_id: str, anchored_digest: str) -> bool:
        """Rebuild the payload from today's rows and compare it with what was anchored."""
        try:
            rebuilt = self._store.reconstruct(submission_id)
        except (ValidationError, ValueError):
            return False  # rows edited into something that is no longer a valid payload
        if rebuilt is None:
            return False
        return payload_digest(rebuilt[0]) == anchored_digest


__all__ = ["MAX_BATCH_LEAVES", "AnchorRun", "Anchorer"]
