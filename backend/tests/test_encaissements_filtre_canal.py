"""Filtre « Encaissé sur » de la liste des encaissements : caisse ou banque.

Règle partagée avec les rapports de trésorerie (`flux_encaissements`) : les
versements actifs de la note font foi ; sans versement, son en-tête décide.
"""

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.api.v1.endpoints.encaissements import list_encaissements
from app.api.v1.endpoints.exports import construire_classeur_encaissements
from app.models.compte_bancaire import CompteBancaire
from app.models.payment_history import PaymentHistory

from test_encaissements import _enc_org, _enc_user, _encaissement_row, _suffix


async def _compte(db, org):
    compte = CompteBancaire(
        organisation_id=org.id, intitule="Compte banque", numero_compte=f"BK-{_suffix()}",
        devise="USD", solde_initial=Decimal("0"), solde_actuel=Decimal("0"),
        is_active=True, account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


def _versement(org, note, *, canal, montant, compte_id=None, statut="ACTIF"):
    return PaymentHistory(
        organisation_id=org.id, encaissement_id=note.id, montant=Decimal(montant), devise="USD",
        canal=canal, compte_bancaire_id=compte_id,
        mode_paiement="cash" if canal == "CAISSE" else "virement", statut=statut,
    )


async def _liste(db, org, user, canal):
    reponse = await list_encaissements(
        include=None, date_debut=None, date_fin=None, statut_paiement=None, numero_recu=None,
        client=None, budget_poste_id=None, type_client=None, mode_paiement=None, canal=canal,
        compte_bancaire_id=None, expert_comptable_id=None, operation_status="ACTIVE",
        deleted_status="all", est_proforma=False, nature_mouvement=None, order=None,
        limit=50, offset=0, include_summary=True, tenant_id=org.id, user=user, db=db,
    )
    return {str(item["id"]) if isinstance(item, dict) else str(item.id) for item in reponse.items}, reponse


@pytest.fixture
async def notes(db_session):
    org = await _enc_org(db_session, name=f"Filtre canal {_suffix()}")
    user = await _enc_user(db_session, org)
    compte = await _compte(db_session, org)

    caisse = await _encaissement_row(db_session, org, user, montant_paye=Decimal("500"))
    db_session.add(_versement(org, caisse, canal="CAISSE", montant="500"))

    banque = await _encaissement_row(
        db_session, org, user, montant_paye=Decimal("500"), canal="BANQUE", compte_bancaire_id=compte.id
    )
    db_session.add(_versement(org, banque, canal="BANQUE", montant="500", compte_id=compte.id))

    # Acompte en caisse, solde par virement : la note répond aux deux canaux.
    mixte = await _encaissement_row(db_session, org, user, montant_paye=Decimal("500"))
    db_session.add(_versement(org, mixte, canal="CAISSE", montant="200"))
    db_session.add(_versement(org, mixte, canal="BANQUE", montant="300", compte_id=compte.id))

    # Pas encore payée : sa destination annoncée (l'en-tête) décide.
    a_venir_banque = await _encaissement_row(
        db_session, org, user, canal="BANQUE", compte_bancaire_id=compte.id
    )

    # En-tête caisse, mais le seul versement actif est entré en banque ; le
    # versement caisse annulé ne compte plus.
    deplacee = await _encaissement_row(db_session, org, user, montant_paye=Decimal("500"))
    db_session.add(_versement(org, deplacee, canal="CAISSE", montant="500", statut="ANNULE"))
    db_session.add(_versement(org, deplacee, canal="BANQUE", montant="500", compte_id=compte.id))

    await db_session.flush()
    toutes = {
        "caisse": caisse, "banque": banque, "mixte": mixte,
        "a_venir_banque": a_venir_banque, "deplacee": deplacee,
    }
    ids = {nom: str(note.id) for nom, note in toutes.items()}
    ids_numeros = {nom: note.numero_recu for nom, note in toutes.items()}
    return org, user, ids, ids_numeros


@pytest.mark.asyncio
async def test_filtre_caisse(db_session, notes):
    org, user, ids, _ = notes
    trouves, reponse = await _liste(db_session, org, user, "CAISSE")
    assert trouves == {ids["caisse"], ids["mixte"]}
    assert reponse.total == 2


@pytest.mark.asyncio
async def test_filtre_banque(db_session, notes):
    org, user, ids, _ = notes
    trouves, reponse = await _liste(db_session, org, user, "banque")
    assert trouves == {ids["banque"], ids["mixte"], ids["a_venir_banque"], ids["deplacee"]}
    assert reponse.total == 4


@pytest.mark.asyncio
async def test_sans_filtre_tout_revient(db_session, notes):
    org, user, ids, _ = notes
    trouves, _ = await _liste(db_session, org, user, None)
    assert trouves == set(ids.values())


@pytest.mark.asyncio
async def test_canal_inconnu_refuse(db_session, notes):
    org, user, _, _ = notes
    with pytest.raises(HTTPException) as exc:
        await _liste(db_session, org, user, "MOBILE")
    assert exc.value.status_code == 400


def _numeros_du_classeur(wb) -> set[str]:
    return {
        str(cellule)
        for feuille in wb.worksheets
        for ligne in feuille.iter_rows(values_only=True)
        for cellule in ligne
        if isinstance(cellule, str) and cellule.startswith("ND-")
    }


@pytest.mark.asyncio
async def test_export_excel_suit_le_filtre(db_session, notes):
    org, _, _, numeros = notes
    wb, _ = await construire_classeur_encaissements(db_session, org.id, canal="CAISSE")
    assert _numeros_du_classeur(wb) == {numeros["caisse"], numeros["mixte"]}

    wb, _ = await construire_classeur_encaissements(db_session, org.id, canal="BANQUE")
    assert _numeros_du_classeur(wb) == {
        numeros["banque"], numeros["mixte"], numeros["a_venir_banque"], numeros["deplacee"]
    }
