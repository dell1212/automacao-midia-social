"""add content_piece_captions and calendar indexes

Revision ID: d51c8a3f7b60
Revises: f3a7c1d94e2b
Create Date: 2026-09-04 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'd51c8a3f7b60'
down_revision = 'f3a7c1d94e2b'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The text published with a piece's media. Until now the adapters used
    # generation_prompt — the image-generation prompt — as the visible post
    # body, and Instagram/Facebook sent no text at all.
    #
    # No backfill: captions.resolve_for_platform falls back to
    # generation_prompt when a piece has no rows here, so every existing piece
    # keeps behaving exactly as it does today until someone writes a caption.
    op.create_table(
        'content_piece_captions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('content_piece_id', sa.Integer(), nullable=False),
        # NULL is the shared "Global" row that every platform falls back to.
        sa.Column('platform', sa.String(), nullable=True),
        sa.Column('title', sa.String(), nullable=True),
        sa.Column('body', sa.String(), nullable=True),
        sa.Column('hashtags', postgresql.JSON(astext_type=sa.Text()), nullable=True),
        sa.Column('link_url', sa.String(), nullable=True),
        sa.Column(
            'is_override', sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['content_piece_id'], ['content_pieces.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'content_piece_id', 'platform', name='uq_content_piece_captions_piece_platform'
        ),
    )
    op.create_index(
        op.f('ix_content_piece_captions_content_piece_id'),
        'content_piece_captions',
        ['content_piece_id'],
    )

    # The calendar filters on scheduled_for over a date range, and the
    # scheduler's Pass 3 has always scanned the same column every 300s with no
    # index behind it.
    op.create_index(
        'ix_content_pieces_scheduled_for', 'content_pieces', ['scheduled_for']
    )
    op.create_index(
        'ix_content_pieces_campaign_scheduled',
        'content_pieces',
        ['campaign_id', 'scheduled_for'],
    )


def downgrade() -> None:
    op.drop_index('ix_content_pieces_campaign_scheduled', table_name='content_pieces')
    op.drop_index('ix_content_pieces_scheduled_for', table_name='content_pieces')
    op.drop_index(
        op.f('ix_content_piece_captions_content_piece_id'),
        table_name='content_piece_captions',
    )
    op.drop_table('content_piece_captions')
