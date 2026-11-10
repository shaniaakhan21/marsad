"""edge: record every execution of the retention purge

Revision ID: c4f1a2d7e901
Revises: b807d50a9617
Create Date: 2026-11-10 09:00:00.000000

Counts and timestamps only. The purge existed before this table did; what did not exist
was any way to show it had actually run.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'c4f1a2d7e901'
down_revision = 'b807d50a9617'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'retention_runs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ran_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retention_days', sa.Integer(), nullable=False),
        sa.Column('incidents_redacted', sa.Integer(), nullable=False),
        sa.Column('provenance_rows_deleted', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_retention_runs')),
        schema='edge',
    )
    op.create_index(op.f('ix_edge_retention_runs_ran_at'), 'retention_runs', ['ran_at'],
                    unique=False, schema='edge')


def downgrade() -> None:
    op.drop_index(op.f('ix_edge_retention_runs_ran_at'), table_name='retention_runs', schema='edge')
    op.drop_table('retention_runs', schema='edge')
