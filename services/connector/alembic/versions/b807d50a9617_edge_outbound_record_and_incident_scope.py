"""edge: the record of what left, and the incident fields A4 reads

Revision ID: b807d50a9617
Revises: dad425257b81
Create Date: 2026-09-22 10:00:00.000000

Two changes, both about the store remembering what it was told:

* `outbound_submissions` and `submission_attempts` — the institution's append-only
  record of every payload sent to the core and every attempt to deliver it. Kept, not
  expired: none of it is free text, and it is what answers "what did we disclose?"
  after the narrative is gone.
* `local_incidents.jurisdictions` and `.essential_service_affected` — previously
  accepted by the API and dropped on write, so A4 resolved every stored incident
  against the institution's configured defaults instead of what the analyst filed.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'b807d50a9617'
down_revision = 'dad425257b81'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('local_incidents', schema='edge') as batch:
        batch.add_column(sa.Column('jurisdictions', sa.JSON(), nullable=False,
                                   server_default='[]'))
        batch.add_column(sa.Column('essential_service_affected', sa.Boolean(), nullable=True))

    op.create_table('outbound_submissions',
    sa.Column('submission_id', sa.String(length=64), nullable=False),
    sa.Column('incident_id', sa.String(length=64), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('payload_digest', sa.String(length=64), nullable=False),
    sa.Column('tokeniser_scheme', sa.String(length=64), nullable=False),
    sa.Column('incident_source', sa.String(length=32), nullable=False),
    sa.Column('confirmed_by', sa.String(length=128), nullable=True),
    sa.Column('built_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('submission_id', name=op.f('pk_outbound_submissions')),
    schema='edge'
    )
    op.create_index(op.f('ix_edge_outbound_submissions_incident_id'), 'outbound_submissions',
                    ['incident_id'], unique=False, schema='edge')
    op.create_index(op.f('ix_edge_outbound_submissions_built_at'), 'outbound_submissions',
                    ['built_at'], unique=False, schema='edge')

    op.create_table('submission_attempts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('submission_id', sa.String(length=64), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('http_status', sa.Integer(), nullable=True),
    sa.Column('core_digest', sa.String(length=64), nullable=True),
    sa.Column('core_response', sa.JSON(), nullable=True),
    sa.Column('error', sa.String(length=500), nullable=True),
    sa.ForeignKeyConstraint(['submission_id'], ['edge.outbound_submissions.submission_id'],
                            name=op.f('fk_submission_attempts_submission_id')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_submission_attempts')),
    schema='edge'
    )
    op.create_index(op.f('ix_edge_submission_attempts_submission_id'), 'submission_attempts',
                    ['submission_id'], unique=False, schema='edge')


def downgrade() -> None:
    op.drop_index(op.f('ix_edge_submission_attempts_submission_id'),
                  table_name='submission_attempts', schema='edge')
    op.drop_table('submission_attempts', schema='edge')
    op.drop_index(op.f('ix_edge_outbound_submissions_built_at'),
                  table_name='outbound_submissions', schema='edge')
    op.drop_index(op.f('ix_edge_outbound_submissions_incident_id'),
                  table_name='outbound_submissions', schema='edge')
    op.drop_table('outbound_submissions', schema='edge')
    with op.batch_alter_table('local_incidents', schema='edge') as batch:
        batch.drop_column('essential_service_affected')
        batch.drop_column('jurisdictions')
