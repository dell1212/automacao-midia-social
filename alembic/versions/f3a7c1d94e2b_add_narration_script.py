"""add narration_script to content_pieces and content_generation_templates

Revision ID: f3a7c1d94e2b
Revises: 8ef14d978a0e
Create Date: 2026-08-31 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3a7c1d94e2b'
down_revision = '8ef14d978a0e'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Spoken text for audio/video narration, distinct from generation_prompt
    # (which describes the visual). Nullable and additive: an existing piece
    # or template with no narration_script keeps falling back to
    # generation_prompt at generation time, exactly as it behaved before.
    op.add_column(
        'content_pieces', sa.Column('narration_script', sa.String(), nullable=True)
    )
    op.add_column(
        'content_generation_templates',
        sa.Column('narration_script', sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('content_generation_templates', 'narration_script')
    op.drop_column('content_pieces', 'narration_script')
