"""Une réquisition payée par tranches se lit dans les exports des sorties.

Tant que la dernière tranche n'est pas payée, la réquisition reste
EN_DECAISSEMENT. Le classeur n'acceptait que APPROUVEE et PAYEE : les tranches
déjà payées en disparaissaient, et le total du pied de colonne avec elles.
Présentes, deux tranches du même dossier se lisaient encore comme deux
paiements sans lien — d'où la colonne « Tranche ».
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.sortie_fonds import SortieFonds
from app.models.user import User
from app.services.tranches_decaissement import libelle_tranche, tranches_par_sortie

# Le paiement d'une tranche passe par le flux comptable : sans cet import, les
# tables `compta_*` manquent aux métadonnées quand ce fichier tourne seul.
from app.modules.comptabilite import models as _compta_models  # noqa: F401

MOMENT = datetime(2026, 9, 17, 10, 0, tzinfo=timezone.utc)


async def _dossier_progressif(db):
    org = Organisation(nom="Tranches", slug=f"tr-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code="II.2.3.3", libelle="Portes ouvertes",
        type="DEPENSE", active=True, montant_prevu=Decimal("10000"), montant_engage=0,
        montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    req = Requisition(
        organisation_id=org.id, numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        objet="Journée de sensibilisation", mode_paiement="cash", type_requisition="classique",
        nature_requisition="BUDGETAIRE", status="EN_DECAISSEMENT", montant_total=Decimal("2470"),
        devise="USD", decaissement_progressif=True,
    )
    db.add(req)
    await db.flush()
    # Ligne ré-imputée : le texte signé cite encore l'ancien poste, les
    # empreintes disent où elle est réellement imputée.
    db.add(LigneRequisition(
        requisition_id=req.id, organisation_id=org.id, rubrique="II.2.3.4 - Suivi évolution stagiaires",
        description="Ligne", quantite=1, montant_unitaire=Decimal("2470"), montant_total=Decimal("2470"),
        budget_poste_id=poste.id, budget_poste_code_snapshot=poste.code,
        budget_poste_libelle_snapshot=poste.libelle,
    ))

    def sortie(montant, jour, statut="VALIDE"):
        return SortieFonds(
            organisation_id=org.id, type_sortie="requisition", requisition_id=req.id,
            montant_paye=Decimal(montant), mode_paiement="cash", devise="USD", canal="CAISSE",
            motif="Tranche", beneficiaire="CK", statut=statut, created_by=user.id,
            date_paiement=MOMENT + timedelta(days=jour), reference_numero=f"PAY-{uuid.uuid4().hex[:8]}",
        )

    premiere, annulee, seconde = sortie("500", 0), sortie("300", 1, "ANNULEE"), sortie("150", 2)
    db.add_all([premiere, annulee, seconde])
    await db.commit()
    return org, req, premiere, annulee, seconde


@pytest.mark.asyncio
async def test_les_tranches_se_numerotent_et_cumulent_dans_l_ordre_des_paiements(db_session):
    org, req, premiere, annulee, seconde = await _dossier_progressif(db_session)

    tranches = await tranches_par_sortie(db_session, org.id, [req.id])

    assert annulee.id not in tranches  # une sortie annulée n'a rien payé
    assert (tranches[premiere.id].numero, tranches[premiere.id].cumul_paye) == (1, Decimal("500"))
    assert (tranches[seconde.id].numero, tranches[seconde.id].cumul_paye) == (2, Decimal("650"))
    assert tranches[seconde.id].reste == Decimal("1820")
    assert libelle_tranche(tranches[seconde.id]) == "Tranche 2 — payé 650,00 / 2 470,00 USD, reste 1 820,00"


@pytest.mark.asyncio
async def test_un_paiement_unique_n_est_pas_une_tranche(db_session):
    org, req, premiere, annulee, seconde = await _dossier_progressif(db_session)
    req.decaissement_progressif = False
    seconde.statut = "ANNULEE"
    await db_session.commit()

    assert await tranches_par_sortie(db_session, org.id, [req.id]) == {}


@pytest.mark.asyncio
async def test_le_classeur_garde_les_tranches_d_une_requisition_en_decaissement(db_session):
    from app.api.v1.endpoints.exports import construire_classeur_sorties_fonds

    org, req, premiere, annulee, seconde = await _dossier_progressif(db_session)

    classeur, _nom = await construire_classeur_sorties_fonds(db_session, org.id)
    lignes = list(classeur["Sorties"].iter_rows(values_only=True))
    entete = [str(v) for v in next(row for row in lignes if "Tranche" in row)]
    i_tranche = entete.index("Tranche")
    i_montant = entete.index("Montant payé (USD)")
    i_poste = entete.index("Poste budgétaire")
    donnees = [row for row in lignes if row[i_montant] in (500.0, 150.0)]

    assert sorted(row[i_montant] for row in donnees) == [150.0, 500.0]
    assert {row[i_tranche] for row in donnees} == {
        "Tranche 1 — payé 500,00 / 2 470,00 USD, reste 1 970,00",
        "Tranche 2 — payé 650,00 / 2 470,00 USD, reste 1 820,00",
    }
    # Le poste affiché est celui de l'imputation, pas le texte signé d'origine.
    assert {row[i_poste] for row in donnees} == {"II.2.3.3 - Portes ouvertes"}
    total = next(row for row in lignes if row[0] == "TOTAL")
    assert total[i_montant] == 650.0


# ---------------------------------------------------------------------------
# Le solde du dossier ne compte rien deux fois
# ---------------------------------------------------------------------------


async def _dossier_paye_par_tranches(db, monkeypatch, montants, total=None):
    """Une réquisition progressive payée tranche par tranche.

    `total` vaut la somme des tranches par défaut : le dossier est alors soldé.
    Un total supérieur laisse un reliquat à payer.
    """
    from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds
    from app.models.caisse_centrale import CaisseCentrale
    from app.models.ordre_decaissement import OrdreDecaissement
    from app.models.service import Service
    from app.schemas.ordre_decaissement import OrdreDecaissementCreate
    from app.schemas.sortie_fonds import SortieFondsCreate
    from app.services.budget_engagement import resynchroniser_engagement_requisition
    from fastapi import BackgroundTasks
    from sqlalchemy import select

    class _FakeRequest:
        headers: dict = {}
        client = None

    async def toujours_autorise(*_a, **_k):
        return True

    monkeypatch.setattr("app.api.v1.endpoints.ordres_decaissement._user_has_permission", toujours_autorise)
    async def numero(*_a, **_k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", numero)

    org = Organisation(nom="Solde", slug=f"sd-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True)
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add_all([user, service, exercice])
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("10000"), solde_cdf=0, est_ouverte=True))
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"DEP-{uuid.uuid4().hex[:4]}",
        libelle="Poste dépense", type="DEPENSE", active=True, montant_prevu=Decimal("10000"),
        montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    total = total if total is not None else sum(montants, Decimal("0"))
    req = Requisition(
        organisation_id=org.id, service_id=service.id, numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        objet="Dossier progressif", mode_paiement="cash", type_requisition="classique",
        nature_requisition="BUDGETAIRE", status="APPROUVEE", examen_status="EXAMINE",
        montant_total=total, devise="USD", decaissement_progressif=True, created_by=user.id,
    )
    db.add(req)
    await db.flush()
    db.add(LigneRequisition(
        organisation_id=org.id, requisition_id=req.id, budget_poste_id=poste.id,
        rubrique="Poste dépense", description="Ligne", quantite=1,
        montant_unitaire=total, montant_total=total, devise="USD",
    ))
    await db.flush()
    await resynchroniser_engagement_requisition(db, req)
    await db.commit()

    async def payer(montant, motif="Achat de carburant"):
        await create_ordre_decaissement(
            payload=OrdreDecaissementCreate(
                requisition_id=req.id, beneficiaire="Bénéficiaire", montant=montant, devise="USD",
                motif=motif,
                lignes=[{"budget_poste_id": poste.id, "montant": montant}],
            ),
            request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
        )
        ordre = (await db.execute(
            select(OrdreDecaissement).where(
                OrdreDecaissement.requisition_id == req.id, OrdreDecaissement.statut == "AUTORISE"
            )
        )).scalars().first()
        await create_sortie_fonds(
            payload=SortieFondsCreate(
                type_sortie="requisition", requisition_id=req.id, ordre_decaissement_id=ordre.id,
                montant_paye=montant, mode_paiement="cash", devise="USD", canal="CAISSE",
                motif="Tranche", beneficiaire="Bénéficiaire", service_id=service.id,
            ),
            request=_FakeRequest(), background_tasks=BackgroundTasks(), user=user,
            tenant_id=org.id, db=db,
        )
        await db.commit()

    for montant in montants:
        await payer(montant)
    return org, user, req, poste, service, payer


@pytest.mark.asyncio
async def test_le_dossier_solde_ne_compte_ni_son_budget_ni_ses_lignes_deux_fois(db_session, monkeypatch):
    """Payé jusqu'au bout, le dossier vaut son montant — une fois.

    Le cumul affiché sur la dernière tranche dit le total du dossier ; c'est un
    cumul, pas un montant payé de plus. Ni le classeur ni le budget ne doivent
    l'additionner à ce qui précède.
    """
    from app.api.v1.endpoints.exports import construire_classeur_sorties_fonds

    montants = [Decimal("500"), Decimal("150"), Decimal("1820")]
    org, user, req, poste, service, payer = await _dossier_paye_par_tranches(
        db_session, monkeypatch, montants
    )

    await db_session.refresh(req)
    await db_session.refresh(poste)
    assert req.status == "PAYEE"  # la dernière tranche solde le dossier
    # Le budget voit le montant du dossier, pas la somme des cumuls affichés.
    assert Decimal(poste.montant_paye) == Decimal("2470")
    assert Decimal(poste.montant_engage) == Decimal("2470")

    classeur, _nom = await construire_classeur_sorties_fonds(db_session, org.id)
    lignes = list(classeur["Sorties"].iter_rows(values_only=True))
    entete = [str(v) for v in next(row for row in lignes if "Tranche" in row)]
    i_montant, i_tranche = entete.index("Montant payé (USD)"), entete.index("Tranche")
    paiements = [row for row in lignes if isinstance(row[i_montant], float) and row[0] != "TOTAL"]

    assert sorted(row[i_montant] for row in paiements) == [150.0, 500.0, 1820.0]
    total = next(row for row in lignes if row[0] == "TOTAL")
    assert total[i_montant] == 2470.0  # trois tranches, pas un quatrième montant
    # L'objet de la tranche accompagne son rang : le motif de l'ordre qui l'a
    # autorisée, qui ne se lit nulle part ailleurs.
    assert (
        "Tranche 3 (Achat de carburant) — payé 2 470,00 / 2 470,00 USD, soldé"
        in {row[i_tranche] for row in paiements}
    )


@pytest.mark.asyncio
async def test_un_dossier_solde_n_autorise_plus_aucune_tranche(db_session, monkeypatch):
    """Soldé, le dossier est PAYEE : plus rien ne s'y autorise ni ne s'y paie."""
    from fastapi import HTTPException

    org, user, req, poste, service, payer = await _dossier_paye_par_tranches(
        db_session, monkeypatch, [Decimal("500"), Decimal("150"), Decimal("1820")]
    )

    with pytest.raises(HTTPException) as refus:
        await payer(Decimal("100"))
    assert refus.value.status_code == 400
    assert "approuvée" in str(refus.value.detail)


@pytest.mark.asyncio
async def test_le_plafond_compte_aussi_les_tranches_autorisees_non_payees(db_session, monkeypatch):
    """Sans cela, le reliquat serait promis deux fois : une tranche autorisée et
    en attente de caisse n'est pas encore payée, mais elle est déjà engagée."""
    from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement
    from app.schemas.ordre_decaissement import OrdreDecaissementCreate
    from fastapi import HTTPException

    org, user, req, poste, service, payer = await _dossier_paye_par_tranches(
        db_session, monkeypatch, [Decimal("500"), Decimal("150")], total=Decimal("2470")
    )

    class _FakeRequest:
        headers: dict = {}
        client = None

    async def autoriser(montant):
        await create_ordre_decaissement(
            payload=OrdreDecaissementCreate(
                requisition_id=req.id, beneficiaire="Bénéficiaire", montant=montant, devise="USD",
                lignes=[{"budget_poste_id": poste.id, "montant": montant}],
            ),
            request=_FakeRequest(), user=user, tenant_id=org.id, db=db_session,
        )

    await autoriser(Decimal("1820"))  # le reliquat entier, autorisé mais pas payé
    with pytest.raises(HTTPException) as refus:
        await autoriser(Decimal("10"))
    assert "Plafond de la réquisition dépassé" in str(refus.value.detail)
