"""add content_piece_targets

Revision ID: b72e5d419a83
Revises: d51c8a3f7b60
Create Date: 2026-09-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b72e5d419a83'
down_revision = 'd51c8a3f7b60'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-piece channel targeting. Additive and backfill-free: no target rows
    # still means "every active account of the client", which is exactly what
    # the scheduler did before this table existed.
    op.create_table(
        'content_piece_targets',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content_piece_id', sa.Integer(), nullable=False),
        sa.Column('social_account_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['content_piece_id'], ['content_pieces.id']),
        sa.ForeignKeyConstraint(['social_account_id'], ['content_social_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'content_piece_id',
            'social_account_id',
            name='uq_content_piece_targets_piece_account',
        ),
    )
    op.create_index(
        op.f('ix_content_piece_targets_content_piece_id'),
        'content_piece_targets',
        ['content_piece_id'],
    )
    op.create_index(
        op.f('ix_content_piece_targets_social_account_id'),
        'content_piece_targets',
        ['social_account_id'],
    )


def downgrade() -> None:
    op.drop_index(
        op.f('ix_content_piece_targets_social_account_id'),
        table_name='content_piece_targets',
    )
    op.drop_index(
        op.f('ix_content_piece_targets_content_piece_id'),
        table_name='content_piece_targets',
    )
    op.drop_table('content_piece_targets')
