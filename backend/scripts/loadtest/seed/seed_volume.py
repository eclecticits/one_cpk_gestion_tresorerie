"""Semeur de VOLUME pour les tests de charge ONEC Smart.

Complete `backend/scripts/load_campaign.py` (commit a67b5ec), qui cree
l'ossature (organisation, 1 service, exercice, 2 postes, caisse, banque,
compte, utilisateurs, experts) mais laisse les tables metier quasi vides.
La reserve n°1 de docs/PERFORMANCE_WORKER_SCALING_20260817.md est justement
la : « Rejouer la campagne sur un volume de donnees representatif de la
production. Sans cela, la projection n'est pas validee. »

Ce script ne touche AUCUN fichier du depot. Il s'execute DANS le conteneur
backend (il importe les modeles de l'application) :

    docker compose cp seed/seed_volume.py backend:/app/seed_volume.py
    docker compose exec backend python /app/seed_volume.py --preset production

Ordre impose par les contraintes de la base :
  1. requisitions inserees en EN_ATTENTE
  2. lignes_requisition inserees (le trigger
     `trg_lignes_requisition_immutable_after_final`, alembic/versions/
     20260723b_historical_document_snapshots.py:171, refuse toute INSERT de
     ligne sur une requisition APPROUVEE / PAYEE / EN_DECAISSEMENT)
  3. UPDATE de statut vers AUTORISEE / APPROUVEE / PAYEE / REJETEE
     (`trg_requisitions_immutable_after_final` ne bloque que si OLD.status est
     deja final, ce qui n'est pas le cas ici)

Les compteurs de `document_sequences` sont repositionnes a la fin, sinon
l'API regenererait des numeros deja pris : voir la boucle de 50 tentatives de
`create_encaissement` (backend/app/api/v1/endpoints/encaissements.py:1437).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

PROJECT_ROOT = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
for candidate in ("/app", PROJECT_ROOT):
    if candidate not in sys.path and os.path.isdir(os.path.join(candidate, "app")):
        sys.path.insert(0, candidate)

from sqlalchemy import func, insert, select, text, update  # noqa: E402

from app.db.session import SessionLocal  # noqa: E402
from app.models.budget import BudgetExercice, BudgetPoste, StatutBudget  # noqa: E402
from app.models.compte_bancaire import CompteBancaire  # noqa: E402
from app.models.document_sequence import DocumentSequence  # noqa: E402
from app.models.encaissement import Encaissement  # noqa: E402
from app.models.expert_comptable import ExpertComptable  # noqa: E402
from app.models.ligne_requisition import LigneRequisition  # noqa: E402
from app.models.organisation import Organisation  # noqa: E402
from app.models.organisation_settings import OrganisationSettings  # noqa: E402
from app.models.requisition import Requisition  # noqa: E402
from app.models.service import Service  # noqa: E402
from app.models.service_rubrique import ServiceRubrique  # noqa: E402
from app.models.sortie_fonds import SortieFonds  # noqa: E402
from app.models.user import User  # noqa: E402

RNG = random.Random(20260826)

# Presets de volume. « production » vise l'ordre de grandeur d'un ONEC apres
# quelques exercices ; « smoke » sert a valider le script en 2 minutes.
PRESETS = {
    "smoke": dict(services=3, postes=40, requisitions=500, encaissements=1000, sorties=300, experts=500),
    "pilote": dict(services=6, postes=150, requisitions=8000, encaissements=15000, sorties=5000, experts=2000),
    "production": dict(services=8, postes=300, requisitions=60000, encaissements=120000, sorties=40000, experts=6000),
}

# Circuit de validation impose au tenant de charge : signature_service et examen
# desactives, validation_1 + validation_2 actives. C'est ce qui rend la chaine
# creation -> validation technique -> visa jouable en 3 appels HTTP.
# Voir backend/app/services/workflow_config.py:41 (preset « simplifie »).
WORKFLOW_LOADTEST = {
    "preset": "simplifie",
    "steps": {
        "signature_service": {"enabled": False},
        "examen": {"enabled": False},
        "validation_1": {"enabled": True},
        "validation_2": {"enabled": True},
    },
}

MODES = ("cash", "virement", "cheque")
TYPES_CLIENT = ("autre", "personne_physique", "personne_morale", "client_externe")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Numerotation:
    """Reproduit exactement le format de app/services/document_sequences.py."""

    def __init__(self) -> None:
        self.counters: dict[tuple[str, int, int | None], int] = {}

    def next(self, doc_type: str, year: int, service_id: int | None, service_code: str) -> str:
        key = (doc_type, year, service_id)
        value = self.counters.get(key, 0) + 1
        self.counters[key] = value
        if doc_type in {"ND", "PF-ND"}:
            return f"{doc_type}-{year}-{value:06d}"
        return f"{doc_type}-{service_code}-{year}-{value:05d}"


async def chunked_insert(db, model, rows: list[dict], batch: int, label: str) -> None:
    total = len(rows)
    for start in range(0, total, batch):
        await db.execute(insert(model), rows[start : start + batch])
        await db.commit()
        print(f"  {label}: {min(start + batch, total)}/{total}", flush=True)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Semis de volume pour la campagne de charge ONEC Smart")
    parser.add_argument("--slug", default="load-test-20260803")
    parser.add_argument("--preset", choices=sorted(PRESETS), default="production")
    parser.add_argument("--services", type=int, default=None)
    parser.add_argument("--postes", type=int, default=None)
    parser.add_argument("--requisitions", type=int, default=None)
    parser.add_argument("--encaissements", type=int, default=None)
    parser.add_argument("--sorties", type=int, default=None)
    parser.add_argument("--experts", type=int, default=None)
    parser.add_argument("--months", type=int, default=24, help="Profondeur d'historique en mois")
    parser.add_argument("--batch", type=int, default=2000)
    args = parser.parse_args()

    conf = dict(PRESETS[args.preset])
    for key in list(conf):
        override = getattr(args, key)
        if override is not None:
            conf[key] = override

    now = utcnow()
    oldest = now - timedelta(days=30 * args.months)
    numero = Numerotation()

    async with SessionLocal() as db:
        org = (await db.execute(select(Organisation).where(Organisation.slug == args.slug))).scalar_one_or_none()
        if org is None:
            raise SystemExit(
                f"Organisation '{args.slug}' introuvable. Lancez d'abord :\n"
                "  docker compose exec backend python scripts/load_campaign.py --stages '' "
                "--seed-users 300 --seed-experts 1000"
            )
        org_id = org.id
        print(f"Organisation {args.slug} -> id={org_id}")

        # Reprise des compteurs existants : sans cela, une seconde execution
        # du semis repartirait a 1 et violerait les contraintes d'unicite
        # (organisation_id, numero_requisition) / (organisation_id, numero_recu)
        # / (organisation_id, reference_numero).
        for doc_type, year, service_id, counter in (
            await db.execute(
                select(
                    DocumentSequence.doc_type,
                    DocumentSequence.year,
                    DocumentSequence.service_id,
                    DocumentSequence.counter,
                ).where(DocumentSequence.tenant_id == org_id)
            )
        ).all():
            numero.counters[(doc_type, year, service_id)] = int(counter)

        # --- Circuit de validation -------------------------------------------------
        settings_row = (
            await db.execute(select(OrganisationSettings).where(OrganisationSettings.organisation_id == org_id))
        ).scalar_one_or_none()
        if settings_row is None:
            db.add(OrganisationSettings(organisation_id=org_id, workflow_config=WORKFLOW_LOADTEST))
        else:
            settings_row.workflow_config = WORKFLOW_LOADTEST
        await db.commit()
        print("Circuit de validation force sur le preset « simplifie ».")

        # --- Services --------------------------------------------------------------
        services = (
            await db.execute(
                select(Service).where(Service.organisation_id == org_id, Service.code.like("LOAD%")).order_by(Service.id)
            )
        ).scalars().all()
        existing_codes = {s.code for s in services}
        for i in range(conf["services"]):
            code = "LOAD" if i == 0 else f"LOAD{i:02d}"
            if code in existing_codes:
                continue
            db.add(Service(organisation_id=org_id, code=code, libelle=f"Service charge {i:02d}", is_active=True))
        await db.commit()
        services = (
            await db.execute(
                select(Service).where(Service.organisation_id == org_id, Service.code.like("LOAD%")).order_by(Service.id)
            )
        ).scalars().all()
        service_rows = [(s.id, s.code) for s in services][: conf["services"]]
        print(f"Services de charge : {len(service_rows)}")

        # --- Exercices et postes budgetaires ---------------------------------------
        years = sorted({oldest.year, now.year})
        exercice_ids: dict[int, int] = {}
        for year in years:
            ex = (
                await db.execute(
                    select(BudgetExercice).where(
                        BudgetExercice.organisation_id == org_id, BudgetExercice.annee == year
                    )
                )
            ).scalar_one_or_none()
            if ex is None:
                ex = BudgetExercice(organisation_id=org_id, annee=year, statut=StatutBudget.BROUILLON)
                db.add(ex)
                await db.flush()
            exercice_ids[year] = ex.id
        await db.commit()

        current_exercice = exercice_ids[now.year]
        existing_postes = (
            await db.execute(
                select(BudgetPoste.code).where(
                    BudgetPoste.organisation_id == org_id, BudgetPoste.exercice_id == current_exercice
                )
            )
        ).scalars().all()
        existing_poste_codes = set(existing_postes)
        # Arbre a 2 niveaux : 1 parent pour 10 enfants, pour que
        # GET /budget/postes/tree ait un arbre reel a construire.
        new_postes: list[dict] = []
        for i in range(conf["postes"]):
            kind = "RECETTE" if i % 4 == 0 else "DEPENSE"
            is_parent = i % 10 == 0
            code = f"LT{i:04d}"
            if code in existing_poste_codes:
                continue
            new_postes.append(
                dict(
                    organisation_id=org_id,
                    exercice_id=current_exercice,
                    code=code,
                    libelle=f"Poste charge {i:04d} ({kind.lower()})",
                    parent_code=None if is_parent else f"LT{(i // 10) * 10:04d}",
                    type=kind,
                    active=True,
                    is_global=False,
                    inclure_dans_calculs=True,
                    montant_prevu=Decimal("250000.00"),
                    montant_engage=Decimal("0"),
                    montant_paye=Decimal("0"),
                    is_deleted=False,
                )
            )
        if new_postes:
            await chunked_insert(db, BudgetPoste, new_postes, args.batch, "budget_postes")
        # Rattachement parent_id depuis parent_code (une seule requete).
        await db.execute(
            text(
                """
                UPDATE budget_postes enfant
                   SET parent_id = parent.id
                  FROM budget_postes parent
                 WHERE enfant.organisation_id = :org
                   AND parent.organisation_id = :org
                   AND enfant.exercice_id = parent.exercice_id
                   AND enfant.parent_code = parent.code
                   AND enfant.parent_id IS DISTINCT FROM parent.id
                """
            ),
            {"org": org_id},
        )
        await db.commit()

        postes = (
            await db.execute(
                select(BudgetPoste.id, BudgetPoste.code, BudgetPoste.libelle, BudgetPoste.type).where(
                    BudgetPoste.organisation_id == org_id,
                    BudgetPoste.exercice_id == current_exercice,
                    BudgetPoste.is_deleted.is_(False),
                )
            )
        ).all()
        postes_recette = [p for p in postes if (p[3] or "") == "RECETTE"]
        postes_depense = [p for p in postes if (p[3] or "") == "DEPENSE"]
        print(f"Postes : {len(postes_recette)} recette / {len(postes_depense)} depense")

        # --- Autorisations service <-> rubrique ------------------------------------
        existing_pairs = set(
            (row[0], row[1])
            for row in (
                await db.execute(select(ServiceRubrique.service_id, ServiceRubrique.budget_poste_id))
            ).all()
        )
        pairs: list[dict] = []
        for service_id, _code in service_rows:
            for poste in postes:
                if (service_id, poste[0]) in existing_pairs:
                    continue
                pairs.append(dict(service_id=service_id, budget_poste_id=poste[0]))
        if pairs:
            await chunked_insert(db, ServiceRubrique, pairs, args.batch, "service_rubriques")

        # --- Repartition des utilisateurs sur les services -------------------------
        users = (
            await db.execute(
                select(User.id, User.role)
                .where(User.organisation_id == org_id, User.email.like("load-%@example.test"))
                .order_by(User.email)
            )
        ).all()
        if not users:
            raise SystemExit("Aucun utilisateur de charge. Lancez d'abord load_campaign.py --stages ''")
        for index, row in enumerate(users):
            await db.execute(
                update(User)
                .where(User.id == row[0])
                .values(service_id=service_rows[index % len(service_rows)][0])
            )
        await db.commit()
        user_ids = [row[0] for row in users]
        print(f"Utilisateurs de charge repartis sur {len(service_rows)} services : {len(user_ids)}")

        # --- Experts comptables ----------------------------------------------------
        experts_count = (await db.execute(select(func.count(ExpertComptable.id)))).scalar_one()
        manquants = max(0, conf["experts"] - int(experts_count))
        if manquants:
            existing_numeros = set(
                (await db.execute(select(ExpertComptable.numero_ordre).where(ExpertComptable.numero_ordre.like("LV/%")))).scalars().all()
            )
            rows = []
            for i in range(manquants):
                num = f"LV/{i:06d}"
                if num in existing_numeros:
                    continue
                rows.append(
                    dict(
                        id=uuid.uuid4(),
                        numero_ordre=num,
                        nom_denomination=f"Expert volume {i:06d}",
                        type_ec="SEC" if i % 7 == 0 else "EC",
                        categorie_personne="Personne Morale" if i % 7 == 0 else "Personne Physique",
                        statut_professionnel=RNG.choice(["En Cabinet", "Indépendant", "Salarié"]),
                        active=True,
                        created_at=now,
                    )
                )
            if rows:
                await chunked_insert(db, ExpertComptable, rows, args.batch, "experts_comptables")

        expert_ids = (
            await db.execute(select(ExpertComptable.id).limit(2000))
        ).scalars().all()

        compte = (
            await db.execute(
                select(CompteBancaire.id).where(
                    CompteBancaire.organisation_id == org_id,
                    CompteBancaire.account_type == "BANK",
                    CompteBancaire.is_active.is_(True),
                ).limit(1)
            )
        ).scalar_one_or_none()

        def random_date() -> datetime:
            delta = (now - oldest).total_seconds()
            return oldest + timedelta(seconds=RNG.random() * delta)

        # --- Requisitions ----------------------------------------------------------
        deja = (
            await db.execute(
                select(func.count(Requisition.id)).where(
                    Requisition.organisation_id == org_id, Requisition.numero_requisition.like("REQ-LOAD%")
                )
            )
        ).scalar_one()
        a_creer = max(0, conf["requisitions"] - int(deja))
        req_rows: list[dict] = []
        ligne_rows: list[dict] = []
        req_meta: list[tuple[uuid.UUID, str]] = []  # (id, statut cible)
        for i in range(a_creer):
            service_id, service_code = service_rows[i % len(service_rows)]
            created = random_date()
            rid = uuid.uuid4()
            num = numero.next("REQ", created.year, service_id, service_code)
            # Distribution des statuts : ~55 % payees/approuvees (le stock que
            # lit la liste), 25 % en attente, 10 % autorisees (visa a poser),
            # 10 % rejetees.
            tirage = RNG.random()
            if tirage < 0.35:
                cible = "PAYEE"
            elif tirage < 0.55:
                cible = "APPROUVEE"
            elif tirage < 0.65:
                cible = "AUTORISEE"
            elif tirage < 0.90:
                cible = "EN_ATTENTE"
            else:
                cible = "REJETEE"
            montant = Decimal(str(RNG.randrange(2500, 900000) / 100))
            createur = user_ids[RNG.randrange(len(user_ids))]
            req_rows.append(
                dict(
                    id=rid,
                    numero_requisition=num,
                    reference_numero=num,
                    objet=f"Depense de charge {i:06d} - {RNG.choice(('fournitures','mission','carburant','honoraires','entretien'))}",
                    mode_paiement=RNG.choice(MODES),
                    type_requisition="classique",
                    status="EN_ATTENTE",
                    montant_total=montant,
                    date_requisition=created,
                    devise="USD",
                    organisation_id=org_id,
                    service_id=service_id,
                    created_by=createur,
                    workflow_snapshot=WORKFLOW_LOADTEST,
                    examen_status="EXAMINE",
                    historical_snapshot_status="not_finalized",
                    snapshot_version=1,
                    row_version=1,
                    a_valoir=False,
                    decaissement_progressif=False,
                    is_deleted=False,
                    created_at=created,
                    updated_at=created,
                )
            )
            req_meta.append((rid, cible))
            for _ in range(RNG.randint(1, 3)):
                poste = postes_depense[RNG.randrange(len(postes_depense))]
                pu = (montant / Decimal("3")).quantize(Decimal("0.01"))
                ligne_rows.append(
                    dict(
                        id=uuid.uuid4(),
                        organisation_id=org_id,
                        requisition_id=rid,
                        budget_poste_id=poste[0],
                        mode_paiement="cash",
                        rubrique=poste[2][:200],
                        description=f"Ligne de charge {uuid.uuid4().hex[:8]}",
                        quantite=1,
                        montant_unitaire=pu,
                        montant_total=pu,
                        devise="USD",
                        budget_poste_code_snapshot=poste[1],
                        budget_poste_libelle_snapshot=poste[2][:255],
                    )
                )
        if req_rows:
            await chunked_insert(db, Requisition, req_rows, args.batch, "requisitions")
            await chunked_insert(db, LigneRequisition, ligne_rows, args.batch, "lignes_requisition")
            # Statuts cibles, APRES insertion des lignes (trigger d'immutabilite).
            par_statut: dict[str, list[uuid.UUID]] = {}
            for rid, cible in req_meta:
                par_statut.setdefault(cible, []).append(rid)
            for cible, ids in par_statut.items():
                if cible == "EN_ATTENTE":
                    continue
                for start in range(0, len(ids), args.batch):
                    lot = ids[start : start + args.batch]
                    valeurs: dict = {"status": cible}
                    if cible in {"AUTORISEE", "APPROUVEE", "PAYEE"}:
                        valeurs["validee_par"] = user_ids[0]
                        valeurs["validee_le"] = now
                    if cible in {"APPROUVEE", "PAYEE"}:
                        valeurs["approuvee_par"] = user_ids[1 % len(user_ids)]
                        valeurs["approuvee_le"] = now
                    await db.execute(update(Requisition).where(Requisition.id.in_(lot)).values(**valeurs))
                    await db.commit()
                print(f"  statuts {cible}: {len(ids)}")

        # --- Encaissements ---------------------------------------------------------
        deja_enc = (
            await db.execute(
                select(func.count(Encaissement.id)).where(Encaissement.organisation_id == org_id)
            )
        ).scalar_one()
        a_creer_enc = max(0, conf["encaissements"] - int(deja_enc))
        enc_rows: list[dict] = []
        for i in range(a_creer_enc):
            service_id, service_code = service_rows[i % len(service_rows)]
            date_enc = random_date()
            poste = postes_recette[RNG.randrange(len(postes_recette))]
            montant = Decimal(str(RNG.randrange(1000, 500000) / 100))
            statut = RNG.choice(["complet", "complet", "complet", "partiel", "non_paye"])
            paye = montant if statut == "complet" else (montant / 2 if statut == "partiel" else Decimal("0.00"))
            type_client = RNG.choice(TYPES_CLIENT) if (i % 3) else "expert_comptable"
            canal = "BANQUE" if (compte and i % 5 == 0) else "CAISSE"
            enc_rows.append(
                dict(
                    id=uuid.uuid4(),
                    numero_recu=numero.next("ND", date_enc.year, None, "CENTRAL"),
                    est_proforma=False,
                    organisation_id=org_id,
                    type_client=type_client,
                    expert_comptable_id=(expert_ids[RNG.randrange(len(expert_ids))] if type_client == "expert_comptable" and expert_ids else None),
                    client_nom=(None if type_client == "expert_comptable" else f"Client charge {i:06d}"),
                    relance_count=0,
                    libelle=f"Encaissement de charge {i:06d}",
                    montant=montant,
                    montant_total=montant,
                    montant_paye=paye,
                    montant_percu=paye,
                    devise_perception="USD",
                    taux_change_applique=Decimal("1"),
                    canal=canal,
                    compte_bancaire_id=(compte if canal == "BANQUE" else None),
                    budget_poste_id=poste[0],
                    budget_poste_code=poste[1],
                    budget_poste_libelle=poste[2][:255],
                    service_id=service_id,
                    statut_paiement=statut,
                    mode_paiement=RNG.choice(MODES),
                    statut_operation="ACTIVE",
                    statut_comptabilisation="NON_COMPTABILISEE",
                    date_encaissement=date_enc,
                    created_by=user_ids[RNG.randrange(len(user_ids))],
                    created_at=date_enc,
                    is_deleted=False,
                    is_reconciled=False,
                )
            )
        if enc_rows:
            await chunked_insert(db, Encaissement, enc_rows, args.batch, "encaissements")

        # --- Sorties de fonds ------------------------------------------------------
        payees = (
            await db.execute(
                select(Requisition.id, Requisition.service_id, Requisition.montant_total)
                .where(
                    Requisition.organisation_id == org_id,
                    Requisition.status == "PAYEE",
                )
                .limit(conf["sorties"])
            )
        ).all()
        deja_sor = (
            await db.execute(select(func.count(SortieFonds.id)).where(SortieFonds.organisation_id == org_id))
        ).scalar_one()
        a_creer_sor = max(0, min(conf["sorties"], len(payees)) - int(deja_sor))
        codes_par_service = {sid: code for sid, code in service_rows}
        sor_rows: list[dict] = []
        for i in range(a_creer_sor):
            index_payee = int(deja_sor) + i
            if index_payee >= len(payees):
                break
            rid, service_id, montant = payees[index_payee]
            date_pay = random_date()
            poste = postes_depense[RNG.randrange(len(postes_depense))]
            code = codes_par_service.get(service_id, "LOAD")
            sor_rows.append(
                dict(
                    id=uuid.uuid4(),
                    type_sortie="requisition",
                    organisation_id=org_id,
                    requisition_id=rid,
                    budget_poste_id=poste[0],
                    budget_poste_code=poste[1],
                    budget_poste_libelle=poste[2][:255],
                    service_id=service_id,
                    montant_paye=montant,
                    date_paiement=date_pay,
                    mode_paiement="cash",
                    devise="USD",
                    canal="CAISSE",
                    reference_numero=numero.next("PAY", date_pay.year, service_id, code),
                    statut="VALIDE",
                    statut_comptabilisation="NON_COMPTABILISEE",
                    motif=f"Paiement de charge {i:06d}",
                    beneficiaire=f"Beneficiaire {i:06d}",
                    created_by=user_ids[RNG.randrange(len(user_ids))],
                    created_at=date_pay,
                    is_reconciled=False,
                )
            )
        if sor_rows:
            await chunked_insert(db, SortieFonds, sor_rows, args.batch, "sorties_fonds")

        # --- Repositionnement des sequences documentaires --------------------------
        # Sans cela, la premiere ecriture de l'API regenere un numero deja pris
        # et part dans la boucle de 50 tentatives d'encaissements.py:1437.
        for (doc_type, year, service_id), value in numero.counters.items():
            existant = (
                await db.execute(
                    select(DocumentSequence).where(
                        DocumentSequence.doc_type == doc_type,
                        DocumentSequence.year == year,
                        DocumentSequence.tenant_id == org_id,
                        DocumentSequence.service_id.is_(None) if service_id is None else DocumentSequence.service_id == service_id,
                    )
                )
            ).scalar_one_or_none()
            if existant is None:
                db.add(
                    DocumentSequence(
                        doc_type=doc_type,
                        year=year,
                        tenant_id=org_id,
                        service_id=service_id,
                        counter=value,
                        updated_at=now,
                    )
                )
            elif existant.counter < value:
                existant.counter = value
                existant.updated_at = now
        await db.commit()

        # --- Engagements budgetaires et statistiques -------------------------------
        await db.execute(
            text(
                """
                UPDATE budget_postes p
                   SET montant_engage = COALESCE(sub.total, 0)
                  FROM (
                        SELECT l.budget_poste_id AS poste_id, SUM(l.montant_total) AS total
                          FROM lignes_requisition l
                          JOIN requisitions r ON r.id = l.requisition_id
                         WHERE r.organisation_id = :org
                           AND r.is_deleted = false
                           AND upper(coalesce(r.examen_status,'')) IN ('EN_EXAMEN','EXAMINE')
                           AND upper(coalesce(r.status,'')) <> 'REJETEE'
                         GROUP BY l.budget_poste_id
                       ) sub
                 WHERE p.id = sub.poste_id
                   AND p.organisation_id = :org
                """
            ),
            {"org": org_id},
        )
        await db.commit()

        # --- Provision de tresorerie ------------------------------------------------
        # Les scenarios d'ecriture decaissent reellement : sans provision, la
        # caisse tombe a zero et les POST /sorties-fonds repondent 400
        # « Fonds insuffisants » (backend/app/api/v1/endpoints/sorties_fonds.py:1591),
        # ce qui fausserait le taux d'erreur.
        await db.execute(
            text(
                "UPDATE caisse_centrale SET solde_usd = 50000000, solde_cdf = 50000000, est_ouverte = true "
                "WHERE organisation_id = :org"
            ),
            {"org": org_id},
        )
        await db.execute(
            text("UPDATE comptes_bancaires SET solde_actuel = 50000000 WHERE organisation_id = :org"),
            {"org": org_id},
        )
        await db.commit()

        for table in ("requisitions", "lignes_requisition", "encaissements", "sorties_fonds", "budget_postes", "experts_comptables", "document_sequences"):
            await db.execute(text(f"ANALYZE public.{table}"))
        await db.commit()

        # --- Inventaire final ------------------------------------------------------
        print("\n--- Volume en base pour l'organisation de charge ---")
        for label, sql in (
            ("requisitions", "select count(*) from requisitions where organisation_id=:org"),
            ("lignes_requisition", "select count(*) from lignes_requisition where organisation_id=:org"),
            ("encaissements", "select count(*) from encaissements where organisation_id=:org"),
            ("sorties_fonds", "select count(*) from sorties_fonds where organisation_id=:org"),
            ("budget_postes", "select count(*) from budget_postes where organisation_id=:org"),
            ("services", "select count(*) from services where organisation_id=:org"),
            ("users", "select count(*) from users where organisation_id=:org"),
            ("experts_comptables", "select count(*) from experts_comptables"),
        ):
            total = (await db.execute(text(sql), {"org": org_id})).scalar_one()
            print(f"  {label:22s} {total}")


if __name__ == "__main__":
    asyncio.run(main())
