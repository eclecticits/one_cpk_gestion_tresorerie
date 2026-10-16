"""bénéficiaires identifiés et justificatifs attendus des sorties

Revision ID: 20261016_benef_justif
Revises: 20261010_dossier_rejet_delai
Create Date: 2026-10-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261016_benef_justif"
down_revision = "20261010_dossier_rejet_delai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beneficiaires_externes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("nom", sa.String(200), nullable=False),
        sa.Column("nom_normalise", sa.String(200), nullable=False),
        sa.Column("telephone", sa.String(50), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("structure", sa.String(200), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("organisation_id", "nom_normalise", name="uq_beneficiaires_externes_org_nom"),
    )
    op.create_index(
        "ix_beneficiaires_externes_organisation_id", "beneficiaires_externes", ["organisation_id"]
    )

    op.add_column("sorties_fonds", sa.Column("beneficiaire_type", sa.String(20), nullable=True))
    op.add_column(
        "sorties_fonds",
        sa.Column(
            "beneficiaire_expert_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("experts_comptables.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column(
            "beneficiaire_employe_id",
            sa.Integer(),
            sa.ForeignKey("hr_employees.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "sorties_fonds",
        sa.Column(
            "beneficiaire_externe_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("beneficiaires_externes.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("sorties_fonds", sa.Column("beneficiaire_email", sa.String(200), nullable=True))
    op.add_column("sorties_fonds", sa.Column("beneficiaire_telephone", sa.String(50), nullable=True))
    op.add_column(
        "sorties_fonds",
        sa.Column("justificatif_statut", sa.String(20), nullable=False, server_default="NON_REQUIS"),
    )
    op.add_column("sorties_fonds", sa.Column("justificatif_echeance", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sorties_fonds", sa.Column("justificatif_relance_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sorties_fonds", sa.Column("justificatif_recu_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sorties_fonds",
        sa.Column(
            "justificatif_recu_par_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("sorties_fonds", sa.Column("justificatif_pieces", postgresql.JSONB(), nullable=True))
    op.add_column("sorties_fonds", sa.Column("justificatif_motif_dispense", sa.Text(), nullable=True))
    # Sert l'écran « Justificatifs en attente » et le planificateur de relance :
    # tous deux ne lisent que les sorties ATTENDU d'une organisation.
    op.create_index(
        "ix_sorties_fonds_org_justificatif",
        "sorties_fonds",
        ["organisation_id", "justificatif_statut"],
    )

    for column in (
        "sortie_copie_emails",
        "sortie_copie_whatsapp",
        "justificatif_autorites_emails",
        "justificatif_autorites_whatsapp",
    ):
        op.add_column("system_settings", sa.Column(column, sa.Text(), nullable=False, server_default=""))
    op.add_column("system_settings", sa.Column("justificatif_postes_codes", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "justificatif_postes_codes")
    for column in (
        "justificatif_autorites_whatsapp",
        "justificatif_autorites_emails",
        "sortie_copie_whatsapp",
        "sortie_copie_emails",
    ):
        op.drop_column("system_settings", column)

    op.drop_index("ix_sorties_fonds_org_justificatif", table_name="sorties_fonds")
    for column in (
        "justificatif_motif_dispense",
        "justificatif_pieces",
        "justificatif_recu_par_id",
        "justificatif_recu_le",
        "justificatif_relance_le",
        "justificatif_echeance",
        "justificatif_statut",
        "beneficiaire_telephone",
        "beneficiaire_email",
        "beneficiaire_externe_id",
        "beneficiaire_employe_id",
        "beneficiaire_expert_id",
        "beneficiaire_type",
    ):
        op.drop_column("sorties_fonds", column)

    op.drop_index("ix_beneficiaires_externes_organisation_id", table_name="beneficiaires_externes")
    op.drop_table("beneficiaires_externes")
