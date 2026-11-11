"""edge: declared providers, the record of declarations, and provider alerts

Revision ID: d2b7f0a8c514
Revises: a9c6e4f1d723
Create Date: 2026-11-11 09:00:00.000000

Provider names and domains are held here and nowhere else; only a token of the domain
crosses. Every declaration is recorded before it leaves, like every submission.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'd2b7f0a8c514'
down_revision = 'a9c6e4f1d723'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'provider_dependencies',
        sa.Column('domain', sa.String(length=253), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('substitutability', sa.String(length=16), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('domain', name=op.f('pk_provider_dependencies')),
        schema='edge',
    )
    op.create_table(
        'outbound_declarations',
        sa.Column('declaration_id', sa.String(length=64), nullable=False),
        sa.Column('kind', sa.String(length=32), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('payload_digest', sa.String(length=64), nullable=False),
        sa.Column('tokeniser_scheme', sa.String(length=64), nullable=False),
        sa.Column('declared_by', sa.String(length=128), nullable=False),
        sa.Column('built_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('core_digest', sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint('declaration_id', name=op.f('pk_outbound_declarations')),
        schema='edge',
    )
    op.create_table(
        'received_provider_alerts',
        sa.Column('alert_id', sa.String(length=64), nullable=False),
        sa.Column('provider_token', sa.String(length=64), nullable=False),
        sa.Column('severity_band', sa.String(length=16), nullable=False),
        sa.Column('ts_bucket', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('alert_id', name=op.f('pk_received_provider_alerts')),
        schema='edge',
    )


def downgrade() -> None:
    op.drop_table('received_provider_alerts', schema='edge')
    op.drop_table('outbound_declarations', schema='edge')
    op.drop_table('provider_dependencies', schema='edge')
