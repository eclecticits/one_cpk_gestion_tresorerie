"""Réquisition à décaissement progressif : ordres de décaissement

- requisitions.decaissement_progressif (bool)
- table ordres_decaissement (tranches autorisées par le demandeur, payées par la caisse)
- permission can_authorize_disbursement (accordée aux rôles disposant de 'requisitions')

Revision ID: 20260719_decaissement_progressif
Revises: 20260704_hr_function_fields
Create Date: 2026-07-19
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260719_decaissement_progressif"
down_revision = "20260704_hr_function_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "requisitions",
        sa.Column("decaissement_progressif", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "ordres_decaissement",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "requisition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requisitions.id", ondelete="CASCADE"),
            nullable=True,  # NULL = ordre de sortie directe (sans réquisition)
            index=True,
        ),
        sa.Column("numero_ordre", sa.String(length=50), nullable=False, index=True),
        sa.Column("beneficiaire", sa.String(length=200), nullable=False),
        sa.Column("montant", sa.Numeric(14, 2), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="AUTORISE", index=True),
        sa.Column("autorise_par", postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column("autorise_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paye_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("paye_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "sortie_fonds_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sorties_fonds.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("annule_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("annule_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("motif_annulation", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("montant > 0", name="ck_ordres_decaissement_montant_positif"),
        sa.CheckConstraint("statut IN ('AUTORISE','PAYE','ANNULE')", name="ck_ordres_decaissement_statut"),
        sa.CheckConstraint("devise IN ('USD','CDF')", name="ck_ordres_decaissement_devise"),
        sa.UniqueConstraint("organisation_id", "numero_ordre", name="uq_ordres_decaissement_org_numero"),
    )

    op.execute(
        """
        INSERT INTO permissions (code, description, created_at)
        VALUES (
            'can_authorize_disbursement',
            'Autoriser les ordres de décaissement (réquisition à décaissement progressif)',
            NOW()
        )
        ON CONFLICT (code) DO NOTHING;
        """
    )
    # Accorder aux rôles disposant déjà du module réquisitions
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT DISTINCT rp.role_id, new_perm.id
        FROM role_permissions rp
        JOIN permissions source_perm
          ON source_perm.id = rp.permission_id
         AND source_perm.code = 'requisitions'
        JOIN permissions new_perm
          ON new_perm.code = 'can_authorize_disbursement'
        ON CONFLICT DO NOTHING;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id IN (SELECT id FROM permissions WHERE code = 'can_authorize_disbursement');
        """
    )
    op.execute("DELETE FROM permissions WHERE code = 'can_authorize_disbursement';")
    op.drop_table("ordres_decaissement")
    op.drop_column("requisitions", "decaissement_progressif")
