"""core: Merkle batches and the local ledger chain

Revision ID: e3b7c1d9a402
Revises: 17725fc17267
Create Date: 2026-11-10 12:00:00.000000

Hashes, counts and timestamps. Every value is derived from columns the core already
holds, so this adds nothing the boundary contract does not already permit.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'e3b7c1d9a402'
down_revision = '17725fc17267'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'anchor_batches',
        sa.Column('batch_id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('merkle_root', sa.String(length=64), nullable=False),
        sa.Column('leaf_count', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('backend', sa.String(length=32), nullable=True),
        sa.Column('transaction', sa.String(length=80), nullable=True),
        sa.Column('block', sa.Integer(), nullable=True),
        sa.Column('anchored_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('batch_id', name=op.f('pk_anchor_batches')),
        schema='core',
    )
    op.create_index(op.f('ix_core_anchor_batches_merkle_root'), 'anchor_batches',
                    ['merkle_root'], unique=False, schema='core')
    op.create_table(
        'anchor_leaves',
        sa.Column('submission_id', sa.String(length=64), nullable=False),
        sa.Column('batch_id', sa.Integer(), nullable=False),
        sa.Column('payload_digest', sa.String(length=64), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['batch_id'], ['core.anchor_batches.batch_id'],
                                name=op.f('fk_anchor_leaves_batch_id')),
        sa.PrimaryKeyConstraint('submission_id', name=op.f('pk_anchor_leaves')),
        schema='core',
    )
    op.create_index(op.f('ix_core_anchor_leaves_batch_id'), 'anchor_leaves', ['batch_id'],
                    unique=False, schema='core')
    op.create_index(op.f('ix_core_anchor_leaves_payload_digest'), 'anchor_leaves',
                    ['payload_digest'], unique=False, schema='core')
    op.create_table(
        'local_ledger_entries',
        sa.Column('height', sa.Integer(), autoincrement=False, nullable=False),
        sa.Column('merkle_root', sa.String(length=64), nullable=False),
        sa.Column('leaf_count', sa.Integer(), nullable=False),
        sa.Column('previous_hash', sa.String(length=64), nullable=False),
        sa.Column('entry_hash', sa.String(length=64), nullable=False),
        sa.Column('anchored_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('height', name=op.f('pk_local_ledger_entries')),
        sa.UniqueConstraint('merkle_root', name=op.f('uq_local_ledger_entries_merkle_root')),
        schema='core',
    )


def downgrade() -> None:
    op.drop_table('local_ledger_entries', schema='core')
    op.drop_table('anchor_leaves', schema='core')
    op.drop_table('anchor_batches', schema='core')
