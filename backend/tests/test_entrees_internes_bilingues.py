"""Les listes d'entrées internes montrent-elles les deux sources ?

Phase 1 de la bascule. Le contrat du module `entrees_caisse` est que la somme
de ses lignes égale le terme correspondant des totaux de trésorerie. Les
agrégateurs unionnent `sorties_fonds` et `transferts_internes` depuis toujours ;
tant que les listes ne lisaient qu'une des deux tables, écrire un transfert dans
la table dédiée faisait afficher à une clôture une entrée que sa propre liste ne
justifiait pas.

Ces tests vérifient l'union, et surtout ce qui la rend fausse discrètement :
les bornes de date, qui ne sont pas les mêmes des deux côtés.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.transfert import TransfertInterneCreate
from app.services.entrees_caisse import (
    list_entrees_internes_banque,
    list_entrees_internes_caisse,
)
from app.services.transferts_internes_service import contrepasser_transfer, create_transfer

HIER = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)


async def _contexte(db, *, caisse_usd=Decimal("1000"), banque_usd=Decimal("1000")):
    org = Organisation(nom="Entrées internes", slug=f"ei-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"e{uuid.uuid4().hex[:6]}@ex.com", role="admin",
                prenom="Ada", nom="Lovelace", organisation_id=org.id)
    db.add(user)
    banque_nom = Banque(organisation_id=org.id, nom="Rawbank")
    db.add(banque_nom)
    await db.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque_nom.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=banque_usd, solde_actuel=banque_usd, is_active=True, account_type="BANK",
    )
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=caisse_usd, solde_cdf=Decimal("0"), est_ouverte=True)
    db.add_all([compte, caisse])
    await db.flush()
    return org, user, compte, caisse


def _sortie(org, user, *, montant, type_sortie, canal, compte_id, quand=HIER):
    return SortieFonds(
        organisation_id=org.id, type_sortie=type_sortie, montant_paye=montant,
        mode_paiement="cash", devise="USD", canal=canal, compte_bancaire_id=compte_id,
        motif="Opération historique", beneficiaire="Caisse centrale", statut="VALIDE",
        date_paiement=quand, created_by=user.id, reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )


@pytest.mark.asyncio
async def test_les_entrees_en_caisse_reunissent_les_deux_sources(db_session):
    org, user, compte, _ = await _contexte(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("50"), type_sortie="approvisionnement_caisse",
                           canal="BANQUE", compte_id=compte.id))
    await db_session.commit()
    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    lignes = await list_entrees_internes_caisse(db_session, tenant_id=org.id, devise="USD")

    assert sum((ligne["montant"] for ligne in lignes), Decimal("0")) == Decimal("170")
    types = {ligne["type_operation"] for ligne in lignes}
    assert types == {"APPROVISIONNEMENT", "TRANSFERT_INTERNE"}
    # `origine` dit de quelle TABLE vient la ligne : c'est ce qui permet de
    # lire un écran mixte pendant toute la durée de la bascule, sans jamais
    # renuméroter une référence historique.
    assert {ligne["origine"] for ligne in lignes} == {"legacy", "transfert_interne"}
    # Les deux origines rendent les mêmes clés : les écrans qui les affichent
    # n'ont pas à savoir de quelle table elles viennent.
    assert all(set(lignes[0]) == set(ligne) for ligne in lignes)


@pytest.mark.asyncio
async def test_les_identifiants_ne_peuvent_pas_se_confondre(db_session):
    """Une sortie n°12 et un transfert n°12 sont deux lignes différentes.

    Sans préfixe, elles partageraient la même clé d'affichage et l'une
    remplacerait l'autre à l'écran.
    """
    org, user, compte, _ = await _contexte(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("50"), type_sortie="approvisionnement_caisse",
                           canal="BANQUE", compte_id=compte.id))
    await db_session.commit()
    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    lignes = await list_entrees_internes_caisse(db_session, tenant_id=org.id, devise="USD")
    identifiants = [ligne["id"] for ligne in lignes]

    assert len(set(identifiants)) == len(identifiants)
    assert any(identifiant.startswith("transfert-") for identifiant in identifiants)


@pytest.mark.asyncio
async def test_les_entrees_bancaires_reunissent_les_deux_sources(db_session):
    org, user, compte, _ = await _contexte(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("30"), type_sortie="versement_banque",
                           canal="CAISSE", compte_id=compte.id))
    await db_session.commit()
    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="CAISSE", destination_type="BANQUE", destination_id=compte.id,
            montant=Decimal("80"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    lignes = await list_entrees_internes_banque(db_session, tenant_id=org.id, devise="USD")

    assert sum((ligne["montant"] for ligne in lignes), Decimal("0")) == Decimal("110")
    assert {ligne["destination"] for ligne in lignes} == {"Rawbank - Compte courant"}


@pytest.mark.asyncio
async def test_un_virement_entre_banques_ne_vient_pas_de_la_caisse(db_session):
    """L'origine est portée par la ligne, pas déduite du type d'opération.

    Le classeur d'encaissements écrivait « Caisse » en dur dans la colonne
    source des entrées bancaires. Vrai pour un versement, faux pour un virement
    de banque à banque — et un faux sur un document exporté.
    """
    org, user, compte, _ = await _contexte(db_session)
    autre = CompteBancaire(
        organisation_id=org.id, intitule="Compte épargne",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("0"), solde_actuel=Decimal("0"), is_active=True, account_type="BANK",
    )
    db_session.add(autre)
    await db_session.commit()
    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id,
            destination_type="BANQUE", destination_id=autre.id,
            montant=Decimal("200"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    lignes = await list_entrees_internes_banque(db_session, tenant_id=org.id, devise="USD")

    assert len(lignes) == 1
    assert lignes[0]["provenance"] == "Rawbank - Compte courant"
    assert lignes[0]["origine"] == "transfert_interne"
    assert lignes[0]["destination"] == "Compte épargne"
    assert lignes[0]["libelle"] == "Transfert interne entre comptes bancaires"


@pytest.mark.asyncio
async def test_un_versement_historique_vient_toujours_de_la_caisse(db_session):
    org, user, compte, _ = await _contexte(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("30"), type_sortie="versement_banque",
                           canal="CAISSE", compte_id=compte.id))
    await db_session.commit()

    lignes = await list_entrees_internes_banque(db_session, tenant_id=org.id, devise="USD")

    assert [ligne["provenance"] for ligne in lignes] == ["Caisse"]
    assert [ligne["origine"] for ligne in lignes] == ["legacy"]


@pytest.mark.asyncio
async def test_les_bornes_de_date_suivent_la_source(db_session):
    """Chaque table a son horodatage : la sortie par `date_paiement`, le
    transfert par `date_transfert`. Une borne appliquée à la mauvaise colonne
    ferait sortir une ligne de la liste sans la sortir du total."""
    org, user, compte, _ = await _contexte(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("50"), type_sortie="approvisionnement_caisse",
                           canal="BANQUE", compte_id=compte.id, quand=HIER))
    await db_session.commit()
    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    # Fenêtre qui exclut la sortie d'hier et garde le transfert de maintenant.
    depuis = transfert.date_transfert - timedelta(minutes=5)
    lignes = await list_entrees_internes_caisse(
        db_session, tenant_id=org.id, devise="USD", date_debut=depuis
    )
    assert [ligne["montant"] for ligne in lignes] == [Decimal("120")]

    # Fenêtre qui s'arrête hier : seule la sortie historique reste.
    lignes = await list_entrees_internes_caisse(
        db_session, tenant_id=org.id, devise="USD", date_fin=HIER
    )
    assert [ligne["montant"] for ligne in lignes] == [Decimal("50")]


@pytest.mark.asyncio
async def test_la_borne_stricte_de_cloture_vaut_pour_les_deux_sources(db_session):
    """`strict_debut` reproduit le « > » de la balance de clôture : une
    opération horodatée à la clôture précédente appartient à la période close."""
    org, user, compte, _ = await _contexte(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("50"), type_sortie="approvisionnement_caisse",
                           canal="BANQUE", compte_id=compte.id, quand=HIER))
    await db_session.commit()
    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    inclusif = await list_entrees_internes_caisse(
        db_session, tenant_id=org.id, devise="USD", date_debut=transfert.date_transfert
    )
    strict = await list_entrees_internes_caisse(
        db_session, tenant_id=org.id, devise="USD",
        date_debut=transfert.date_transfert, strict_debut=True,
    )

    assert [ligne["montant"] for ligne in inclusif] == [Decimal("120")]
    assert strict == []


@pytest.mark.asyncio
async def test_une_contrepassation_est_visible_a_cote_de_l_originale(db_session):
    """Les deux lignes restent affichées : masquer l'originale montrerait une
    correction sans l'opération qu'elle corrige, et le total ne tomberait plus.
    """
    org, user, compte, _ = await _contexte(db_session)
    await db_session.commit()
    origine = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )
    await contrepasser_transfer(
        db_session, transfer_id=origine.id, tenant_id=org.id, user=user, motif="Erreur de saisie"
    )

    entrees_caisse = await list_entrees_internes_caisse(db_session, tenant_id=org.id, devise="USD")
    entrees_banque = await list_entrees_internes_banque(db_session, tenant_id=org.id, devise="USD")

    # L'entrée en caisse d'origine reste ; la correction est une entrée
    # bancaire, dans l'autre sens et à sa propre date.
    assert [ligne["montant"] for ligne in entrees_caisse] == [Decimal("120")]
    assert [ligne["montant"] for ligne in entrees_banque] == [Decimal("120")]
    assert entrees_banque[0]["libelle"] == "Contre-passation d'un transfert interne"


@pytest.mark.asyncio
async def test_la_borne_de_lignes_porte_sur_l_ensemble_fusionne(db_session):
    """Borner chaque source séparément rendrait les N premières de chacune,
    c'est-à-dire pas les N plus récentes."""
    org, user, compte, _ = await _contexte(db_session)
    for _ in range(3):
        db_session.add(_sortie(org, user, montant=Decimal("10"), type_sortie="approvisionnement_caisse",
                               canal="BANQUE", compte_id=compte.id, quand=HIER))
    await db_session.commit()
    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id, user=user,
    )

    lignes = await list_entrees_internes_caisse(db_session, tenant_id=org.id, devise="USD", limit=2)

    assert len(lignes) == 2
    # Le transfert est le plus récent : il doit être en tête, pas noyé par les
    # trois lignes historiques.
    assert lignes[0]["montant"] == Decimal("120")


@pytest.mark.asyncio
async def test_les_lignes_restent_cloisonnees_par_organisation(db_session):
    org_a, user_a, compte_a, _ = await _contexte(db_session)
    org_b, user_b, compte_b, _ = await _contexte(db_session)
    await db_session.commit()
    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=compte_b.id, destination_type="CAISSE",
            montant=Decimal("500"), devise="USD",
        ),
        tenant_id=org_b.id, user=user_b,
    )

    assert await list_entrees_internes_caisse(db_session, tenant_id=org_a.id, devise="USD") == []
    lignes_b = await list_entrees_internes_caisse(db_session, tenant_id=org_b.id, devise="USD")
    assert [ligne["montant"] for ligne in lignes_b] == [Decimal("500")]
