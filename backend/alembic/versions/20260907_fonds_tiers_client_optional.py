"""allow fonds de tiers without a client reference

The client remains mandatory for budgetary and regularisable movements, while
the Fonds de tiers workflow uses its own referential identity.
"""

from alembic import op


revision = "20260907_ft_client_optional"
down_revision = "20260906_fonds_tiers_ref"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_encaissements_client_ref", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_client_ref",
        "encaissements",
        """
        (nature_mouvement = 'FONDS_DE_TIERS')
        OR (type_client = 'expert_comptable' AND expert_comptable_id IS NOT NULL)
        OR (type_client <> 'expert_comptable' AND client_nom IS NOT NULL AND length(trim(client_nom)) > 0)
        """,
    )


def downgrade() -> None:
    op.drop_constraint("ck_encaissements_client_ref", "encaissements", type_="check")
    op.create_check_constraint(
        "ck_encaissements_client_ref",
        "encaissements",
        """
        (type_client = 'expert_comptable' AND expert_comptable_id IS NOT NULL)
        OR (type_client <> 'expert_comptable' AND client_nom IS NOT NULL AND length(trim(client_nom)) > 0)
        """,
    )
