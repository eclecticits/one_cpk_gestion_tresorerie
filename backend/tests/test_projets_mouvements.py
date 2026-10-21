"""Entrées et sorties d'un projet : ce qui compte, ce qui ne compte pas."""

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.api.v1.endpoints.projets_activites import mouvements_projet_activite, synthese_projets_activites
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.projet_activite import ProjetActivite
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User

QUAND = datetime(2026, 5, 10, 10, 0, tzinfo=timezone.utc)


def _s() -> str:
    return uuid.uuid4().hex[:8]


async def _contexte(db):
    org = Organisation(nom="Projets", slug=f"pj-{_s()}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{_s()}@example.com", nom="Kasa", prenom="Ada", role="admin", organisation_id=org.id, active=True)
    a = ProjetActivite(organisation_id=org.id, code=f"A-{_s()}", libelle="Formation", type="PROJET")
    b = ProjetActivite(organisation_id=org.id, code=f"B-{_s()}", libelle="Autre", type="ACTIVITE")
    db.add_all([user, a, b])
    await db.flush()
    return org, user, a, b


def _entree(org, user, projet, montant, **extra):
    return Encaissement(
        organisation_id=org.id, numero_recu=f"R-{_s()}", type_client="personne_physique", client_nom="Membre",
        libelle="Cotisation", montant=montant, montant_total=montant, montant_paye=montant, montant_percu=montant,
        devise_perception="USD", taux_change_applique=Decimal("1"), canal="CAISSE", mode_paiement="cash",
        statut_paiement="complet", date_encaissement=QUAND, date_paiement=QUAND, created_by=user.id,
        project_activity_id=projet.id, **extra,
    )


def _sortie(org, user, montant, devise="USD", **extra):
    return SortieFonds(
        organisation_id=org.id, type_sortie="autre", montant_paye=montant, mode_paiement="cash", devise=devise,
        canal="CAISSE", motif="Dépense", beneficiaire="Fournisseur", statut="VALIDE", date_paiement=QUAND,
        created_by=user.id, reference_numero=f"PAY-{_s()}", **extra,
    )


@pytest.mark.asyncio
async def test_mouvements_projet_entrees_sorties_et_exclusions(db_session):
    db = db_session
    org, user, a, b = await _contexte(db)
    req = Requisition(
        numero_requisition=f"REQ-{_s()}", reference_numero=f"REQ-{_s()}", objet="Atelier", mode_paiement="cash",
        type_requisition="classique", status="APPROUVEE", examen_status="EXAMINE", montant_total=Decimal("200"),
        organisation_id=org.id, created_at=QUAND, updated_at=QUAND, is_deleted=False, project_activity_id=a.id,
    )
    db.add(req)
    await db.flush()
    db.add_all([
        _entree(org, user, a, Decimal("500")),
        _entree(org, user, b, Decimal("300")),  # autre projet
        _entree(org, user, a, Decimal("999"), statut_operation="ANNULEE"),  # annulée
        _sortie(org, user, Decimal("120"), requisition_id=req.id),  # hérite du projet de la réquisition
        _sortie(org, user, Decimal("50000"), devise="CDF", project_activity_id=a.id),  # sortie directe
        _sortie(org, user, Decimal("77"), project_activity_id=a.id, annulee_le=QUAND),  # annulée
        _sortie(org, user, Decimal("40"), project_activity_id=b.id),  # autre projet
    ])
    await db.commit()

    m = await mouvements_projet_activite(item_id=a.id, date_debut=None, date_fin=None, user=user, tenant_id=org.id, db=db)
    assert m["totaux"]["entrees_usd"] == Decimal("500")
    assert m["totaux"]["sorties"] == {"USD": Decimal("120"), "CDF": Decimal("50000")}
    # Le solde ne retire que les sorties en USD : on n'additionne pas deux devises.
    assert m["totaux"]["solde_usd"] == Decimal("380")
    assert {s["requisition"] for s in m["sorties"]} == {req.numero_requisition, None}

    # Hors période : rien.
    vide = await mouvements_projet_activite(item_id=a.id, date_debut=date(2026, 6, 1), date_fin=None, user=user, tenant_id=org.id, db=db)
    assert vide["entrees"] == [] and vide["sorties"] == []

    lignes = {l["projet_id"]: l for l in await synthese_projets_activites(date_debut=None, date_fin=None, user=user, tenant_id=org.id, db=db)}
    assert lignes[a.id]["nb_entrees"] == 1 and lignes[a.id]["nb_sorties"] == 2
    assert lignes[b.id]["entrees_usd"] == Decimal("300")
    assert lignes[b.id]["solde_usd"] == Decimal("260")
