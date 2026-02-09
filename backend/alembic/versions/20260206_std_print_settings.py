"""standardize print settings fields

Revision ID: 20260206_std_print_settings
Revises: 9172c1fbac69
Create Date: 2026-02-06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260206_std_print_settings"
down_revision = "20260205_req_devise"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.add_column(sa.Column("pied_de_page_legal", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("afficher_qr_code", sa.Boolean(), nullable=False, server_default=sa.text("true")))
        batch.add_column(sa.Column("recu_label_signature", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("recu_nom_signataire", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("req_titre_officiel", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("req_label_gauche", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("req_nom_gauche", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("req_label_droite", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("req_nom_droite", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("trans_titre_officiel", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("trans_label_gauche", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("trans_nom_gauche", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("trans_label_droite", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("trans_nom_droite", sa.String(length=200), nullable=False, server_default=""))

        batch.drop_column("footer_text")
        batch.drop_column("signature_name")
        batch.drop_column("signature_title")
        batch.drop_column("label_validation_transport")
        batch.drop_column("label_approbation_transport")
        batch.drop_column("nom_tresoriere")
        batch.drop_column("nom_approbateur")


def downgrade() -> None:
    with op.batch_alter_table("print_settings") as batch:
        batch.add_column(sa.Column("nom_approbateur", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("nom_tresoriere", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("label_approbation_transport", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("label_validation_transport", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("signature_title", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("signature_name", sa.String(length=200), nullable=False, server_default=""))
        batch.add_column(sa.Column("footer_text", sa.Text(), nullable=False, server_default=""))

        batch.drop_column("trans_nom_droite")
        batch.drop_column("trans_label_droite")
        batch.drop_column("trans_nom_gauche")
        batch.drop_column("trans_label_gauche")
        batch.drop_column("trans_titre_officiel")
        batch.drop_column("req_nom_droite")
        batch.drop_column("req_label_droite")
        batch.drop_column("req_nom_gauche")
        batch.drop_column("req_label_gauche")
        batch.drop_column("req_titre_officiel")
        batch.drop_column("recu_nom_signataire")
        batch.drop_column("recu_label_signature")
        batch.drop_column("afficher_qr_code")
        batch.drop_column("pied_de_page_legal")
