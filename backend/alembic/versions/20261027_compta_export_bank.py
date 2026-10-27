"""Historique des exports comptables et relevés bancaires.

Revision ID: 20261027_compta_export_bank
Revises: 20261024b_cdf_versements
Create Date: 2026-10-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261027_compta_export_bank"
down_revision = "20261024b_cdf_versements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # L'export opérationnel appartient aussi au comptable, au chef comptable et
    # au DAF. La permission existait mais seul le rôle CAC la recevait.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r
        CROSS JOIN permissions p
        WHERE r.code IN ('comptable', 'chef_comptable', 'daf')
          AND p.code = 'compta.export'
        ON CONFLICT DO NOTHING
        """
    )
    op.create_table(
        "compta_exports",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("type_export", sa.String(length=30), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("journal", sa.String(length=10), nullable=False),
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=True),
        sa.Column("devise", sa.String(length=3), nullable=False),
        sa.Column("date_debut", sa.Date(), nullable=False),
        sa.Column("date_fin", sa.Date(), nullable=False),
        sa.Column("nombre_ecritures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nombre_lignes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("total_credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("ecart", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("nom_fichier", sa.String(length=255), nullable=False),
        sa.Column("empreinte_fichier", sa.String(length=64), nullable=False),
        sa.Column("empreinte_selection", sa.String(length=64), nullable=False),
        sa.Column("genere_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reexport_de_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "type_export IN ('LOGICIEL_COMPTABLE','CONTROLE_BANCAIRE')",
            name="ck_compta_export_type",
        ),
        sa.CheckConstraint("format IN ('XLSX','CSV')", name="ck_compta_export_format"),
        sa.CheckConstraint("journal IN ('CAISSE','BANQUE','TOUS')", name="ck_compta_export_journal"),
        sa.CheckConstraint("devise IN ('USD','CDF')", name="ck_compta_export_devise"),
        sa.CheckConstraint("date_fin >= date_debut", name="ck_compta_export_dates"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["compte_bancaire_id"], ["comptes_bancaires.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reexport_de_id"], ["compta_exports.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compta_exports_organisation_id", "compta_exports", ["organisation_id"])
    op.create_index("ix_compta_exports_compte_bancaire_id", "compta_exports", ["compte_bancaire_id"])
    op.create_index("ix_compta_exports_genere_par", "compta_exports", ["genere_par"])
    op.create_index("ix_compta_exports_org_created", "compta_exports", ["organisation_id", "created_at"])
    op.create_index(
        "ix_compta_exports_org_fingerprint", "compta_exports", ["organisation_id", "empreinte_selection"]
    )

    op.create_table(
        "compta_export_ecritures",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("export_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ecriture_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["export_id"], ["compta_exports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["ecriture_id"], ["compta_ecritures.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("export_id", "ecriture_id", name="uq_compta_export_ecriture"),
    )
    op.create_index(
        "ix_compta_export_ecritures_org_ecriture",
        "compta_export_ecritures", ["organisation_id", "ecriture_id"],
    )
    op.create_index("ix_compta_export_ecritures_export_id", "compta_export_ecritures", ["export_id"])
    op.create_index("ix_compta_export_ecritures_ecriture_id", "compta_export_ecritures", ["ecriture_id"])

    op.create_table(
        "compta_releves_bancaires",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False),
        sa.Column("nom_fichier", sa.String(length=255), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("empreinte_fichier", sa.String(length=64), nullable=False),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="IMPORTE"),
        sa.Column("nombre_lignes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nombre_doublons", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nombre_propositions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nombre_rapprochees", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("importe_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("format IN ('XLSX','CSV')", name="ck_compta_releve_format"),
        sa.CheckConstraint(
            "statut IN ('IMPORTE','PARTIEL','RAPPROCHE')", name="ck_compta_releve_statut"
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["compte_bancaire_id"], ["comptes_bancaires.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organisation_id", "compte_bancaire_id", "empreinte_fichier",
            name="uq_compta_releve_fichier",
        ),
    )
    op.create_index("ix_compta_releves_bancaires_organisation_id", "compta_releves_bancaires", ["organisation_id"])
    op.create_index("ix_compta_releves_bancaires_compte_bancaire_id", "compta_releves_bancaires", ["compte_bancaire_id"])
    op.create_index("ix_compta_releves_bancaires_importe_par", "compta_releves_bancaires", ["importe_par"])
    op.create_index(
        "ix_compta_releves_org_compte_created",
        "compta_releves_bancaires", ["organisation_id", "compte_bancaire_id", "created_at"],
    )

    op.create_table(
        "compta_releve_bancaire_lignes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organisation_id", sa.Integer(), nullable=False),
        sa.Column("releve_import_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compte_bancaire_id", sa.Integer(), nullable=False),
        sa.Column("numero_ligne", sa.Integer(), nullable=False),
        sa.Column("date_operation", sa.Date(), nullable=False),
        sa.Column("date_valeur", sa.Date(), nullable=True),
        sa.Column("reference", sa.String(length=150), nullable=True),
        sa.Column("tiers", sa.String(length=255), nullable=True),
        sa.Column("libelle", sa.Text(), nullable=False),
        sa.Column("debit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("credit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("solde", sa.Numeric(18, 2), nullable=True),
        sa.Column("devise", sa.String(length=3), nullable=False),
        sa.Column("empreinte_ligne", sa.String(length=64), nullable=False),
        sa.Column("est_doublon", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("doublon_de_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("statut_rapprochement", sa.String(length=20), nullable=False, server_default="NON_RAPPROCHE"),
        sa.Column("operation_type", sa.String(length=30), nullable=True),
        sa.Column("operation_id", sa.String(length=64), nullable=True),
        sa.Column("score", sa.Numeric(5, 2), nullable=True),
        sa.Column("propositions", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("rapproche_par", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rapproche_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("debit >= 0 AND credit >= 0", name="ck_compta_releve_ligne_montants"),
        sa.CheckConstraint("NOT (debit > 0 AND credit > 0)", name="ck_compta_releve_ligne_sens"),
        sa.CheckConstraint("(debit + credit) > 0", name="ck_compta_releve_ligne_non_nulle"),
        sa.CheckConstraint(
            "statut_rapprochement IN ('NON_RAPPROCHE','PROPOSE','INCERTAIN','RAPPROCHE','IGNORE')",
            name="ck_compta_releve_ligne_statut",
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisations.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["releve_import_id"], ["compta_releves_bancaires.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["compte_bancaire_id"], ["comptes_bancaires.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["doublon_de_id"], ["compta_releve_bancaire_lignes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("releve_import_id", "numero_ligne", name="uq_compta_releve_ligne_numero"),
    )
    op.create_index("ix_compta_releve_bancaire_lignes_organisation_id", "compta_releve_bancaire_lignes", ["organisation_id"])
    op.create_index("ix_compta_releve_bancaire_lignes_releve_import_id", "compta_releve_bancaire_lignes", ["releve_import_id"])
    op.create_index("ix_compta_releve_bancaire_lignes_compte_bancaire_id", "compta_releve_bancaire_lignes", ["compte_bancaire_id"])
    op.create_index("ix_compta_releve_bancaire_lignes_date_operation", "compta_releve_bancaire_lignes", ["date_operation"])
    op.create_index("ix_compta_releve_bancaire_lignes_est_doublon", "compta_releve_bancaire_lignes", ["est_doublon"])
    op.create_index(
        "ix_compta_releve_lignes_org_compte_empreinte",
        "compta_releve_bancaire_lignes", ["organisation_id", "compte_bancaire_id", "empreinte_ligne"],
    )
    op.create_index(
        "ix_compta_releve_lignes_import_statut",
        "compta_releve_bancaire_lignes", ["releve_import_id", "statut_rapprochement"],
    )


def downgrade() -> None:
    op.drop_table("compta_releve_bancaire_lignes")
    op.drop_table("compta_releves_bancaires")
    op.drop_table("compta_export_ecritures")
    op.drop_table("compta_exports")
    op.execute(
        """
        DELETE FROM role_permissions
        WHERE permission_id = (SELECT id FROM permissions WHERE code = 'compta.export')
          AND role_id IN (SELECT id FROM roles WHERE code IN ('comptable', 'chef_comptable', 'daf'))
        """
    )
