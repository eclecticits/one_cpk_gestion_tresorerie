"""Changement du compte bancaire d'un volet de réquisition.

Cas d'origine : REQ-ADM-2026-00062, mixte, en décaissement. La caisse a payé
sa part, le loyer (volet virement sur TMB) n'est pas parti et doit sortir
d'Equity. Le changement de canal est fermé à ce stade ; celui-ci ne l'est pas,
tant que le volet visé n'a rien décaissé.

Les déclencheurs sont installés depuis la migration elle-même : `create_all()`
n'en crée aucun.
"""

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models.banque import Banque
from app.models.compte_bancaire import CompteBancaire
from app.models.ligne_requisition import LigneRequisition
from app.models.ordre_decaissement import OrdreDecaissement
from app.services.changement_canal_requisition import changer_compte_volet

from test_budget_engagements import _org, _poste, _requisition, _user


def _migration(nom):
    chemin = Path(__file__).resolve().parents[1] / "alembic" / "versions" / f"{nom}.py"
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _poser_les_verrous(db):
    mig = _migration("20261104_compte_volet")
    await db.execute(text(mig.fonction_lignes()))
    await db.execute(text(mig.fonction_requisitions()))
    for instruction in _migration("20261008_changement_canal").declencheurs():
        await db.execute(text(instruction))
    await db.flush()


async def _compte(db, org, banque, intitule):
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule=intitule,
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("10000"), solde_actuel=Decimal("10000"),
        is_active=True, account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


async def _contexte(db, *, statut="EN_DECAISSEMENT", entete_sur_tmb=False):
    """Réquisition mixte : une ligne caisse (celle du fixture), une ligne loyer sur TMB."""
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    req = await _requisition(db, org, user, poste, examen_status="EXAMINEE")
    banque_tmb = Banque(organisation_id=org.id, nom="TMB")
    banque_equity = Banque(organisation_id=org.id, nom="Equity BCDC")
    db.add_all([banque_tmb, banque_equity])
    await db.flush()
    tmb = await _compte(db, org, banque_tmb, "ORDRE NATIONAL DES EXPERTS COMPTABLE")
    equity = await _compte(db, org, banque_equity, "ORDRE NATIONAL DES EXPERT COMPTABLE")
    db.add(
        LigneRequisition(
            organisation_id=org.id, requisition_id=req.id, budget_poste_id=poste.id,
            rubrique="Loyers bureau", description="Loyer", quantite=1,
            montant_unitaire=Decimal("6082"), montant_total=Decimal("6082"), devise="USD",
            mode_paiement="virement", compte_bancaire_id=tmb.id,
        )
    )
    req.mode_paiement = "mixte"
    if entete_sur_tmb:
        req.mode_paiement = "virement"
        req.compte_bancaire_id = tmb.id
    req.status = statut
    await db.flush()
    await _poser_les_verrous(db)
    return org, user, req, tmb, equity


async def _lignes(db, req):
    return (
        await db.execute(select(LigneRequisition).where(LigneRequisition.requisition_id == req.id))
    ).scalars().all()


def _ordre(org, user, req, *, mode, canal, compte_id=None, statut="PAYE"):
    return OrdreDecaissement(
        organisation_id=org.id, requisition_id=req.id, numero_ordre=f"OD-{uuid.uuid4().hex[:6]}",
        beneficiaire="Bailleur", beneficiaire_normalise="BAILLEUR",
        montant=Decimal("10"), devise="USD", mode_paiement=mode, canal=canal,
        compte_bancaire_id=compte_id, statut=statut, autorise_par=user.id,
    )


@pytest.mark.asyncio
async def test_volet_banque_change_de_compte_en_decaissement(db_session):
    org, user, req, tmb, equity = await _contexte(db_session)
    # La caisse a déjà payé sa part : cela n'engage pas le volet banque.
    db_session.add(_ordre(org, user, req, mode="cash", canal="CAISSE"))
    await db_session.flush()

    resultat = await changer_compte_volet(
        db_session, requisition=req, ancien_compte_id=tmb.id,
        nouveau_compte_id=equity.id, tenant_id=org.id,
    )

    assert resultat["lignes_modifiees"] == 1
    lignes = await _lignes(db_session, req)
    banque = [l for l in lignes if l.mode_paiement == "virement"]
    caisse = [l for l in lignes if l.mode_paiement != "virement"]
    assert [l.compte_bancaire_id for l in banque] == [equity.id]
    assert banque[0].mode_paiement == "virement"
    assert all(l.compte_bancaire_id is None for l in caisse)
    assert req.mode_paiement == "mixte"


@pytest.mark.asyncio
async def test_entete_suit_quand_il_porte_le_compte(db_session):
    org, _, req, tmb, equity = await _contexte(db_session, statut="APPROUVEE", entete_sur_tmb=True)

    await changer_compte_volet(
        db_session, requisition=req, ancien_compte_id=tmb.id,
        nouveau_compte_id=equity.id, tenant_id=org.id,
    )

    assert req.compte_bancaire_id == equity.id
    assert req.bank_account_snapshot["id"] == equity.id


@pytest.mark.asyncio
async def test_ordre_sur_l_ancien_compte_bloque(db_session):
    org, user, req, tmb, equity = await _contexte(db_session)
    db_session.add(_ordre(org, user, req, mode="virement", canal="BANQUE", compte_id=tmb.id, statut="AUTORISE"))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await changer_compte_volet(
            db_session, requisition=req, ancien_compte_id=tmb.id,
            nouveau_compte_id=equity.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_ordre_annule_ne_bloque_pas(db_session):
    org, user, req, tmb, equity = await _contexte(db_session)
    db_session.add(_ordre(org, user, req, mode="virement", canal="BANQUE", compte_id=tmb.id, statut="ANNULE"))
    await db_session.flush()

    resultat = await changer_compte_volet(
        db_session, requisition=req, ancien_compte_id=tmb.id,
        nouveau_compte_id=equity.id, tenant_id=org.id,
    )
    assert resultat["lignes_modifiees"] == 1


@pytest.mark.asyncio
async def test_requisition_payee_garde_ses_comptes(db_session):
    org, _, req, tmb, equity = await _contexte(db_session, statut="PAYEE")

    with pytest.raises(HTTPException) as exc:
        await changer_compte_volet(
            db_session, requisition=req, ancien_compte_id=tmb.id,
            nouveau_compte_id=equity.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_compte_sans_volet_refuse(db_session):
    org, _, req, _, equity = await _contexte(db_session)

    with pytest.raises(HTTPException) as exc:
        await changer_compte_volet(
            db_session, requisition=req, ancien_compte_id=equity.id,
            nouveau_compte_id=equity.id + 999, tenant_id=org.id,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_le_drapeau_ne_laisse_pas_passer_le_mode(db_session):
    """Sous ce drapeau, seul le compte bouge : un mode modifié est refusé."""
    _, _, req, _, equity = await _contexte(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("SET LOCAL onec.changement_compte_volet = 'on'"))
            await db_session.execute(
                text(
                    "UPDATE lignes_requisition SET mode_paiement = 'cheque', compte_bancaire_id = :c "
                    "WHERE requisition_id = :rid AND mode_paiement = 'virement'"
                ),
                {"c": equity.id, "rid": req.id},
            )


@pytest.mark.asyncio
async def test_le_drapeau_ne_debloque_pas_une_piece_payee(db_session):
    _, _, req, _, equity = await _contexte(db_session, statut="PAYEE")

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("SET LOCAL onec.changement_compte_volet = 'on'"))
            await db_session.execute(
                text(
                    "UPDATE lignes_requisition SET compte_bancaire_id = :c "
                    "WHERE requisition_id = :rid AND mode_paiement = 'virement'"
                ),
                {"c": equity.id, "rid": req.id},
            )


@pytest.mark.asyncio
async def test_sans_le_drapeau_la_base_refuse_toujours(db_session):
    _, _, req, _, equity = await _contexte(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE lignes_requisition SET compte_bancaire_id = :c "
                    "WHERE requisition_id = :rid AND mode_paiement = 'virement'"
                ),
                {"c": equity.id, "rid": req.id},
            )
