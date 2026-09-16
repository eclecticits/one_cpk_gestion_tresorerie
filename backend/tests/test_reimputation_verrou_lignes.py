"""La ré-imputation face au verrou des lignes validées.

Les lignes d'une réquisition sont gelées par un déclencheur PostgreSQL dès la
première validation : le validateur qui appose son visa lit un texte censé ne
plus bouger. Or la ré-imputation existe pour corriger des pièces autorisées,
approuvées ou payées — exactement les états que le verrou refuse.

Ces tests n'existent que parce que la suite ne pouvait pas voir le problème :
le schéma de test naît de `Base.metadata.create_all()`, qui crée les tables mais
aucun déclencheur. Tout passait au vert pendant que la fonctionnalité renvoyait
500 sur la moindre pièce réelle. Le déclencheur est donc installé ici, à partir
du SQL de la migration elle-même, et non d'une copie qui divergerait.
"""

import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.ligne_requisition import LigneRequisition
from app.services.budget_engagement import resynchroniser_engagement_requisition
from app.services.reimputation_budgetaire import reimputer_requisition

from test_budget_engagements import _org, _poste, _requisition, _user
from test_reimputation_budgetaire import _poste_voisin


def _migration():
    """Le module de migration, pour éprouver son SQL plutôt que le recopier."""
    chemin = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions" / "20260916_verrou_reimputation.py"
    )
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _poser_le_verrou(db):
    """Installe la fonction et le déclencheur tels que la migration les définit."""
    mig = _migration()
    await db.execute(text(mig.fonction(avec_reimputation=True)))
    for instruction in mig.declencheur().strip().split(";"):
        if instruction.strip():
            await db.execute(text(instruction))
    await db.flush()


async def _contexte_verrouille(db, *, statut="APPROUVEE"):
    org = await _org(db)
    user = await _user(db, org)
    ancien = await _poste(db, org)
    nouveau = await _poste_voisin(db, org, ancien)
    req = await _requisition(db, org, user, ancien, examen_status="EXAMINEE")
    req.status = statut
    await db.flush()
    await resynchroniser_engagement_requisition(db, req)
    await _poser_le_verrou(db)
    return org, user, ancien, nouveau, req


@pytest.mark.parametrize("statut", ["AUTORISEE", "APPROUVEE", "PAYEE", "EN_DECAISSEMENT"])
@pytest.mark.asyncio
async def test_la_correction_passe_sur_une_requisition_verrouillee(db_session, statut):
    """Le cœur du sujet : corriger l'imputation d'une pièce validée doit aboutir."""
    org, user, ancien, nouveau, req = await _contexte_verrouille(db_session, statut=statut)

    resultat = await reimputer_requisition(
        db_session,
        requisition=req,
        nouveau_poste_id=nouveau.id,
        user_id=user.id,
        motif=f"Correction sur une pièce {statut}",
    )

    assert resultat["lignes_deplacees"] == 1
    ligne = (await db_session.execute(
        select(LigneRequisition).where(LigneRequisition.requisition_id == req.id)
    )).scalars().first()
    await db_session.refresh(ligne)
    assert ligne.budget_poste_id == nouveau.id


@pytest.mark.asyncio
async def test_le_verrou_refuse_toujours_une_modification_de_montant(db_session):
    """Le drapeau n'ouvre pas la porte en grand : le texte signé reste figé.

    Même posé, `onec.reimputation` ne laisse passer qu'un déplacement de poste.
    Toucher au montant sous couvert de correction retombe sur le refus.
    """
    org, user, ancien, nouveau, req = await _contexte_verrouille(db_session)
    ligne = (await db_session.execute(
        select(LigneRequisition).where(LigneRequisition.requisition_id == req.id)
    )).scalars().first()

    await db_session.execute(text("SET LOCAL onec.reimputation = 'on'"))
    with pytest.raises(DBAPIError) as err:
        await db_session.execute(
            text("UPDATE lignes_requisition SET montant_total = :m WHERE id = :id"),
            {"m": Decimal("1.00"), "id": ligne.id},
        )
        await db_session.flush()
    assert "modification des lignes interdite" in str(err.value)


@pytest.mark.asyncio
async def test_sans_le_drapeau_le_verrou_tient(db_session):
    """Contrôle de la garde elle-même : sans annonce, une ligne validée ne bouge pas.

    Si ce test cessait d'échouer, c'est le verrou qui aurait disparu, et les deux
    précédents ne prouveraient plus rien.
    """
    org, user, ancien, nouveau, req = await _contexte_verrouille(db_session)
    ligne = (await db_session.execute(
        select(LigneRequisition).where(LigneRequisition.requisition_id == req.id)
    )).scalars().first()

    with pytest.raises(DBAPIError) as err:
        await db_session.execute(
            text("UPDATE lignes_requisition SET budget_poste_id = :p WHERE id = :id"),
            {"p": nouveau.id, "id": ligne.id},
        )
        await db_session.flush()
    assert "modification des lignes interdite" in str(err.value)
