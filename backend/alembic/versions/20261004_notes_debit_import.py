"""Import Excel des notes de débit des experts-comptables.

- table `notes_debit_imports` : un fichier importé, ses colonnes et ses totaux ;
- `encaissements.note_debit_import_id` : la note renvoie à l'import d'où elle
  vient (nul pour une note saisie au formulaire) ;
- permission `treso.experts_comptables.import_notes_debit`, accordée à
  l'administrateur et au comptable. Importer, c'est émettre des créances en
  nombre : le caissier, qui encaisse, ne le fait pas. La répartition se change
  ensuite dans l'écran des permissions.

Revision ID: 20261004_notes_debit_import
Revises: 20261003_reimput_explicite
Create Date: 2026-10-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql


revision = "20261004_notes_debit_import"
down_revision = "20261003_reimput_explicite"
branch_labels = None
depends_on = None


CODE = "treso.experts_comptables.import_notes_debit"
DESCRIPTION = "Trésorerie — Experts-comptables : importer des notes de débit (Excel)"
ROLES = ("admin", "comptable")

SEMER = """
    INSERT INTO permissions (code, description, created_at)
    VALUES (:code, :description, now())
    ON CONFLICT (code) DO UPDATE SET description = EXCLUDED.description
"""

ACCORDER = """
    INSERT INTO role_permissions (role_id, permission_id)
    SELECT r.id, p.id
    FROM roles r, permissions p
    WHERE r.code = :role AND p.code = :code
    ON CONFLICT DO NOTHING
"""


def upgrade() -> None:
    op.create_table(
        "notes_debit_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organisation_id",
            sa.Integer(),
            sa.ForeignKey("organisations.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("fichier", sa.String(300), nullable=False),
        sa.Column("nb_notes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("nb_lignes_ecartees", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("montant_total", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("montant_arrieres", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("colonnes", postgresql.JSON(), nullable=True),
        sa.Column("service_id", sa.Integer(), sa.ForeignKey("services.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_notes_debit_imports_organisation_id", "notes_debit_imports", ["organisation_id"])

    op.add_column(
        "encaissements",
        sa.Column("note_debit_import_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_encaissements_note_debit_import",
        "encaissements",
        "notes_debit_imports",
        ["note_debit_import_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_encaissements_note_debit_import_id", "encaissements", ["note_debit_import_id"])

    bind = op.get_bind()
    bind.execute(text(SEMER), {"code": CODE, "description": DESCRIPTION})
    for role in ROLES:
        bind.execute(text(ACCORDER), {"role": role, "code": CODE})


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text("DELETE FROM role_permissions WHERE permission_id IN (SELECT id FROM permissions WHERE code = :code)"),
        {"code": CODE},
    )
    bind.execute(text("DELETE FROM permissions WHERE code = :code"), {"code": CODE})

    op.drop_index("ix_encaissements_note_debit_import_id", table_name="encaissements")
    op.drop_constraint("fk_encaissements_note_debit_import", "encaissements", type_="foreignkey")
    op.drop_column("encaissements", "note_debit_import_id")
    op.drop_index("ix_notes_debit_imports_organisation_id", table_name="notes_debit_imports")
    op.drop_table("notes_debit_imports")
