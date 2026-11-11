"""edge: notices received from the core

Revision ID: a9c6e4f1d723
Revises: f5a8d3c2b610
Create Date: 2026-11-10 18:00:00.000000

What the core told this firm about matches. Peer counts and public technique IDs; nothing
the firm wrote and nothing about which peers.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'a9c6e4f1d723'
down_revision = 'f5a8d3c2b610'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'received_notices',
        sa.Column('notice_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('peer_count', sa.Integer(), nullable=False),
        sa.Column('indicator_type', sa.String(length=16), nullable=True),
        sa.Column('shared_techniques', sa.JSON(), nullable=False),
        sa.Column('similarity', sa.Float(), nullable=True),
        sa.Column('campaign_id', sa.String(length=64), nullable=True),
        sa.Column('detected_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('notice_id', name=op.f('pk_received_notices')),
        schema='edge',
    )
    op.create_index(op.f('ix_edge_received_notices_detected_at'), 'received_notices',
                    ['detected_at'], unique=False, schema='edge')


def downgrade() -> None:
    op.drop_index(op.f('ix_edge_received_notices_detected_at'), table_name='received_notices',
                  schema='edge')
    op.drop_table('received_notices', schema='edge')
