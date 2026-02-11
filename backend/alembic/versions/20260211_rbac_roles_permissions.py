"""add rbac roles and permissions

Revision ID: 20260211_rbac_roles_permissions
Revises: 20260211_user_otp
Create Date: 2026-02-11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260211_rbac_roles_permissions"
down_revision = "20260211_user_otp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=50), nullable=False, unique=True),
        sa.Column("label", sa.String(length=100), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "permissions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("code", sa.String(length=80), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.Integer(), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", sa.Integer(), sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
    )

    op.add_column("users", sa.Column("role_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_users_role_id", "users", "roles", ["role_id"], ["id"])
    op.create_index("ix_users_role_id", "users", ["role_id"])

    op.execute(
        """
        INSERT INTO roles (code, label, description, created_at)
        VALUES
          ('admin', 'Administrateur', 'Gestion totale du système', NOW()),
          ('rapporteur', 'Rapporteur', 'Avis technique et validation intermédiaire', NOW()),
          ('tresorier', 'Trésorier', 'Prépare et vérifie les opérations', NOW()),
          ('caissier', 'Caissier', 'Exécute les sorties de fonds', NOW()),
          ('demandeur', 'Demandeur', 'Initie des réquisitions', NOW()),
          ('president', 'Président', 'Validation finale', NOW())
        ON CONFLICT (code) DO NOTHING;
        """
    )

    op.execute(
        """
        INSERT INTO permissions (code, description, created_at)
        VALUES
          ('can_create_requisition', 'Initier un bon de réquisition', NOW()),
          ('can_verify_technical', 'Apposer un avis technique', NOW()),
          ('can_validate_final', 'Validation finale pour décaissement', NOW()),
          ('can_execute_payment', 'Exécuter une sortie de fonds', NOW()),
          ('can_manage_users', 'Gérer les utilisateurs et rôles', NOW()),
          ('can_edit_settings', 'Modifier la configuration système', NOW()),
          ('can_view_reports', 'Accéder aux rapports et audits', NOW())
        ON CONFLICT (code) DO NOTHING;
        """
    )

    # Assign permissions to roles
    role_permission_pairs = [
        ("admin", "can_create_requisition"),
        ("admin", "can_verify_technical"),
        ("admin", "can_validate_final"),
        ("admin", "can_execute_payment"),
        ("admin", "can_manage_users"),
        ("admin", "can_edit_settings"),
        ("admin", "can_view_reports"),
        ("rapporteur", "can_verify_technical"),
        ("rapporteur", "can_view_reports"),
        ("president", "can_validate_final"),
        ("president", "can_view_reports"),
        ("caissier", "can_execute_payment"),
        ("tresorier", "can_execute_payment"),
        ("tresorier", "can_view_reports"),
        ("demandeur", "can_create_requisition"),
    ]
    for role_code, perm_code in role_permission_pairs:
        op.execute(
            f"""
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r, permissions p
            WHERE r.code = '{role_code}' AND p.code = '{perm_code}'
            ON CONFLICT DO NOTHING;
            """
        )

    # Map existing users to new roles
    op.execute(
        """
        UPDATE users SET role_id = (SELECT id FROM roles WHERE code='admin')
        WHERE role = 'admin';
        """
    )
    op.execute(
        """
        UPDATE users SET role_id = (SELECT id FROM roles WHERE code='rapporteur')
        WHERE role = 'rapporteur';
        """
    )
    op.execute(
        """
        UPDATE users SET role_id = (SELECT id FROM roles WHERE code='tresorier')
        WHERE role = 'comptabilite';
        """
    )
    op.execute(
        """
        UPDATE users SET role_id = (SELECT id FROM roles WHERE code='caissier')
        WHERE role = 'tresorerie';
        """
    )
    op.execute(
        """
        UPDATE users SET role_id = (SELECT id FROM roles WHERE code='demandeur')
        WHERE role IN ('reception', 'secretariat');
        """
    )
    op.execute(
        """
        UPDATE users SET role_id = (SELECT id FROM roles WHERE code='demandeur')
        WHERE role_id IS NULL;
        """
    )


def downgrade() -> None:
    op.drop_index("ix_users_role_id", table_name="users")
    op.drop_constraint("fk_users_role_id", "users", type_="foreignkey")
    op.drop_column("users", "role_id")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_table("roles")
