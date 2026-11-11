"""edge: impact assessment on a local incident

Revision ID: f5a8d3c2b610
Revises: c4f1a2d7e901
Create Date: 2026-11-10 14:00:00.000000

Bands are structural and kept. System names are free text and expire with the narrative.
Neither is on the boundary contract.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = 'f5a8d3c2b610'
down_revision = 'c4f1a2d7e901'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('local_incidents', schema='edge') as batch:
        batch.add_column(sa.Column('impact', sa.JSON(), nullable=True))
        batch.add_column(sa.Column('systems_affected', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('local_incidents', schema='edge') as batch:
        batch.drop_column('systems_affected')
        batch.drop_column('impact')
