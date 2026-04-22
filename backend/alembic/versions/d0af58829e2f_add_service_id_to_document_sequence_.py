"""add_service_id_to_document_sequence_manual

Revision ID: d0af58829e2f
Revises: 20260421_enc_articles
Create Date: 2026-04-22 11:10:51.646919

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd0af58829e2f'
down_revision = '20260421_enc_articles'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add service_id column
    op.add_column('document_sequences', sa.Column('service_id', sa.Integer(), nullable=True))
    
    # Create foreign key
    op.create_foreign_key('fk_document_sequences_service_id', 'document_sequences', 'services', ['service_id'], ['id'], ondelete='CASCADE')
    
    # Create index
    op.create_index(op.f('ix_document_sequences_service_id'), 'document_sequences', ['service_id'], unique=False)
    
    # Handle the unique constraint
    # First drop old one
    op.drop_constraint('uq_doc_type_year_tenant', 'document_sequences', type_='unique')
    
    # Add new one including service_id
    op.create_unique_constraint('uq_doc_type_year_tenant_service', 'document_sequences', ['doc_type', 'year', 'tenant_id', 'service_id'])


def downgrade() -> None:
    op.drop_constraint('uq_doc_type_year_tenant_service', 'document_sequences', type_='unique')
    op.create_unique_constraint('uq_doc_type_year_tenant', 'document_sequences', ['doc_type', 'year', 'tenant_id'])
    op.drop_index(op.f('ix_document_sequences_service_id'), table_name='document_sequences')
    op.drop_constraint('fk_document_sequences_service_id', 'document_sequences', type_='foreignkey')
    op.drop_column('document_sequences', 'service_id')
