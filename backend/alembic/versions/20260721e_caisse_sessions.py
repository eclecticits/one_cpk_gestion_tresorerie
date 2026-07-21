"""Sessions de caisse (ouverture/clôture, Modèle B).

- caisse_centrale : est_ouverte + ouverte_le + ouverte_par_id.
  Les caisses EXISTANTES sont initialisées à est_ouverte=true (server_default)
  pour ne pas bloquer l'exploitation en cours ; le défaut applicatif des
  nouvelles caisses reste False (il faut ouvrir avant d'opérer).
- ouvertures_caisse : historique des ouvertures (fond de caisse compté).

Revision ID: 20260721e_caisse_sessions
Revises: 20260721d_sortie_programme_par
Create Date: 2026-07-21
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


revision = "20260721e_caisse_sessions"
down_revision = "20260721d_sortie_programme_par"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "caisse_centrale",
        sa.Column("est_ouverte", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )
    op.add_column("caisse_centrale", sa.Column("ouverte_le", sa.DateTime(timezone=True), nullable=True))
    op.add_column("caisse_centrale", sa.Column("ouverte_par_id", UUID(as_uuid=True), nullable=True))
    # Le défaut applicatif (nouvelles caisses) est False : on retire le
    # server_default après remplissage des lignes existantes.
    op.alter_column("caisse_centrale", "est_ouverte", server_default=None)

    op.create_table(
        "ouvertures_caisse",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="RESTRICT"), nullable=False, index=True),
        sa.Column("reference_numero", sa.String(length=50), nullable=False, index=True),
        sa.Column("date_ouverture", sa.DateTime(timezone=True), nullable=False),
        sa.Column("caissier_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("solde_ouverture_usd", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("solde_ouverture_cdf", sa.Numeric(14, 2), nullable=False, server_default="0"),
        sa.Column("billetage_usd", JSONB(), nullable=True),
        sa.Column("billetage_cdf", JSONB(), nullable=True),
        sa.Column("observation", sa.String(length=500), nullable=True),
        sa.Column("statut", sa.String(length=30), nullable=False, server_default="OUVERTE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("organisation_id", "reference_numero", name="uq_ouvertures_org_reference_numero"),
    )


def downgrade() -> None:
    op.drop_table("ouvertures_caisse")
    op.drop_column("caisse_centrale", "ouverte_par_id")
    op.drop_column("caisse_centrale", "ouverte_le")
    op.drop_column("caisse_centrale", "est_ouverte")
