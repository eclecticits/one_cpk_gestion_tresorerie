"""Déclarations d'assurance préparatoires du module Tableau."""
from alembic import op
import sqlalchemy as sa

revision = "tableau_insurance_declarations"
down_revision = "tableau_pp_status_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tableau_insurance_declarations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_import_id", sa.Integer(), sa.ForeignKey("secretariat_tableau_imports.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_row_id", sa.Integer(), sa.ForeignKey("tableau_source_rows.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("member_identity_id", sa.Integer(), sa.ForeignKey("tableau_member_identities.id", ondelete="SET NULL")),
        sa.Column("membre_source", sa.String(300)), sa.Column("numero_ordre_source", sa.String(100)),
        sa.Column("numero_ordre_normalise", sa.String(50)), sa.Column("declare_source", sa.String(100)),
        sa.Column("declare_normalise", sa.Boolean()), sa.Column("souscrit_source", sa.String(100)),
        sa.Column("souscrit_normalise", sa.Boolean()), sa.Column("fin_couverture_source", sa.String(100)),
        sa.Column("fin_couverture", sa.Date()), sa.Column("annee_souscription_source", sa.String(100)),
        sa.Column("annee_souscription", sa.Integer()), sa.Column("assureur_source", sa.Text()),
        sa.Column("assureur_normalise", sa.String(300)), sa.Column("periode_source", sa.Text()),
        sa.Column("periode_normalisee", sa.String(100)), sa.Column("date_situation", sa.Date(), nullable=False),
        sa.Column("row_hash", sa.String(64)), sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    for name, cols in {
        "ix_tableau_insurance_declarations_organisation_id": ["organisation_id"],
        "ix_tableau_insurance_declarations_source_import_id": ["source_import_id"],
        "ix_tableau_insurance_declarations_source_row_id": ["source_row_id"],
        "ix_tableau_insurance_declarations_member_identity_id": ["member_identity_id"],
        "ix_tableau_insurance_declarations_numero_ordre_normalise": ["numero_ordre_normalise"],
        "ix_tableau_insurance_declarations_date_situation": ["date_situation"],
        "ix_tableau_insurance_declarations_row_hash": ["row_hash"],
        "ix_tableau_insurance_lookup": ["organisation_id", "numero_ordre_normalise", "date_situation"],
    }.items():
        op.create_index(name, "tableau_insurance_declarations", cols)


def downgrade() -> None:
    for name in ["ix_tableau_insurance_lookup", "ix_tableau_insurance_declarations_row_hash", "ix_tableau_insurance_declarations_date_situation", "ix_tableau_insurance_declarations_numero_ordre_normalise", "ix_tableau_insurance_declarations_member_identity_id", "ix_tableau_insurance_declarations_source_row_id", "ix_tableau_insurance_declarations_source_import_id", "ix_tableau_insurance_declarations_organisation_id"]:
        op.drop_index(name, table_name="tableau_insurance_declarations")
    op.drop_table("tableau_insurance_declarations")
