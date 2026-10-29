"""À valoir sur une sortie directe programmée, sans passer par une réquisition."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement, update_ordre_decaissement
from app.api.v1.endpoints.reports import journal_tresorerie
from app.models.caisse_centrale import CaisseCentrale
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.organisation import Organisation
from app.models.service import Service
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.ordre_decaissement import OrdreDecaissementCreate

PAYE_LE = datetime(2026, 9, 15, 10, tzinfo=timezone.utc)


async def _contexte(db):
    org = Organisation(nom="À valoir direct", slug=f"avd-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Secrétariat", is_active=True)
    user = User(id=uuid.uuid4(), email=f"avd-{uuid.uuid4().hex[:6]}@example.com", role="admin", organisation_id=org.id)
    db.add_all([service, user])
    db.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=Decimal("5000"), solde_cdf=0))
    await db.commit()
    return org, user, service


def _payload(service, **extra) -> OrdreDecaissementCreate:
    return OrdreDecaissementCreate(
        requisition_id=None, beneficiaire="Jean MUKENDI", montant=Decimal("60"),
        devise="USD", service_id=service.id, motif="Carburant mission", **extra,
    )


def test_a_valoir_sans_instance_est_refuse():
    with pytest.raises(ValidationError):
        OrdreDecaissementCreate(
            beneficiaire="Jean", montant=Decimal("10"), service_id=1, motif="x", a_valoir=True,
        )


@pytest.mark.asyncio
async def test_sortie_directe_a_valoir_puis_corrigee(db_session):
    org, user, service = await _contexte(db_session)
    appel = dict(request=None, user=user, tenant_id=org.id, db=db_session)

    ordre = await create_ordre_decaissement(
        payload=_payload(
            service, a_valoir=True, instance_beneficiaire=" Conseil National ", notes_a_valoir="Remboursé en octobre"
        ),
        **appel,
    )
    assert ordre["a_valoir"] is True
    assert ordre["instance_beneficiaire"] == "Conseil National"
    assert ordre["notes_a_valoir"] == "Remboursé en octobre"

    # Décocher la case vide l'instance et la note.
    corrige = await update_ordre_decaissement(
        ordre_id=str(ordre["id"]),
        payload=_payload(service, instance_beneficiaire="Conseil National", notes_a_valoir="x"),
        **appel,
    )
    assert corrige["a_valoir"] is False
    assert corrige["instance_beneficiaire"] is None
    assert corrige["notes_a_valoir"] is None


@pytest.mark.asyncio
async def test_le_journal_signale_la_sortie_directe_a_valoir(db_session):
    org, user, service = await _contexte(db_session)
    appel = dict(request=None, user=user, tenant_id=org.id, db=db_session)
    cree = await create_ordre_decaissement(
        payload=_payload(service, a_valoir=True, instance_beneficiaire="Conseil National"), **appel
    )

    # Paiement par la caisse : la sortie n'a pas de réquisition, l'ordre la porte.
    sortie = SortieFonds(
        organisation_id=org.id, type_sortie="autre", reference_numero=f"SF-{uuid.uuid4().hex[:6]}",
        montant_paye=Decimal("60"), date_paiement=PAYE_LE, mode_paiement="cash", devise="USD",
        canal="CAISSE", statut="VALIDE", motif="Carburant mission", beneficiaire="Jean MUKENDI",
    )
    db_session.add(sortie)
    await db_session.flush()
    ordre = await db_session.get(OrdreDecaissement, uuid.UUID(str(cree["id"])))
    ordre.sortie_fonds_id = sortie.id
    ordre.statut = "PAYE"
    await db_session.commit()

    releve = await journal_tresorerie(
        canal="CAISSE", devise="USD", date_debut="2026-09-01", date_fin="2026-09-30",
        user=user, db=db_session, tenant_id=org.id,
    )
    ligne = next(l for l in releve.lignes if l.libelle_base == "Carburant mission")
    assert ligne.a_valoir is True
    assert "Conseil National" in ligne.a_valoir_alerte
