"""revert requisition statuses to 2-step validation

Revision ID: 20260224_req_status_2step
Revises: 20260224_req_status_met
Create Date: 2026-02-24 13:30:00.000000
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "20260224_req_status_2step"
down_revision = "20260224_req_status_met"
branch_labels = None
depends_on = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute(
        """
        UPDATE requisitions
        SET status = 'APPROUVE_COMMISSION'
        WHERE UPPER(status) = 'EN_ATTENTE';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'VALIDE_TECHNIQUE'
        WHERE UPPER(status) = 'AUTORISEE';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'DECAISSE'
        WHERE UPPER(status) = 'PAYEE';
        """
    )
    op.execute(
        """
        UPDATE requisitions
        SET status = 'REJETTE'
        WHERE UPPER(status) = 'REJETEE';
        """
    )
