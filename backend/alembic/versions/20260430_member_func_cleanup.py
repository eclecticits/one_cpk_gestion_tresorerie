"""Cleanup duplicate member functions by canonical default labels.

Revision ID: 20260430_member_clean
Revises: 20260430_member_defs
Create Date: 2026-04-30
"""

from __future__ import annotations

from alembic import op


revision = "20260430_member_clean"
down_revision = "20260430_member_defs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    canonical_pairs = [
        ("president", "Président(e)"),
        ("vicepresident", "Vice-président(e)"),
        ("rapporteur", "Rapporteur"),
        ("rapporteuradjoint", "Rapporteur adjoint"),
        ("tresorier", "Trésorier"),
        ("tresoriereadjoint", "Trésorier(e) adjoint"),
        ("secretaireexecutif", "Secrétaire exécutif"),
        ("assistant", "Assistant(e)"),
    ]

    for key, canonical_label in canonical_pairs:
        escaped = canonical_label.replace("'", "''")
        op.execute(
            f"""
            WITH canonical AS (
                SELECT organisation_id, id
                FROM service_member_functions
                WHERE label = '{escaped}'
            ),
            duplicates AS (
                SELECT smf.organisation_id, smf.id
                FROM service_member_functions smf
                JOIN canonical c ON c.organisation_id = smf.organisation_id
                WHERE smf.id <> c.id
                  AND regexp_replace(lower(translate(smf.label,
                    'àáâäãåèéêëìíîïòóôöõùúûüýÿçñÀÁÂÄÃÅÈÉÊËÌÍÎÏÒÓÔÖÕÙÚÛÜÝÇÑ',
                    'aaaaaaeeeeiiiiooooouuuuyycnAAAAAAEEEEIIIIOOOOOUUUUYCN'
                  )), '[^a-z0-9]+', '', 'g') = '{key}'
            )
            UPDATE commission_members cm
            SET function_id = c.id
            FROM duplicates d
            JOIN canonical c ON c.organisation_id = d.organisation_id
            WHERE cm.function_id = d.id
            """
        )
        op.execute(
            f"""
            DELETE FROM service_member_functions smf
            USING service_member_functions canonical
            WHERE smf.id <> canonical.id
              AND smf.organisation_id = canonical.organisation_id
              AND canonical.label = '{escaped}'
              AND regexp_replace(lower(translate(smf.label,
                'àáâäãåèéêëìíîïòóôöõùúûüýÿçñÀÁÂÄÃÅÈÉÊËÌÍÎÏÒÓÔÖÕÙÚÛÜÝÇÑ',
                'aaaaaaeeeeiiiiooooouuuuyycnAAAAAAEEEEIIIIOOOOOUUUUYCN'
              )), '[^a-z0-9]+', '', 'g') = '{key}'
            """
        )


def downgrade() -> None:
    pass
