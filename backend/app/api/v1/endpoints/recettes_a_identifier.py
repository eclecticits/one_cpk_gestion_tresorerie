"""Recettes à identifier : saisie, suivi et identification.

Voir `app/services/recettes_a_identifier.py` pour le principe. L'identification
vers une NOUVELLE recette passe par `POST /encaissements` avec
`identification_source_id` : la note se saisit avec le formulaire habituel
(client, articles, tarifs, postes). Ici ne vivent que la saisie du versement,
son suivi et le règlement d'une note déjà émise.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_tenant_id, get_current_user, has_permission
from app.db.session import get_db
from app.models.encaissement import Encaissement
from app.models.user import User
from app.services.audit_service import get_request_ip
from app.services.client_receipt_email import schedule_client_payment_email
from app.services.encaissement_payments import record_encaissement_payment
from app.services.recettes_a_identifier import (
    creer_recette_a_identifier,
    lister_recettes_a_identifier,
    pistes_identification,
)
from app.services.report_cache import invalidate_report_summary_cache


router = APIRouter()

PERMISSION_IDENTIFIER = "treso.encaissements.identifier"


class RecetteAIdentifierCreate(BaseModel):
    compte_bancaire_id: int
    #: Dans la devise du compte bancaire, tel que le relevé l'affiche.
    montant: Decimal = Field(gt=0)
    date_valeur: date
    #: Libellé du relevé, recopié tel quel : c'est lui qu'on interrogera pour
    #: retrouver le payeur.
    libelle: str = Field(min_length=1, max_length=500)
    reference: str | None = Field(default=None, max_length=100)
    mode_paiement: Literal["virement", "cheque", "mobile_money", "card"] = "virement"


class ReglerNotePayload(BaseModel):
    encaissement_id: uuid.UUID
    montant: Decimal = Field(gt=0)


def _uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="Identifiant invalide")


@router.get("", dependencies=[Depends(has_permission("encaissements"))])
async def lister(
    statut: Literal["ouvertes", "toutes"] = Query("ouvertes"),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await lister_recettes_a_identifier(
        db, organisation_id=tenant_id, ouvertes_seulement=statut == "ouvertes"
    )


@router.post("", status_code=201, dependencies=[Depends(has_permission("encaissements"))])
async def creer(
    payload: RecetteAIdentifierCreate,
    request: Request,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if payload.date_valeur > datetime.now(timezone.utc).date():
        raise HTTPException(status_code=400, detail="La date de valeur ne peut pas être dans le futur")
    recette = await creer_recette_a_identifier(
        db,
        organisation_id=tenant_id,
        compte_bancaire_id=payload.compte_bancaire_id,
        montant=payload.montant,
        date_valeur=datetime.combine(payload.date_valeur, time(12, 0), tzinfo=timezone.utc),
        libelle=payload.libelle,
        reference=payload.reference,
        mode_paiement=payload.mode_paiement,
        user_id=user.id,
        ip_address=get_request_ip(request),
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    return {"id": str(recette.id), "numero": recette.numero_recu}


@router.get("/{recette_id}/pistes", dependencies=[Depends(has_permission(PERMISSION_IDENTIFIER))])
async def pistes(
    recette_id: str,
    q: str | None = Query(None, max_length=100),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    return await pistes_identification(db, organisation_id=tenant_id, source_id=_uuid(recette_id), recherche=q)


@router.post("/{recette_id}/regler-note", dependencies=[Depends(has_permission(PERMISSION_IDENTIFIER))])
async def regler_note(
    recette_id: str,
    payload: ReglerNotePayload,
    request: Request,
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
    tenant_id: int = Depends(get_current_tenant_id),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Le versement inconnu était le règlement d'une note de débit déjà émise."""
    source_id = _uuid(recette_id)
    source = (
        await db.execute(
            select(Encaissement).where(Encaissement.id == source_id, Encaissement.organisation_id == tenant_id)
        )
    ).scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Recette à identifier introuvable")
    note = (
        await db.execute(
            select(Encaissement).where(
                Encaissement.id == payload.encaissement_id,
                Encaissement.organisation_id == tenant_id,
                Encaissement.is_deleted.is_(False),
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Note de débit introuvable")
    if (note.nature_mouvement or "BUDGETAIRE").upper() != "BUDGETAIRE":
        raise HTTPException(status_code=400, detail="Seule une note de débit budgétaire se règle ainsi")

    versement = await record_encaissement_payment(
        db,
        organisation_id=tenant_id,
        encaissement_id=note.id,
        montant=payload.montant,
        mode_paiement=source.mode_paiement,
        reference=source.reference,
        notes=f"Identifié depuis la recette {source.numero_recu}",
        user_id=user.id,
        ip_address=get_request_ip(request),
        identification_source_id=source.id,
    )
    await db.commit()
    await invalidate_report_summary_cache(tenant_id)
    await db.refresh(note)
    await schedule_client_payment_email(
        db,
        background_tasks,
        note,
        tenant_id,
        montant_recu=versement.montant,
        mode_paiement_recu=source.mode_paiement,
    )
    return {"versement_id": str(versement.id), "encaissement_id": str(note.id), "numero_recu": note.numero_recu}
