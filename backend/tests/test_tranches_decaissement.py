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
