"""Ajoute le référentiel optionnel des projets et activités."""

from alembic import op
import sqlalchemy as sa


revision = "20260804_projets_activites"
down_revision = "20260803_sortie_drafts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projets_activites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organisation_id", sa.Integer(), sa.ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=50), nullable=False),
        sa.Column("libelle", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False, server_default="PROJET"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("type IN ('PROJET','ACTIVITE')", name="ck_projets_activites_type"),
        sa.UniqueConstraint("organisation_id", "code", name="uq_projets_activites_org_code"),
    )
    op.create_index("ix_projets_activites_organisation_id", "projets_activites", ["organisation_id"])
    op.create_index("ix_projets_activites_is_active", "projets_activites", ["is_active"])
    op.add_column("encaissements", sa.Column("project_activity_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_encaissements_project_activity_id",
        "encaissements",
        "projets_activites",
        ["project_activity_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_encaissements_project_activity_id", "encaissements", ["project_activity_id"])


def downgrade() -> None:
    op.drop_index("ix_encaissements_project_activity_id", table_name="encaissements")
    op.drop_constraint("fk_encaissements_project_activity_id", "encaissements", type_="foreignkey")
    op.drop_column("encaissements", "project_activity_id")
    op.drop_index("ix_projets_activites_is_active", table_name="projets_activites")
    op.drop_index("ix_projets_activites_organisation_id", table_name="projets_activites")
    op.drop_table("projets_activites")
