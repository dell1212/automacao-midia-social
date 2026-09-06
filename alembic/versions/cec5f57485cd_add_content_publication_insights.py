"""add content_publication_insights

Revision ID: cec5f57485cd
Revises: b72e5d419a83
Create Date: 2026-09-05 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'cec5f57485cd'
down_revision = 'b72e5d419a83'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # One snapshot per (publication, collection) — never overwritten. A
    # failure is also a row: a collection error records null metrics with
    # error_code filled in, so a broken token stays visible in the same
    # table instead of turning into silence.
    op.create_table(
        'content_publication_insights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('tenant_id', sa.Integer(), nullable=False),
        sa.Column('client_id', sa.Integer(), nullable=False),
        sa.Column('content_piece_id', sa.Integer(), nullable=False),
        sa.Column('publication_id', sa.Integer(), nullable=False),
        sa.Column('social_account_id', sa.Integer(), nullable=False),
        sa.Column('platform', sa.String(), nullable=False),
        sa.Column('publication_cycle', sa.Integer(), nullable=False),
        sa.Column('collected_at', sa.DateTime(), nullable=False),
        sa.Column('reach', sa.Integer(), nullable=True),
        sa.Column('impressions', sa.Integer(), nullable=True),
        sa.Column('likes', sa.Integer(), nullable=True),
        sa.Column('comments', sa.Integer(), nullable=True),
        sa.Column('shares', sa.Integer(), nullable=True),
        sa.Column('raw', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['tenant_id'], ['content_tenants.id']),
        sa.ForeignKeyConstraint(['client_id'], ['content_clients.id']),
        sa.ForeignKeyConstraint(['content_piece_id'], ['content_pieces.id']),
        sa.ForeignKeyConstraint(
            ['publication_id'], ['content_social_publications.id']
        ),
        sa.ForeignKeyConstraint(
            ['social_account_id'], ['content_social_accounts.id']
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_content_publication_insights_tenant_id'),
        'content_publication_insights', ['tenant_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_client_id'),
        'content_publication_insights', ['client_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_content_piece_id'),
        'content_publication_insights', ['content_piece_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_publication_id'),
        'content_publication_insights', ['publication_id'],
    )
    op.create_index(
        op.f('ix_content_publication_insights_social_account_id'),
        'content_publication_insights', ['social_account_id'],
    )
    # Composite: the collection worker reads "what was the last collection
    # for this publication" (publication_id, collected_at); the dashboard
    # reads "every collection for a tenant within a window" (tenant_id,
    # collected_at). An ascending index also serves ORDER BY ... DESC —
    # Postgres scans a B-tree backwards at no extra cost, with no need for an
    # explicit DESC index.
    op.create_index(
        'ix_content_publication_insights_pub_collected',
        'content_publication_insights', ['publication_id', 'collected_at'],
    )
    op.create_index(
        'ix_content_publication_insights_tenant_collected',
        'content_publication_insights', ['tenant_id', 'collected_at'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_content_publication_insights_tenant_collected',
        table_name='content_publication_insights',
    )
    op.drop_index(
        'ix_content_publication_insights_pub_collected',
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_social_account_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_publication_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_content_piece_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_client_id'),
        table_name='content_publication_insights',
    )
    op.drop_index(
        op.f('ix_content_publication_insights_tenant_id'),
        table_name='content_publication_insights',
    )
    op.drop_table('content_publication_insights')
