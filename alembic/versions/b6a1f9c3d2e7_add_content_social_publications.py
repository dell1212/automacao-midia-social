"""add content_social_publications table

Revision ID: b6a1f9c3d2e7
Revises: 574ed629fa1f
Create Date: 2026-08-28 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
import sqlmodel


revision = 'b6a1f9c3d2e7'
down_revision = '574ed629fa1f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'content_social_publications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('content_piece_id', sa.Integer(), nullable=False),
        sa.Column('social_account_id', sa.Integer(), nullable=False),
        sa.Column('platform', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            'status',
            sa.Enum('queued', 'running', 'retrying', 'succeeded', 'failed', name='content_social_publication_status'),
            nullable=False,
        ),
        sa.Column('attempt_count', sa.Integer(), nullable=False),
        sa.Column('max_attempts', sa.Integer(), nullable=False),
        sa.Column('publication_cycle', sa.Integer(), nullable=False),
        sa.Column('next_run_at', sa.DateTime(), nullable=True),
        sa.Column('platform_post_id', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('platform_post_url', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('error_code', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('error_message', sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column('request_payload', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['content_tenants.id']),
        sa.ForeignKeyConstraint(['client_id'], ['content_clients.id']),
        sa.ForeignKeyConstraint(['content_piece_id'], ['content_pieces.id']),
        sa.ForeignKeyConstraint(['social_account_id'], ['content_social_accounts.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'content_piece_id', 'social_account_id',
            name='uq_content_social_publications_piece_account',
        ),
    )
    op.create_index(
        op.f('ix_content_social_publications_tenant_id'),
        'content_social_publications', ['tenant_id'], unique=False,
    )
    op.create_index(
        op.f('ix_content_social_publications_client_id'),
        'content_social_publications', ['client_id'], unique=False,
    )
    op.create_index(
        op.f('ix_content_social_publications_content_piece_id'),
        'content_social_publications', ['content_piece_id'], unique=False,
    )
    op.create_index(
        op.f('ix_content_social_publications_social_account_id'),
        'content_social_publications', ['social_account_id'], unique=False,
    )
    # Dispatcher claim query filters on (status, next_run_at) together —
    # a composite index keeps that scan cheap as the table grows.
    op.create_index(
        'ix_content_social_publications_status_next_run_at',
        'content_social_publications', ['status', 'next_run_at'], unique=False,
    )
    op.add_column('content_pieces', sa.Column('publication_summary', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('content_pieces', 'publication_summary')
    op.drop_index(
        'ix_content_social_publications_status_next_run_at',
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_social_account_id'),
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_content_piece_id'),
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_client_id'),
        table_name='content_social_publications',
    )
    op.drop_index(
        op.f('ix_content_social_publications_tenant_id'),
        table_name='content_social_publications',
    )
    op.drop_table('content_social_publications')
    sa.Enum(name='content_social_publication_status').drop(op.get_bind(), checkfirst=True)
