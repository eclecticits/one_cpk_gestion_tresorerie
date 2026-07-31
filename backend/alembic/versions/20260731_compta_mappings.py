"""Module Comptabilité — Lot 2 : mappings et idempotence de génération

Ajoute :
- `compta_mapping_poste_budgetaire` : poste budgétaire → compte comptable
  (charge ou produit selon le sens du poste).
- `compta_mapping_compte_bancaire` : compte bancaire/caisse → compte
  comptable (512x ou 571).
- Contrainte d'unicité sur l'origine des écritures automatiques
  (organisation_id, module_origine, type_origine, objet_origine_id) :
  garantit qu'un même fait générateur (encaissement, sortie de fonds...) ne
  produit jamais deux écritures, même en cas de rejeu (idempotence, cf. §4.2
  du dossier d'architecture).

Revision ID: 20260731_compta_mappings
Revises: 20260731_compta_rbac
Create Date: 2026-07-31
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260731_compta_mappings"
down_revision = "20260731_compta_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "compta_mapping_poste_budgetaire",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column(
            "budget_poste_id", sa.Integer(), sa.ForeignKey("budget_postes.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "compte_id", sa.Integer(), sa.ForeignKey("compta_comptes.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "budget_poste_id", name="uq_compta_mapping_poste_budgetaire"
        ),
    )

    op.create_table(
        "compta_mapping_compte_bancaire",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column(
            "compte_bancaire_id", sa.Integer(), sa.ForeignKey("comptes_bancaires.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column(
            "compte_id", sa.Integer(), sa.ForeignKey("compta_comptes.id", ondelete="RESTRICT"),
            nullable=False, index=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint(
            "organisation_id", "compte_bancaire_id", name="uq_compta_mapping_compte_bancaire"
        ),
    )

    # Idempotence : NULL est autorisé (écritures manuelles, sans origine), mais
    # deux écritures ne peuvent jamais partager la même origine renseignée.
    op.create_index(
        "uq_compta_ecriture_origine_idempotence",
        "compta_ecritures",
        ["organisation_id", "module_origine", "type_origine", "objet_origine_id"],
        unique=True,
        postgresql_where=sa.text(
            "module_origine IS NOT NULL AND type_origine IS NOT NULL AND objet_origine_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_compta_ecriture_origine_idempotence", table_name="compta_ecritures")
    op.drop_table("compta_mapping_compte_bancaire")
    op.drop_table("compta_mapping_poste_budgetaire")
