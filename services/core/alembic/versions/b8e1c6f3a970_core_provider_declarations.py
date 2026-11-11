"""core: declared dependencies and provider incidents

Revision ID: b8e1c6f3a970
Revises: e3b7c1d9a402
Create Date: 2026-11-11 09:00:00.000000

Pseudonyms, keyed tokens and closed vocabularies. No provider name or domain has a
column here, because neither crosses the boundary.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b8e1c6f3a970'
down_revision = 'e3b7c1d9a402'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'declared_dependencies',
        sa.Column('institution_ref', sa.String(length=64), nullable=False),
        sa.Column('provider_token', sa.String(length=64), nullable=False),
        sa.Column('substitutability', sa.String(length=16), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('declared_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('institution_ref', 'provider_token',
                                name=op.f('pk_declared_dependencies')),
        schema='core',
    )
    op.create_index(op.f('ix_core_declared_dependencies_provider_token'),
                    'declared_dependencies', ['provider_token'], unique=False, schema='core')
    op.create_table(
        'declaration_sequences',
        sa.Column('institution_ref', sa.String(length=64), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('institution_ref', name=op.f('pk_declaration_sequences')),
        schema='core',
    )
    op.create_table(
        'provider_incidents',
        sa.Column('declaration_id', sa.String(length=64), nullable=False),
        sa.Column('institution_ref', sa.String(length=64), nullable=False),
        sa.Column('provider_token', sa.String(length=64), nullable=False),
        sa.Column('severity_band', sa.String(length=16), nullable=False),
        sa.Column('ts_bucket', sa.DateTime(timezone=True), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('declaration_id', name=op.f('pk_provider_incidents')),
        schema='core',
    )
    op.create_index(op.f('ix_core_provider_incidents_provider_token'), 'provider_incidents',
                    ['provider_token'], unique=False, schema='core')


def downgrade() -> None:
    op.drop_table('provider_incidents', schema='core')
    op.drop_table('declaration_sequences', schema='core')
    op.drop_table('declared_dependencies', schema='core')
