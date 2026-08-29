"""Phase 3 : `POST /sorties-fonds` écrit-il là où le drapeau le dit ?

La bascule d'écriture ne change ni le payload, ni les permissions, ni les
validations : elle change la table dans laquelle l'opération atterrit. Ces
tests vérifient les deux moitiés de cette phrase — que le moteur change
vraiment quand le drapeau est ouvert, et que **rien d'autre** ne change.

Trois propriétés tiennent le dispositif :

- **fermé, le drapeau ne fait rien.** C'est ce qui rend la bascule déployable
  sans décision : le code part en production inerte ;
- **elle s'ouvre un type et une organisation à la fois.** Ouvrir
  `versement_banque` ne bascule pas les approvisionnements, et une liste
  d'organisations permet un tenant pilote ;
- **la refermer n'annule rien.** Les transferts déjà écrits restent dans la
  table dédiée et continuent d'être lus. C'est la règle absolue du chantier :
  aucune ligne n'est jamais recopiée d'une table à l'autre.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds
from app.core.config import settings
from app.models.banque import Banque
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.organisation import Organisation
from app.models.sortie_fonds import SortieFonds
from app.models.transfert_interne import TransfertInterne
from app.models.user import User
from app.schemas.sortie_fonds import SortieFondsCreate
from app.services.entrees_caisse import list_entrees_internes_banque


class _FakeRequest:
    headers: dict = {}
    client = None


def _ouvrir(monkeypatch, *, types: str, tenants: str = ""):
    """Ouvre le drapeau de bascule pour la durée du test."""
    monkeypatch.setattr(settings, "transferts_engine_types", types)
    monkeypatch.setattr(settings, "transferts_engine_tenants", tenants)


async def _contexte(db):
    org = Organisation(nom="Bascule", slug=f"bs-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"s{uuid.uuid4().hex[:6]}@ex.com", role="admin",
                prenom="Alan", nom="Turing", organisation_id=org.id)
    banque = Banque(organisation_id=org.id, nom="Rawbank")
    db.add_all([user, banque])
    await db.flush()
    compte = CompteBancaire(
        organisation_id=org.id, banque_id=banque.id, intitule="Compte courant",
        numero_compte=f"BK-{uuid.uuid4().hex[:8]}", devise="USD",
        solde_initial=Decimal("1000"), solde_actuel=Decimal("1000"),
        is_active=True, account_type="BANK",
    )
    caisse = CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("1000"),
                            solde_cdf=Decimal("0"), est_ouverte=True)
    db.add_all([compte, caisse])
    await db.flush()
    await db.commit()
    return org, user, compte, caisse


def _payload(compte, *, type_sortie="versement_banque", montant="100", devise="USD"):
    return SortieFondsCreate(
        type_sortie=type_sortie,
        montant_paye=Decimal(montant),
        mode_paiement="cash",
        devise=devise,
        canal="CAISSE" if type_sortie == "versement_banque" else "BANQUE",
        compte_bancaire_id=compte.id,
        motif="Mouvement interne",
        beneficiaire="",
    )


async def _creer(db, org, user, payload, *, cle=None):
    return await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), background_tasks=BackgroundTasks(),
        idempotency_key=cle, user=user, tenant_id=org.id, db=db,
    )


async def _reveiller(db, *objets):
    """Le service annule sa transaction quand il refuse une opération.

    Les objets ORM en sortent expirés : les relire ensuite déclencherait un
    chargement paresseux hors contexte async (`MissingGreenlet`), et le test
    échouerait pour une raison qui n'est pas celle qu'il examine.
    """
    for objet in objets:
        await db.refresh(objet)


async def _compter(db, modele, org):
    return int(await db.scalar(
        select(func.count()).select_from(modele).where(modele.organisation_id == org.id)
    ) or 0)


# ---------------------------------------------------------------------------
# Le drapeau fermé
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drapeau_ferme_le_versement_reste_sur_le_chemin_historique(db_session):
    """Le code part en production inerte : c'est ce qui rend la bascule déployable."""
    org, user, compte, caisse = await _contexte(db_session)

    sortie = await _creer(db_session, org, user, _payload(compte))

    assert sortie.origine == "legacy"
    assert (sortie.reference_numero or "").startswith("PAY-")
    assert await _compter(db_session, SortieFonds, org) == 1
    assert await _compter(db_session, TransfertInterne, org) == 0


# ---------------------------------------------------------------------------
# Le drapeau ouvert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drapeau_ouvert_le_versement_part_au_moteur_dedie(db_session, monkeypatch):
    org, user, compte, caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")

    sortie = await _creer(db_session, org, user, _payload(compte))

    assert sortie.origine == "transfert_interne"
    # Numérotation tranchée en Phase 2 : le moteur dédié numérote en TRF-,
    # aucune opération n'est renumérotée, la rupture de série est assumée.
    assert (sortie.reference_numero or "").startswith("TRF-")
    assert sortie.type_sortie == "versement_banque"
    assert sortie.montant_paye == Decimal("100")
    assert sortie.statut == "VALIDE"

    assert await _compter(db_session, SortieFonds, org) == 0
    transfert = await db_session.scalar(
        select(TransfertInterne).where(TransfertInterne.organisation_id == org.id)
    )
    # L'identité annoncée au frontend est celle que porte le transfert : c'est
    # sur elle qu'il attachera le bon imprimé.
    assert sortie.id == transfert.document_uuid

    # La trésorerie bouge exactement comme sur le chemin historique.
    await db_session.refresh(caisse)
    await db_session.refresh(compte)
    assert Decimal(str(caisse.solde_usd)) == Decimal("900")
    assert Decimal(str(compte.solde_actuel)) == Decimal("1100")


@pytest.mark.asyncio
async def test_l_ecran_qui_vient_de_saisir_l_operation_la_voit(db_session, monkeypatch):
    """Le lien entre les phases 2 et 3 : sans la lecture bilingue, l'opération
    disparaîtrait de l'écran à la seconde où elle est enregistrée."""
    from app.api.v1.endpoints.sorties_fonds import list_sorties_fonds

    org, user, compte, _caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")
    sortie = await _creer(db_session, org, user, _payload(compte))

    reponse = await list_sorties_fonds(
        include=None, date_debut=None, date_fin=None, type_sortie=None,
        mode_paiement=None, canal=None, compte_bancaire_id=None, statut=None,
        requisition_id=None, requisition_numero=None, reference=None, order=None,
        limit=100, offset=0, include_summary=True, user=user, tenant_id=org.id, db=db_session,
    )
    assert [item.id for item in reponse.items] == [sortie.id]
    assert reponse.total_transferts_internes == Decimal("100")
    assert reponse.total_depenses_reelles == Decimal("0")

    # Et les lecteurs bilingues de la Phase 1 aussi : l'entrée en banque est
    # affichable, donc le total de clôture qui la contient est justifié.
    lignes = await list_entrees_internes_banque(db_session, tenant_id=org.id)
    assert [ligne["montant"] for ligne in lignes] == [Decimal("100")]
    assert lignes[0]["origine"] == "transfert_interne"


@pytest.mark.asyncio
async def test_l_approvisionnement_bascule_aussi_quand_on_l_ouvre(db_session, monkeypatch):
    org, user, compte, caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="approvisionnement_caisse")

    sortie = await _creer(
        db_session, org, user, _payload(compte, type_sortie="approvisionnement_caisse")
    )

    assert sortie.origine == "transfert_interne"
    assert sortie.canal == "BANQUE"  # l'argent sort du compte bancaire
    await db_session.refresh(caisse)
    await db_session.refresh(compte)
    assert Decimal(str(caisse.solde_usd)) == Decimal("1100")
    assert Decimal(str(compte.solde_actuel)) == Decimal("900")


# ---------------------------------------------------------------------------
# Un type à la fois, une organisation à la fois
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ouvrir_un_type_ne_bascule_pas_l_autre(db_session, monkeypatch):
    org, user, compte, _caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")

    versement = await _creer(db_session, org, user, _payload(compte))
    appro = await _creer(
        db_session, org, user, _payload(compte, type_sortie="approvisionnement_caisse", montant="40")
    )

    assert versement.origine == "transfert_interne"
    assert appro.origine == "legacy"
    assert await _compter(db_session, TransfertInterne, org) == 1
    assert await _compter(db_session, SortieFonds, org) == 1


@pytest.mark.asyncio
async def test_la_liste_d_organisations_permet_un_tenant_pilote(db_session, monkeypatch):
    org, user, compte, _caisse = await _contexte(db_session)
    # Le type est ouvert, mais pour une autre organisation.
    _ouvrir(monkeypatch, types="versement_banque", tenants=str(org.id + 10_000))

    sortie = await _creer(db_session, org, user, _payload(compte))
    assert sortie.origine == "legacy"

    # La même organisation, nommée cette fois.
    _ouvrir(monkeypatch, types="versement_banque", tenants=f"{org.id + 10_000},{org.id}")
    sortie = await _creer(db_session, org, user, _payload(compte))
    assert sortie.origine == "transfert_interne"


@pytest.mark.asyncio
async def test_refermer_le_drapeau_n_efface_pas_ce_qui_est_ecrit(db_session, monkeypatch):
    """La règle absolue du chantier : aucune ligne n'est jamais recopiée.

    Refermer le drapeau doit rendre le chemin historique aux **nouvelles**
    opérations, sans toucher aux anciennes — que les lecteurs continuent
    d'unionner. Une reprise d'historique doublerait chaque total de clôture.
    """
    org, user, compte, _caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")
    delegue = await _creer(db_session, org, user, _payload(compte))

    _ouvrir(monkeypatch, types="")
    historique = await _creer(db_session, org, user, _payload(compte, montant="30"))

    assert historique.origine == "legacy"
    assert await _compter(db_session, TransfertInterne, org) == 1
    assert await _compter(db_session, SortieFonds, org) == 1

    from app.api.v1.endpoints.sorties_fonds import list_sorties_fonds

    reponse = await list_sorties_fonds(
        include=None, date_debut=None, date_fin=None, type_sortie=None,
        mode_paiement=None, canal=None, compte_bancaire_id=None, statut=None,
        requisition_id=None, requisition_numero=None, reference=None, order=None,
        limit=100, offset=0, include_summary=True, user=user, tenant_id=org.id, db=db_session,
    )
    assert {item.id for item in reponse.items} == {delegue.id, historique.id}
    assert reponse.total_transferts_internes == Decimal("130")


# ---------------------------------------------------------------------------
# Ce que la délégation ne relâche pas
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_les_validations_du_payload_valent_toujours(db_session, monkeypatch):
    """Elles s'appliquent avant la délégation : rien n'est écrit d'aucun côté."""
    org, user, compte, _caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")

    # Un montant nul n'atteint jamais l'endpoint : le schéma le refuse, des deux
    # côtés du drapeau.
    with pytest.raises(ValidationError):
        _payload(compte, montant="0")

    with pytest.raises(HTTPException) as erreur:
        await _creer(db_session, org, user, _payload(compte, devise="CDF"))
    assert "Devise incompatible" in str(erreur.value.detail)
    await _reveiller(db_session, org, user, compte)

    compte.is_active = False
    await db_session.commit()
    with pytest.raises(HTTPException):
        await _creer(db_session, org, user, _payload(compte))
    await _reveiller(db_session, org)

    assert await _compter(db_session, TransfertInterne, org) == 0
    assert await _compter(db_session, SortieFonds, org) == 0


@pytest.mark.asyncio
async def test_un_transfert_delegue_refuse_toujours_une_requisition(db_session, monkeypatch):
    org, user, compte, _caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")
    payload = _payload(compte)
    payload.requisition_id = uuid.uuid4()

    with pytest.raises(HTTPException) as erreur:
        await _creer(db_session, org, user, payload)
    assert erreur.value.status_code == 400
    await _reveiller(db_session, org)
    assert await _compter(db_session, TransfertInterne, org) == 0


@pytest.mark.asyncio
async def test_la_cle_d_idempotence_protege_le_chemin_delegue(db_session, monkeypatch):
    """Le double-clic ne doit pas déplacer l'argent deux fois — et le second
    appel doit rendre le MÊME identifiant, sinon le bon s'attacherait à une
    opération qui n'existe pas."""
    org, user, compte, caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")
    cle = f"cle-{uuid.uuid4().hex}"

    premier = await _creer(db_session, org, user, _payload(compte), cle=cle)
    second = await _creer(db_session, org, user, _payload(compte), cle=cle)

    assert premier.id == second.id
    assert await _compter(db_session, TransfertInterne, org) == 1
    await db_session.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("900")


@pytest.mark.asyncio
async def test_un_solde_de_caisse_insuffisant_refuse_le_versement_delegue(db_session, monkeypatch):
    org, user, compte, _caisse = await _contexte(db_session)
    _ouvrir(monkeypatch, types="versement_banque")

    with pytest.raises(HTTPException) as erreur:
        await _creer(db_session, org, user, _payload(compte, montant="5000"))
    assert erreur.value.status_code == 409
    await _reveiller(db_session, org)
    assert await _compter(db_session, TransfertInterne, org) == 0
