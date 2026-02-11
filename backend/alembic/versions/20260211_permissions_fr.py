"""update permission labels in French

Revision ID: 20260211_permissions_fr
Revises: 20260211_drop_menu_permissions
Create Date: 2026-02-11
"""

from alembic import op
from sqlalchemy import text

revision = "20260211_permissions_fr"
down_revision = "20260211_drop_menu_permissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    updates = [
        ("can_create_requisition", "Créer une réquisition"),
        ("can_verify_technical", "Avis technique"),
        ("can_validate_final", "Validation finale"),
        ("can_execute_payment", "Exécuter la sortie de fonds"),
        ("can_manage_users", "Gérer les utilisateurs"),
        ("can_edit_settings", "Gérer les paramètres"),
        ("can_view_reports", "Accès aux rapports"),
    ]
    for code, label in updates:
        conn.execute(
            text("UPDATE permissions SET description = :label WHERE code = :code"),
            {"label": label, "code": code},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for code in [
        "can_create_requisition",
        "can_verify_technical",
        "can_validate_final",
        "can_execute_payment",
        "can_manage_users",
        "can_edit_settings",
        "can_view_reports",
    ]:
        conn.execute(
            text("UPDATE permissions SET description = NULL WHERE code = :code"),
            {"code": code},
        )
