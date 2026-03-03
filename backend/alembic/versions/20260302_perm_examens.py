"""add permission for examens dossier menu

Revision ID: 20260302_perm_examens
Revises: 20260302_dossier_exam
Create Date: 2026-03-02
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260302_perm_examens"
down_revision = "20260302_dossier_exam"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "INSERT INTO permissions (code, description, created_at) "
            "VALUES (:code, :description, NOW()) "
            "ON CONFLICT (code) DO NOTHING"
        ).bindparams(
            code="menu_validation_examens",
            description="Accès aux dossiers d'examen",
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM permissions WHERE code = :code").bindparams(
            code="menu_validation_examens"
        )
    )
