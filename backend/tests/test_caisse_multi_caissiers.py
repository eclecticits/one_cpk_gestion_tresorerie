"""Plusieurs caissiers sur le même tenant : le tiroir reste juste.

Un tenant n'a qu'une caisse, et plusieurs agents encaissent dessus en même
temps. Ces tests portent sur ce que la concurrence peut casser sans jamais
lever d'erreur visible : un versement qui écrase l'autre, une séance ouverte
deux fois, un solde figé pendant qu'un versement entre encore.

Ils ouvrent de vraies sessions parallèles (`async_session`), seule façon de
faire jouer les verrous de ligne : une session unique ne s'attend jamais
elle-même.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.clotures import get_cloture_pdf_data, open_caisse
from app.core.audit_context import set_audit_org_id, set_audit_user_id
from app.models.caisse_centrale import CaisseCentrale
from app.models.cloture_caisse import ClotureCaisse
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.ouverture_caisse import OuvertureCaisse
from app.models.user import User
from app.schemas.cloture import OuvertureCreateRequest
from app.services.encaissement_payments import record_encaissement_payment


class _FakeRequest:
    headers: dict = {}
    client = None


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org_et_caissiers(session, *, nb_caissiers: int = 2, caisse_ouverte: bool = True):
    org = Organisation(nom="Caisse partagée", slug=f"caisse-{_suffix()}", is_active=True)
    session.add(org)
    await session.flush()
    caissiers = []
    for index in range(nb_caissiers):
        user = User(
            id=uuid.uuid4(),
            email=f"caissier{index}-{_suffix()}@ex.com",
            role="caissier",
            prenom="Caissier",
            nom=str(index),
            organisation_id=org.id,
        )
        session.add(user)
        caissiers.append(user)
    session.add(
        CaisseCentrale(
            organisation_id=org.id,
            solde_usd=Decimal("0"),
            solde_cdf=Decimal("0"),
            est_ouverte=caisse_ouverte,
        )
    )
    await session.flush()
    return org, caissiers


def _note(org: Organisation, user: User, total: Decimal) -> Encaissement:
    return Encaissement(
        organisation_id=org.id,
        numero_recu=f"ND-{_suffix()}",
        type_client="personne_physique",
        client_nom="Client partagé",
        libelle="Cotisation",
        montant=total,
        montant_total=total,
        montant_paye=Decimal("0"),
        montant_percu=Decimal("0"),
        devise_perception="USD",
        taux_change_applique=Decimal("1"),
        canal="CAISSE",
        mode_paiement="cash",
        statut_paiement="non_paye",
        date_encaissement=datetime.now(timezone.utc),
        created_by=user.id,
    )


@pytest.mark.asyncio
async def test_deux_caissiers_encaissent_en_parallele_sans_perdre_de_versement(async_session):
    """Deux versements simultanés s'ajoutent : aucun n'écrase l'autre."""
    async with async_session() as setup:
        org, (caissier_a, caissier_b) = await _org_et_caissiers(setup)
        note_a = _note(org, caissier_a, Decimal("400"))
        note_b = _note(org, caissier_b, Decimal("600"))
        setup.add_all([note_a, note_b])
        await setup.commit()
        org_id, note_a_id, note_b_id = org.id, note_a.id, note_b.id
        caissier_a_id, caissier_b_id = caissier_a.id, caissier_b.id

    async def encaisser(note_id, user_id, montant):
        set_audit_org_id(org_id)
        set_audit_user_id(user_id)
        async with async_session() as session:
            await record_encaissement_payment(
                session,
                organisation_id=org_id,
                encaissement_id=note_id,
                montant=montant,
                mode_paiement="cash",
                reference=None,
                notes=None,
                user_id=user_id,
            )
            await session.commit()

    await asyncio.gather(
        encaisser(note_a_id, caissier_a_id, Decimal("400")),
        encaisser(note_b_id, caissier_b_id, Decimal("600")),
    )

    async with async_session() as check:
        caisse = (
            await check.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org_id))
        ).scalar_one()
        assert caisse.solde_usd == Decimal("1000.00")


@pytest.mark.asyncio
async def test_un_seul_versement_passe_quand_deux_caissiers_soldent_la_meme_note(async_session):
    """La même note encaissée deux fois : le reste dû est vérifié sous verrou."""
    async with async_session() as setup:
        org, (caissier_a, caissier_b) = await _org_et_caissiers(setup)
        note = _note(org, caissier_a, Decimal("500"))
        setup.add(note)
        await setup.commit()
        org_id, note_id = org.id, note.id
        caissier_a_id, caissier_b_id = caissier_a.id, caissier_b.id

    async def solder(user_id):
        set_audit_org_id(org_id)
        set_audit_user_id(user_id)
        async with async_session() as session:
            try:
                await record_encaissement_payment(
                    session,
                    organisation_id=org_id,
                    encaissement_id=note_id,
                    montant=Decimal("500"),
                    mode_paiement="cash",
                    reference=None,
                    notes=None,
                    user_id=user_id,
                )
                await session.commit()
                return True
            except HTTPException as exc:
                await session.rollback()
                assert exc.status_code == 400
                return False

    resultats = await asyncio.gather(solder(caissier_a_id), solder(caissier_b_id))

    assert sum(1 for ok in resultats if ok) == 1, "la note a été encaissée deux fois"
    async with async_session() as check:
        note_relue = await check.get(Encaissement, note_id)
        caisse = (
            await check.execute(select(CaisseCentrale).where(CaisseCentrale.organisation_id == org_id))
        ).scalar_one()
        assert note_relue.montant_paye == Decimal("500.00")
        assert caisse.solde_usd == Decimal("500.00")


@pytest.mark.asyncio
async def test_deux_ouvertures_simultanees_n_ouvrent_la_caisse_qu_une_fois(async_session):
    """Deux caissiers ouvrent en même temps : une seule séance est créée."""
    async with async_session() as setup:
        org, (caissier_a, caissier_b) = await _org_et_caissiers(setup, caisse_ouverte=False)
        await setup.commit()
        org_id = org.id
        caissier_a_id, caissier_b_id = caissier_a.id, caissier_b.id

    async def ouvrir(user_id):
        set_audit_org_id(org_id)
        set_audit_user_id(user_id)
        async with async_session() as session:
            user = await session.get(User, user_id)
            try:
                await open_caisse(
                    payload=OuvertureCreateRequest(solde_ouverture_usd=0, solde_ouverture_cdf=0),
                    request=_FakeRequest(),
                    user=user,
                    db=session,
                    tenant_id=org_id,
                )
                await session.commit()
                return True
            except HTTPException as exc:
                await session.rollback()
                assert exc.status_code == 400
                return False

    resultats = await asyncio.gather(ouvrir(caissier_a_id), ouvrir(caissier_b_id))

    assert sum(1 for ok in resultats if ok) == 1, "la caisse a été ouverte deux fois"
    async with async_session() as check:
        ouvertures = (
            await check.execute(
                select(OuvertureCaisse).where(OuvertureCaisse.organisation_id == org_id)
            )
        ).scalars().all()
        assert len(ouvertures) == 1


@pytest.mark.asyncio
async def test_le_pv_de_cloture_ne_sort_pas_de_son_organisation(db_session):
    """L'identifiant d'une clôture est un entier de séquence, donc devinable."""
    org_a, (caissier_a,) = await _org_et_caissiers(db_session, nb_caissiers=1)
    org_b, (caissier_b,) = await _org_et_caissiers(db_session, nb_caissiers=1)
    cloture = ClotureCaisse(
        organisation_id=org_a.id,
        reference_numero=f"CLO-{_suffix()}",
        date_cloture=datetime.now(timezone.utc),
        caissier_id=caissier_a.id,
        solde_theorique_usd=Decimal("0"),
        solde_physique_usd=Decimal("0"),
        solde_theorique_cdf=Decimal("0"),
        solde_physique_cdf=Decimal("0"),
    )
    db_session.add(cloture)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_cloture_pdf_data(cloture_id=cloture.id, db=db_session, tenant_id=org_b.id)
    assert exc.value.status_code == 404

    # Et la même lecture, depuis son organisation, reste possible.
    data = await get_cloture_pdf_data(cloture_id=cloture.id, db=db_session, tenant_id=org_a.id)
    assert data is not None
