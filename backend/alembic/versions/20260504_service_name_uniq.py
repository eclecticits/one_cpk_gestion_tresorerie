"""Prevent duplicate services by normalized label.

Revision ID: 20260504_service_name_uniq
Revises: 20260504_tenant_boot
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260504_service_name_uniq"
down_revision = "20260504_tenant_boot"
branch_labels = None
depends_on = None


def _normalize_service_label(value: str | None) -> str:
    return " ".join((value or "").strip().split()).lower()


def _merge_document_sequences(conn, document_sequences, *, canonical_service_id: int, duplicate_service_id: int) -> None:
    rows = conn.execute(
        sa.select(
            document_sequences.c.id,
            document_sequences.c.doc_type,
            document_sequences.c.year,
            document_sequences.c.tenant_id,
            document_sequences.c.counter,
            document_sequences.c.updated_at,
        ).where(document_sequences.c.service_id == duplicate_service_id)
    ).mappings().all()

    for row in rows:
        existing = conn.execute(
            sa.select(
                document_sequences.c.id,
                document_sequences.c.counter,
                document_sequences.c.updated_at,
            ).where(
                document_sequences.c.doc_type == row["doc_type"],
                document_sequences.c.year == row["year"],
                document_sequences.c.tenant_id == row["tenant_id"],
                document_sequences.c.service_id == canonical_service_id,
            )
        ).mappings().first()
        if existing is None:
            conn.execute(
                document_sequences.update()
                .where(document_sequences.c.id == row["id"])
                .values(service_id=canonical_service_id)
            )
            continue

        next_counter = max(int(existing["counter"] or 0), int(row["counter"] or 0))
        next_updated_at = max(existing["updated_at"], row["updated_at"])
        conn.execute(
            document_sequences.update()
            .where(document_sequences.c.id == existing["id"])
            .values(counter=next_counter, updated_at=next_updated_at)
        )
        conn.execute(document_sequences.delete().where(document_sequences.c.id == row["id"]))


def _merge_service_member_functions(
    conn,
    service_member_functions,
    commission_members,
    *,
    organisation_id: int,
    canonical_service_id: int,
    duplicate_service_id: int,
) -> None:
    canonical_rows = conn.execute(
        sa.select(
            service_member_functions.c.id,
            service_member_functions.c.label,
        ).where(
            service_member_functions.c.organisation_id == organisation_id,
            service_member_functions.c.service_id == canonical_service_id,
        )
    ).mappings().all()
    canonical_by_label = {
        _normalize_service_label(row["label"]): row["id"]
        for row in canonical_rows
    }

    duplicate_rows = conn.execute(
        sa.select(
            service_member_functions.c.id,
            service_member_functions.c.label,
            service_member_functions.c.sort_order,
            service_member_functions.c.is_default,
            service_member_functions.c.is_active,
            service_member_functions.c.created_at,
            service_member_functions.c.updated_at,
        ).where(
            service_member_functions.c.organisation_id == organisation_id,
            service_member_functions.c.service_id == duplicate_service_id,
        )
    ).mappings().all()

    for row in duplicate_rows:
        label_key = _normalize_service_label(row["label"])
        target_function_id = canonical_by_label.get(label_key)
        if target_function_id is None:
            target_function_id = conn.execute(
                service_member_functions.insert()
                .values(
                    label=row["label"],
                    sort_order=row["sort_order"],
                    is_default=row["is_default"],
                    is_active=row["is_active"],
                    organisation_id=organisation_id,
                    service_id=canonical_service_id,
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                .returning(service_member_functions.c.id)
            ).scalar_one()
            canonical_by_label[label_key] = target_function_id

        conn.execute(
            commission_members.update()
            .where(commission_members.c.function_id == row["id"])
            .values(function_id=target_function_id)
        )


def _merge_duplicate_service(
    conn,
    services,
    users,
    user_services,
    requisitions,
    encaissements,
    sorties_fonds,
    service_rubriques,
    commission_members,
    service_member_functions,
    document_sequences,
    *,
    organisation_id: int,
    canonical_service_id: int,
    duplicate_service_id: int,
) -> None:
    canonical_user_services = user_services.alias("canonical_user_services")
    canonical_service_rubriques = service_rubriques.alias("canonical_service_rubriques")

    _merge_service_member_functions(
        conn,
        service_member_functions,
        commission_members,
        organisation_id=organisation_id,
        canonical_service_id=canonical_service_id,
        duplicate_service_id=duplicate_service_id,
    )

    conn.execute(users.update().where(users.c.service_id == duplicate_service_id).values(service_id=canonical_service_id))

    conn.execute(
        user_services.delete().where(
            user_services.c.service_id == duplicate_service_id,
            sa.exists(
                sa.select(1).where(
                    canonical_user_services.c.user_id == user_services.c.user_id,
                    canonical_user_services.c.service_id == canonical_service_id,
                )
            ),
        )
    )
    conn.execute(
        user_services.update()
        .where(user_services.c.service_id == duplicate_service_id)
        .values(service_id=canonical_service_id)
    )

    conn.execute(requisitions.update().where(requisitions.c.service_id == duplicate_service_id).values(service_id=canonical_service_id))
    conn.execute(encaissements.update().where(encaissements.c.service_id == duplicate_service_id).values(service_id=canonical_service_id))
    conn.execute(sorties_fonds.update().where(sorties_fonds.c.service_id == duplicate_service_id).values(service_id=canonical_service_id))

    conn.execute(
        service_rubriques.delete().where(
            service_rubriques.c.service_id == duplicate_service_id,
            sa.exists(
                sa.select(1).where(
                    canonical_service_rubriques.c.budget_poste_id == service_rubriques.c.budget_poste_id,
                    canonical_service_rubriques.c.service_id == canonical_service_id,
                )
            ),
        )
    )
    conn.execute(
        service_rubriques.update()
        .where(service_rubriques.c.service_id == duplicate_service_id)
        .values(service_id=canonical_service_id)
    )

    conn.execute(
        commission_members.update()
        .where(commission_members.c.service_id == duplicate_service_id)
        .values(service_id=canonical_service_id)
    )

    _merge_document_sequences(
        conn,
        document_sequences,
        canonical_service_id=canonical_service_id,
        duplicate_service_id=duplicate_service_id,
    )

    conn.execute(services.delete().where(services.c.id == duplicate_service_id))


def upgrade() -> None:
    conn = op.get_bind()

    services = sa.table(
        "services",
        sa.column("id", sa.Integer),
        sa.column("organisation_id", sa.Integer),
        sa.column("libelle", sa.String),
    )
    users = sa.table(
        "users",
        sa.column("id", sa.String),
        sa.column("service_id", sa.Integer),
    )
    user_services = sa.table(
        "user_services",
        sa.column("user_id", sa.String),
        sa.column("service_id", sa.Integer),
    )
    requisitions = sa.table(
        "requisitions",
        sa.column("id", sa.Integer),
        sa.column("service_id", sa.Integer),
    )
    encaissements = sa.table(
        "encaissements",
        sa.column("id", sa.Integer),
        sa.column("service_id", sa.Integer),
    )
    sorties_fonds = sa.table(
        "sorties_fonds",
        sa.column("id", sa.Integer),
        sa.column("service_id", sa.Integer),
    )
    service_rubriques = sa.table(
        "service_rubriques",
        sa.column("id", sa.Integer),
        sa.column("service_id", sa.Integer),
        sa.column("budget_poste_id", sa.Integer),
    )
    commission_members = sa.table(
        "commission_members",
        sa.column("id", sa.Integer),
        sa.column("service_id", sa.Integer),
        sa.column("function_id", sa.Integer),
    )
    service_member_functions = sa.table(
        "service_member_functions",
        sa.column("id", sa.Integer),
        sa.column("label", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("is_default", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("organisation_id", sa.Integer),
        sa.column("service_id", sa.Integer),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    document_sequences = sa.table(
        "document_sequences",
        sa.column("id", sa.String),
        sa.column("doc_type", sa.String),
        sa.column("year", sa.Integer),
        sa.column("tenant_id", sa.Integer),
        sa.column("service_id", sa.Integer),
        sa.column("counter", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    duplicate_groups = conn.execute(
        sa.text(
            """
            WITH ranked AS (
                SELECT
                    id,
                    organisation_id,
                    regexp_replace(lower(btrim(libelle)), '\\s+', ' ', 'g') AS libelle_norm,
                    row_number() OVER (
                        PARTITION BY organisation_id, regexp_replace(lower(btrim(libelle)), '\\s+', ' ', 'g')
                        ORDER BY id ASC
                    ) AS rn
                FROM services
            )
            SELECT
                organisation_id,
                libelle_norm,
                array_agg(id ORDER BY id ASC) AS service_ids
            FROM ranked
            GROUP BY organisation_id, libelle_norm
            HAVING count(*) > 1
            """
        )
    ).mappings().all()

    for group in duplicate_groups:
        service_ids = list(group["service_ids"] or [])
        if len(service_ids) < 2:
            continue
        canonical_service_id = int(service_ids[0])
        for duplicate_service_id in (int(value) for value in service_ids[1:]):
            _merge_duplicate_service(
                conn,
                services,
                users,
                user_services,
                requisitions,
                encaissements,
                sorties_fonds,
                service_rubriques,
                commission_members,
                service_member_functions,
                document_sequences,
                organisation_id=int(group["organisation_id"]),
                canonical_service_id=canonical_service_id,
                duplicate_service_id=duplicate_service_id,
            )

    op.create_index(
        "uq_services_org_libelle_norm",
        "services",
        [
            sa.text("organisation_id"),
            sa.text("regexp_replace(lower(btrim(libelle)), '\\s+', ' ', 'g')"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_services_org_libelle_norm", table_name="services")
