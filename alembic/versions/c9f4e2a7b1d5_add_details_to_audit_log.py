"""add details to audit log

Revision ID: c9f4e2a7b1d5
Revises: a7d3f8c1b2e9
Create Date: 2026-08-30 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c9f4e2a7b1d5'
down_revision = 'a7d3f8c1b2e9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'content_audit_logs',
        sa.Column('details', sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('content_audit_logs', 'details')
