"""Le filet de la bascule : la réconciliation détecte-t-elle ce qu'elle promet ?

Un contrôle qui ne tombe jamais en panne ne prouve rien. Chaque test ci-dessous
part d'une organisation dont les soldes sont justes, puis casse **une** chose et
vérifie que le rapport la nomme — c'est la seule façon de savoir que la photo de
départ vaudra quelque chose une fois prise sur la production.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.retour_caisse import RetourCaisse
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.schemas.transfert import TransfertInterneCreate
from app.services.transferts_internes_service import contrepasser_transfer, create_transfer
from scripts.reconcile_tresorerie import (
    TOLERANCE_PAR_DEFAUT,
    controler_caisse,
    controler_comptes_bancaires,
    controler_couverture_affichage,
    reconcilier_organisation,
)

MOMENT = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)


async def _organisation(db):
    org = Organisation(nom="Réconciliation", slug=f"rec-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _utilisateur(db, org):
    user = User(id=uuid.uuid4(), email=f"r{uuid.uuid4().hex[:6]}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


async def _caisse_avec_compte_cash(db, org, *, initial=Decimal("0"), solde=Decimal("0")):
    """La caisse a deux faces : le compte CASH qui porte son solde d'ouverture
    (`solde_initial`, terme de la formule) et `caisse_centrale` qui porte son
    solde courant. C'est le montage que produit le bootstrap d'un tenant."""
    db.add(
        CompteBancaire(
            organisation_id=org.id,
            intitule="Caisse USD",
            numero_compte=f"CASH-USD-{uuid.uuid4().hex[:8]}",
            devise="USD",
            solde_initial=initial,
            solde_actuel=initial,
            is_active=True,
            account_type="CASH",
        )
    )
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=solde, solde_cdf=Decimal("0"), est_ouverte=True)
    db.add(caisse)
    await db.flush()
    return caisse


async def _banque(db, org, *, solde_initial=Decimal("0"), solde=None):
    compte = CompteBancaire(
        organisation_id=org.id,
        intitule="Compte courant",
        numero_compte=f"BANK-{uuid.uuid4().hex[:8]}",
        devise="USD",
        solde_initial=solde_initial,
        solde_actuel=solde_initial if solde is None else solde,
        is_active=True,
        account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


def _encaissement(org, *, montant, canal="CAISSE", compte_id=None, statut_operation="ACTIVE"):
    return Encaissement(
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client",
        libelle="Recette",
        montant=montant,
        montant_total=montant,
        montant_paye=montant,
        montant_percu=montant,
        devise_perception="USD",
        canal=canal,
        compte_bancaire_id=compte_id,
        statut_paiement="complet",
        mode_paiement="cash",
        est_proforma=False,
        is_deleted=False,
        statut_operation=statut_operation,
        date_encaissement=MOMENT,
    )


def _sortie(org, user, *, montant, canal="CAISSE", type_sortie="sortie_directe", compte_id=None, statut="VALIDE"):
    return SortieFonds(
        organisation_id=org.id,
        type_sortie=type_sortie,
        montant_paye=montant,
        mode_paiement="cash",
        devise="USD",
        canal=canal,
        compte_bancaire_id=compte_id,
        motif="Opération",
        beneficiaire="Bénéficiaire",
        statut=statut,
        date_paiement=MOMENT,
        created_by=user.id,
        reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
    )


def _ecart(controles, perimetre_contient: str, devise: str = "USD") -> Decimal:
    for controle in controles:
        if perimetre_contient in controle.perimetre and controle.devise == devise:
            return controle.ecart
    raise AssertionError(f"contrôle introuvable : {perimetre_contient} [{devise}]")


async def _organisation_saine(db):
    """Une organisation dont chaque solde stocké est exactement justifié.

    Caisse : 200 d'ouverture + 300 encaissés + 50 approvisionnés + 20 rendus
             − 100 sortis − 30 versés = 440.
    Banque : 1 000 d'ouverture + 30 reçus du versement − 50 retirés pour
             l'approvisionnement = 980.
    """
    org = await _organisation(db)
    user = await _utilisateur(db, org)
    caisse = await _caisse_avec_compte_cash(db, org, initial=Decimal("200"), solde=Decimal("440"))
    banque = await _banque(db, org, solde_initial=Decimal("1000"), solde=Decimal("980"))

    db.add(_encaissement(org, montant=Decimal("300")))
    sortie = _sortie(org, user, montant=Decimal("100"))
    db.add(sortie)
    db.add(_sortie(org, user, montant=Decimal("50"), canal="BANQUE", type_sortie="approvisionnement_caisse", compte_id=banque.id))
    db.add(_sortie(org, user, montant=Decimal("30"), canal="CAISSE", type_sortie="versement_banque", compte_id=banque.id))
    await db.flush()
    db.add(
        RetourCaisse(
            organisation_id=org.id,
            sortie_fonds_id=sortie.id,
            type_retour="reliquat_avance",
            montant=Decimal("20"),
            devise="USD",
            canal="CAISSE",
            mode="cash",
            reference_numero=f"RET-{uuid.uuid4().hex[:8]}",
            motif="Reliquat",
            date_retour=MOMENT,
            statut="VALIDE",
            created_by=user.id,
        )
    )
    await db.flush()
    return org, user, caisse, banque


@pytest.mark.asyncio
async def test_photo_de_depart_conforme_sur_une_organisation_saine(db_session):
    org, _, _, _ = await _organisation_saine(db_session)

    rapport = await reconcilier_organisation(db_session, organisation_id=org.id, nom=org.nom)

    assert rapport.ecarts(TOLERANCE_PAR_DEFAUT) == []
    assert _ecart(rapport.caisse, "Caisse centrale") == Decimal("0")
    assert _ecart(rapport.banques, "Banque #") == Decimal("0")


@pytest.mark.asyncio
async def test_un_solde_de_caisse_qui_derive_est_nomme_avec_son_ecart(db_session):
    """Le cas qui justifie tout le script : de l'argent qui apparaît sans
    mouvement pour l'expliquer."""
    org, _, caisse, _ = await _organisation_saine(db_session)
    caisse.solde_usd = Decimal("465")  # +25 que rien ne justifie
    await db_session.flush()

    controles = await controler_caisse(db_session, org.id)

    assert _ecart(controles, "Caisse centrale") == Decimal("25")
    en_defaut = [c for c in controles if not c.juste(TOLERANCE_PAR_DEFAUT)]
    assert len(en_defaut) == 1
    # La décomposition accompagne l'écart : sans elle, le rapport dit qu'il y a
    # un problème sans donner par quel bout le prendre.
    assert en_defaut[0].termes["encaissements"] == Decimal("300")
    # Le versement à la banque est une sortie de caisse comme une autre : son
    # canal est CAISSE, il rejoint donc les 100 de la sortie directe.
    assert en_defaut[0].termes["sorties"] == Decimal("-130")


@pytest.mark.asyncio
async def test_un_solde_bancaire_qui_derive_est_nomme_avec_son_ecart(db_session):
    org, _, _, banque = await _organisation_saine(db_session)
    banque.solde_actuel = Decimal("900")  # −80 que rien ne justifie
    await db_session.flush()

    controles = await controler_comptes_bancaires(db_session, org.id)

    assert _ecart(controles, "Banque #") == Decimal("-80")


@pytest.mark.asyncio
async def test_une_sortie_annulee_sort_du_perimetre(db_session):
    """Une sortie annulée a été re-créditée : la compter reviendrait à débiter
    deux fois la caisse dans la formule."""
    org, user, caisse, _ = await _organisation_saine(db_session)
    db_session.add(_sortie(org, user, montant=Decimal("70"), statut="ANNULEE"))
    await db_session.flush()

    controles = await controler_caisse(db_session, org.id)

    assert _ecart(controles, "Caisse centrale") == Decimal("0")


@pytest.mark.asyncio
async def test_un_encaissement_supprime_sort_du_perimetre(db_session):
    org, _, _, _ = await _organisation_saine(db_session)
    annule = _encaissement(org, montant=Decimal("400"), statut_operation="ANNULE")
    db_session.add(annule)
    await db_session.flush()

    controles = await controler_caisse(db_session, org.id)

    assert _ecart(controles, "Caisse centrale") == Decimal("0")


@pytest.mark.asyncio
async def test_le_moteur_dedie_laisse_les_soldes_reconcilies(db_session):
    """Un transfert écrit dans la table dédiée doit rester expliqué par la
    formule : c'est la condition pour que la bascule ne crée aucun écart."""
    org, user, caisse, banque = await _organisation_saine(db_session)
    await db_session.commit()

    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=banque.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id,
        user=user,
    )

    rapport = await reconcilier_organisation(db_session, organisation_id=org.id, nom=org.nom)

    assert _ecart(rapport.caisse, "Caisse centrale") == Decimal("0")
    assert _ecart(rapport.banques, "Banque #") == Decimal("0")


@pytest.mark.asyncio
async def test_une_contrepassation_reste_neutre_pour_la_reconciliation(db_session):
    """L'original garde son montant et son statut CONTREPASSE, l'inverse existe
    à côté : la formule ne filtre aucun statut, les deux s'annulent et les
    soldes reviennent exactement à leur point de départ."""
    org, user, caisse, banque = await _organisation_saine(db_session)
    await db_session.commit()
    caisse_avant = Decimal(str(caisse.solde_usd))
    banque_avant = Decimal(str(banque.solde_actuel))

    transfert = await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=banque.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id,
        user=user,
    )
    await contrepasser_transfer(
        db_session, transfer_id=transfert.id, tenant_id=org.id, user=user, motif="Erreur de saisie"
    )

    await db_session.refresh(caisse)
    await db_session.refresh(banque)
    assert Decimal(str(caisse.solde_usd)) == caisse_avant
    assert Decimal(str(banque.solde_actuel)) == banque_avant

    rapport = await reconcilier_organisation(db_session, organisation_id=org.id, nom=org.nom)
    assert _ecart(rapport.caisse, "Caisse centrale") == Decimal("0")
    assert _ecart(rapport.banques, "Banque #") == Decimal("0")


@pytest.mark.asyncio
async def test_les_lignes_affichees_justifient_les_totaux_du_chemin_historique(db_session):
    """Approvisionnements et versements : le total agrégé et la liste affichée
    viennent de deux requêtes différentes. Elles doivent tomber sur le même
    montant, sinon un écran montre autre chose que ce qu'il additionne."""
    org, _, _, _ = await _organisation_saine(db_session)

    couvertures = await controler_couverture_affichage(db_session, org.id)

    appro = next(c for c in couvertures if "entrées de caisse" in c.terme and c.devise == "USD")
    versement = next(c for c in couvertures if "entrées bancaires" in c.terme and c.devise == "USD")
    assert appro.total == Decimal("50") == appro.affichable
    assert appro.lignes == 1
    assert versement.total == Decimal("30") == versement.affichable
    assert versement.lignes == 1


@pytest.mark.asyncio
async def test_un_transfert_dedie_est_compte_et_affichable(db_session):
    """Le trou que la Phase 1 a bouché, gardé fermé par ce test.

    Le montant entre dans les totaux de clôture (les agrégateurs unionnent les
    deux sources) **et** dans la liste que les écrans affichent. Avant la Phase
    1, `entrees_caisse.py` ne lisait que `sorties_fonds` : une clôture montrait
    une entrée que sa propre liste ne justifiait pas — sur un document signé.
    """
    org, user, _, banque = await _organisation_saine(db_session)
    await db_session.commit()

    await create_transfer(
        db_session,
        payload=TransfertInterneCreate(
            source_type="BANQUE", source_id=banque.id, destination_type="CAISSE",
            montant=Decimal("120"), devise="USD",
        ),
        tenant_id=org.id,
        user=user,
    )

    couvertures = await controler_couverture_affichage(db_session, org.id)
    caisse = next(c for c in couvertures if "entrées de caisse" in c.terme and c.devise == "USD")

    # 50 d'approvisionnement historique + 120 du moteur dédié, des deux côtés.
    assert caisse.total == Decimal("170")
    assert caisse.affichable == Decimal("170")
    assert caisse.lignes == 2
    assert caisse.juste(TOLERANCE_PAR_DEFAUT)


@pytest.mark.asyncio
async def test_une_organisation_voisine_ne_pollue_pas_le_rapport(db_session):
    """Le rapport est par organisation : un écart chez l'une ne doit ni
    apparaître ni se compenser chez l'autre."""
    org_a, _, caisse_a, _ = await _organisation_saine(db_session)
    org_b, _, _, _ = await _organisation_saine(db_session)
    caisse_a.solde_usd = Decimal("999")
    await db_session.flush()

    rapport_a = await reconcilier_organisation(db_session, organisation_id=org_a.id, nom=org_a.nom)
    rapport_b = await reconcilier_organisation(db_session, organisation_id=org_b.id, nom=org_b.nom)

    assert rapport_a.ecarts(TOLERANCE_PAR_DEFAUT) != []
    assert rapport_b.ecarts(TOLERANCE_PAR_DEFAUT) == []
