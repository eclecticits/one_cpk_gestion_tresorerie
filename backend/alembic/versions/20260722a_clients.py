"""Référentiel clients + lien encaissements.client_id.

- Table `clients` : identité des clients (nom, email, téléphone, adresse),
  unique par organisation sur lower(nom) pour éviter les doublons.
- `encaissements.client_id` : lien vers le client (nullable, les anciens
  encaissements gardent leur client_nom texte).

Revision ID: 20260722a_clients
Revises: 20260721f_ouverture_ecart
Create Date: 2026-07-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision = "20260722a_clients"
down_revision = "20260721f_ouverture_ecart"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clients",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("nom", sa.String(300), nullable=False),
        sa.Column("type_client", sa.String(50), nullable=True),
        sa.Column("email", sa.String(200), nullable=True),
        sa.Column("telephone", sa.String(50), nullable=True),
        sa.Column("adresse", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_clients_organisation_id", "clients", ["organisation_id"])
    op.create_index("ix_clients_nom", "clients", ["nom"])
    op.create_index(
        "uq_clients_org_nom_lower",
        "clients",
        ["organisation_id", sa.text("lower(nom)")],
        unique=True,
    )

    op.add_column(
        "encaissements",
        sa.Column("client_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_encaissements_client_id", "encaissements", ["client_id"])
    op.create_foreign_key(
        "fk_encaissements_client_id",
        "encaissements",
        "clients",
        ["client_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Reprise de l'existant : créer un client par nom distinct déjà saisi
    # dans les encaissements (hors experts-comptables), puis lier.
    op.execute(
        """
        INSERT INTO clients (id, organisation_id, nom, type_client, active, created_at, updated_at)
        SELECT gen_random_uuid(), e.organisation_id, min(trim(e.client_nom)),
               max(e.type_client), true, now(), now()
        FROM encaissements e
        WHERE e.client_nom IS NOT NULL
          AND length(trim(e.client_nom)) > 0
          AND e.type_client <> 'expert_comptable'
        GROUP BY e.organisation_id, lower(trim(e.client_nom))
        ON CONFLICT DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE encaissements e
        SET client_id = c.id
        FROM clients c
        WHERE e.client_id IS NULL
          AND e.client_nom IS NOT NULL
          AND e.type_client <> 'expert_comptable'
          AND c.organisation_id = e.organisation_id
          AND lower(c.nom) = lower(trim(e.client_nom))
        """
    )


def downgrade() -> None:
    op.drop_constraint("fk_encaissements_client_id", "encaissements", type_="foreignkey")
    op.drop_index("ix_encaissements_client_id", table_name="encaissements")
    op.drop_column("encaissements", "client_id")
    op.drop_index("uq_clients_org_nom_lower", table_name="clients")
    op.drop_index("ix_clients_nom", table_name="clients")
    op.drop_index("ix_clients_organisation_id", table_name="clients")
    op.drop_table("clients")
