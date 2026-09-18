"""Une collation de réunion se compte par tête, pas par ordre.

La sortie directe est plafonnée à 100 USD, et ce plafond a un sens : elle
n'échappe à la réquisition que parce qu'elle est petite. C'est sa petitesse qui
la justifie, jamais son intitulé — sans quoi il suffirait de nommer une dépense
« collation » pour la soustraire à toute approbation.

Une collation échoue pourtant à ce test sans rien avoir d'abusif : quarante
participants à cinq dollars font deux cents dollars. Le montant n'est pas la
bonne unité de mesure ; le prix par tête l'est. Ce fichier fixe ce que ce
déplacement doit préserver.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement
from app.models.caisse_centrale import CaisseCentrale
from app.models.ordre_decaissement import OrdreDecaissement
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.service import Service
from app.models.user import User
from app.schemas.ordre_decaissement import OrdreDecaissementCreate

LE_JOUR = date(2026, 9, 18)


async def _contexte(db):
    org = Organisation(nom="Collation", slug=f"col-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    service = Service(
        organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Secrétariat", is_active=True
    )
    user = User(
        id=uuid.uuid4(),
        email=f"col-{uuid.uuid4().hex[:6]}@example.com",
        role="admin",
        organisation_id=org.id,
    )
    db.add_all([service, user])
    db.add(CaisseCentrale(organisation_id=org.id, est_ouverte=True, solde_usd=Decimal("5000"), solde_cdf=0))
    await db.commit()
    return org, user, service


async def _collation(db, org, user, service, *, participants, par_personne, reunion="Conseil d'administration", jour=LE_JOUR):
    return await create_ordre_decaissement(
        payload=OrdreDecaissementCreate(
            requisition_id=None,
            beneficiaire="Secrétaire général",
            # Le total envoyé est volontairement faux : le serveur le dérive.
            montant=Decimal("1"),
            devise="USD",
            type_sortie="COLLATION",
            reunion_intitule=reunion,
            reunion_date=jour,
            participants=participants,
            montant_par_personne=Decimal(str(par_personne)),
            service_id=service.id,
            motif="Collation",
        ),
        request=None,
        user=user,
        tenant_id=org.id,
        db=db,
    )


async def _simple(db, org, user, service, *, montant, beneficiaire="Secrétaire général"):
    return await create_ordre_decaissement(
        payload=OrdreDecaissementCreate(
            requisition_id=None,
            beneficiaire=beneficiaire,
            montant=Decimal(str(montant)),
            devise="USD",
            service_id=service.id,
            motif="Achat urgent",
        ),
        request=None,
        user=user,
        tenant_id=org.id,
        db=db,
    )


@pytest.mark.asyncio
async def test_une_collation_passe_au_dela_des_cent_dollars(db_session):
    """Quarante têtes à cinq dollars : deux cents dollars, et pourtant une
    collation. Le plafond de montant refusait ce qui n'a rien d'abusif."""
    org, user, service = await _contexte(db_session)

    ordre = await _collation(db_session, org, user, service, participants=40, par_personne=5)

    assert ordre["montant"] == Decimal("200.00")
    assert ordre["type_sortie"] == "COLLATION"
    assert ordre["participants"] == 40


@pytest.mark.asyncio
async def test_le_meme_montant_en_sortie_simple_reste_refuse(db_session):
    """Le type ne dispense de rien : il change l'unité de ce qui est mesuré."""
    org, user, service = await _contexte(db_session)

    with pytest.raises(HTTPException) as refus:
        await _simple(db_session, org, user, service, montant=200)
    assert "100 USD" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_le_prix_par_tete_borne_ce_qu_est_une_collation(db_session):
    """Deux cents dollars pour deux personnes n'est pas une collation, quel que
    soit le nom qu'on lui donne."""
    org, user, service = await _contexte(db_session)

    with pytest.raises(HTTPException) as refus:
        await _collation(db_session, org, user, service, participants=2, par_personne=200)
    assert "par personne" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_le_total_reste_borne_meme_a_petit_prix(db_session):
    """À neuf cents dollars la dépense mérite une approbation, même à cinq
    dollars la tête."""
    org, user, service = await _contexte(db_session)

    with pytest.raises(HTTPException) as refus:
        await _collation(db_session, org, user, service, participants=200, par_personne=5)
    assert "au total" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_le_total_est_derive_jamais_declare(db_session):
    """Entre ce que le serveur contrôle et ce que la caisse paiera, un écart
    n'aurait aucune raison d'exister."""
    org, user, service = await _contexte(db_session)

    ordre = await _collation(db_session, org, user, service, participants=12, par_personne="7.50")

    assert ordre["montant"] == Decimal("90.00")  # et non le 1 envoyé
    assert ordre["montant_par_personne"] == Decimal("7.50")


@pytest.mark.asyncio
async def test_une_meme_reunion_ne_se_decoupe_pas(db_session):
    """Sans regroupement par réunion, il suffirait de servir la même salle en
    plusieurs fois pour ignorer le plafond total."""
    org, user, service = await _contexte(db_session)
    await _collation(db_session, org, user, service, participants=60, par_personne=5)

    with pytest.raises(HTTPException) as refus:
        await _collation(db_session, org, user, service, participants=60, par_personne=5)
    assert "Fractionnement" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_deux_reunions_du_meme_jour_sont_deux_depenses(db_session):
    """Le regroupement porte sur la réunion, non sur celui qui prend l'argent."""
    org, user, service = await _contexte(db_session)
    await _collation(db_session, org, user, service, participants=60, par_personne=5)

    autre = await _collation(
        db_session, org, user, service, participants=60, par_personne=5, reunion="Commission de discipline"
    )

    assert autre["montant"] == Decimal("300.00")


@pytest.mark.asyncio
async def test_une_collation_ne_bloque_pas_la_sortie_directe_simple(db_session):
    """C'est le piège du dispositif : laisser la collation dans le cumul des
    ordres simples ferait qu'une collation de 400 USD interdirait pour 24 h
    toute sortie directe du même responsable, au nom d'un fractionnement qui
    n'existe pas."""
    org, user, service = await _contexte(db_session)
    await _collation(db_session, org, user, service, participants=80, par_personne=5)

    ordre = await _simple(db_session, org, user, service, montant=90)

    assert ordre["montant"] == Decimal("90")


@pytest.mark.asyncio
async def test_une_collation_sans_tetes_ni_prix_est_refusee(db_session):
    """Ce qui la distingue doit être présent, ou elle n'est qu'un montant qui se
    réclame d'un nom."""
    org, user, service = await _contexte(db_session)

    with pytest.raises(HTTPException) as refus:
        await create_ordre_decaissement(
            payload=OrdreDecaissementCreate(
                requisition_id=None,
                beneficiaire="Secrétaire général",
                montant=Decimal("200"),
                devise="USD",
                type_sortie="COLLATION",
                reunion_intitule="Conseil",
                reunion_date=LE_JOUR,
                service_id=service.id,
                motif="Collation",
            ),
            request=None,
            user=user,
            tenant_id=org.id,
            db=db_session,
        )
    assert "participants" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_les_plafonds_se_reglent_par_organisation(db_session):
    """Un traiteur fait varier ce qu'un code figé ne suivrait pas."""
    org, user, service = await _contexte(db_session)
    db_session.add(
        OrganisationSettings(
            organisation_id=org.id,
            collation_plafond_par_personne_usd=Decimal("25"),
            collation_plafond_total_usd=Decimal("2000"),
        )
    )
    await db_session.commit()

    ordre = await _collation(db_session, org, user, service, participants=60, par_personne=20)

    assert ordre["montant"] == Decimal("1200.00")


@pytest.mark.asyncio
async def test_la_collation_porte_sa_justification_en_base(db_session):
    """Le total cesse d'être un chiffre tapé à la main dont la description
    dirait « collation CA » : ce qui le produit est écrit là où on le relit."""
    org, user, service = await _contexte(db_session)
    cree = await _collation(db_session, org, user, service, participants=30, par_personne=4)

    ordre = (
        await db_session.execute(
            select(OrdreDecaissement).where(OrdreDecaissement.id == uuid.UUID(cree["id"]))
        )
    ).scalar_one()

    assert ordre.reunion_intitule == "Conseil d'administration"
    assert ordre.reunion_date == LE_JOUR
    assert ordre.reunion_normalisee == "conseil d'administration"
    assert ordre.participants == 30
    assert ordre.montant_par_personne == Decimal("4.00")
