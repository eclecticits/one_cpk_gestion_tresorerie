"""Lecture seule et capture immuable du référentiel officiel des experts."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.expert_comptable import ExpertComptable
from app.models.user import User
from .audit import record_tableau_audit
from .models import TableauReferenceMember, TableauReferenceSnapshot


def normalize_official_order(value: str | None) -> str:
    """Clé de rapprochement ; la graphie officielle reste conservée séparément."""
    return "".join(str(value or "").strip().upper().split())


def _json_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class OfficialExpertRecord:
    id: uuid.UUID
    numero_ordre: str
    numero_ordre_normalise: str
    values: dict[str, Any]
    active: bool
    province_attache: str | None
    row_checksum: str


async def list_official_experts_read_only(db: AsyncSession) -> list[OfficialExpertRecord]:
    """Retourne des valeurs détachées : aucun objet ORM officiel n'est exposé."""
    rows = (await db.execute(
        select(
            ExpertComptable.id,
            ExpertComptable.numero_ordre,
            ExpertComptable.nom_denomination,
            ExpertComptable.type_ec,
            ExpertComptable.categorie_personne,
            ExpertComptable.statut_professionnel,
            ExpertComptable.sexe,
            ExpertComptable.telephone,
            ExpertComptable.email,
            ExpertComptable.province_attache,
            ExpertComptable.nif,
            ExpertComptable.cabinet_attache,
            ExpertComptable.nom_employeur,
            ExpertComptable.raison_sociale,
            ExpertComptable.associe_gerant,
            ExpertComptable.active,
            ExpertComptable.created_at,
        ).order_by(ExpertComptable.numero_ordre, ExpertComptable.id)
    )).all()

    result: list[OfficialExpertRecord] = []
    for row in rows:
        values = {
            "official_expert_id": str(row.id),
            "numero_ordre": row.numero_ordre,
            "nom_denomination": row.nom_denomination,
            "type_ec": row.type_ec,
            "categorie_personne": row.categorie_personne,
            "statut_professionnel": row.statut_professionnel,
            "sexe": row.sexe,
            "telephone": row.telephone,
            "email": row.email,
            "province_attache": row.province_attache,
            "nif": row.nif,
            "cabinet_attache": row.cabinet_attache,
            "nom_employeur": row.nom_employeur,
            "raison_sociale": row.raison_sociale,
            "associe_gerant": row.associe_gerant,
            "active": bool(row.active),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        result.append(OfficialExpertRecord(
            id=row.id,
            numero_ordre=row.numero_ordre,
            numero_ordre_normalise=normalize_official_order(row.numero_ordre),
            values=values,
            active=bool(row.active),
            province_attache=row.province_attache,
            row_checksum=_json_hash(values),
        ))
    return result


async def capture_official_snapshot(
    db: AsyncSession,
    user: User,
    *,
    scope_type: str = "NATIONAL",
    scope_definition: dict[str, Any] | None = None,
) -> TableauReferenceSnapshot:
    """Capture explicite et auditée ; aucune écriture dans ``experts_comptables``."""
    if scope_type != "NATIONAL":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Seul le snapshot national est disponible tant que le périmètre explicite n'est pas défini.",
        )

    official_rows = await list_official_experts_read_only(db)
    registry_checksum = _json_hash([row.row_checksum for row in official_rows])
    captured_at = datetime.now(timezone.utc)
    snapshot = TableauReferenceSnapshot(
        created_by=user.id,
        captured_at=captured_at,
        sealed_at=None,
        source_name="experts_comptables",
        scope_type=scope_type,
        scope_organisation_id=None,
        scope_definition_json=scope_definition or {"mode": "all", "include_without_province": True},
        registry_checksum=registry_checksum,
        member_count=len(official_rows),
        metadata_json={"immutable": True},
    )
    db.add(snapshot)
    try:
        await db.flush()
        for row in official_rows:
            db.add(TableauReferenceMember(
                snapshot_id=snapshot.id,
                official_expert_id=row.id,
                numero_ordre=row.numero_ordre,
                numero_ordre_normalise=row.numero_ordre_normalise,
                active=row.active,
                province_attache=row.province_attache,
                official_values=row.values,
                row_checksum=row.row_checksum,
            ))
        await db.flush()
        snapshot.sealed_at = datetime.now(timezone.utc)
        await record_tableau_audit(
            db,
            organisation_id=user.organisation_id,
            user_id=user.id,
            action="tableau.reference_snapshot.create",
            target_type="tableau_reference_snapshot",
            target_id=snapshot.id,
            metadata_json={
                "scope_type": scope_type,
                "member_count": len(official_rows),
                "registry_checksum": registry_checksum,
            },
        )
        await db.commit()
        await db.refresh(snapshot)
        return snapshot
    except Exception:
        await db.rollback()
        raise
