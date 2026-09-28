"""Passé 30 minutes, qui a le droit d'annuler une sortie le peut encore.

La fenêtre de 30 minutes laissait une erreur découverte tard sans correction
possible. Tout porteur de `cancel_sortie_fonds` annule désormais hors délai, à
deux conditions : un motif, et une trace « annulation tardive » dans l'audit.
Sans la permission, rien ne change : le refus tombe avant tout calcul de délai.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.sorties_fonds import update_sortie_statut
from app.models.audit_log import AuditLog
from app.models.caisse_centrale import CaisseCentrale
from app.schemas.sortie_fonds import SortieFondsStatusUpdate
from tests.test_annulation_permissions import (  # noqa: F401 — `registre` est une fixture
    _FakeRequest,
    _contexte,
    _sortie,
    registre,
)


async def _sortie_vieille_de(db, org, user, *, minutes: int):
    sortie = await _sortie(db, org, user)
    sortie.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    await db.commit()
    return sortie


async def _annuler(db, org, user, sortie, *, motif: str | None):
    return await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation=motif),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )


async def _trace(db, sortie) -> dict:
    log = await db.scalar(
        select(AuditLog)
        .where(AuditLog.entity_id == str(sortie.id), AuditLog.action == "SORTIE_CANCELLED")
    )
    assert log is not None
    return log.new_value


@pytest.mark.parametrize("role", ["admin", "comptable", "secretaire_executif"])
@pytest.mark.asyncio
async def test_le_porteur_de_la_permission_annule_apres_30_minutes(db_session, registre, role):
    org, user = await _contexte(
        db_session, role_utilisateur=role, permissions=("cancel_sortie_fonds",), registre=registre)
    sortie = await _sortie_vieille_de(db_session, org, user, minutes=120)

    rendu = await _annuler(db_session, org, user, sortie, motif="Erreur découverte au rapprochement")

    assert rendu.statut == "ANNULEE"
    assert rendu.motif_annulation == "Erreur découverte au rapprochement"
    # L'argent revient à la caisse, comme pour une annulation dans le délai.
    caisse = await db_session.scalar(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org.id))
    await db_session.refresh(caisse)
    assert caisse.solde_usd == Decimal("1060")
    assert (await _trace(db_session, sortie))["annulation_tardive"] is True


@pytest.mark.asyncio
async def test_hors_delai_le_motif_est_obligatoire(db_session, registre):
    org, user = await _contexte(
        db_session, role_utilisateur="comptable", permissions=("cancel_sortie_fonds",), registre=registre)
    sortie = await _sortie_vieille_de(db_session, org, user, minutes=120)

    with pytest.raises(HTTPException) as erreur:
        await _annuler(db_session, org, user, sortie, motif="   ")

    assert erreur.value.status_code == 400
    assert "Motif obligatoire" in erreur.value.detail


@pytest.mark.parametrize("role", ["caissier", "tresorier"])
@pytest.mark.asyncio
async def test_sans_la_permission_rien_ne_change(db_session, registre, role):
    org, user = await _contexte(
        db_session, role_utilisateur=role, permissions=("menu_sorties_fonds",), registre=registre)
    sortie = await _sortie_vieille_de(db_session, org, user, minutes=120)

    with pytest.raises(HTTPException) as erreur:
        await _annuler(db_session, org, user, sortie, motif="Saisie en double")

    assert erreur.value.status_code == 403


@pytest.mark.asyncio
async def test_dans_le_delai_l_annulation_n_est_pas_marquee_tardive(db_session, registre):
    org, user = await _contexte(
        db_session, role_utilisateur="comptable", permissions=("cancel_sortie_fonds",), registre=registre)
    sortie = await _sortie_vieille_de(db_session, org, user, minutes=5)

    rendu = await _annuler(db_session, org, user, sortie, motif="Saisie en double")

    assert rendu.statut == "ANNULEE"
    assert (await _trace(db_session, sortie))["annulation_tardive"] is False
