"""Ajoute la table des retours en caisse (remboursement après sortie de fonds)."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260805_retours_caisse"
down_revision = "20260804_compta_mode"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retours_caisse",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "sortie_fonds_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sorties_fonds.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "requisition_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("requisitions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("type_retour", sa.String(length=30), nullable=False, server_default="reliquat_avance"),
        sa.Column(
            "budget_poste_id",
            sa.Integer(),
            sa.ForeignKey("budget_postes.id"),
            nullable=True,
        ),
        sa.Column("budget_poste_code", sa.String(length=20), nullable=True),
        sa.Column("budget_poste_libelle", sa.String(length=255), nullable=True),
        sa.Column("ajuste_budget", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "service_id",
            sa.Integer(),
            sa.ForeignKey("services.id"),
            nullable=True,
        ),
        sa.Column("montant", sa.Numeric(14, 2), nullable=False),
        sa.Column("devise", sa.String(length=3), nullable=False, server_default="USD"),
        sa.Column("canal", sa.String(length=10), nullable=False, server_default="CAISSE"),
        sa.Column(
            "compte_bancaire_id",
            sa.Integer(),
            sa.ForeignKey("comptes_bancaires.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("mode", sa.String(length=50), nullable=False, server_default="cash"),
        sa.Column("reference", sa.String(length=100), nullable=True),
        sa.Column("reference_numero", sa.String(length=50), nullable=True),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("commentaire", sa.Text(), nullable=True),
        sa.Column("piece_justificative", sa.String(length=200), nullable=True),
        sa.Column("exchange_rate_snapshot", sa.Numeric(12, 4), nullable=True),
        sa.Column("date_retour", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("statut", sa.String(length=20), nullable=False, server_default="VALIDE"),
        sa.Column(
            "statut_comptabilisation",
            sa.String(length=40),
            nullable=False,
            server_default="NON_COMPTABILISEE",
        ),
        sa.Column("message_comptabilisation", sa.Text(), nullable=True),
        sa.Column("motif_annulation", sa.Text(), nullable=True),
        sa.Column("annulee_le", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "annulee_par_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("annulation_ip", sa.String(length=64), nullable=True),
        sa.Column("ancien_statut", sa.String(length=20), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("canal IN ('CAISSE','BANQUE')", name="ck_retours_caisse_canal"),
        sa.CheckConstraint("devise IN ('USD','CDF')", name="ck_retours_caisse_devise"),
        sa.CheckConstraint(
            "(canal = 'BANQUE' AND compte_bancaire_id IS NOT NULL) OR (canal = 'CAISSE')",
            name="ck_retours_caisse_compte_bancaire",
        ),
        sa.CheckConstraint("montant > 0", name="ck_retours_caisse_montant_positif"),
        sa.CheckConstraint(
            "type_retour IN ('reliquat_avance','correction','trop_percu')",
            name="ck_retours_caisse_type_retour",
        ),
        sa.UniqueConstraint(
            "organisation_id", "reference_numero", name="uq_retours_caisse_org_reference_numero"
        ),
    )
    op.create_index("ix_retours_caisse_organisation_id", "retours_caisse", ["organisation_id"])
    op.create_index("ix_retours_caisse_sortie_fonds_id", "retours_caisse", ["sortie_fonds_id"])
    op.create_index("ix_retours_caisse_requisition_id", "retours_caisse", ["requisition_id"])
    op.create_index("ix_retours_caisse_budget_poste_id", "retours_caisse", ["budget_poste_id"])
    op.create_index("ix_retours_caisse_service_id", "retours_caisse", ["service_id"])
    op.create_index("ix_retours_caisse_compte_bancaire_id", "retours_caisse", ["compte_bancaire_id"])
    op.create_index("ix_retours_caisse_reference_numero", "retours_caisse", ["reference_numero"])
    op.create_index("ix_retours_caisse_statut_comptabilisation", "retours_caisse", ["statut_comptabilisation"])
    op.create_index("ix_retours_caisse_created_by", "retours_caisse", ["created_by"])


def downgrade() -> None:
    for ix in (
        "ix_retours_caisse_created_by",
        "ix_retours_caisse_statut_comptabilisation",
        "ix_retours_caisse_reference_numero",
        "ix_retours_caisse_compte_bancaire_id",
        "ix_retours_caisse_service_id",
        "ix_retours_caisse_budget_poste_id",
        "ix_retours_caisse_requisition_id",
        "ix_retours_caisse_sortie_fonds_id",
        "ix_retours_caisse_organisation_id",
    ):
        op.drop_index(ix, table_name="retours_caisse")
    op.drop_table("retours_caisse")
