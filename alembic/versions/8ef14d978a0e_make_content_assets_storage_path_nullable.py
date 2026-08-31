"""make content_assets.storage_path nullable

Revision ID: 8ef14d978a0e
Revises: c9f4e2a7b1d5
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = '8ef14d978a0e'
down_revision = 'c9f4e2a7b1d5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # An asset registered from an external URL (avatar reuse: no upload, no
    # storage object of our own) has nothing to put here.
    op.alter_column(
        'content_assets', 'storage_path',
        existing_type=sa.String(), nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        'content_assets', 'storage_path',
        existing_type=sa.String(), nullable=False,
    )
