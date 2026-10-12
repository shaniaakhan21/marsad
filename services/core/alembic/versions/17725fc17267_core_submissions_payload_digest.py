"""core: record the digest of every payload as received

Revision ID: 17725fc17267
Revises: a7e459274457
Create Date: 2026-09-22 10:00:00.000000

The digest is derived from columns the core already holds, so this adds nothing the
boundary contract does not already permit. Nullable, because rows received before it
existed have no recorded digest and inventing one after the fact would claim a receipt
that never happened.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = '17725fc17267'
down_revision = 'a7e459274457'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('submissions', schema='core') as batch:
        batch.add_column(sa.Column('payload_digest', sa.String(length=64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('submissions', schema='core') as batch:
        batch.drop_column('payload_digest')
