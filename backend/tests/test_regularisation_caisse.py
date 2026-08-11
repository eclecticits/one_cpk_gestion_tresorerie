"""Régularisation des écarts de caisse constatés au comptage physique.

Règle vérifiée ici : un comptage physique ne remplace JAMAIS le solde théorique.
L'écart donne lieu à une opération financière identifiable, et seulement si
l'utilisateur la demande. Sans confirmation, la caisse s'ouvre ou se clôture
quand même, sur le solde théorique, et l'écart reste ouvert.
"""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.api.v1.endpoints.clotures import create_cloture, open_caisse
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.regularisation_caisse import RegularisationCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.system_settings import SystemSettings
from app.models.user import User
from app.schemas.cloture import ClotureCreateRequest, OuvertureCreateRequest


async def _setup(db_session, *, solde_logiciel=Decimal("10000"), avec_postes=True):
    """Org avec une caisse FERMÉE portant `solde_logiciel`, et les postes de régularisation."""
    org = Organisation(nom="Regul Test", slug=f"reg-{uuid.uuid4().hex[:8]}", is_active=True)
    db_session.add(org)
    await db_session.flush()

    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db_session.add(exercice)
    await db_session.flush()

    poste_exc = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code="REC-ECART",
        libelle="Excédents de caisse", type="RECETTE", active=True,
        montant_prevu=Decimal("1000"), montant_engage=0, montant_paye=0, is_deleted=False,
    )
    poste_def = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code="DEP-ECART",
        libelle="Déficits de caisse", type="DEPENSE", active=True,
        montant_prevu=Decimal("1000"), montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db_session.add_all([poste_exc, poste_def])
    await db_session.flush()

    db_session.add(SystemSettings(
        organisation_id=org.id,
        budget_poste_excedent_caisse_id=poste_exc.id if avec_postes else None,
        budget_poste_deficit_caisse_id=poste_def.id if avec_postes else None,
    ))

    caisse = CaisseCentrale(
        organisation_id=org.id, est_ouverte=False, solde_usd=solde_logiciel, solde_cdf=0
    )
    db_session.add(caisse)

    user = User(
        id=uuid.uuid4(), email=f"reg-{uuid.uuid4().hex[:6]}@example.com",
        role="admin", organisation_id=org.id,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(caisse)
    await db_session.refresh(poste_exc)
    await db_session.refresh(poste_def)
    return org, user, caisse, poste_exc, poste_def


async def _ouvrir(db_session, org, user, *, compte, regulariser, motif=None):
    payload = OuvertureCreateRequest(
        solde_ouverture_usd=compte,
        solde_ouverture_cdf=Decimal("0"),
        regulariser_ecart=regulariser,
        motif_regularisation=motif,
    )
    return await open_caisse(
        payload=payload, request=None, user=user, db=db_session, tenant_id=org.id
    )


async def _seed_encaissement_caisse(db_session, org, montant):
    """Encaissement CAISSE/USD réel, pour que le théorique de clôture existe.

    `caisse.solde_usd` (référence de l'ouverture) et `_compute_balance()`
    (référence de la clôture) sont calculés différemment : la clôture dérive son
    théorique des FLUX. Un solde posé directement sur la caisse ne suffit donc
    pas à faire exister un théorique de clôture.
    """
    from datetime import datetime, timezone

    enc = Encaissement(
        id=uuid.uuid4(),
        organisation_id=org.id,
        numero_recu=f"ND-SEED-{uuid.uuid4().hex[:6]}",
        libelle="Encaissement initial",
        type_client="organisation",
        client_nom="Seed",
        montant=montant, montant_total=montant, montant_paye=montant, montant_percu=montant,
        devise_perception="USD", taux_change_applique=Decimal("1"),
        canal="CAISSE", mode_paiement="cash", statut_paiement="complet",
        est_proforma=False,
        date_encaissement=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    db_session.add(enc)
    await db_session.commit()
    return enc


async def _solde(db_session, caisse_id):
    row = (await db_session.execute(
        select(CaisseCentrale).where(CaisseCentrale.id == caisse_id)
    )).scalar_one()
    await db_session.refresh(row)
    return row.solde_usd


@pytest.mark.asyncio
async def test_cas1_excedent_regularise_cree_un_encaissement(db_session):
    """Physique 10 150 > logiciel 10 000 : encaissement de 150, solde -> 10 150."""
    org, user, caisse, poste_exc, _ = await _setup(db_session)

    out = await _ouvrir(
        db_session, org, user,
        compte=Decimal("10150"), regulariser=True, motif="Excédent constaté au comptage",
    )

    assert out.ecart_usd == Decimal("150.00")
    assert out.regularisation_erreurs == []
    assert len(out.regularisations) == 1
    assert out.regularisations[0]["sens"] == "EXCEDENT"
    assert out.regularisations[0]["montant"] == "150.00"
    assert out.regularisations[0]["encaissement_id"] is not None

    # 10 000 + 150 = 10 150 : le solde rejoint le comptage PAR l'opération.
    assert await _solde(db_session, caisse.id) == Decimal("10150.00")

    enc = (await db_session.execute(
        select(Encaissement).where(Encaissement.organisation_id == org.id)
    )).scalars().all()
    assert len(enc) == 1
    assert enc[0].montant_paye == Decimal("150.00")
    assert enc[0].budget_poste_id == poste_exc.id
    assert enc[0].canal == "CAISSE"

    reg = (await db_session.execute(
        select(RegularisationCaisse).where(RegularisationCaisse.organisation_id == org.id)
    )).scalars().all()
    assert len(reg) == 1
    assert reg[0].source_type == "OUVERTURE"
    assert reg[0].solde_theorique == Decimal("10000.00")
    assert reg[0].solde_physique == Decimal("10150.00")
    assert reg[0].motif == "Excédent constaté au comptage"


@pytest.mark.asyncio
async def test_cas2_deficit_regularise_cree_une_sortie(db_session):
    """Physique 9 850 < logiciel 10 000 : sortie de 150, solde -> 9 850."""
    org, user, caisse, _, poste_def = await _setup(db_session)

    out = await _ouvrir(
        db_session, org, user,
        compte=Decimal("9850"), regulariser=True, motif="Manquant constaté au comptage",
    )

    assert out.ecart_usd == Decimal("-150.00")
    assert out.regularisation_erreurs == []
    assert len(out.regularisations) == 1
    assert out.regularisations[0]["sens"] == "DEFICIT"
    assert out.regularisations[0]["montant"] == "150.00"
    assert out.regularisations[0]["sortie_fonds_id"] is not None

    assert await _solde(db_session, caisse.id) == Decimal("9850.00")

    sorties = (await db_session.execute(
        select(SortieFonds).where(SortieFonds.organisation_id == org.id)
    )).scalars().all()
    assert len(sorties) == 1
    assert sorties[0].type_sortie == "regularisation_caisse"
    assert sorties[0].montant_paye == Decimal("150.00")
    assert sorties[0].budget_poste_id == poste_def.id


@pytest.mark.asyncio
async def test_cas3_aucun_ecart_aucune_operation(db_session):
    """Physique = logiciel : rien n'est créé, la caisse s'ouvre normalement."""
    org, user, caisse, _, _ = await _setup(db_session)

    out = await _ouvrir(
        db_session, org, user, compte=Decimal("10000"), regulariser=True, motif="RAS",
    )

    assert out.ecart_usd == Decimal("0.00")
    assert out.regularisations == []
    assert out.regularisation_erreurs == []
    assert await _solde(db_session, caisse.id) == Decimal("10000.00")

    reg = (await db_session.execute(
        select(RegularisationCaisse).where(RegularisationCaisse.organisation_id == org.id)
    )).scalars().all()
    assert reg == []


@pytest.mark.asyncio
async def test_refus_de_regulariser_conserve_le_solde_theorique(db_session):
    """Le principe fondamental : sans confirmation, PAS de solde_logiciel = solde_physique."""
    org, user, caisse, _, _ = await _setup(db_session)

    out = await _ouvrir(db_session, org, user, compte=Decimal("10150"), regulariser=False)

    # L'écart est constaté et conservé...
    assert out.ecart_usd == Decimal("150.00")
    assert out.regularisations == []
    # ...mais le solde logiciel NE PREND PAS le montant compté.
    assert await _solde(db_session, caisse.id) == Decimal("10000.00")

    # Aucune opération financière n'a été créée.
    assert (await db_session.execute(
        select(RegularisationCaisse).where(RegularisationCaisse.organisation_id == org.id)
    )).scalars().all() == []
    assert (await db_session.execute(
        select(Encaissement).where(Encaissement.organisation_id == org.id)
    )).scalars().all() == []

    # Et la caisse est bien ouverte malgré l'écart.
    caisse_db = (await db_session.execute(
        select(CaisseCentrale).where(CaisseCentrale.id == caisse.id)
    )).scalar_one()
    assert caisse_db.est_ouverte is True


@pytest.mark.asyncio
async def test_postes_non_configures_nempeche_pas_ouverture(db_session):
    """Paramétrage manquant : échec propre, caisse ouverte, écart laissé ouvert."""
    org, user, caisse, _, _ = await _setup(db_session, avec_postes=False)

    out = await _ouvrir(
        db_session, org, user, compte=Decimal("10150"), regulariser=True, motif="Excédent",
    )

    assert out.regularisations == []
    assert len(out.regularisation_erreurs) == 1
    assert "poste budgétaire" in out.regularisation_erreurs[0]

    # La caisse s'ouvre, sur le solde théorique.
    caisse_db = (await db_session.execute(
        select(CaisseCentrale).where(CaisseCentrale.id == caisse.id)
    )).scalar_one()
    assert caisse_db.est_ouverte is True
    assert caisse_db.solde_usd == Decimal("10000.00")


@pytest.mark.asyncio
async def test_motif_absent_refuse_la_regularisation_sans_bloquer(db_session):
    """Un motif vide n'autorise pas la régularisation, mais n'empêche pas l'ouverture."""
    org, user, caisse, _, _ = await _setup(db_session)

    out = await _ouvrir(
        db_session, org, user, compte=Decimal("10150"), regulariser=True, motif="   ",
    )

    assert out.regularisations == []
    assert len(out.regularisation_erreurs) == 1
    assert "motif" in out.regularisation_erreurs[0].lower()
    assert await _solde(db_session, caisse.id) == Decimal("10000.00")


@pytest.mark.asyncio
async def test_cloture_ne_realigne_plus_le_solde_sur_le_comptage(db_session):
    """À la clôture aussi, le comptage ne remplace pas le solde sans régularisation."""
    org, user, caisse, _, _ = await _setup(db_session)
    await _ouvrir(db_session, org, user, compte=Decimal("10000"), regulariser=False)

    payload = ClotureCreateRequest(
        solde_physique_usd=Decimal("9900"),
        solde_physique_cdf=Decimal("0"),
        regulariser_ecart=False,
    )
    out = await create_cloture(
        payload=payload, request=None, user=user, db=db_session, tenant_id=org.id
    )

    assert out.solde_physique_usd == Decimal("9900.00")
    assert out.regularisations == []
    # Le solde reste théorique : l'écart n'est pas absorbé en silence.
    assert await _solde(db_session, caisse.id) == Decimal("10000.00")


@pytest.mark.asyncio
async def test_ecart_non_regularise_ne_se_reporte_pas_sur_la_periode_suivante(db_session):
    """Le report d'une clôture repart du THÉORIQUE, pas du comptage physique.

    Sinon un écart refusé serait absorbé en silence une période plus tard —
    la règle métier serait contournée avec un tour de retard.
    """
    from app.api.v1.endpoints.clotures import get_balance_check

    org, user, caisse, _, _ = await _setup(db_session)
    # Le théorique de clôture se déduit des FLUX (et non de caisse.solde_usd) :
    # on adosse donc le solde à un encaissement réel.
    await _seed_encaissement_caisse(db_session, org, Decimal("10000"))
    await _ouvrir(db_session, org, user, compte=Decimal("10000"), regulariser=False)

    # Clôture avec un manquant de 100 que l'on choisit de NE PAS régulariser.
    await create_cloture(
        payload=ClotureCreateRequest(
            solde_physique_usd=Decimal("9900"),
            solde_physique_cdf=Decimal("0"),
            regulariser_ecart=False,
        ),
        request=None, user=user, db=db_session, tenant_id=org.id,
    )

    balance = await get_balance_check(db=db_session, tenant_id=org.id)
    # Le report vaut le théorique (10 000), pas le comptage (9 900).
    assert balance.solde_initial_usd == Decimal("10000.00")


@pytest.mark.asyncio
async def test_ecart_regularise_se_reporte_sur_le_comptage(db_session):
    """Régularisé, le report rejoint bien le montant compté."""
    from app.api.v1.endpoints.clotures import get_balance_check

    org, user, caisse, _, _ = await _setup(db_session)
    await _seed_encaissement_caisse(db_session, org, Decimal("10000"))
    await _ouvrir(db_session, org, user, compte=Decimal("10000"), regulariser=False)

    out = await create_cloture(
        payload=ClotureCreateRequest(
            solde_physique_usd=Decimal("9900"),
            solde_physique_cdf=Decimal("0"),
            regulariser_ecart=True,
            motif_regularisation="Manquant justifié",
        ),
        request=None, user=user, db=db_session, tenant_id=org.id,
    )
    assert len(out.regularisations) == 1
    assert out.regularisations[0]["sens"] == "DEFICIT"

    balance = await get_balance_check(db=db_session, tenant_id=org.id)
    # 10 000 théorique − 100 régularisés = 9 900 = le comptage.
    assert balance.solde_initial_usd == Decimal("9900.00")


@pytest.mark.asyncio
async def test_ecart_refuse_apparait_dans_la_liste_puis_disparait_une_fois_regularise(db_session):
    """Un écart refusé reste listé, et sort de la liste après régularisation."""
    from app.api.v1.endpoints.clotures import (
        list_ecarts_caisse,
        regulariser_ecart_a_posteriori,
    )
    from app.schemas.cloture import EcartRegularisationRequest

    org, user, caisse, poste_exc, _ = await _setup(db_session)
    await _ouvrir(db_session, org, user, compte=Decimal("10150"), regulariser=False)

    ouverts = await list_ecarts_caisse(
        non_regularises_seulement=True, limit=100, tenant_id=org.id, db=db_session
    )
    assert len(ouverts) == 1
    ligne = ouverts[0]
    assert ligne["source_type"] == "OUVERTURE"
    assert ligne["devise"] == "USD"
    assert ligne["ecart"] == "150.00"
    assert ligne["sens"] == "EXCEDENT"
    assert ligne["regularise"] is False

    res = await regulariser_ecart_a_posteriori(
        source_type="OUVERTURE",
        source_id=ligne["source_id"],
        payload=EcartRegularisationRequest(motif="Régularisé après vérification", devise="USD"),
        user=user, tenant_id=org.id, db=db_session,
    )
    assert res["ok"] is True
    assert res["regularisations"][0]["montant"] == "150.00"

    # Le solde rejoint enfin le comptage, par l'opération.
    assert await _solde(db_session, caisse.id) == Decimal("10150.00")

    restants = await list_ecarts_caisse(
        non_regularises_seulement=True, limit=100, tenant_id=org.id, db=db_session
    )
    assert restants == []

    # L'écart reste visible dans l'historique complet, marqué régularisé.
    tous = await list_ecarts_caisse(
        non_regularises_seulement=False, limit=100, tenant_id=org.id, db=db_session
    )
    assert len(tous) == 1
    assert tous[0]["regularise"] is True


@pytest.mark.asyncio
async def test_regularisation_a_posteriori_sans_poste_configure_echoue_proprement(db_session):
    from app.api.v1.endpoints.clotures import regulariser_ecart_a_posteriori
    from app.schemas.cloture import EcartRegularisationRequest
    from fastapi import HTTPException

    org, user, caisse, _, _ = await _setup(db_session, avec_postes=False)
    out = await _ouvrir(db_session, org, user, compte=Decimal("10150"), regulariser=False)

    with pytest.raises(HTTPException) as exc:
        await regulariser_ecart_a_posteriori(
            source_type="OUVERTURE", source_id=out.id,
            payload=EcartRegularisationRequest(motif="Tentative", devise="USD"),
            user=user, tenant_id=org.id, db=db_session,
        )
    assert exc.value.status_code == 400
    assert "poste budgétaire" in exc.value.detail
