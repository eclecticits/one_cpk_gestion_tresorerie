from __future__ import annotations

import logging
import socket
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.config import settings
from app.db.session import get_db
from app.models.user import User

router = APIRouter()
logger = logging.getLogger("onec_cpk_debug")


def _sanitize_dsn(dsn: str) -> str:
    try:
        parsed = urlparse(dsn)
        if parsed.password:
            netloc = parsed.netloc.replace(parsed.password, "****")
        else:
            netloc = parsed.netloc
        return parsed._replace(netloc=netloc).geturl()
    except Exception:
        return "(invalid dsn)"


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _end_exclusive(day: date | None) -> date | None:
    if not day:
        return None
    return day + timedelta(days=1)


@router.get("/ping")
async def ping(
    request: Request,
    user: User = Depends(require_roles(["admin"])),
) -> dict:
    return {
        "service": "onec-cpk-api",
        "version": settings.env,
        "time": datetime.now(timezone.utc).isoformat(),
        "hostname": socket.gethostname(),
        "port": request.url.port,
        "db_dsn_sanitized": _sanitize_dsn(settings.database_url),
    }


@router.get("/finance-sanity")
async def finance_sanity(
    start: str = Query(..., description="YYYY-MM-DD"),
    end: str = Query(..., description="YYYY-MM-DD"),
    user: User = Depends(require_roles(["admin"])),
    db: AsyncSession = Depends(get_db),
) -> dict:
    meta: dict = {}
    found_tables: list[str] = []
    columns_by_table: dict[str, list[str]] = {}

    try:
        start_date = _parse_date(start)
        end_date = _parse_date(end)
        if not start_date or not end_date:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid start/end date")
        end_excl = _end_exclusive(end_date)

        logger.info(
            "finance-sanity start=%s end=%s db=%s",
            start_date,
            end_date,
            _sanitize_dsn(settings.database_url),
        )

        meta_res = await db.execute(
            text(
                """
                SELECT current_database() AS db_name,
                       current_user AS current_user,
                       inet_server_addr() AS server_addr,
                       inet_server_port() AS server_port,
                       current_schema() AS current_schema
                """
            )
        )
        meta = meta_res.mappings().first() or {}

        candidates = [
            "sorties_fonds",
            "sorties",
            "encaissements",
            "encaissement",
            "payments",
            "paiements",
        ]
        tables_res = await db.execute(
            text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'public'
                ORDER BY table_name
                """
            )
        )
        found_tables = [row[0] for row in tables_res.all()]

        for table in candidates:
            if table not in found_tables:
                continue
            cols_res = await db.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                      AND table_name = :table_name
                    ORDER BY column_name
                    """
                ),
                {"table_name": table},
            )
            columns_by_table[table] = [row[0] for row in cols_res.all()]

        if "sorties_fonds" not in found_tables or "encaissements" not in found_tables:
            return {
                "db": {
                    "db_name": meta.get("db_name"),
                    "current_user": meta.get("current_user"),
                    "server_addr": meta.get("server_addr"),
                    "server_port": meta.get("server_port"),
                    "current_schema": meta.get("current_schema"),
                    "database_url": _sanitize_dsn(settings.database_url),
                },
                "found": {"tables": found_tables, "columns_by_table": columns_by_table},
                "error": {
                    "type": "missing_tables",
                    "message": "Required tables not found in current schema",
                    "hint": "Check DATABASE_URL or schema import",
                },
            }

        counts_res = await db.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM public.sorties_fonds) AS sorties_total,
                  (SELECT COUNT(*) FROM public.encaissements) AS encaissements_total
                """
            )
        )
        counts = counts_res.mappings().first() or {}

        last_sortie_res = await db.execute(
            text(
                """
                SELECT id,
                       montant_paye AS montant,
                       date_paiement AS date_metier,
                       created_at
                FROM public.sorties_fonds
                ORDER BY COALESCE(date_paiement, created_at) DESC
                LIMIT 1
                """
            )
        )
        last_sortie = last_sortie_res.mappings().first() or None

        in_range_date_res = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE date_paiement::date >= :start
                  AND date_paiement::date < :end_excl
                """
            ),
            {"start": start_date, "end_excl": end_excl},
        )
        in_range_date = in_range_date_res.mappings().first() or {}

        in_range_created_res = await db.execute(
            text(
                """
                SELECT COUNT(*) AS count,
                       COALESCE(SUM(montant_paye),0) AS total
                FROM public.sorties_fonds
                WHERE created_at::date >= :start
                  AND created_at::date < :end_excl
                """
            ),
            {"start": start_date, "end_excl": end_excl},
        )
        in_range_created = in_range_created_res.mappings().first() or {}

        return {
            "db": {
                "db_name": meta.get("db_name"),
                "current_user": meta.get("current_user"),
                "server_addr": meta.get("server_addr"),
                "server_port": meta.get("server_port"),
                "current_schema": meta.get("current_schema"),
                "database_url": _sanitize_dsn(settings.database_url),
            },
            "found": {"tables": found_tables, "columns_by_table": columns_by_table},
            "counts": {
                "sorties_total": counts.get("sorties_total"),
                "encaissements_total": counts.get("encaissements_total"),
            },
            "last_sortie": last_sortie,
            "range": {
                "start": start_date.isoformat(),
                "end": end_date.isoformat(),
                "count_sorties_in_range_by_date": in_range_date.get("count"),
                "sum_sorties_in_range_by_date": in_range_date.get("total"),
                "count_sorties_in_range_by_created_at": in_range_created.get("count"),
                "sum_sorties_in_range_by_created_at": in_range_created.get("total"),
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("finance-sanity failed")
        return {
            "db": {
                "db_name": meta.get("db_name"),
                "current_user": meta.get("current_user"),
                "server_addr": meta.get("server_addr"),
                "server_port": meta.get("server_port"),
                "current_schema": meta.get("current_schema"),
                "database_url": _sanitize_dsn(settings.database_url),
            },
            "found": {"tables": found_tables, "columns_by_table": columns_by_table},
            "error": {
                "type": type(exc).__name__,
                "message": str(exc),
                "hint": "Check table/column names and DATABASE_URL",
            },
        }
