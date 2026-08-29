"""Un mouvement interne laisse-t-il TOUJOURS ses deux traces ?

Un versement à la banque sort de la caisse **et** entre en banque. Un
approvisionnement sort de la banque **et** entre en caisse. Un audit qui ne
retrouve qu'un seul des deux côtés ne peut pas rapprocher l'opération : il voit
de l'argent disparaître d'une poche sans jamais le voir arriver dans l'autre.

C'est la propriété que ces tests verrouillent, sur les **quatre** cas qui
existent pendant la bascule — chemin historique et moteur dédié, dans les deux
sens. Pour chacun :

- le journal de la poche qui envoie porte une ligne en **sortie** ;
- le journal de la poche qui reçoit porte une ligne en **entrée** ;
- les deux lignes portent le **même montant** et la **même référence**, ce qui
  permet de les rapprocher ;
- l'écriture comptable porte les deux jambes, équilibrées.

Ces tests sont volontairement redondants avec les agrégats : un total juste
n'est pas une trace. Un auditeur lit des lignes, pas des sommes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.v1.endpoints.reports import journal_tresorerie
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.modules.comptabilite.models import ComptaEcriture
from app.schemas.transfert import TransfertInterneCreate
from app.services.transferts_internes_service import create_transfer
from tests.test_comptabilite_wiring import _activer_comptabilite

MOMENT = datetime(2026, 8, 25, 11, 0, tzinfo=timezone.utc)


async def _contexte(db):
    org = Organisation(nom="Traçabilité", slug=f"tr-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"t{uuid.uuid4().hex[:6]}@ex.com", role="admin",
                prenom="Grace", nom="Hopper", organisation_id=org.id)
    banque = Banque(organisation_id=org.id, nom="Rawbank")
    db.add_all([user, banque])
    await db.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("1000"), solde_actuel=Decimal("1000"),
        is_active=True, account_type="BANK",
    )
    db.add_all([
        compte,
        CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("1000"), solde_cdf=Decimal("0"), est_ouverte=True),
    ])
    await db.flush()
    return org, user, compte


async def _journal(db, user, org, canal, compte_id=None):
    return await journal_tresorerie(
        canal=canal, devise="USD", compte_bancaire_id=compte_id,
        date_debut=None, date_fin=None, user=user, db=db, tenant_id=org.id,
    )


def _lignes(journal, *, sens: str) -> list:
    """Lignes non nulles du côté demandé (`entree` ou `sortie`)."""
    return [ligne for ligne in journal.lignes if Decimal(getattr(ligne, sens)) > 0]


def _sortie_legacy(org, user, *, type_sortie, canal, compte_id, montant, reference):
    return SortieFonds(
        organisation_id=org.id, type_sortie=type_sortie, montant_paye=montant,
        mode_paiement="cash", devise="USD", canal=canal, compte_bancaire_id=compte_id,
        motif="Mouvement interne", beneficiaire="Interne", statut="VALIDE",
        date_paiement=MOMENT, created_by=user.id, reference_numero=reference,
    )


# ---------------------------------------------------------------------------
# Chemin historique
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_versement_legacy_trace_la_sortie_de_caisse_et_l_entree_en_banque(db_session):
    org, user, compte = await _contexte(db_session)
    reference = f"PAY-{uuid.uuid4().hex[:8]}"
    db_session.add(_sortie_legacy(
        org, user, type_sortie="versement_banque", canal="CAISSE",
        compte_id=compte.id, montant=Decimal("300"), reference=reference,
    ))
    await db_session.commit()

    caisse = await _journal(db_session, user, org, "CAISSE")
    banque = await _journal(db_session, user, org, "BANQUE", compte.id)

    sorties_caisse = _lignes(caisse, sens="sortie")
    entrees_banque = _lignes(banque, sens="entree")
    assert [l.sortie for l in sorties_caisse] == [Decimal("300")]
    assert [l.entree for l in entrees_banque] == [Decimal("300")]
    # Même référence des deux côtés : c'est elle qui permet de rapprocher les
    # deux jambes d'un même mouvement lors d'un contrôle.
    assert sorties_caisse[0].reference == reference == entrees_banque[0].reference
    assert entrees_banque[0].type_operation == "VERSEMENT"
    # Rien n'est compté deux fois : la caisse ne voit pas d'entrée, la banque
    # pas de sortie.
    assert _lignes(caisse, sens="entree") == []
    assert _lignes(banque, sens="sortie") == []


@pytest.mark.asyncio
async def test_approvisionnement_legacy_trace_la_sortie_banque_et_l_entree_en_caisse(db_session):
    org, user, compte = await _contexte(db_session)
    reference = f"PAY-{uuid.uuid4().hex[:8]}"
    db_session.add(_sortie_legacy(
        org, user, type_sortie="approvisionnement_caisse", canal="BANQUE",
        compte_id=compte.id, montant=Decimal("250"), reference=reference,
    ))
    await db_session.commit()

    caisse = await _journal(db_session, user, org, "CAISSE")
    banque = await _journal(db_session, user, org, "BANQUE", compte.id)

    sorties_banque = _lignes(banque, sens="sortie")
    entrees_caisse = _lignes(caisse, sens="entree")
    assert [l.sortie for l in sorties_banque] == [Decimal("250")]
    assert [l.entree for l in entrees_caisse] == [Decimal("250")]
    assert sorties_banque[0].reference == reference == entrees_caisse[0].reference
    assert entrees_caisse[0].type_operation == "APPROVISIONNEMENT"
    assert _lignes(caisse, sens="sortie") == []
    assert _lignes(banque, sens="entree") == []


# ---------------------------------------------------------------------------
# Moteur dédié
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transfert_caisse_vers_banque_trace_ses_deux_jambes(db_session):
    org, user, compte = await _contexte(db_session)
    await db_session.commit()
    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="CAISSE", destination_type="BANQUE", destination_id=compte.id,
            montant=Decimal("300"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    caisse = await _journal(db_session, user, org, "CAISSE")
    banque = await _journal(db_session, user, org, "BANQUE", compte.id)

    sorties_caisse = _lignes(caisse, sens="sortie")
    entrees_banque = _lignes(banque, sens="entree")
    assert [l.sortie for l in sorties_caisse] == [Decimal("300")]
    assert [l.entree for l in entrees_banque] == [Decimal("300")]
    assert sorties_caisse[0].type_operation == "TRANSFERT_SORTIE"
    assert entrees_banque[0].type_operation == "TRANSFERT_ENTREE"
    # Une seule référence `TRF-` porte les deux jambes : l'opération est
    # rapprochable d'un journal à l'autre sans connaître la table.
    assert sorties_caisse[0].reference == transfert.reference == entrees_banque[0].reference
    assert transfert.reference.startswith("TRF-")


@pytest.mark.asyncio
async def test_transfert_banque_vers_caisse_trace_ses_deux_jambes(db_session):
    org, user, compte = await _contexte(db_session)
    await db_session.commit()
    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("250"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    caisse = await _journal(db_session, user, org, "CAISSE")
    banque = await _journal(db_session, user, org, "BANQUE", compte.id)

    assert [l.sortie for l in _lignes(banque, sens="sortie")] == [Decimal("250")]
    assert [l.entree for l in _lignes(caisse, sens="entree")] == [Decimal("250")]
    assert _lignes(banque, sens="sortie")[0].type_operation == "TRANSFERT_SORTIE"
    assert _lignes(caisse, sens="entree")[0].type_operation == "TRANSFERT_ENTREE"
    assert _lignes(caisse, sens="entree")[0].reference == transfert.reference


@pytest.mark.asyncio
async def test_virement_entre_banques_trace_le_debit_et_le_credit_sur_chaque_compte(db_session):
    """Le cas qu'un journal par compte pourrait laisser passer : les deux jambes
    tombent sur le même canal, mais sur deux comptes différents."""
    org, user, source = await _contexte(db_session)
    destination = CompteBancaire(
        organisation_id=org.id, banque_id=source.banque_id, intitule="Compte épargne",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("0"), solde_actuel=Decimal("0"),
        is_active=True, account_type="BANK",
    )
    db_session.add(destination)
    await db_session.commit()
    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=source.id,
            destination_type="BANQUE", destination_id=destination.id,
            montant=Decimal("400"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    journal_source = await _journal(db_session, user, org, "BANQUE", source.id)
    journal_destination = await _journal(db_session, user, org, "BANQUE", destination.id)

    assert [l.sortie for l in _lignes(journal_source, sens="sortie")] == [Decimal("400")]
    assert _lignes(journal_source, sens="entree") == []
    assert [l.entree for l in _lignes(journal_destination, sens="entree")] == [Decimal("400")]
    assert _lignes(journal_destination, sens="sortie") == []
    assert _lignes(journal_source, sens="sortie")[0].reference == transfert.reference


# ---------------------------------------------------------------------------
# Comptabilité : les deux jambes de l'écriture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_l_ecriture_porte_le_debit_d_une_poche_et_le_credit_de_l_autre(db_session):
    """Une écriture équilibrée ne suffit pas : encore faut-il qu'elle touche
    **deux comptes de trésorerie distincts**, un débité et un crédité. Une
    écriture qui débiterait et créditerait le même compte serait équilibrée et
    ne dirait rien du mouvement."""
    org, user, compte = await _contexte(db_session)
    await _activer_comptabilite(db_session, org)
    await db_session.commit()
    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="CAISSE", destination_type="BANQUE", destination_id=compte.id,
            montant=Decimal("150"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    ecriture = await db_session.scalar(
        select(ComptaEcriture)
        .options(selectinload(ComptaEcriture.lignes))
        .where(
            ComptaEcriture.organisation_id == org.id,
            ComptaEcriture.type_origine == "transfert_interne",
            ComptaEcriture.objet_origine_id == str(transfert.id),
        )
    )
    assert ecriture is not None
    debits = [l for l in ecriture.lignes if Decimal(l.debit or 0) > 0]
    credits = [l for l in ecriture.lignes if Decimal(l.credit or 0) > 0]
    assert len(debits) == 1 and len(credits) == 1
    assert Decimal(debits[0].debit) == Decimal(credits[0].credit) == Decimal("150")
    # Deux comptes distincts : la poche qui reçoit et la poche qui envoie.
    assert debits[0].compte_id != credits[0].compte_id


@pytest.mark.asyncio
async def test_les_deux_jambes_restent_lisibles_apres_contrepassation(db_session):
    """La correction n'efface aucune trace : le mouvement d'origine garde ses
    deux jambes, et la correction ajoute les siennes, en sens inverse."""
    from app.services.transferts_internes_service import contrepasser_transfer

    org, user, compte = await _contexte(db_session)
    await db_session.commit()
    origine = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="CAISSE", destination_type="BANQUE", destination_id=compte.id,
            montant=Decimal("300"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )
    inverse = await contrepasser_transfer(
        db_session, transfer_id=origine.id, tenant_id=org.id, user=user, motif="Erreur de saisie"
    )

    caisse = await _journal(db_session, user, org, "CAISSE")
    banque = await _journal(db_session, user, org, "BANQUE", compte.id)

    # Caisse : la sortie d'origine ET l'entrée de la correction.
    assert [l.sortie for l in _lignes(caisse, sens="sortie")] == [Decimal("300")]
    assert [l.entree for l in _lignes(caisse, sens="entree")] == [Decimal("300")]
    # Banque : l'entrée d'origine ET la sortie de la correction.
    assert [l.entree for l in _lignes(banque, sens="entree")] == [Decimal("300")]
    assert [l.sortie for l in _lignes(banque, sens="sortie")] == [Decimal("300")]
    # Quatre lignes, deux références distinctes : l'audit voit l'opération et
    # sa correction, jamais une ligne modifiée.
    references = {l.reference for l in caisse.lignes} | {l.reference for l in banque.lignes}
    assert references == {origine.reference, inverse.reference}
    assert origine.reference != inverse.reference
    # Et le net est nul des deux côtés : rien n'a été créé ni perdu.
    assert caisse.total_entrees == caisse.total_sorties
    assert banque.total_entrees == banque.total_sorties
