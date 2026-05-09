"""Enforce strict tenant scoping on remaining business tables.

Revision ID: 20260509_tenant_strict_scope
Revises: 0005_requisitions_tables, 0005_validate_enc_constraints, 20260210_req_pdf,
    20260211_sortie_notifications, 20260217_budget_poste_snapshots,
    20260225_add_exchange_multi, 20260225_drop_type_operation,
    20260225_remove_mini_req, 20260226_add_sortie_annulee_le,
    20260325_services_tenant_scope, 20260326_org_theme_text_color,
    20260421_enc_articles, 20260504_service_admin_canon
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260509_tenant_strict_scope"
down_revision = (
    "0005_requisitions_tables",
    "0005_validate_enc_constraints",
    "20260210_req_pdf",
    "20260211_sortie_notifications",
    "20260217_budget_poste_snapshots",
    "20260225_add_exchange_multi",
    "20260225_drop_type_operation",
    "20260225_remove_mini_req",
    "20260226_add_sortie_annulee_le",
    "20260325_services_tenant_scope",
    "20260326_org_theme_text_color",
    "20260421_enc_articles",
    "20260504_service_admin_canon",
)
branch_labels = None
depends_on = None


def _drop_unique_constraint_for_column(table_name: str, column_name: str) -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            DECLARE constraint_name text;
            BEGIN
                SELECT con.conname
                INTO constraint_name
                FROM pg_constraint con
                WHERE con.conrelid = '{table_name}'::regclass
                  AND con.contype = 'u'
                  AND array_length(con.conkey, 1) = 1
                  AND con.conkey[1] = (
                      SELECT attnum
                      FROM pg_attribute
                      WHERE attrelid = '{table_name}'::regclass
                        AND attname = '{column_name}'
                        AND NOT attisdropped
                  )
                LIMIT 1;

                IF constraint_name IS NOT NULL THEN
                    EXECUTE format('ALTER TABLE {table_name} DROP CONSTRAINT %I', constraint_name);
                END IF;
            END $$;
            """
        )
    )


def upgrade() -> None:
    conn = op.get_bind()

    op.add_column("dossiers_requisition", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("lignes_requisition", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("requisition_annexes", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("requisition_approvers", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("requisition_status_history", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("remboursements_transport", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("participants_transport", sa.Column("organisation_id", sa.Integer(), nullable=True))
    op.add_column("transferts_internes", sa.Column("organisation_id", sa.Integer(), nullable=True))

    conn.execute(
        sa.text(
            """
            UPDATE dossiers_requisition d
            SET organisation_id = src.organisation_id
            FROM (
                SELECT
                    d0.id,
                    COALESCE(
                        MAX(r.organisation_id),
                        MAX(u.organisation_id),
                        (SELECT MIN(id) FROM organisations)
                    ) AS organisation_id
                FROM dossiers_requisition d0
                LEFT JOIN requisitions r ON r.dossier_id = d0.id
                LEFT JOIN users u ON u.id = d0.created_by
                GROUP BY d0.id
            ) src
            WHERE d.id = src.id
              AND d.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE lignes_requisition lr
            SET organisation_id = r.organisation_id
            FROM requisitions r
            WHERE r.id = lr.requisition_id
              AND lr.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE requisition_annexes ra
            SET organisation_id = r.organisation_id
            FROM requisitions r
            WHERE r.id = ra.requisition_id
              AND ra.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE requisition_approvers ra
            SET organisation_id = COALESCE(
                (SELECT u.organisation_id FROM users u WHERE u.id = ra.user_id),
                (SELECT creator.organisation_id FROM users creator WHERE creator.id = ra.added_by),
                (SELECT MIN(id) FROM organisations)
            )
            WHERE ra.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE requisition_status_history h
            SET organisation_id = COALESCE(
                (SELECT r.organisation_id FROM requisitions r WHERE r.id = h.requisition_id),
                (SELECT u.organisation_id FROM users u WHERE u.id = h.changed_by),
                (SELECT MIN(id) FROM organisations)
            )
            WHERE h.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE remboursements_transport rt
            SET organisation_id = COALESCE(
                (SELECT r.organisation_id FROM requisitions r WHERE r.id = rt.requisition_id),
                (SELECT u.organisation_id FROM users u WHERE u.id = rt.created_by),
                (SELECT MIN(id) FROM organisations)
            )
            WHERE rt.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE participants_transport pt
            SET organisation_id = rt.organisation_id
            FROM remboursements_transport rt
            WHERE rt.id = pt.remboursement_id
              AND pt.organisation_id IS NULL;
            """
        )
    )
    conn.execute(
        sa.text(
            """
            UPDATE transferts_internes ti
            SET organisation_id = COALESCE(
                (
                    SELECT src.organisation_id
                    FROM comptes_bancaires src
                    WHERE ti.source_type = 'BANQUE'
                      AND src.id = ti.source_id
                ),
                (
                    SELECT dst.organisation_id
                    FROM comptes_bancaires dst
                    WHERE ti.destination_type = 'BANQUE'
                      AND dst.id = ti.destination_id
                ),
                (SELECT u.organisation_id FROM users u WHERE u.id = ti.execute_par),
                (SELECT MIN(id) FROM organisations)
            )
            WHERE ti.organisation_id IS NULL;
            """
        )
    )

    op.alter_column("dossiers_requisition", "organisation_id", nullable=False)
    op.alter_column("lignes_requisition", "organisation_id", nullable=False)
    op.alter_column("requisition_annexes", "organisation_id", nullable=False)
    op.alter_column("requisition_approvers", "organisation_id", nullable=False)
    op.alter_column("requisition_status_history", "organisation_id", nullable=False)
    op.alter_column("remboursements_transport", "organisation_id", nullable=False)
    op.alter_column("participants_transport", "organisation_id", nullable=False)
    op.alter_column("transferts_internes", "organisation_id", nullable=False)

    op.create_index("ix_dossiers_requisition_organisation_id", "dossiers_requisition", ["organisation_id"])
    op.create_index("ix_lignes_requisition_organisation_id", "lignes_requisition", ["organisation_id"])
    op.create_index("ix_requisition_annexes_organisation_id", "requisition_annexes", ["organisation_id"])
    op.create_index("ix_requisition_approvers_organisation_id", "requisition_approvers", ["organisation_id"])
    op.create_index("ix_requisition_status_history_organisation_id", "requisition_status_history", ["organisation_id"])
    op.create_index("ix_remboursements_transport_organisation_id", "remboursements_transport", ["organisation_id"])
    op.create_index("ix_participants_transport_organisation_id", "participants_transport", ["organisation_id"])
    op.create_index("ix_transferts_internes_organisation_id", "transferts_internes", ["organisation_id"])

    op.create_foreign_key(
        "fk_dossiers_requisition_organisation_id",
        "dossiers_requisition",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lignes_requisition_organisation_id",
        "lignes_requisition",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_lignes_requisition_requisition_id",
        "lignes_requisition",
        "requisitions",
        ["requisition_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_requisition_annexes_organisation_id",
        "requisition_annexes",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_requisition_approvers_organisation_id",
        "requisition_approvers",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_requisition_status_history_organisation_id",
        "requisition_status_history",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_remboursements_transport_organisation_id",
        "remboursements_transport",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_remboursements_transport_requisition_id",
        "remboursements_transport",
        "requisitions",
        ["requisition_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_participants_transport_organisation_id",
        "participants_transport",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_transferts_internes_organisation_id",
        "transferts_internes",
        "organisations",
        ["organisation_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    _drop_unique_constraint_for_column("requisitions", "numero_requisition")
    op.drop_index("uq_requisitions_reference_numero", table_name="requisitions")
    op.create_unique_constraint(
        "uq_requisitions_org_numero",
        "requisitions",
        ["organisation_id", "numero_requisition"],
    )
    op.create_unique_constraint(
        "uq_requisitions_org_reference_numero",
        "requisitions",
        ["organisation_id", "reference_numero"],
    )

    op.drop_index("ix_dossiers_requisition_reference", table_name="dossiers_requisition")
    _drop_unique_constraint_for_column("dossiers_requisition", "reference")
    op.create_unique_constraint(
        "uq_dossiers_requisition_org_reference",
        "dossiers_requisition",
        ["organisation_id", "reference"],
    )

    _drop_unique_constraint_for_column("remboursements_transport", "numero_remboursement")
    op.drop_index("uq_remboursements_transport_reference_numero", table_name="remboursements_transport")
    op.create_unique_constraint(
        "uq_remboursements_transport_org_numero",
        "remboursements_transport",
        ["organisation_id", "numero_remboursement"],
    )
    op.create_unique_constraint(
        "uq_remboursements_transport_org_reference",
        "remboursements_transport",
        ["organisation_id", "reference_numero"],
    )

    op.drop_index("uq_sorties_fonds_reference_numero", table_name="sorties_fonds")
    op.create_unique_constraint(
        "uq_sorties_fonds_org_reference_numero",
        "sorties_fonds",
        ["organisation_id", "reference_numero"],
    )

    op.drop_constraint("uq_clotures_reference_numero", "clotures", type_="unique")
    op.create_unique_constraint(
        "uq_clotures_org_reference_numero",
        "clotures",
        ["organisation_id", "reference_numero"],
    )

    _drop_unique_constraint_for_column("comptes_bancaires", "numero_compte")
    op.create_unique_constraint(
        "uq_comptes_bancaires_org_numero_compte",
        "comptes_bancaires",
        ["organisation_id", "numero_compte"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_comptes_bancaires_org_numero_compte", "comptes_bancaires", type_="unique")
    op.create_unique_constraint("comptes_bancaires_numero_compte_key", "comptes_bancaires", ["numero_compte"])

    op.drop_constraint("uq_clotures_org_reference_numero", "clotures", type_="unique")
    op.create_unique_constraint("uq_clotures_reference_numero", "clotures", ["reference_numero"])

    op.drop_constraint("uq_sorties_fonds_org_reference_numero", "sorties_fonds", type_="unique")
    op.create_index("uq_sorties_fonds_reference_numero", "sorties_fonds", ["reference_numero"], unique=True)

    op.drop_constraint("uq_remboursements_transport_org_reference", "remboursements_transport", type_="unique")
    op.drop_constraint("uq_remboursements_transport_org_numero", "remboursements_transport", type_="unique")
    op.create_unique_constraint(
        "remboursements_transport_numero_remboursement_key",
        "remboursements_transport",
        ["numero_remboursement"],
    )
    op.create_index(
        "uq_remboursements_transport_reference_numero",
        "remboursements_transport",
        ["reference_numero"],
        unique=True,
    )

    op.drop_constraint("uq_dossiers_requisition_org_reference", "dossiers_requisition", type_="unique")
    op.create_unique_constraint("dossiers_requisition_reference_key", "dossiers_requisition", ["reference"])
    op.create_index("ix_dossiers_requisition_reference", "dossiers_requisition", ["reference"], unique=True)

    op.drop_constraint("uq_requisitions_org_reference_numero", "requisitions", type_="unique")
    op.drop_constraint("uq_requisitions_org_numero", "requisitions", type_="unique")
    op.create_unique_constraint("uq_requisitions_numero", "requisitions", ["numero_requisition"])
    op.create_index("uq_requisitions_reference_numero", "requisitions", ["reference_numero"], unique=True)

    op.drop_constraint("fk_transferts_internes_organisation_id", "transferts_internes", type_="foreignkey")
    op.drop_constraint("fk_participants_transport_organisation_id", "participants_transport", type_="foreignkey")
    op.drop_constraint("fk_remboursements_transport_requisition_id", "remboursements_transport", type_="foreignkey")
    op.drop_constraint("fk_remboursements_transport_organisation_id", "remboursements_transport", type_="foreignkey")
    op.drop_constraint("fk_requisition_status_history_organisation_id", "requisition_status_history", type_="foreignkey")
    op.drop_constraint("fk_requisition_approvers_organisation_id", "requisition_approvers", type_="foreignkey")
    op.drop_constraint("fk_requisition_annexes_organisation_id", "requisition_annexes", type_="foreignkey")
    op.drop_constraint("fk_lignes_requisition_requisition_id", "lignes_requisition", type_="foreignkey")
    op.drop_constraint("fk_lignes_requisition_organisation_id", "lignes_requisition", type_="foreignkey")
    op.drop_constraint("fk_dossiers_requisition_organisation_id", "dossiers_requisition", type_="foreignkey")

    op.drop_index("ix_transferts_internes_organisation_id", table_name="transferts_internes")
    op.drop_index("ix_participants_transport_organisation_id", table_name="participants_transport")
    op.drop_index("ix_remboursements_transport_organisation_id", table_name="remboursements_transport")
    op.drop_index("ix_requisition_status_history_organisation_id", table_name="requisition_status_history")
    op.drop_index("ix_requisition_approvers_organisation_id", table_name="requisition_approvers")
    op.drop_index("ix_requisition_annexes_organisation_id", table_name="requisition_annexes")
    op.drop_index("ix_lignes_requisition_organisation_id", table_name="lignes_requisition")
    op.drop_index("ix_dossiers_requisition_organisation_id", table_name="dossiers_requisition")

    op.drop_column("transferts_internes", "organisation_id")
    op.drop_column("participants_transport", "organisation_id")
    op.drop_column("remboursements_transport", "organisation_id")
    op.drop_column("requisition_status_history", "organisation_id")
    op.drop_column("requisition_approvers", "organisation_id")
    op.drop_column("requisition_annexes", "organisation_id")
    op.drop_column("lignes_requisition", "organisation_id")
    op.drop_column("dossiers_requisition", "organisation_id")
