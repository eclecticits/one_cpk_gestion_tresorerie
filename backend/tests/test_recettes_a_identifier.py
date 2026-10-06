"""Recettes à identifier : l'argent entre en banque avant qu'on sache qui a payé.

Ce que ces tests tiennent :
- la saisie crédite la banque tout de suite, jamais le budget ;
- identifier DÉPLACE le versement : la banque n'est pas créditée une seconde
  fois et les flux de trésorerie totalisent toujours le seul montant reçu ;
- l'identification annulée rend le montant à la recette d'origine, pas à la
  banque ;
- en comptabilité automatique : Banque / compte d'attente à la réception,
  compte d'attente / produit à l'identification.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget
from app.models.compte_bancaire import CompteBancaire
from app.models.encaissement import Encaissement
from app.models.organisation import Organisation
from app.models.organisation_settings import OrganisationSettings
from app.models.payment_history import PaymentHistory
from app.models.user import User
from app.modules.comptabilite.models import ComptaCompte, ComptaEcriture
from app.modules.comptabilite.services.mapping_defaut_service import generer_mappings_par_defaut
from app.modules.comptabilite.services.setup_service import setup_comptabilite
from app.schemas.payment import EncaissementCancelPayload, EncaissementCreate
from app.services.encaissement_flux import flux_encaissements

# Les écritures comptables sont générées dans le flux : sans cet import, les
# tables `compta_*` manquent aux métadonnées quand ce fichier tourne seul.
from app.modules.comptabilite import models as _compta_models  # noqa: F401


class _FakeRequest:
    headers: dict = {}
    client = None


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


async def _org(db):
    org = Organisation(nom="Recettes à identifier", slug=f"ri-{_suffix()}", is_active=True)
    db.add(org)
    await db.flush()
    return org


async def _user(db, org, role="admin"):
    user = User(id=uuid.uuid4(), email=f"{_suffix()}@ex.com", role=role, organisation_id=org.id)
    db.add(user)
    await db.flush()
    return user


async def _poste(db, org):
    exercice = BudgetExercice(organisation_id=org.id, annee=date.today().year, statut=StatutBudget.BROUILLON)
    db.add(exercice)
    await db.flush()
    poste = BudgetPoste(
        organisation_id=org.id, exercice_id=exercice.id, code=f"REC-{_suffix()[:6]}",
        libelle="Cotisations", type="RECETTE", active=True,
        montant_prevu=Decimal("10000"), montant_engage=0, montant_paye=0, is_deleted=False,
    )
    db.add(poste)
    await db.flush()
    return poste


async def _banque(db, org, solde=Decimal("0")):
    compte = CompteBancaire(
        organisation_id=org.id, intitule="Rawbank", numero_compte=f"RB-{_suffix()}",
        devise="USD", solde_initial=solde, solde_actuel=solde, is_active=True, account_type="BANK",
    )
    db.add(compte)
    await db.flush()
    return compte


@pytest.fixture
def sans_notifications(monkeypatch):
    async def rien(*_a, **_k):
        return None

    async def numero(**_k):
        return f"ND-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.encaissements._generate_numero_recu", numero)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements.schedule_client_payment_email", rien)
    monkeypatch.setattr("app.api.v1.endpoints.encaissements._notify_paiement_whatsapp", rien)
    monkeypatch.setattr("app.api.v1.endpoints.recettes_a_identifier.schedule_client_payment_email", rien)


async def _saisir(db, org, user, banque, montant="500", jours=0, libelle="VIR RECU DE MUKENDI JEAN REF 8841"):
    from app.api.v1.endpoints.recettes_a_identifier import RecetteAIdentifierCreate, creer

    res = await creer(
        payload=RecetteAIdentifierCreate(
            compte_bancaire_id=banque.id,
            montant=Decimal(montant),
            date_valeur=date.today() - timedelta(days=jours),
            libelle=libelle,
            reference=f"REF-{_suffix()}",
        ),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    return uuid.UUID(res["id"])


def _note(poste, montant, *, paye="0", source=None, client="Jean Mukendi"):
    return EncaissementCreate(
        type_client="personne_physique", client_sexe="M", client_nom=client,
        libelle="Cotisation annuelle",
        montant=Decimal(montant), montant_total=Decimal(montant), montant_paye=Decimal(paye),
        montant_percu=Decimal(paye), devise_perception="USD",
        mode_paiement="cash", canal="CAISSE",
        budget_poste_id=poste.id,
        identification_source_id=source,
    )


async def _creer(db, org, user, payload):
    from app.api.v1.endpoints.encaissements import create_encaissement

    return await create_encaissement(
        payload=payload, background_tasks=BackgroundTasks(), user=user, tenant_id=org.id, db=db,
    )


async def _flux_banque(db, org, banque) -> Decimal:
    flux = flux_encaissements(org.id)
    total = (
        await db.execute(select(func.coalesce(func.sum(flux.c.montant), 0)).where(flux.c.compte_bancaire_id == banque.id))
    ).scalar_one()
    return Decimal(str(total))


async def test_saisie_credite_la_banque_et_pas_le_budget(db_session, sans_notifications):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    banque = await _banque(db, org)
    await db.commit()

    source_id = await _saisir(db, org, user, banque, "500", jours=40)

    await db.refresh(banque)
    await db.refresh(poste)
    assert banque.solde_actuel == Decimal("500")
    assert poste.montant_paye == Decimal("0")
    assert await _flux_banque(db, org, banque) == Decimal("500")

    source = await db.get(Encaissement, source_id)
    assert source.nature_mouvement == "A_IDENTIFIER"
    assert source.impact_budgetaire is False
    assert source.hors_budget_status == "A_IDENTIFIER"
    assert source.numero_recu.startswith("ATT-")
    assert source.client_nom is None

    from app.api.v1.endpoints.recettes_a_identifier import lister

    liste = await lister(statut="ouvertes", tenant_id=org.id, db=db)
    (item,) = liste["items"]
    assert item["reste"] == "500.00"
    assert item["tranche"] == "31-90"
    assert liste["totaux"] == [
        {"devise": "USD", "par_tranche": {"0-30": "0.00", "31-90": "500.00", "+90": "0.00"}, "total": "500.00"}
    ]


async def test_identifier_deplace_le_versement_sans_recrediter_la_banque(db_session, sans_notifications):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    banque = await _banque(db, org)
    await db.commit()
    source_id = await _saisir(db, org, user, banque, "500", jours=3)
    date_valeur = (await db.get(Encaissement, source_id)).date_paiement

    # 1. Une partie réglait une note de débit déjà émise, restée impayée.
    note = await _creer(db, org, user, _note(poste, "200"))
    from app.api.v1.endpoints.recettes_a_identifier import ReglerNotePayload, pistes, regler_note

    suggestions = await pistes(recette_id=str(source_id), q=None, tenant_id=org.id, db=db)
    assert any(s["encaissement_id"] == str(note["id"]) and s["raison"] == "nom" for s in suggestions)

    await regler_note(
        recette_id=str(source_id),
        payload=ReglerNotePayload(encaissement_id=note["id"], montant=Decimal("200")),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    note_db = await db.get(Encaissement, note["id"])
    await db.refresh(note_db)
    assert note_db.montant_paye == Decimal("200")
    source = await db.get(Encaissement, source_id)
    await db.refresh(source)
    assert source.montant_paye == Decimal("300")
    assert source.hors_budget_status == "PARTIELLEMENT_IDENTIFIE"

    # 2. Le reste devient une nouvelle recette, avec son reçu.
    nouvelle = await _creer(db, org, user, _note(poste, "300", paye="300", source=source_id, client="Marie Kabila"))

    await db.refresh(source)
    await db.refresh(banque)
    await db.refresh(poste)
    assert source.montant_paye == Decimal("0")
    assert source.hors_budget_status == "IDENTIFIE"
    assert banque.solde_actuel == Decimal("500"), "la banque ne reçoit l'argent qu'une fois"
    assert poste.montant_paye == Decimal("500")
    assert await _flux_banque(db, org, banque) == Decimal("500")

    versement_origine = (
        await db.execute(
            select(PaymentHistory).where(
                PaymentHistory.encaissement_id == source_id, PaymentHistory.identification_source_id.is_(None)
            )
        )
    ).scalar_one()
    assert versement_origine.statut == "TRANSFERE"

    versement_nouveau = (
        await db.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == nouvelle["id"]))
    ).scalar_one()
    assert versement_nouveau.identification_source_id == source_id
    assert versement_nouveau.canal == "BANQUE" and versement_nouveau.compte_bancaire_id == banque.id
    assert versement_nouveau.date_paiement == date_valeur, "la trésorerie garde la date de valeur"

    from app.api.v1.endpoints.recettes_a_identifier import lister

    assert (await lister(statut="ouvertes", tenant_id=org.id, db=db))["items"] == []
    (item,) = (await lister(statut="toutes", tenant_id=org.id, db=db))["items"]
    assert item["montant_initial"] == "500.00"
    assert {i["montant"] for i in item["identifications"]} == {"200.00", "300.00"}


async def test_annuler_une_identification_rend_le_montant_a_la_recette(db_session, sans_notifications):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    banque = await _banque(db, org)
    await db.commit()
    source_id = await _saisir(db, org, user, banque, "500")
    nouvelle = await _creer(db, org, user, _note(poste, "500", paye="500", source=source_id))

    from app.api.v1.endpoints.encaissements import cancel_encaissement_operation

    # La recette d'origine ne s'annule pas tant que des encaissements en sont tirés.
    with pytest.raises(HTTPException) as exc:
        await cancel_encaissement_operation(
            encaissement_id=str(source_id),
            payload=EncaissementCancelPayload(motif_annulation="Erreur de saisie"),
            request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
        )
    assert exc.value.status_code == 400

    await cancel_encaissement_operation(
        encaissement_id=str(nouvelle["id"]),
        payload=EncaissementCancelPayload(motif_annulation="Mauvais payeur"),
        request=_FakeRequest(), user=user, tenant_id=org.id, db=db,
    )

    source = await db.get(Encaissement, source_id)
    await db.refresh(source)
    await db.refresh(banque)
    await db.refresh(poste)
    assert source.montant_paye == Decimal("500")
    assert source.hors_budget_status == "A_IDENTIFIER"
    assert banque.solde_actuel == Decimal("500"), "l'argent n'a pas quitté la banque"
    assert poste.montant_paye == Decimal("0")
    assert await _flux_banque(db, org, banque) == Decimal("500")
    versement_origine = (
        await db.execute(
            select(PaymentHistory).where(
                PaymentHistory.encaissement_id == source_id, PaymentHistory.identification_source_id.is_(None)
            )
        )
    ).scalar_one()
    assert versement_origine.statut == "ACTIF" and versement_origine.montant == Decimal("500")


async def test_garde_fous(db_session, sans_notifications):
    db = db_session
    org = await _org(db)
    admin = await _user(db, org)
    caissier = await _user(db, org, role="caissier")
    poste = await _poste(db, org)
    banque = await _banque(db, org)
    await db.commit()
    source_id = await _saisir(db, org, admin, banque, "100")

    with pytest.raises(HTTPException) as exc:
        await _creer(db, org, caissier, _note(poste, "100", paye="100", source=source_id))
    assert exc.value.status_code == 403

    payload = _note(poste, "100", paye="100").model_copy(update={"nature_mouvement": "A_IDENTIFIER"})
    with pytest.raises(HTTPException) as exc:
        await _creer(db, org, admin, payload)
    assert exc.value.status_code == 400

    # Même compte, même libellé, même référence, même jour : le même relevé saisi deux fois.
    from app.api.v1.endpoints.recettes_a_identifier import RecetteAIdentifierCreate, creer

    donnees = RecetteAIdentifierCreate(
        compte_bancaire_id=banque.id, montant=Decimal("80"), date_valeur=date.today(),
        libelle="VIR INCONNU", reference="RB-77",
    )
    await creer(payload=donnees, request=_FakeRequest(), user=admin, tenant_id=org.id, db=db)
    with pytest.raises(HTTPException) as exc:
        await creer(payload=donnees, request=_FakeRequest(), user=admin, tenant_id=org.id, db=db)
    assert exc.value.status_code == 409

    # En dernier : l'échec survient après l'écriture de la note, la session est à jeter.
    with pytest.raises(HTTPException) as exc:
        await _creer(db, org, admin, _note(poste, "150", paye="150", source=source_id))
    assert exc.value.status_code == 400 and "reste à identifier" in exc.value.detail


async def _activer_comptabilite(db, org):
    db.add(OrganisationSettings(organisation_id=org.id, accounting_integration_mode="automatic"))
    await setup_comptabilite(
        db, organisation_id=org.id, organisation_nom=org.nom, type_referentiel="SYSCEBNL",
        exercice_date_debut=date(date.today().year, 1, 1), exercice_date_fin=date(date.today().year, 12, 31),
    )
    await generer_mappings_par_defaut(db, organisation_id=org.id)
    await db.flush()


async def _lignes(db, versement_id) -> dict[str, tuple[Decimal, Decimal]]:
    ecriture = (
        await db.execute(
            select(ComptaEcriture)
            .options(selectinload(ComptaEcriture.lignes))
            .where(ComptaEcriture.type_origine == "payment_history", ComptaEcriture.objet_origine_id == str(versement_id))
        )
    ).scalar_one()
    comptes = {
        c.id: c.numero
        for c in (await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_([l.compte_id for l in ecriture.lignes])))).scalars()
    }
    return {comptes[l.compte_id]: (l.debit, l.credit) for l in ecriture.lignes}


async def test_comptabilite_passe_par_le_compte_d_attente(db_session, sans_notifications):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    banque = await _banque(db, org)
    await _activer_comptabilite(db, org)
    await db.commit()

    source_id = await _saisir(db, org, user, banque, "250")
    versement_origine = (
        await db.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == source_id))
    ).scalar_one()
    assert await _lignes(db, versement_origine.id) == {
        "512": (Decimal("250"), Decimal("0")),
        "4718": (Decimal("0"), Decimal("250")),
    }

    nouvelle = await _creer(db, org, user, _note(poste, "250", paye="250", source=source_id))
    versement = (
        await db.execute(select(PaymentHistory).where(PaymentHistory.encaissement_id == nouvelle["id"]))
    ).scalar_one()
    assert await _lignes(db, versement.id) == {
        "4718": (Decimal("250"), Decimal("0")),
        "758": (Decimal("0"), Decimal("250")),
    }


# ── Remboursement par réquisition puis sortie de fonds ─────────────────────


async def _requisition_remboursement(db, org, source_id, montant, status="APPROUVEE"):
    from app.models.requisition import Requisition

    req = Requisition(
        organisation_id=org.id,
        numero_requisition=f"REQ-{_suffix()}",
        objet="Remboursement d'un virement reçu par erreur",
        mode_paiement="virement",
        type_requisition="classique",
        nature_requisition="RECETTE_A_IDENTIFIER",
        recette_a_identifier_id=source_id,
        status=status,
        montant_total=Decimal(montant),
        devise="USD",
        beneficiaire="Société Kasaï Trading",
    )
    db.add(req)
    await db.flush()
    return req


async def _payer(db, org, user, banque, req, montant):
    from app.api.v1.endpoints.sorties_fonds import create_sortie_fonds
    from app.schemas.sortie_fonds import SortieFondsCreate

    return await create_sortie_fonds(
        payload=SortieFondsCreate(
            type_sortie="remboursement_recette_a_identifier",
            requisition_id=req.id,
            nature_mouvement="A_IDENTIFIER",
            montant_paye=Decimal(montant),
            mode_paiement="virement",
            devise="USD",
            canal="BANQUE",
            compte_bancaire_id=banque.id,
            motif="Remboursement",
            beneficiaire="",
        ),
        request=_FakeRequest(),
        background_tasks=BackgroundTasks(),
        user=user,
        tenant_id=org.id,
        db=db,
    )


@pytest.fixture
def numeros_sortie(monkeypatch):
    async def numero(*_a, **_k):
        return f"PAY-{_suffix()}"

    monkeypatch.setattr("app.api.v1.endpoints.sorties_fonds.generate_document_number", numero)


async def test_remboursement_reserve_puis_sort_de_la_banque(db_session, sans_notifications, numeros_sortie):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    poste = await _poste(db, org)
    banque = await _banque(db, org)
    await db.commit()
    source_id = await _saisir(db, org, user, banque, "500")

    # La réquisition en circuit retient sa part : elle ne s'identifie plus.
    req = await _requisition_remboursement(db, org, source_id, "300", status="EN_ATTENTE")
    await db.commit()
    from app.api.v1.endpoints.recettes_a_identifier import lister

    (item,) = (await lister(statut="ouvertes", tenant_id=org.id, db=db))["items"]
    assert item["disponible"] == "200.00" and item["reservations"] == [req.numero_requisition]

    from app.services.recettes_a_identifier import verifier_remboursement

    with pytest.raises(HTTPException) as exc:
        await verifier_remboursement(
            db, organisation_id=org.id, recette_id=source_id, devise="USD", montant=Decimal("250")
        )
    assert req.numero_requisition in exc.value.detail

    req.status = "APPROUVEE"
    await db.commit()
    sortie = await _payer(db, org, user, banque, req, "300")

    await db.refresh(banque)
    assert banque.solde_actuel == Decimal("200"), "le remboursement sort réellement de la banque"
    assert sortie.recette_a_identifier_id == source_id
    assert sortie.nature_mouvement == "A_IDENTIFIER"
    assert sortie.beneficiaire == "Société Kasaï Trading"
    await db.refresh(req)
    assert req.status == "PAYEE"

    source = await db.get(Encaissement, source_id)
    await db.refresh(source)
    assert source.montant_paye == Decimal("500"), "la recette garde ce qui est entré"
    assert source.hors_budget_status == "PARTIELLEMENT_IDENTIFIE"

    (item,) = (await lister(statut="ouvertes", tenant_id=org.id, db=db))["items"]
    assert item["reste"] == "200.00" and item["montant_rembourse"] == "300.00"

    # Le reste s'identifie normalement ; la recette est alors soldée.
    await _creer(db, org, user, _note(poste, "200", paye="200", source=source_id))
    await db.refresh(source)
    await db.refresh(banque)
    assert source.hors_budget_status == "IDENTIFIE"
    assert banque.solde_actuel == Decimal("200")


async def test_remboursement_total_puis_annule(db_session, sans_notifications, numeros_sortie):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    banque = await _banque(db, org)
    await db.commit()
    source_id = await _saisir(db, org, user, banque, "120")
    req = await _requisition_remboursement(db, org, source_id, "120")
    await db.commit()
    sortie = await _payer(db, org, user, banque, req, "120")

    source = await db.get(Encaissement, source_id)
    await db.refresh(source)
    assert source.hors_budget_status == "REMBOURSEE"

    from app.api.v1.endpoints.sorties_fonds import update_sortie_statut
    from app.schemas.sortie_fonds import SortieFondsStatusUpdate

    await update_sortie_statut(
        sortie_id=str(sortie.id),
        payload=SortieFondsStatusUpdate(statut="ANNULEE", motif_annulation="Virement retourné par la banque"),
        request=_FakeRequest(),
        user=user,
        tenant_id=org.id,
        db=db,
    )
    await db.refresh(source)
    await db.refresh(banque)
    assert source.hors_budget_status == "A_IDENTIFIER"
    assert banque.solde_actuel == Decimal("120")


async def test_remboursement_comptabilise_contre_le_compte_d_attente(db_session, sans_notifications, numeros_sortie):
    db = db_session
    org = await _org(db)
    user = await _user(db, org)
    banque = await _banque(db, org)
    await _activer_comptabilite(db, org)
    await db.commit()
    source_id = await _saisir(db, org, user, banque, "90")
    req = await _requisition_remboursement(db, org, source_id, "90")
    await db.commit()
    sortie = await _payer(db, org, user, banque, req, "90")

    ecriture = (
        await db.execute(
            select(ComptaEcriture)
            .options(selectinload(ComptaEcriture.lignes))
            .where(ComptaEcriture.type_origine == "sortie_fonds", ComptaEcriture.objet_origine_id == str(sortie.id))
        )
    ).scalar_one()
    comptes = {
        c.id: c.numero
        for c in (await db.execute(select(ComptaCompte).where(ComptaCompte.id.in_([l.compte_id for l in ecriture.lignes])))).scalars()
    }
    assert {comptes[l.compte_id]: (l.debit, l.credit) for l in ecriture.lignes} == {
        "4718": (Decimal("90"), Decimal("0")),
        "512": (Decimal("0"), Decimal("90")),
    }
