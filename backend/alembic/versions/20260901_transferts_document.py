"""Identité documentaire des transferts saisis par le chemin `sorties-fonds`.

Préalable à la bascule de `versement_banque` vers le moteur dédié.

Un versement saisi aujourd'hui produit une `SortieFonds` : le frontend en reçoit
l'UUID, génère le bon, et le lui attache par `POST /sorties-fonds/{id}/pdf`. Le
moteur dédié, lui, a une clé primaire entière et ne sait rien stocker d'un
document. Basculer sans ces trois colonnes ferait disparaître en silence le bon
imprimé et les pièces jointes du caissier — un justificatif de dépôt bancaire,
typiquement.

`document_uuid` est NULL pour un transfert créé directement sur
`/transferts-internes` : celui-là n'a jamais annoncé d'UUID à personne. L'index
unique est donc partiel.
"""

from alembic import op
import sqlalchemy as sa


revision = "20260901_transferts_document"
down_revision = "20260831_transferts_repair"
branch_labels = None
depends_on = None

TABLE = "transferts_internes"


def _colonnes(inspector: sa.Inspector) -> set[str]:
    return {col["name"] for col in inspector.get_columns(TABLE)}


def _index(inspector: sa.Inspector) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(TABLE)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    colonnes = _colonnes(inspector)
    for nom, colonne in (
        ("document_uuid", sa.Column("document_uuid", sa.UUID(), nullable=True)),
        ("pdf_path", sa.Column("pdf_path", sa.String(500), nullable=True)),
        ("annexes", sa.Column("annexes", sa.dialects.postgresql.JSONB(), nullable=True)),
    ):
        if nom not in colonnes:
            op.add_column(TABLE, colonne)

    inspector = sa.inspect(bind)
    if "uq_transferts_internes_document_uuid" not in _index(inspector):
        op.create_index(
            "uq_transferts_internes_document_uuid", TABLE, ["document_uuid"], unique=True,
            postgresql_where=sa.text("document_uuid IS NOT NULL"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "uq_transferts_internes_document_uuid" in _index(inspector):
        op.drop_index("uq_transferts_internes_document_uuid", table_name=TABLE)
    inspector = sa.inspect(bind)
    colonnes = _colonnes(inspector)
    for nom in ("annexes", "pdf_path", "document_uuid"):
        if nom in colonnes:
            op.drop_column(TABLE, nom)
