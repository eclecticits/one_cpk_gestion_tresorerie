"""fonds tiers referential tiers

Le tiers pour qui des fonds sont détenus cesse d'être une chaîne libre : c'est
soit une organisation du référentiel (`tiers_organisation_id`), soit un tiers
hors référentiel nommé à la main (`tiers_nom_libre`). `tiers_concerne` survit en
lecture seule pour les opérations antérieures, qui n'ont ni l'un ni l'autre —
d'où une contrainte à trois branches plutôt qu'un simple NOT NULL.

Revision ID: 20260906_fonds_tiers_ref
Revises: 20260905_hors_budget_backfill
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa


revision = "20260906_fonds_tiers_ref"
down_revision = "20260905_hors_budget_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fonds_tiers_operations", sa.Column("tiers_organisation_id", sa.Integer(), nullable=True))
    op.add_column("fonds_tiers_operations", sa.Column("tiers_nom_libre", sa.String(length=255), nullable=True))
    op.alter_column("fonds_tiers_operations", "tiers_concerne", existing_type=sa.String(length=255), nullable=True)
    op.create_index(
        "ix_fonds_tiers_operations_tiers_organisation_id",
        "fonds_tiers_operations",
        ["tiers_organisation_id"],
    )
    op.create_foreign_key(
        "fk_fonds_tiers_tiers_organisation_id",
        "fonds_tiers_operations",
        "organisations",
        ["tiers_organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_fonds_tiers_tiers_source",
        "fonds_tiers_operations",
        """
        (
            tiers_organisation_id IS NOT NULL
            AND tiers_nom_libre IS NULL
        )
        OR (
            tiers_organisation_id IS NULL
            AND tiers_nom_libre IS NOT NULL
            AND btrim(tiers_nom_libre) <> ''
        )
        OR (
            tiers_organisation_id IS NULL
            AND tiers_nom_libre IS NULL
            AND tiers_concerne IS NOT NULL
            AND btrim(tiers_concerne) <> ''
        )
        """,
    )


def downgrade() -> None:
    op.drop_constraint("ck_fonds_tiers_tiers_source", "fonds_tiers_operations", type_="check")
    op.drop_constraint("fk_fonds_tiers_tiers_organisation_id", "fonds_tiers_operations", type_="foreignkey")
    op.drop_index("ix_fonds_tiers_operations_tiers_organisation_id", table_name="fonds_tiers_operations")

    # Toute opération créée depuis l'upgrade a `tiers_concerne` à NULL : son
    # identité vit dans les deux colonnes qu'on s'apprête à supprimer. Il faut
    # la replier dans le champ historique AVANT de le rendre obligatoire, sinon
    # le downgrade échoue dès la première opération du nouveau format — et,
    # s'il passait, il effacerait le nom du tiers.
    op.execute(
        """
        UPDATE fonds_tiers_operations AS f
           SET tiers_concerne = o.nom
          FROM organisations AS o
         WHERE f.tiers_concerne IS NULL
           AND f.tiers_organisation_id IS NOT NULL
           AND o.id = f.tiers_organisation_id
        """
    )
    op.execute(
        """
        UPDATE fonds_tiers_operations
           SET tiers_concerne = COALESCE(NULLIF(btrim(tiers_nom_libre), ''), 'Tiers non identifié')
         WHERE tiers_concerne IS NULL
        """
    )

    op.alter_column("fonds_tiers_operations", "tiers_concerne", existing_type=sa.String(length=255), nullable=False)
    op.drop_column("fonds_tiers_operations", "tiers_nom_libre")
    op.drop_column("fonds_tiers_operations", "tiers_organisation_id")
