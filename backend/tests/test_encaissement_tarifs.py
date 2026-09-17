"""Un libellé d'encaissement peut fixer son prix, son imputation, ou les deux.

Les deux champs sont indépendants : c'est la demande, et c'est ce qui distingue
un tarif d'une simple liste de suggestions. Un tarif qui n'aurait de sens que
complet obligerait à inventer un poste pour figer un prix, ou un prix pour
figer un poste.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1.endpoints.encaissement_tarifs import (
    create_encaissement_tarif,
    delete_encaissement_tarif,
    list_encaissement_tarifs,
    update_encaissement_tarif,
)
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.organisation import Organisation
from app.models.print_settings import PrintSettings
from app.models.user import User
from app.schemas.encaissement_tarif import EncaissementTarifCreate, EncaissementTarifUpdate
from app.services.encaissement_tarifs import tarifs_resolus


async def _contexte(db, *, annee=2026, code="II.1.1.2", type_poste="RECETTE"):
    org = Organisation(nom="Tarifs", slug=f"tf-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    exercice = BudgetExercice(organisation_id=org.id, annee=annee, statut=StatutBudget.VOTE)
    db.add_all([user, exercice])
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=code, libelle="Cotisations",
        type=type_poste, active=True, montant_prevu=Decimal("100000"), montant_engage=0,
        montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    db.add(PrintSettings(organisation_id=org.id, fiscal_year=annee))
    await db.commit()
    return org, user, exercice, poste


async def _creer(db, org, user, **kwargs):
    payload = EncaissementTarifCreate(**kwargs)
    return await create_encaissement_tarif(payload=payload, user=user, tenant_id=org.id, db=db)


@pytest.mark.asyncio
async def test_un_tarif_peut_ne_fixer_que_le_prix(db_session):
    """Le prix est ferme, l'imputation se décide au cas par cas."""
    org, user, _exercice, _poste = await _contexte(db_session)

    tarif = await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    assert tarif.montant == Decimal("50")
    assert tarif.budget_poste_code is None
    assert tarif.budget_poste_id is None


@pytest.mark.asyncio
async def test_un_tarif_peut_ne_fixer_que_le_poste(db_session):
    """Le montant varie, mais la recette tombe toujours au même endroit."""
    org, user, _exercice, poste = await _contexte(db_session)

    tarif = await _creer(db_session, org, user, libelle="Arriérés de cotisation", budget_poste_code=poste.code)

    assert tarif.montant is None
    assert tarif.budget_poste_id == poste.id
    assert tarif.budget_poste_libelle == "Cotisations"


@pytest.mark.asyncio
async def test_le_code_se_resout_au_poste_de_l_exercice_courant(db_session):
    """Le tarif suit l'exercice : c'est tout l'intérêt de retenir un code.

    Le même code existe dans deux exercices avec deux identifiants ; le tarif
    doit désigner celui de l'année sur laquelle on travaille.
    """
    org, user, exercice, poste_2026 = await _contexte(db_session)
    exercice_2027 = BudgetExercice(organisation_id=org.id, annee=2027, statut=StatutBudget.VOTE)
    db_session.add(exercice_2027)
    await db_session.flush()
    poste_2027 = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice_2027.id, code=poste_2026.code,
        libelle="Cotisations", type="RECETTE", active=True, montant_prevu=Decimal("120000"),
        montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db_session.add(poste_2027)
    await db_session.commit()

    tarif = await _creer(db_session, org, user, libelle="Cotisation cabinet", montant=Decimal("300"),
                         budget_poste_code=poste_2026.code)
    assert tarif.budget_poste_id == poste_2026.id

    # L'organisation bascule sur l'exercice suivant : le même tarif vise
    # désormais le poste 2027, sans rien ressaisir.
    settings = (
        await db_session.execute(select(PrintSettings).where(PrintSettings.organisation_id == org.id))
    ).scalar_one()
    settings.fiscal_year = 2027
    await db_session.commit()

    resolus = await tarifs_resolus(db_session, org.id)
    assert [poste.id for _tarif, poste in resolus] == [poste_2027.id]


@pytest.mark.asyncio
async def test_un_code_sans_poste_de_recette_ne_vaut_pas_imputation(db_session):
    """Mieux vaut un tarif qui se dit muet qu'un tarif qui impute au hasard."""
    org, user, _exercice, poste = await _contexte(db_session, type_poste="DEPENSE")

    tarif = await _creer(db_session, org, user, libelle="Vente de formulaires", budget_poste_code=poste.code)

    assert tarif.budget_poste_code == poste.code  # le réglage est conservé
    assert tarif.budget_poste_id is None  # mais il ne désigne aucune recette


@pytest.mark.asyncio
async def test_deux_tarifs_ne_partagent_pas_un_libelle(db_session):
    """La saisie reconnaît un tarif par son libellé : deux tarifs homonymes la
    laisseraient sans réponse. La casse et les espaces ne font pas deux."""
    org, user, _exercice, _poste = await _contexte(db_session)
    await _creer(db_session, org, user, libelle="Cotisation stagiaire", montant=Decimal("50"))

    with pytest.raises(HTTPException) as refus:
        await _creer(db_session, org, user, libelle="  COTISATION   stagiaire ", montant=Decimal("60"))
    assert refus.value.status_code == 409


@pytest.mark.asyncio
async def test_un_champ_se_vide_sans_emporter_l_autre(db_session):
    """Retirer le prix ne doit pas retirer l'imputation, et réciproquement."""
    org, user, _exercice, poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation cabinet",
                         montant=Decimal("300"), budget_poste_code=poste.code)

    sans_prix = await update_encaissement_tarif(
        tarif_id=tarif.id, payload=EncaissementTarifUpdate(montant=None), tenant_id=org.id, db=db_session
    )
    assert sans_prix.montant is None
    assert sans_prix.budget_poste_id == poste.id

    sans_poste = await update_encaissement_tarif(
        tarif_id=tarif.id,
        payload=EncaissementTarifUpdate(montant=Decimal("320"), budget_poste_code=None),
        tenant_id=org.id,
        db=db_session,
    )
    assert sans_poste.montant == Decimal("320")
    assert sans_poste.budget_poste_code is None


@pytest.mark.asyncio
async def test_la_liste_garde_l_ordre_regle_a_la_main(db_session):
    """L'administrateur classait déjà sa pré-liste : l'ordre est un réglage."""
    org, user, _exercice, _poste = await _contexte(db_session)
    premier = await _creer(db_session, org, user, libelle="Cotisation cabinet")
    second = await _creer(db_session, org, user, libelle="Cotisation salarié")

    await update_encaissement_tarif(
        tarif_id=second.id, payload=EncaissementTarifUpdate(position=0), tenant_id=org.id, db=db_session
    )

    liste = await list_encaissement_tarifs(actifs=False, _user=user, tenant_id=org.id, db=db_session)
    assert [t.libelle for t in liste] == ["Cotisation salarié", "Cotisation cabinet"]

    await delete_encaissement_tarif(tarif_id=premier.id, tenant_id=org.id, db=db_session)
    reste = await list_encaissement_tarifs(actifs=False, _user=user, tenant_id=org.id, db=db_session)
    assert [t.libelle for t in reste] == ["Cotisation salarié"]


@pytest.mark.asyncio
async def test_un_tarif_inactif_ne_se_propose_plus(db_session):
    """Cesser de proposer un tarif n'est pas l'effacer : l'an prochain il resservira."""
    org, user, _exercice, _poste = await _contexte(db_session)
    tarif = await _creer(db_session, org, user, libelle="Cotisation 2025", montant=Decimal("40"))
    await update_encaissement_tarif(
        tarif_id=tarif.id, payload=EncaissementTarifUpdate(is_active=False), tenant_id=org.id, db=db_session
    )

    assert await list_encaissement_tarifs(actifs=True, _user=user, tenant_id=org.id, db=db_session) == []
    assert len(await list_encaissement_tarifs(actifs=False, _user=user, tenant_id=org.id, db=db_session)) == 1
