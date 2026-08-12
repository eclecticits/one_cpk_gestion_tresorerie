"""Tests des flux financiers sensibles (audit M4 / H1 / H2).

Couvre :
- H1 : rejet des montants négatifs/nuls sur les sorties (schéma + endpoint).
- H2 : immuabilité des ordres de décaissement (pas de route de modification,
       montant verrouillé à l'exécution).
- Intégrité des soldes : débit caisse à la sortie + re-crédit à l'annulation.
- Versement caisse -> banque et approvisionnement banque -> caisse (+ annulations).
- Complément de paiement d'encaissement : crédit réel de la caisse.
- Encadrement des relances : plafond et délai minimum.

Ces tests appellent directement les fonctions d'endpoint (comme les autres tests
du projet) avec la session de test. Ils nécessitent TEST_DATABASE_URL (base
DÉDIÉE, jamais la production : le harnais fait DROP SCHEMA).
"""

import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.caisse_centrale import CaisseCentrale
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.ligne_requisition import LigneRequisition
from app.models.organisation import Organisation
from app.models.requisition import Requisition
from app.models.service import Service
from app.models.user import User
from app.schemas.sortie_fonds import SortieFondsCreate


class _FakeRequest:
    """Request minimal pour get_request_ip (pas de client => IP None)."""

    headers: dict = {}
    client = None


# ---------------------------------------------------------------------------
# Helpers de mise en place
# ---------------------------------------------------------------------------

async def _org(db):
    org = Organisation(nom="Treasury Test", slug=f"trez-{uuid.uuid4().hex[:8]}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _depense_poste(db, org, montant_prevu=100000):
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id,
        exercice_id=exercice.id,
        code=f"DEP-{uuid.uuid4().hex[:6]}",
        libelle="Poste dépense",
        type="DEPENSE",
        active=True,
        montant_prevu=montant_prevu,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _service(db, org):
    service = Service(organisation_id=org.id, code=f"S{uuid.uuid4().hex[:4]}", libelle="Service", is_active=True)
    db.add(service)
    await db.flush()
    return service


async def _caisse(db, org, *, usd=Decimal("0"), cdf=Decimal("0"), ouverte=True):
    caisse = CaisseCentrale(
        organisation_id=org.id, solde_usd=usd, solde_cdf=cdf, est_ouverte=ouverte
    )
    db.add(caisse)
    await db.flush()
    return caisse


async def _banque(db, org, *, solde=Decimal("0"), devise="USD"):
    compte = CompteBancaire(
        organisation_id=org.id,
        intitule="Compte banque",
        numero_compte=f"TEST-{uuid.uuid4().hex[:10]}",
        devise=devise,
        solde_initial=solde,
        solde_actuel=solde,
        is_active=True,
        account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


async def _admin(db, org):
    user = User(id=uuid.uuid4(), email=f"a{uuid.uuid4().hex[:6]}@ex.com", role="admin", organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


# ---------------------------------------------------------------------------
# H1 — rejet des montants négatifs / nuls (niveau schéma, sans DB)
# ---------------------------------------------------------------------------

def test_sortie_schema_rejette_montant_negatif():
    with pytest.raises(ValidationError):
        SortieFondsCreate(
            type_sortie="sortie_directe",
            montant_paye=Decimal("-10"),
            mode_paiement="cash",
            motif="x",
            beneficiaire="y",
        )


def test_sortie_schema_rejette_montant_nul():
    with pytest.raises(ValidationError):
        SortieFondsCreate(
            type_sortie="sortie_directe",
            montant_paye=Decimal("0"),
            mode_paiement="cash",
            motif="x",
            beneficiaire="y",
        )


# ---------------------------------------------------------------------------
# H2 — immuabilité des ordres de décaissement (surface d'API)
# ---------------------------------------------------------------------------

def test_ordres_decaissement_pas_de_route_de_modification():
    """Un ordre AUTORISE ne doit pas pouvoir être modifié (montant/bénéficiaire)
    après création : aucune route PUT/PATCH ne doit exister sur la ressource."""
    from app.api.v1.endpoints import ordres_decaissement as od

    methods = set()
    for route in od.router.routes:
        for m in getattr(route, "methods", set()) or set():
            methods.add(m.upper())
    assert "PUT" not in methods
    assert "PATCH" not in methods


# ---------------------------------------------------------------------------
# Intégrité des soldes : sortie de fonds débite la caisse, annulation re-crédite
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_sortie_debite_caisse_et_annulation_recredite(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste = await _depense_poste(db, org)
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("500"))
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds, update_sortie_statut
    from app.schemas.sortie_fonds import SortieFondsStatusUpdate

    payload = SortieFondsCreate(
        type_sortie="autre",
        montant_paye=Decimal("120"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Test sortie",
        beneficiaire="Fournisseur",
        service_id=service.id,
        budget_poste_id=poste.id,
    )
    sortie = await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
    )
    await db.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("380")  # 500 - 120

    # Annulation : la caisse est re-créditée.
    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Erreur de saisie"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("500")


@pytest.mark.asyncio
async def test_requisition_classique_payee_ne_peut_pas_etre_repayee(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste = await _depense_poste(db, org)
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("500"))
    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Paiement classique",
        mode_paiement="cash",
        type_requisition="classique",
        status="APPROUVEE",
        montant_total=Decimal("120"),
        devise="USD",
    )
    db.add(req)
    await db.flush()
    db.add(
        LigneRequisition(
            organisation_id=org.id,
            requisition_id=req.id,
            budget_poste_id=poste.id,
            rubrique="Poste dépense",
            description="Ligne test",
            quantite=1,
            montant_unitaire=Decimal("120"),
            montant_total=Decimal("120"),
            devise="USD",
        )
    )
    user = await _admin(db, org)
    await db.commit()

    async def fake_num(*a, **k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    payload = SortieFondsCreate(
        type_sortie="requisition",
        requisition_id=req.id,
        montant_paye=Decimal("120"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Paiement classique",
        beneficiaire="Bénéficiaire",
        service_id=service.id,
        budget_poste_id=poste.id,
    )
    await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
    )
    await db.refresh(req)
    await db.refresh(caisse)
    assert req.status == "PAYEE"
    assert Decimal(str(caisse.solde_usd)) == Decimal("380")

    with pytest.raises(HTTPException) as exc:
        await create_sortie_fonds(
            payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
        )
    assert exc.value.status_code == 400
    await db.rollback()
    await db.refresh(caisse)
    assert Decimal(str(caisse.solde_usd)) == Decimal("380")


# ---------------------------------------------------------------------------
# Versement caisse -> banque : caisse débitée, banque créditée, annulation inverse
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_versement_banque_transfere_et_annulation_inverse(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    caisse = await _caisse(db, org, usd=Decimal("1000"))
    banque = await _banque(db, org, solde=Decimal("200"))
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds, update_sortie_statut
    from app.schemas.sortie_fonds import SortieFondsStatusUpdate

    payload = SortieFondsCreate(
        type_sortie="versement_banque",
        montant_paye=Decimal("300"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        compte_bancaire_id=banque.id,
        motif="Dépôt banque",
        beneficiaire="Banque",
    )
    sortie = await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
    )
    await db.refresh(caisse)
    await db.refresh(banque)
    assert Decimal(str(caisse.solde_usd)) == Decimal("700")   # 1000 - 300
    assert Decimal(str(banque.solde_actuel)) == Decimal("500")  # 200 + 300

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Annulation versement"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(caisse)
    await db.refresh(banque)
    assert Decimal(str(caisse.solde_usd)) == Decimal("1000")
    assert Decimal(str(banque.solde_actuel)) == Decimal("200")


# ---------------------------------------------------------------------------
# Approvisionnement banque -> caisse : banque débitée, caisse créditée
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approvisionnement_caisse_transfere_et_annulation_inverse(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    caisse = await _caisse(db, org, usd=Decimal("50"))
    banque = await _banque(db, org, solde=Decimal("1000"))
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds, update_sortie_statut
    from app.schemas.sortie_fonds import SortieFondsStatusUpdate

    payload = SortieFondsCreate(
        type_sortie="approvisionnement_caisse",
        montant_paye=Decimal("400"),
        mode_paiement="cash",
        devise="USD",
        canal="BANQUE",
        compte_bancaire_id=banque.id,
        motif="Approvisionnement caisse",
        beneficiaire="Caisse",
    )
    sortie = await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
    )
    await db.refresh(caisse)
    await db.refresh(banque)
    assert Decimal(str(banque.solde_actuel)) == Decimal("600")  # 1000 - 400
    assert Decimal(str(caisse.solde_usd)) == Decimal("450")      # 50 + 400

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Annulation appro"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(caisse)
    await db.refresh(banque)
    assert Decimal(str(banque.solde_actuel)) == Decimal("1000")
    assert Decimal(str(caisse.solde_usd)) == Decimal("50")


# ---------------------------------------------------------------------------
# /reports/summary par canal : la jambe ENTRANTE des transferts internes doit
# être comptée, sinon le solde du rapport diverge du solde réel du compte.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_par_canal_compte_les_entrees_internes(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    caisse = await _caisse(db, org, usd=Decimal("1000"))
    banque = await _banque(db, org, solde=Decimal("200"))
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.reports import summary
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    # Versement caisse -> banque : 300 sortent de la caisse, 300 entrent en banque.
    await create_sortie_fonds(
        payload=SortieFondsCreate(
            type_sortie="versement_banque",
            montant_paye=Decimal("300"),
            mode_paiement="cash",
            devise="USD",
            canal="CAISSE",
            compte_bancaire_id=banque.id,
            motif="Dépôt banque",
            beneficiaire="Banque",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    # Approvisionnement banque -> caisse : 100 sortent de la banque, 100 entrent
    # en caisse.
    await create_sortie_fonds(
        payload=SortieFondsCreate(
            type_sortie="approvisionnement_caisse",
            montant_paye=Decimal("100"),
            mode_paiement="cash",
            devise="USD",
            canal="BANQUE",
            compte_bancaire_id=banque.id,
            motif="Approvisionnement caisse",
            beneficiaire="Caisse",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(caisse)
    await db.refresh(banque)
    assert Decimal(str(caisse.solde_usd)) == Decimal("800")     # 1000 - 300 + 100
    assert Decimal(str(banque.solde_actuel)) == Decimal("400")  # 200 + 300 - 100

    banque_res = await summary(canal="BANQUE", user=user, db=db, tenant_id=org.id)
    banque_totals = banque_res.stats.totals
    # Le versement reçu est une entrée du canal BANQUE (sa ligne porte canal=CAISSE).
    assert Decimal(banque_totals.entrees_internes) == Decimal("300")
    assert Decimal(banque_totals.sorties_total) == Decimal("100")
    # 200 (solde initial du compte) + 300 - 100 = solde réel du compte.
    assert Decimal(banque_totals.solde) == Decimal(str(banque.solde_actuel))

    caisse_res = await summary(canal="CAISSE", user=user, db=db, tenant_id=org.id)
    caisse_totals = caisse_res.stats.totals
    assert Decimal(caisse_totals.entrees_internes) == Decimal("100")
    assert Decimal(caisse_totals.sorties_total) == Decimal("300")

    # Vue consolidée : les deux jambes sont visibles (400 sortants, 400 entrants)
    # et se compensent, donc aucun impact sur le solde.
    all_res = await summary(canal=None, user=user, db=db, tenant_id=org.id)
    all_totals = all_res.stats.totals
    assert Decimal(all_totals.entrees_internes) == Decimal("400")
    assert Decimal(all_totals.transferts_internes) == Decimal("400")
    assert Decimal(all_totals.depenses_reelles) == Decimal("0")
    # Aucune dépense réelle : le solde consolidé reste le solde d'ouverture.
    assert Decimal(all_totals.solde) == Decimal(all_totals.solde_initial)
    # Le rapport se recompose de bout en bout à partir des lignes affichées.
    assert Decimal(all_totals.solde) == (
        Decimal(all_totals.solde_initial)
        + Decimal(all_totals.encaissements_total)
        + Decimal(all_totals.entrees_internes)
        - Decimal(all_totals.sorties_total)
    )


# ---------------------------------------------------------------------------
# /reports/summary : totaux par devise, sans conversion ni mélange USD/CDF.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_totaux_par_devise_ne_melangent_pas_usd_et_cdf(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    # Enveloppe large : le poste est imputé en USD comme en CDF, sans conversion.
    poste = await _depense_poste(db, org, montant_prevu=10_000_000)
    service = await _service(db, org)
    await _caisse(db, org, usd=Decimal("1000"), cdf=Decimal("5000000"))
    # Imputer une sortie CDF sur un poste budgétaire exige un taux de change
    # (sorties_fonds.py:733) : il ne sert QU'À l'imputation budgétaire, les
    # totaux par devise du rapport restent en montants bruts non convertis.
    from app.models.print_settings import PrintSettings

    db.add(PrintSettings(organisation_id=org.id, exchange_rate_cdf=2500))
    await db.commit()
    user = await _admin(db, org)

    async def fake_num(*a, **k):
        return f"PAY-{uuid.uuid4().hex[:8]}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    from app.api.v1.endpoints.reports import summary
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds

    for montant, devise in ((Decimal("120"), "USD"), (Decimal("300000"), "CDF")):
        await create_sortie_fonds(
            payload=SortieFondsCreate(
                type_sortie="autre",
                montant_paye=montant,
                mode_paiement="cash",
                devise=devise,
                canal="CAISSE",
                motif=f"Dépense {devise}",
                beneficiaire="Fournisseur",
                service_id=service.id,
                budget_poste_id=poste.id,
            ),
            request=_FakeRequest(),
            user=user,
            tenant_id=org.id,
            db=db,
        )

    res = await summary(canal="CAISSE", user=user, db=db, tenant_id=org.id)
    totals = res.stats.totals

    # Champ plat : somme brute des deux devises, sans conversion — c'est
    # précisément le nombre qui n'a pas de sens et que `par_devise` remplace.
    assert Decimal(totals.sorties_total) == Decimal("300120")

    par_devise = {ligne.devise: ligne for ligne in totals.par_devise}
    assert set(par_devise) == {"USD", "CDF"}
    assert Decimal(par_devise["USD"].sorties_total) == Decimal("120")
    assert Decimal(par_devise["CDF"].sorties_total) == Decimal("300000")
    assert Decimal(par_devise["USD"].depenses_reelles) == Decimal("120")
    assert Decimal(par_devise["CDF"].depenses_reelles) == Decimal("300000")
    # Chaque ligne se recompose sur elle-même.
    for ligne in totals.par_devise:
        assert Decimal(ligne.solde) == (
            Decimal(ligne.solde_initial)
            + Decimal(ligne.encaissements_total)
            + Decimal(ligne.entrees_internes)
            - Decimal(ligne.sorties_total)
        )

    # Filtre devise : le champ plat devient exact parce qu'il ne porte plus
    # qu'une seule devise.
    usd = await summary(canal="CAISSE", devise="USD", user=user, db=db, tenant_id=org.id)
    assert Decimal(usd.stats.totals.sorties_total) == Decimal("120")
    cdf = await summary(canal="CAISSE", devise="CDF", user=user, db=db, tenant_id=org.id)
    assert Decimal(cdf.stats.totals.sorties_total) == Decimal("300000")

    # La ventilation, elle, reste complète quelle que soit la devise regardée :
    # c'est ce qui empêche de croire son rapport exhaustif en vue USD.
    for res_filtre in (usd, cdf):
        assert {l.devise for l in res_filtre.stats.totals.par_devise} == {"USD", "CDF"}

    with pytest.raises(HTTPException) as exc:
        await summary(devise="EUR", user=user, db=db, tenant_id=org.id)
    assert exc.value.status_code == 400


# ---------------------------------------------------------------------------
# /reports/summary : le solde d'ouverture d'un canal ne prend que SES comptes.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_summary_solde_ouverture_ne_melange_pas_caisse_et_banque(db_session):
    db = db_session
    org = await _org(db)
    await _caisse(db, org, usd=Decimal("0"))
    # Ouverture bancaire 500, ouverture caisse (compte CASH) 30.
    await _banque(db, org, solde=Decimal("500"))
    db.add(
        CompteBancaire(
            organisation_id=org.id,
            intitule="Caisse principale",
            numero_compte=f"CASH-{uuid.uuid4().hex[:10]}",
            devise="USD",
            solde_initial=Decimal("30"),
            solde_actuel=Decimal("30"),
            is_active=True,
            account_type="CASH",
        )
    )
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.reports import summary

    banque = await summary(canal="BANQUE", user=user, db=db, tenant_id=org.id)
    caisse = await summary(canal="CAISSE", user=user, db=db, tenant_id=org.id)
    tous = await summary(user=user, db=db, tenant_id=org.id)

    # Chaque canal s'ouvre sur SES comptes : la caisse ne démarre pas avec les
    # 500 de la banque, ni l'inverse.
    assert Decimal(banque.stats.totals.solde_initial) == Decimal("500")
    assert Decimal(caisse.stats.totals.solde_initial) == Decimal("30")
    # Vue consolidée : les deux, comme avant la correction.
    assert Decimal(tous.stats.totals.solde_initial) == Decimal("530")

    # La ventilation par devise doit suivre le même périmètre, faute de quoi les
    # deux blocs du rapport se contrediraient.
    for res, attendu in ((banque, Decimal("500")), (caisse, Decimal("30")), (tous, Decimal("530"))):
        usd = next(l for l in res.stats.totals.par_devise if l.devise == "USD")
        assert Decimal(usd.solde_initial) == attendu


# ---------------------------------------------------------------------------
# Complément de paiement d'encaissement : crédite réellement la caisse (bug M4)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_complement_paiement_credite_caisse(db_session):
    db = db_session
    org = await _org(db)
    caisse = await _caisse(db, org, usd=Decimal("0"))
    # Poste recette pour l'imputation budgétaire du complément.
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"REC-{uuid.uuid4().hex[:6]}",
        libelle="Recette", type="RECETTE", active=True,
        montant_prevu=100000, montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()

    enc = Encaissement(
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client Partiel",
        libelle="Prestation",
        montant=Decimal("100"),
        montant_total=Decimal("100"),
        montant_paye=Decimal("40"),
        montant_percu=Decimal("40"),
        devise_perception="USD",
        canal="CAISSE",
        statut_paiement="partiel",
        mode_paiement="cash",
        budget_poste_id=poste.id,
        date_encaissement=datetime.now(timezone.utc),
    )
    db.add(enc)
    await db.commit()
    user = await _admin(db, org)

    from app.api.v1.endpoints.payments import create_payment
    from app.schemas.payment import PaymentHistoryCreate
    from fastapi import BackgroundTasks

    result = await create_payment(
        payload=PaymentHistoryCreate(encaissement_id=enc.id, montant=Decimal("60"), mode_paiement="cash"),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    assert Decimal(str(result["montant"])) == Decimal("60")
    await db.refresh(caisse)
    await db.refresh(enc)
    # Le complément de 60 doit être entré en caisse (bug corrigé).
    assert Decimal(str(caisse.solde_usd)) == Decimal("60")
    assert enc.statut_paiement == "complet"


# ---------------------------------------------------------------------------
# Relances : plafond (3) et délai minimum (7 jours)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_relance_plafond_et_delai(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    exercice = BudgetExercice(organisation_id=org.id, annee=2026, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"REC-{uuid.uuid4().hex[:6]}",
        libelle="Recette", type="RECETTE", active=True,
        montant_prevu=100000, montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    enc = Encaissement(
        organisation_id=org.id,
        type_client="client_externe",
        client_nom="Client Débiteur",
        libelle="Prestation",
        montant=Decimal("100"),
        montant_total=Decimal("100"),
        montant_paye=Decimal("30"),
        montant_percu=Decimal("30"),
        devise_perception="USD",
        canal="CAISSE",
        statut_paiement="partiel",
        mode_paiement="cash",
        budget_poste_id=poste.id,
        date_encaissement=datetime.now(timezone.utc),
        relance_count=0,
    )
    db.add(enc)
    await db.commit()
    user = await _admin(db, org)

    # On simule un envoi email toujours réussi.
    async def fake_send(db_, bt, encaissement, tenant_id, *, relance=False, send_now=False):
        return "client@example.com"

    monkeypatch.setattr(
        "app.api.v1.endpoints.encaissements.schedule_client_payment_email", fake_send
    )

    from app.api.v1.endpoints.encaissements import relancer_solde_client
    from fastapi import BackgroundTasks, HTTPException

    # 1re relance OK.
    r1 = await relancer_solde_client(
        encaissement_id=str(enc.id), background_tasks=BackgroundTasks(),
        user=user, tenant_id=org.id, db=db,
    )
    assert r1["relance_count"] == 1

    # 2e relance immédiate : refusée (délai minimum 7 jours).
    with pytest.raises(HTTPException) as exc:
        await relancer_solde_client(
            encaissement_id=str(enc.id), background_tasks=BackgroundTasks(),
            user=user, tenant_id=org.id, db=db,
        )
    assert exc.value.status_code == 400

    # On avance le temps : dernière relance il y a 8 jours, count = 3 (plafond).
    await db.refresh(enc)
    enc.derniere_relance_le = datetime.now(timezone.utc) - timedelta(days=8)
    enc.relance_count = 3
    await db.commit()
    with pytest.raises(HTTPException) as exc2:
        await relancer_solde_client(
            encaissement_id=str(enc.id), background_tasks=BackgroundTasks(),
            user=user, tenant_id=org.id, db=db,
        )
    assert exc2.value.status_code == 400  # plafond atteint


# ---------------------------------------------------------------------------
# Décaissement progressif réparti sur plusieurs postes budgétaires
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decaissement_progressif_multi_postes(db_session, monkeypatch):
    db = db_session
    org = await _org(db)
    poste_a = await _depense_poste(db, org, montant_prevu=100000)
    poste_b = BudgetPoste(
        organisation_id=org.id,
        exercice_id=poste_a.exercice_id,
        code=f"DEP-{uuid.uuid4().hex[:6]}",
        libelle="Poste dépense B",
        type="DEPENSE",
        active=True,
        montant_prevu=100000,
        montant_engage=0,
        montant_paye=0,
        is_deleted=False,
    )
    db.add(poste_b)
    await db.flush()
    service = await _service(db, org)
    caisse = await _caisse(db, org, usd=Decimal("2000"))
    user = await _admin(db, org)
    req = Requisition(
        organisation_id=org.id,
        service_id=service.id,
        numero_requisition=f"REQ-{uuid.uuid4().hex[:8]}",
        reference_numero=f"REF-{uuid.uuid4().hex[:8]}",
        objet="Progressif multi-postes",
        mode_paiement="cash",
        type_requisition="classique",
        status="APPROUVEE",
        montant_total=Decimal("1000"),
        devise="USD",
        decaissement_progressif=True,
        created_by=user.id,
    )
    db.add(req)
    await db.flush()
    for poste, montant in ((poste_a, "600"), (poste_b, "400")):
        db.add(LigneRequisition(
            organisation_id=org.id, requisition_id=req.id, budget_poste_id=poste.id,
            rubrique="R", description="R", quantite=1,
            montant_unitaire=Decimal(montant), montant_total=Decimal(montant), devise="USD",
        ))
    await db.commit()
    # Ids capturés en local : un rollback (test d'erreur ci-dessous) expire les
    # objets ORM et rendrait leur accès sync impossible (MissingGreenlet).
    req_id = req.id
    poste_a_id = poste_a.id
    poste_b_id = poste_b.id
    service_id = service.id

    async def fake_num(*a, **k):
        return f"DOC-{uuid.uuid4().hex[:8]}"
    monkeypatch.setattr("app.api.v1.endpoints.ordres_decaissement.generate_document_number", fake_num)
    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", fake_num)

    async def fake_perm(*a, **k):
        return True
    monkeypatch.setattr("app.api.v1.endpoints.ordres_decaissement._user_has_permission", fake_perm)

    from sqlalchemy import select
    from app.models.ordre_decaissement import OrdreDecaissement
    from app.api.v1.endpoints.ordres_decaissement import create_ordre_decaissement
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds
    from app.schemas.ordre_decaissement import OrdreDecaissementCreate

    # Autoriser une tranche répartie : A=300, B=200 (total 500).
    await create_ordre_decaissement(
        payload=OrdreDecaissementCreate(
            requisition_id=req_id, beneficiaire="Bénéf", montant=Decimal("500"), devise="USD",
            lignes=[
                {"budget_poste_id": poste_a_id, "montant": Decimal("300")},
                {"budget_poste_id": poste_b_id, "montant": Decimal("200")},
            ],
        ),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )
    ordre = (await db.execute(
        select(OrdreDecaissement).where(OrdreDecaissement.requisition_id == req_id)
    )).scalar_one()

    # La caissière paie la tranche → imputation par poste.
    payload = SortieFondsCreate(
        type_sortie="requisition",
        requisition_id=req_id,
        ordre_decaissement_id=ordre.id,
        montant_paye=Decimal("500"),
        mode_paiement="cash",
        devise="USD",
        canal="CAISSE",
        motif="Tranche répartie",
        beneficiaire="Bénéf",
        service_id=service_id,
    )
    await create_sortie_fonds(
        payload=payload, request=_FakeRequest(), user=user, tenant_id=org.id, db=db
    )

    await db.refresh(poste_a)
    await db.refresh(poste_b)
    await db.refresh(caisse)
    await db.refresh(ordre)
    assert Decimal(str(poste_a.montant_paye)) == Decimal("300")
    assert Decimal(str(poste_b.montant_paye)) == Decimal("200")
    assert Decimal(str(caisse.solde_usd)) == Decimal("1500")
    assert ordre.statut == "PAYE"
