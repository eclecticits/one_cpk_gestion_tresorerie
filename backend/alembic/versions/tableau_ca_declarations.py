"""Déclarations CA préparatoires du module Tableau."""
from alembic import op
import sqlalchemy as sa

revision = "tableau_ca_declarations"
down_revision = "tableau_member_prep"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_ca_declarations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_row_id", sa.Integer(), sa.ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("member_identity_id", sa.Integer(), sa.ForeignKey("tableau_member_identities.id", ondelete="SET NULL"), nullable=True),
        sa.Column("numero_ordre_source", sa.String(100)),
        sa.Column("numero_ordre_normalise", sa.String(50)),
        sa.Column("membre_libelle_source", sa.String(300)),
        sa.Column("actif_source", sa.String(100)),
        sa.Column("actif_normalise", sa.Boolean()),
        sa.Column("annee", sa.Integer()),
        sa.Column("devise_source", sa.String(50)),
        sa.Column("devise_normalisee", sa.String(10)),
        sa.Column("ca_facture_source", sa.Text()),
        sa.Column("ca_facture", sa.Numeric(20, 2)),
        sa.Column("ca_collecte_source", sa.Text()),
        sa.Column("ca_collecte", sa.Numeric(20, 2)),
        sa.Column("date_mise_a_jour_source", sa.String(100)),
        sa.Column("date_mise_a_jour", sa.Date()),
        sa.Column("date_situation", sa.Date(), nullable=False),
        sa.Column("row_hash", sa.String(64)),
        sa.Column("ca_present", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for name, cols in {
        "ix_tableau_ca_declarations_organisation_id": ["organisation_id"],
        "ix_tableau_ca_declarations_source_import_id": ["source_import_id"],
        "ix_tableau_ca_declarations_source_row_id": ["source_row_id"],
        "ix_tableau_ca_declarations_member_identity_id": ["member_identity_id"],
        "ix_tableau_ca_declarations_numero_ordre_normalise": ["numero_ordre_normalise"],
        "ix_tableau_ca_declarations_annee": ["annee"],
        "ix_tableau_ca_declarations_devise_normalisee": ["devise_normalisee"],
        "ix_tableau_ca_declarations_date_situation": ["date_situation"],
        "ix_tableau_ca_declarations_row_hash": ["row_hash"],
        "ix_tableau_ca_lookup": ["organisation_id", "numero_ordre_normalise", "date_situation"],
    }.items():
        op.create_index(name, "tableau_ca_declarations", cols)


def downgrade() -> None:
    for name in [
        "ix_tableau_ca_lookup", "ix_tableau_ca_declarations_row_hash",
        "ix_tableau_ca_declarations_date_situation", "ix_tableau_ca_declarations_devise_normalisee",
        "ix_tableau_ca_declarations_annee", "ix_tableau_ca_declarations_numero_ordre_normalise",
        "ix_tableau_ca_declarations_member_identity_id", "ix_tableau_ca_declarations_source_row_id",
        "ix_tableau_ca_declarations_source_import_id", "ix_tableau_ca_declarations_organisation_id",
    ]:
        op.drop_index(name, table_name="tableau_ca_declarations")
    op.drop_table("tableau_ca_declarations")
