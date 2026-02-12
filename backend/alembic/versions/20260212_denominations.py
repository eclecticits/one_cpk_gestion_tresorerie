"""add denominations table

Revision ID: 20260212_denominations
Revises: 20260212_clotures_pdf_path
Create Date: 2026-02-12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260212_denominations"
down_revision = "20260212_clotures_pdf_path"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "denominations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("devise", sa.String(length=10), nullable=False),
        sa.Column("valeur", sa.Numeric(14, 2), nullable=False),
        sa.Column("label", sa.String(length=100), nullable=False),
        sa.Column("est_actif", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("ordre", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_denominations_devise", "denominations", ["devise"])

    op.execute(
        """
        INSERT INTO denominations (devise, valeur, label, est_actif, ordre) VALUES
        ('USD', 100, '100 $', true, 1),
        ('USD', 50, '50 $', true, 2),
        ('USD', 20, '20 $', true, 3),
        ('USD', 10, '10 $', true, 4),
        ('USD', 5, '5 $', true, 5),
        ('USD', 1, '1 $', true, 6),
        ('CDF', 20000, '20 000 FC', true, 1),
        ('CDF', 10000, '10 000 FC', true, 2),
        ('CDF', 5000, '5 000 FC', true, 3),
        ('CDF', 1000, '1 000 FC', true, 4),
        ('CDF', 500, '500 FC', true, 5),
        ('CDF', 200, '200 FC', true, 6),
        ('CDF', 100, '100 FC', true, 7),
        ('CDF', 50, '50 FC', true, 8);
        """
    )

    op.alter_column("denominations", "est_actif", server_default=None)
    op.alter_column("denominations", "ordre", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_denominations_devise", table_name="denominations")
    op.drop_table("denominations")
