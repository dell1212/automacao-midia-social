"""add is_active to config entities

Revision ID: a7d3f8c1b2e9
Revises: e4c2a9f1b6d3
Create Date: 2026-08-29 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7d3f8c1b2e9'
down_revision = 'e4c2a9f1b6d3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'content_clients',
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'content_avatars',
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        'content_generation_templates',
        sa.Column('is_active', sa.Boolean(), server_default=sa.true(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column('content_generation_templates', 'is_active')
    op.drop_column('content_avatars', 'is_active')
    op.drop_column('content_clients', 'is_active')
