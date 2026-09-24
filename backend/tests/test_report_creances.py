"""Une dette ne tombe pas avec l'exercice : elle passe en arriérés.

Une note « Cotisation 2026 » restée impayée à la clôture de 2026 voit son reste
dû reporté sur le poste d'arriérés de 2027. Ce qui a été payé en 2026 reste
réalisé en 2026 ; ce qui est payé ensuite s'impute en 2027. L'exercice clôturé,
lui, ne bouge plus.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.organisation import Organisation
from app.models.payment_history import PaymentHistory
from app.models.report_creance import ReportCreance
from app.models.service import Service
from app.models.service_rubrique import ServiceRubrique
from app.models.user import User
from app.schemas.payment import EncaissementArticleCreate, EncaissementCreate

# Les écritures comptables sont générées dans le flux : sans cet import, les
# tables `compta_*` manquent aux métadonnées quand ce fichier tourne seul.
from app.modules.comptabilite import models as _compta_models  # noqa: F401


@pytest.fixture(autouse=True)
def _numero_recu(monkeypatch):
    async def faux_recu(**_kwargs):
        return f"REC-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", faux_recu)


def _poste(org_id: int, exercice_id: int, code: str, libelle: str, arrieres: str | None) -> BudgetPoste:
    return BudgetPoste(
        organisation_id=org_id, exercice_id=exercice_id, code=code, libelle=libelle, type="RECETTE",
        active=True, montant_prevu=Decimal("100000"), montant_engage=0, montant_paye=0, is_deleted=False,
        code_poste_arrieres=arrieres,
    )


async def _contexte(db, *, avec_2027: bool = True, correspondance: bool = True):
    """Un conseil, 2026 en cours, 2027 préparé ; « Cotisation » et « Inscription »
    se reportent sur leurs arriérés, les arriérés sur eux-mêmes."""
    org = Organisation(nom="Arriérés", slug=f"ar-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4().hex[:8]}@ex.com", role="admin", organisation_id=org.id)
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True)
    ex2026 = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.VOTE)
    db.add_all([user, service, ex2026])
    db.add(CaisseCentrale(organisation_id=org.id, solde_usd=Decimal("0"), solde_cdf=0, est_ouverte=True))
    await db.flush()

    arr_cot = "R.9.1" if correspondance else None
    arr_ins = "R.9.2" if correspondance else None
    p = {
        "cot26": _poste(org.id, ex2026.id, "R.1", "Cotisation", arr_cot),
        "ins26": _poste(org.id, ex2026.id, "R.2", "Inscription", arr_ins),
    }
    ex2027 = None
    if avec_2027:
        ex2027 = BudgetExercice(organisation_id=org.id, annee=2027, statut=StatutBudget.BROUILLON)
        db.add(ex2027)
        await db.flush()
        p["cot27"] = _poste(org.id, ex2027.id, "R.1", "Cotisation", "R.9.1")
        p["arr_cot27"] = _poste(org.id, ex2027.id, "R.9.1", "Arriérés de cotisation", "R.9.1")
        p["arr_ins27"] = _poste(org.id, ex2027.id, "R.9.2", "Arriérés d'inscription", "R.9.2")
    db.add_all(p.values())
    await db.flush()
    for poste in p.values():
        db.add(ServiceRubrique(service_id=service.id, budget_poste_id=poste.id, active=True))
    await db.commit()
    return org, user, service, ex2026, ex2027, p


async def _note(db, org, user, service, poste: BudgetPoste, montant: str, articles=None) -> uuid.UUID:
    from app.api.v1.endpoints.encaissements import create_encaissement

    enc = await create_encaissement(
        payload=EncaissementCreate(
            type_client="personne_physique", client_sexe="M", client_nom="Cabinet ABC",
            libelle="Cotisation 2026", montant=Decimal(montant), montant_total=Decimal(montant),
            montant_paye=Decimal("0"), mode_paiement="cash", canal="CAISSE", service_id=service.id,
            budget_poste_id=poste.id, articles=articles or [],
        ),
        background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db,
    )
    await db.commit()
    return uuid.UUID(str(enc["id"]))


async def _payer(db, org, user, encaissement_id, montant: str) -> PaymentHistory:
    from app.services.encaissement_payments import record_encaissement_payment

    payment = await record_encaissement_payment(
        db, organisation_id=org.id, encaissement_id=encaissement_id, montant=Decimal(montant),
        mode_paiement="cash", reference=f"V-{uuid.uuid4().hex[:6]}", notes=None, user_id=user.id,
    )
    await db.commit()
    return payment


async def _cloturer(db, org, user, annee: int = 2026) -> dict:
    from app.api.v1.endpoints.budget import close_budget_exercise

    return await close_budget_exercise(annee=annee, user=user, tenant_id=org.id, db=db)


async def _paye(db, poste: BudgetPoste) -> Decimal:
    await db.refresh(poste)
    return Decimal(poste.montant_paye)


async def _reports(db, encaissement_id) -> list[ReportCreance]:
    return list(
        (await db.execute(select(ReportCreance).where(ReportCreance.encaissement_id == encaissement_id)))
        .scalars()
        .all()
    )


@pytest.mark.asyncio
async def test_le_reste_du_passe_en_arrieres_et_s_y_encaisse(db_session):
    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _payer(db, org, user, note, "100")

    resultat = await _cloturer(db, org, user)

    assert resultat["statut"] == StatutBudget.CLOTURE.value
    assert resultat["report"]["notes_reportees"] == 1
    assert resultat["report"]["montant_reporte"] == "200.00"
    [report] = await _reports(db, note)
    assert (report.poste_source_id, report.poste_cible_id) == (p["cot26"].id, p["arr_cot27"].id)
    assert Decimal(report.montant) == Decimal("200")

    # Payé en 2027 : les arriérés 2027 reçoivent, 2026 reste tel qu'il a été clos.
    paiement = await _payer(db, org, user, note, "150")
    assert await _paye(db, p["cot26"]) == Decimal("100")
    assert await _paye(db, p["arr_cot27"]) == Decimal("150")
    assert await _paye(db, p["cot27"]) == Decimal("0")
    assert paiement.budget_poste_id == p["arr_cot27"].id


@pytest.mark.asyncio
async def test_la_cloture_est_refusee_sans_poste_d_arrieres(db_session):
    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db, correspondance=False)
    await _note(db, org, user, service, p["cot26"], "300")

    with pytest.raises(HTTPException) as refus:
        await _cloturer(db, org, user)
    await db.rollback()

    assert refus.value.status_code == 409
    assert refus.value.detail["code"] == "POSTE_ARRIERES_MANQUANT"
    assert [m["code"] for m in refus.value.detail["postes"]] == ["R.1"]
    await db.refresh(ex2026)
    assert ex2026.statut == StatutBudget.VOTE


@pytest.mark.asyncio
async def test_la_cloture_est_refusee_sans_exercice_suivant(db_session):
    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db, avec_2027=False)
    await _note(db, org, user, service, p["cot26"], "300")

    with pytest.raises(HTTPException) as refus:
        await _cloturer(db, org, user)
    await db.rollback()

    assert refus.value.detail["code"] == "EXERCICE_SUIVANT_ABSENT"
    await db.refresh(ex2026)
    assert ex2026.statut == StatutBudget.VOTE


@pytest.mark.asyncio
async def test_une_note_soldee_ne_bloque_ni_ne_se_reporte(db_session):
    db = db_session
    org, user, service, _ex2026, _ex2027, p = await _contexte(db, correspondance=False)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _payer(db, org, user, note, "300")

    resultat = await _cloturer(db, org, user)

    assert resultat["report"]["notes_reportees"] == 0
    assert await _reports(db, note) == []


@pytest.mark.asyncio
async def test_un_exercice_clos_sans_report_refuse_l_encaissement(db_session):
    """Exercice clôturé avant que le report existe : le paiement est refusé
    plutôt que de modifier 2026, et le rattrapage le débloque."""
    from app.api.v1.endpoints.budget import reporter_creances

    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    ex2026.statut = StatutBudget.CLOTURE
    await db.commit()

    with pytest.raises(HTTPException) as refus:
        await _payer(db, org, user, note, "50")
    await db.rollback()
    assert refus.value.status_code == 400
    assert "2026" in refus.value.detail
    assert await _paye(db, p["cot26"]) == Decimal("0")
    await db.refresh(org)
    await db.refresh(user)

    premier = await reporter_creances(annee=2026, user=user, tenant_id=org.id, db=db)
    second = await reporter_creances(annee=2026, user=user, tenant_id=org.id, db=db)
    assert premier["notes_reportees"] == 1
    assert second["notes_reportees"] == 0
    assert len(await _reports(db, note)) == 1

    await _payer(db, org, user, note, "50")
    assert await _paye(db, p["arr_cot27"]) == Decimal("50")


@pytest.mark.asyncio
async def test_un_paiement_de_l_exercice_clos_ne_s_annule_plus(db_session):
    from app.services.encaissement_payments import cancel_encaissement_payment

    db = db_session
    org, user, service, _ex2026, _ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    acompte = await _payer(db, org, user, note, "100")
    await _cloturer(db, org, user)

    with pytest.raises(HTTPException) as refus:
        await cancel_encaissement_payment(
            db, organisation_id=org.id, payment_id=acompte.id, motif_annulation="Erreur", user_id=user.id
        )
    await db.rollback()
    assert refus.value.status_code == 400
    assert await _paye(db, p["cot26"]) == Decimal("100")


@pytest.mark.asyncio
async def test_une_nouvelle_note_ne_vise_plus_un_poste_clos(db_session):
    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db)
    ex2026.statut = StatutBudget.CLOTURE
    await db.commit()

    with pytest.raises(HTTPException) as refus:
        await _note(db, org, user, service, p["cot26"], "300")
    await db.rollback()
    assert refus.value.status_code == 400
    assert "clôturé" in refus.value.detail


@pytest.mark.asyncio
async def test_rouvrir_rend_la_creance_a_son_exercice(db_session):
    from app.api.v1.endpoints.budget import reopen_budget_exercise

    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _cloturer(db, org, user)

    resultat = await reopen_budget_exercise(annee=2026, user=user, tenant_id=org.id, db=db)

    assert resultat["reports_annules"] == 1
    [report] = await _reports(db, note)
    assert report.statut == "ANNULE"
    # De nouveau ouvert, 2026 encaisse sa propre note.
    await _payer(db, org, user, note, "100")
    assert await _paye(db, p["cot26"]) == Decimal("100")
    assert await _paye(db, p["arr_cot27"]) == Decimal("0")

    # Reclôturer reporte à nouveau, malgré le report annulé qui porte la même clé.
    resultat = await _cloturer(db, org, user)
    assert resultat["report"]["montant_reporte"] == "200.00"


@pytest.mark.asyncio
async def test_rouvrir_est_refuse_apres_un_versement_sur_les_arrieres(db_session):
    from app.api.v1.endpoints.budget import reopen_budget_exercise

    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _cloturer(db, org, user)
    await _payer(db, org, user, note, "50")

    with pytest.raises(HTTPException) as refus:
        await reopen_budget_exercise(annee=2026, user=user, tenant_id=org.id, db=db)
    await db.rollback()
    assert refus.value.status_code == 409
    await db.refresh(ex2026)
    assert ex2026.statut == StatutBudget.CLOTURE


@pytest.mark.asyncio
async def test_deux_articles_reportent_chacun_leur_part(db_session):
    db = db_session
    org, user, service, _ex2026, _ex2027, p = await _contexte(db)
    note = await _note(
        db, org, user, service, p["cot26"], "400",
        articles=[
            EncaissementArticleCreate(
                libelle="Cotisation", quantite=1, prix_unitaire=Decimal("300"), montant=Decimal("300"),
                budget_poste_id=p["cot26"].id,
            ),
            EncaissementArticleCreate(
                libelle="Inscription", quantite=1, prix_unitaire=Decimal("100"), montant=Decimal("100"),
                budget_poste_id=p["ins26"].id,
            ),
        ],
    )
    await _payer(db, org, user, note, "200")  # 150 + 50 en 2026
    await _cloturer(db, org, user)

    reports = {r.poste_cible_id: Decimal(r.montant) for r in await _reports(db, note)}
    assert reports == {p["arr_cot27"].id: Decimal("150"), p["arr_ins27"].id: Decimal("50")}

    await _payer(db, org, user, note, "200")
    assert await _paye(db, p["arr_cot27"]) == Decimal("150")
    assert await _paye(db, p["arr_ins27"]) == Decimal("50")
    assert await _paye(db, p["cot26"]) == Decimal("150")
    assert await _paye(db, p["ins26"]) == Decimal("50")


@pytest.mark.asyncio
async def test_une_dette_impayee_deux_ans_passe_d_arrieres_en_arrieres(db_session):
    from app.services.report_creances import reporter_creances_exercice

    db = db_session
    org, user, service, _ex2026, ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _cloturer(db, org, user)

    ex2028 = BudgetExercice(organisation_id=org.id, annee=2028, statut=StatutBudget.BROUILLON)
    db.add(ex2028)
    await db.flush()
    arr_cot28 = _poste(org.id, ex2028.id, "R.9.1", "Arriérés de cotisation", "R.9.1")
    db.add(arr_cot28)
    await db.flush()
    db.add(ServiceRubrique(service_id=service.id, budget_poste_id=arr_cot28.id, active=True))
    ex2027.statut = StatutBudget.CLOTURE
    await reporter_creances_exercice(db, organisation_id=org.id, exercice=ex2027, user_id=user.id)
    await db.commit()

    statuts = {(r.poste_cible_id, r.statut) for r in await _reports(db, note)}
    assert statuts == {(p["arr_cot27"].id, "REMPLACE"), (arr_cot28.id, "ACTIVE")}

    await _payer(db, org, user, note, "300")
    assert await _paye(db, arr_cot28) == Decimal("300")
    assert await _paye(db, p["arr_cot27"]) == Decimal("0")


@pytest.mark.asyncio
async def test_annuler_une_note_reportee_eteint_son_report(db_session):
    from app.services.report_creances import annuler_reports_encaissement, synthese_reports

    db = db_session
    org, user, service, ex2026, _ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _cloturer(db, org, user)

    await annuler_reports_encaissement(db, organisation_id=org.id, encaissement_id=note, user_id=user.id)
    await db.commit()

    [report] = await _reports(db, note)
    assert report.statut == "ANNULE"
    synthese = await synthese_reports(db, organisation_id=org.id, exercice=ex2026)
    assert synthese["reportes"] == []


@pytest.mark.asyncio
async def test_la_note_et_le_budget_suivant_disent_ou_est_passee_la_dette(db_session):
    from app.api.v1.endpoints.encaissements import lister_notes_impayees
    from app.services.report_creances import synthese_reports

    db = db_session
    org, user, service, ex2026, ex2027, p = await _contexte(db)
    note = await _note(db, org, user, service, p["cot26"], "300")
    await _payer(db, org, user, note, "100")
    await _cloturer(db, org, user)

    liste = await lister_notes_impayees(
        client_id=None, expert_comptable_id=None, nom="Cabinet ABC", limit=20,
        tenant_id=org.id, user=user, db=db,
    )
    [ligne] = liste["notes"]
    assert ligne["arrieres"] == [
        {"code": "R.9.1", "libelle": "Arriérés de cotisation", "annee": 2027, "montant": "200.00"}
    ]

    recus = (await synthese_reports(db, organisation_id=org.id, exercice=ex2027))["recus"]
    assert [(r["poste_id"], r["montant"], r["notes"]) for r in recus] == [(p["arr_cot27"].id, "200.00", 1)]
    emis = (await synthese_reports(db, organisation_id=org.id, exercice=ex2026))["reportes"]
    assert [(r["poste_id"], r["montant"]) for r in emis] == [(p["cot26"].id, "200.00")]
