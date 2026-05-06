"""Canonicalize legacy administration services.

Revision ID: 20260504_service_admin_canon
Revises: 20260504_service_name_uniq
Create Date: 2026-05-04
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260504_service_admin_canon"
down_revision = "20260504_service_name_uniq"
branch_labels = None
depends_on = None


CANONICAL_CODE = "ADM"
CANONICAL_LABEL = "Administration"
ADMIN_CODES = {"ADM", "ADMIN"}
ADMIN_LABELS = {"administration", "administrations"}


def _normalize_code(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split()).upper()
    if normalized == "ADMIN":
        return "ADM"
    return normalized


def _normalize_label(value: str | None) -> str:
    normalized = " ".join((value or "").strip().split()).lower()
    if normalized in ADMIN_LABELS:
        return "administration"
    return normalized


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

        conn.execute(
            document_sequences.update()
            .where(document_sequences.c.id == existing["id"])
            .values(
                counter=max(int(existing["counter"] or 0), int(row["counter"] or 0)),
                updated_at=max(existing["updated_at"], row["updated_at"]),
            )
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
        " ".join((row["label"] or "").strip().split()).lower(): row["id"]
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
        label_key = " ".join((row["label"] or "").strip().split()).lower()
        target_function_id = canonical_by_label.get(label_key)
        if target_function_id is None:
            target_function_id = conn.execute(
                service_member_functions.insert()
                .values(
                    label=" ".join((row["label"] or "").strip().split()),
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
        sa.column("code", sa.String),
        sa.column("libelle", sa.String),
        sa.column("is_active", sa.Boolean),
    )
    users = sa.table("users", sa.column("id", sa.String), sa.column("service_id", sa.Integer))
    user_services = sa.table("user_services", sa.column("user_id", sa.String), sa.column("service_id", sa.Integer))
    requisitions = sa.table("requisitions", sa.column("id", sa.Integer), sa.column("service_id", sa.Integer))
    encaissements = sa.table("encaissements", sa.column("id", sa.Integer), sa.column("service_id", sa.Integer))
    sorties_fonds = sa.table("sorties_fonds", sa.column("id", sa.Integer), sa.column("service_id", sa.Integer))
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
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("doc_type", sa.String),
        sa.column("year", sa.Integer),
        sa.column("tenant_id", sa.Integer),
        sa.column("service_id", sa.Integer),
        sa.column("counter", sa.Integer),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )

    service_rows = conn.execute(
        sa.select(
            services.c.id,
            services.c.organisation_id,
            services.c.code,
            services.c.libelle,
            services.c.is_active,
        ).order_by(services.c.organisation_id.asc(), services.c.id.asc())
    ).mappings().all()

    by_org: dict[int, list[dict]] = {}
    for row in service_rows:
        by_org.setdefault(int(row["organisation_id"]), []).append(dict(row))

    for organisation_id, rows in by_org.items():
        admin_candidates = [
            row
            for row in rows
            if _normalize_code(row["code"]) == CANONICAL_CODE or _normalize_label(row["libelle"]) == "administration"
        ]
        if not admin_candidates:
            continue

        exact_canonical = next(
            (
                row for row in admin_candidates
                if " ".join((row["code"] or "").strip().split()).upper() == CANONICAL_CODE
                and " ".join((row["libelle"] or "").strip().split()) == CANONICAL_LABEL
            ),
            None,
        )
        canonical = exact_canonical or next(
            (
                row for row in admin_candidates
                if " ".join((row["code"] or "").strip().split()).upper() == CANONICAL_CODE
            ),
            admin_candidates[0],
        )

        conn.execute(
            services.update()
            .where(services.c.id == canonical["id"])
            .values(code=CANONICAL_CODE, libelle=CANONICAL_LABEL, is_active=True)
        )

        for duplicate in admin_candidates:
            if int(duplicate["id"]) == int(canonical["id"]):
                continue
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
                organisation_id=organisation_id,
                canonical_service_id=int(canonical["id"]),
                duplicate_service_id=int(duplicate["id"]),
            )

    op.create_index(
        "uq_services_org_code_norm",
        "services",
        [
            sa.text("organisation_id"),
            sa.text("regexp_replace(upper(btrim(code)), '\\s+', ' ', 'g')"),
        ],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_services_org_code_norm", table_name="services")
