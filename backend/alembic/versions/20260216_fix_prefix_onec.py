"""fix existing document prefixes to ONEC

Revision ID: 20260216_fix_prefix_onec
Revises: 20260216_recu_numero_prefix_onec
Create Date: 2026-02-16
"""

from alembic import op

revision = "20260216_fix_prefix_onec"
down_revision = "20260216_recu_numero_prefix_onec"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE public.requisitions
        SET reference_numero = REPLACE(reference_numero, '-ONE-CPK-', '-ONEC-CPK-')
        WHERE reference_numero LIKE '%-ONE-CPK-%';
        """
    )
    op.execute(
        """
        UPDATE public.remboursements_transport
        SET reference_numero = REPLACE(reference_numero, '-ONE-CPK-', '-ONEC-CPK-')
        WHERE reference_numero LIKE '%-ONE-CPK-%';
        """
    )
    op.execute(
        """
        UPDATE public.sorties_fonds
        SET reference_numero = REPLACE(reference_numero, '-ONE-CPK-', '-ONEC-CPK-')
        WHERE reference_numero LIKE '%-ONE-CPK-%';
        """
    )
    op.execute(
        """
        UPDATE public.encaissements
        SET numero_recu = REPLACE(numero_recu, '-ONE-CPK-', '-ONEC-CPK-')
        WHERE numero_recu LIKE '%-ONE-CPK-%';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE public.requisitions
        SET reference_numero = REPLACE(reference_numero, '-ONEC-CPK-', '-ONE-CPK-')
        WHERE reference_numero LIKE '%-ONEC-CPK-%';
        """
    )
    op.execute(
        """
        UPDATE public.remboursements_transport
        SET reference_numero = REPLACE(reference_numero, '-ONEC-CPK-', '-ONE-CPK-')
        WHERE reference_numero LIKE '%-ONEC-CPK-%';
        """
    )
    op.execute(
        """
        UPDATE public.sorties_fonds
        SET reference_numero = REPLACE(reference_numero, '-ONEC-CPK-', '-ONE-CPK-')
        WHERE reference_numero LIKE '%-ONEC-CPK-%';
        """
    )
    op.execute(
        """
        UPDATE public.encaissements
        SET numero_recu = REPLACE(numero_recu, '-ONEC-CPK-', '-ONE-CPK-')
        WHERE numero_recu LIKE '%-ONEC-CPK-%';
        """
    )
