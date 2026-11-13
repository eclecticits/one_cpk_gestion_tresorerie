"""Changement du canal de paiement d'une réquisition validée et non payée.

Les déclencheurs de verrou sont installés à partir du SQL de la migration
elle-même : le schéma de test naît de `create_all()`, qui n'en crée aucun, et
sans eux la suite ne verrait pas ce que la base refuse.
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
from app.models.requisition import Requisition
from app.services.changement_canal_requisition import changer_canal_requisition

from test_budget_engagements import _org, _poste, _requisition, _user


def _migration():
    chemin = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261008_changement_canal.py"
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _poser_les_verrous(db):
    mig = _migration()
    await db.execute(text(mig.fonction_lignes(avec_canal=True)))
    await db.execute(text(mig.fonction_requisitions(avec_canal=True)))
    for instruction in mig.declencheurs():
        await db.execute(text(instruction))
    await db.flush()


async def _contexte(db, *, statut="APPROUVEE"):
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    req = await _requisition(db, org, user, poste, examen_status="EXAMINEE")
    banque = Banque(organisation_id=org.id, nom="Equity")
    db.add(banque)
    await db.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("1000"), solde_actuel=Decimal("1000"),
        is_active=True, account_type="BANK",
    )
    db.add(compte)
    req.status = statut
    await db.flush()
    await _poser_les_verrous(db)
    return org, user, req, compte


async def _lignes(db, req):
    return (
        await db.execute(select(LigneRequisition).where(LigneRequisition.requisition_id == req.id))
    ).scalars().all()


@pytest.mark.parametrize("statut", ["AUTORISEE", "APPROUVEE"])
@pytest.mark.asyncio
async def test_caisse_vers_banque_sur_requisition_validee(db_session, statut):
    org, _, req, compte = await _contexte(db_session, statut=statut)

    resultat = await changer_canal_requisition(
        db_session, requisition=req, mode_paiement="virement",
        compte_bancaire_id=compte.id, tenant_id=org.id,
    )

    assert resultat["avant"]["mode_paiement"] == "cash"
    assert req.mode_paiement == "virement"
    assert req.compte_bancaire_id == compte.id
    assert req.bank_account_snapshot["id"] == compte.id
    for ligne in await _lignes(db_session, req):
        assert ligne.mode_paiement == "virement"
        assert ligne.compte_bancaire_id == compte.id


@pytest.mark.asyncio
async def test_banque_vers_caisse(db_session):
    org, _, req, compte = await _contexte(db_session)
    await changer_canal_requisition(
        db_session, requisition=req, mode_paiement="virement",
        compte_bancaire_id=compte.id, tenant_id=org.id,
    )

    await changer_canal_requisition(
        db_session, requisition=req, mode_paiement="cash",
        compte_bancaire_id=None, tenant_id=org.id,
    )

    assert req.mode_paiement == "cash"
    assert req.compte_bancaire_id is None
    for ligne in await _lignes(db_session, req):
        assert ligne.mode_paiement == "cash"
        assert ligne.compte_bancaire_id is None


@pytest.mark.parametrize("statut", ["PAYEE", "EN_DECAISSEMENT"])
@pytest.mark.asyncio
async def test_requisition_payee_garde_son_canal(db_session, statut):
    org, _, req, compte = await _contexte(db_session, statut=statut)

    with pytest.raises(HTTPException) as exc:
        await changer_canal_requisition(
            db_session, requisition=req, mode_paiement="virement",
            compte_bancaire_id=compte.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_ordre_de_decaissement_emis_bloque(db_session):
    org, user, req, compte = await _contexte(db_session)
    db_session.add(
        OrdreDecaissement(
            organisation_id=org.id, requisition_id=req.id, numero_ordre=f"OD-{uuid.uuid4().hex[:6]}",
            beneficiaire="Fournisseur", beneficiaire_normalise="FOURNISSEUR",
            montant=Decimal("10"), devise="USD", mode_paiement="cash", canal="CAISSE",
            statut="AUTORISE", autorise_par=user.id,
        )
    )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await changer_canal_requisition(
            db_session, requisition=req, mode_paiement="virement",
            compte_bancaire_id=compte.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_sans_le_service_la_base_refuse_toujours(db_session):
    """Hors du service, le verrou des lignes validées tient."""
    _, _, req, compte = await _contexte(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(
                text("UPDATE lignes_requisition SET mode_paiement = 'virement' WHERE requisition_id = :rid"),
                {"rid": req.id},
            )


@pytest.mark.asyncio
async def test_le_drapeau_ne_laisse_passer_que_le_canal(db_session):
    """Même sous le drapeau, toucher autre chose que le canal est refusé."""
    _, _, req, _ = await _contexte(db_session)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("SET LOCAL onec.changement_canal = 'on'"))
            await db_session.execute(
                text("UPDATE requisitions SET mode_paiement = 'virement', objet = 'Autre' WHERE id = :rid"),
                {"rid": req.id},
            )


@pytest.mark.asyncio
async def test_le_drapeau_ne_debloque_pas_une_piece_payee(db_session):
    _, _, req, _ = await _contexte(db_session, statut="PAYEE")

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("SET LOCAL onec.changement_canal = 'on'"))
            await db_session.execute(
                text("UPDATE requisitions SET mode_paiement = 'virement' WHERE id = :rid"),
                {"rid": req.id},
            )


# --- Décaissement progressif : le canal du reste à payer change encore --------


def _migration_progressif():
    chemin = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20261113_canal_progressif.py"
    spec = importlib.util.spec_from_file_location(chemin.stem, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _contexte_progressif(db, *, statut="EN_DECAISSEMENT", progressif=True):
    """Réquisition entamée, verrous de la dernière migration posés."""
    org, user, req, compte = await _contexte(db, statut="APPROUVEE")
    req.decaissement_progressif = progressif
    await db.flush()
    req.status = statut
    await db.flush()
    mig = _migration_progressif()
    await db.execute(text(mig.fonction_lignes()))
    await db.execute(text(mig.fonction_requisitions()))
    await db.flush()
    return org, user, req, compte


def _tranche(org, user, req, *, statut):
    return OrdreDecaissement(
        organisation_id=org.id, requisition_id=req.id, numero_ordre=f"OD-{uuid.uuid4().hex[:6]}",
        beneficiaire="Fournisseur", beneficiaire_normalise="FOURNISSEUR",
        montant=Decimal("10"), devise="USD", mode_paiement="cash", canal="CAISSE",
        statut=statut, autorise_par=user.id,
    )


@pytest.mark.asyncio
async def test_progressif_entame_change_de_canal_pour_le_reste(db_session):
    """Une tranche payée en espèces n'empêche pas de passer le reste en banque,
    et elle garde son canal."""
    org, user, req, compte = await _contexte_progressif(db_session)
    payee = _tranche(org, user, req, statut="PAYE")
    db_session.add(payee)
    await db_session.flush()

    await changer_canal_requisition(
        db_session, requisition=req, mode_paiement="virement",
        compte_bancaire_id=compte.id, tenant_id=org.id,
    )

    assert req.status == "EN_DECAISSEMENT"
    assert req.mode_paiement == "virement"
    assert req.compte_bancaire_id == compte.id
    for ligne in await _lignes(db_session, req):
        assert ligne.mode_paiement == "virement"
        assert ligne.compte_bancaire_id == compte.id
    await db_session.refresh(payee)
    assert payee.mode_paiement == "cash"
    assert payee.canal == "CAISSE"


@pytest.mark.asyncio
async def test_progressif_tranche_en_attente_bloque(db_session):
    org, user, req, compte = await _contexte_progressif(db_session)
    db_session.add(_tranche(org, user, req, statut="AUTORISE"))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await changer_canal_requisition(
            db_session, requisition=req, mode_paiement="virement",
            compte_bancaire_id=compte.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409
    assert "tranche" in exc.value.detail


@pytest.mark.asyncio
async def test_progressif_tranche_annulee_ne_bloque_pas(db_session):
    org, user, req, compte = await _contexte_progressif(db_session)
    db_session.add(_tranche(org, user, req, statut="ANNULE"))
    await db_session.flush()

    await changer_canal_requisition(
        db_session, requisition=req, mode_paiement="virement",
        compte_bancaire_id=compte.id, tenant_id=org.id,
    )
    assert req.mode_paiement == "virement"


@pytest.mark.asyncio
async def test_progressif_solde_garde_son_canal(db_session):
    org, _, req, compte = await _contexte_progressif(db_session, statut="PAYEE")

    with pytest.raises(HTTPException) as exc:
        await changer_canal_requisition(
            db_session, requisition=req, mode_paiement="virement",
            compte_bancaire_id=compte.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_classique_en_decaissement_reste_fermee(db_session):
    """L'ouverture ne vaut que pour le décaissement progressif."""
    org, _, req, compte = await _contexte_progressif(db_session, progressif=False)

    with pytest.raises(HTTPException) as exc:
        await changer_canal_requisition(
            db_session, requisition=req, mode_paiement="virement",
            compte_bancaire_id=compte.id, tenant_id=org.id,
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_le_drapeau_ne_debloque_pas_une_classique_en_decaissement(db_session):
    """Même posé à la main, le drapeau ne vaut en décaissement que pour une
    pièce progressive : la base lit la réquisition, pas l'intention."""
    _, _, req, _ = await _contexte_progressif(db_session, progressif=False)

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("SET LOCAL onec.changement_canal = 'on'"))
            await db_session.execute(
                text("UPDATE requisitions SET mode_paiement = 'virement' WHERE id = :rid"),
                {"rid": req.id},
            )


@pytest.mark.asyncio
async def test_le_drapeau_ne_debloque_pas_une_progressive_soldee(db_session):
    _, _, req, _ = await _contexte_progressif(db_session, statut="PAYEE")

    with pytest.raises(DBAPIError):
        async with db_session.begin_nested():
            await db_session.execute(text("SET LOCAL onec.changement_canal = 'on'"))
            await db_session.execute(
                text("UPDATE lignes_requisition SET mode_paiement = 'virement' WHERE requisition_id = :rid"),
                {"rid": req.id},
            )
