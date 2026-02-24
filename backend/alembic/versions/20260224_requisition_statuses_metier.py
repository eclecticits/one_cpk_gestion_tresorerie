"""harmonize requisition statuses to business terms

Revision ID: 20260224_req_status_met
Revises: 20260224_requisition_signing
Create Date: 2026-02-24
"""

from __future__ import annotations

from alembic import op


revision = "20260224_req_status_met"
down_revision = "20260224_requisition_signing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE requisitions
        SET status = 'EN_ATTENTE_COMMISSION'
        WHERE UPPER(status) IN ('EN_ATTENTE', 'BROUILLON', 'A_VALIDER');
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'APPROUVE_COMMISSION'
        WHERE UPPER(status) IN ('APPROUVE_COMMISSION');
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'VALIDE_TECHNIQUE'
        WHERE UPPER(status) IN ('AUTORISEE', 'VALIDEE', 'APPROUVEE');
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'DECAISSE'
        WHERE UPPER(status) IN ('PAYEE');
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'REJETTE'
        WHERE UPPER(status) IN ('REJETEE');
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE requisitions
        SET status = 'EN_ATTENTE'
        WHERE UPPER(status) = 'EN_ATTENTE_COMMISSION';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'EN_ATTENTE'
        WHERE UPPER(status) = 'APPROUVE_COMMISSION';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'AUTORISEE'
        WHERE UPPER(status) = 'VALIDE_TECHNIQUE';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'PAYEE'
        WHERE UPPER(status) = 'DECAISSE';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'REJETEE'
        WHERE UPPER(status) = 'REJETTE';
        """
    )
